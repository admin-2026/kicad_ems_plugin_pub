"""The process a detached run happens in.

    <python> <install>/<package>/emkit/run_agent.py --worker <sim-dir> <job-id>

Not a verb. ``run start`` does all the board work -- pre-flight, stackup,
gerbers, the ports, the config -- and then spawns this, which does the one
thing left: sit through the solver's run and record how it went. The
split is on the line that matters, because **this half needs no pcbnew.**
Everything that required KiCad's Python has already happened by the time it
starts; what is left is the bundled binary and a folder full of files.

It is reached by a flag rather than by being a verb so that ``--help`` never
has to mention it and no caller can reach it by accident. The exchange with
``run start`` is entirely the job file: the parent writes it before spawning,
and this rewrites it as the run moves on and once more when it ends, whichever
way it ended. **The last write is the answer.**

Nothing is printed. The solver's own output is a flood and a detached process
has nowhere useful to put it, so it goes to the job's log -- in the run's own
folder, beside the dumps it is about -- where ``run log`` can reach it.
"""

import os
import sys
import time

from ..sim import jobs, launch, runinfo, runlock, runner, runsession, simulate

# What this pass calls itself in the board's lock directory -- the phrase a
# window's "something else is already running" warning will show. A noun
# phrase somebody can act on, and it names the frontend, because "stop it"
# means going somewhere different for each.
LABEL = "a simulation run started from the command line"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: run_agent.py --worker <sim-dir> <job-id>", file=sys.stderr)
        return 2
    sim_dir, job_id = argv
    job = jobs.read(sim_dir, job_id)
    if job is None:
        print(f"no job {job_id} under {sim_dir}", file=sys.stderr)
        return 1

    # The first act: claim the pid. Until this lands the job reads as starting
    # rather than as running, and after the startup grace as lost -- which is
    # what makes a worker that dies before it gets here reportable at all.
    job = job._replace(pid=os.getpid(), state=jobs.RUNNING)
    jobs.write(sim_dir, job)
    # Line-buffered and explicitly UTF-8: a poller reads this while it is
    # being written, and the solver's output is not guaranteed to be ASCII on
    # a console whose codepage is not.
    log = open(
        jobs.log_path(sim_dir, job_id),
        "w",
        encoding="utf-8",
        errors="replace",
        buffering=1,
    )
    # Claimed *here*, not by ``run start``: the claim names a pid, and the
    # process that started this one is already gone. Until this lands the job
    # file is the only record, which is what its startup grace is for.
    claim = runlock.claim(sim_dir, LABEL)
    try:
        _solve(sim_dir, job, log)
    except Exception as exc:  # every failure ends the job; none escape silently
        log.write(f"ERROR: {exc}\n")
        _finish(sim_dir, job, jobs.FAILED, str(exc))
        return 1
    finally:
        runlock.release(claim)
        log.close()
    return 0


def _solve(sim_dir, job, log):
    # How this machine starts a solve -- natively, or inside a container. The
    # decision is made here, in the process that launches it, and not by
    # `run start`: the two are different processes and a preference could have
    # changed between them, but more to the point a launcher names a container
    # that only this process can kill.
    launcher = launch.prepare(job.docker)
    log.write(launcher.label + "\n")
    stamp = job.id
    reports = []  # every report archived, newest last
    session = runsession.RunSession(
        on_line=lambda text: log.write(text + "\n"),
        on_outputs=lambda sample: _archive(sim_dir, job, stamp, log, reports),
    )
    runner.solve(
        session,
        launcher,
        sim_dir,
        stamp,
        grid_only=job.grid_only,
        on_phase=lambda phase: _phase(sim_dir, job, phase),
        on_grid=lambda path: log.write(f"archived the grid preview to {path}\n"),
    )
    # A cooperative stop ends the solver cleanly and still writes its report,
    # so it lands here rather than in the failure path -- and is recorded as a
    # stop, because "done" would claim a run that was cut short finished.
    _finish(sim_dir, job, _ended(reports), "")


def _ended(reports):
    """How the run ended, as the *solver* recorded it in the report it wrote.

    Not as this process believes it ended. ``run stop`` posts a line to the
    control file from whatever shell the caller happened to be in, so the
    session driving the solver here never learns a stop was asked for -- its
    own ``stop_requested`` is only set by the window, which asks through the
    session it holds. Reading the run series instead means one answer whoever
    asked, and it is the answer the report page shows.
    """
    if not reports:
        return jobs.DONE  # a grid-only run, which writes no report
    info = runinfo.read(reports[-1])
    return jobs.STOPPED if info and info.stop == "interrupted" else jobs.DONE


def _archive(sim_dir, job, stamp, log, reports):
    """One set of outputs has landed -- a mid-run snapshot, or the run's final
    ones, which an interrupted run writes exactly the same way. Keep it, and
    score it against what the form this run was started from was aiming at.

    Never fatal: a run whose report could not be archived still ran, and the
    job should say so rather than look like a crash.
    """
    try:
        dump = simulate.archive_dump(sim_dir, simulate.REPORT, stamp)
    except OSError as exc:
        log.write(f"could not archive the report: {exc}\n")
        return
    reports.append(dump)
    log.write(f"archived the report to {dump}\n")
    # The viewer is installed here rather than at start: a human handed the
    # run's viewer_url needs the pages to exist, and this is the moment there
    # is finally something for them to draw.
    try:
        simulate.install_viewer(sim_dir)
    except OSError as exc:
        log.write(f"could not install the viewer: {exc}\n")
    try:
        from ... import runjob

        # The job carries the form rather than a path to one, so this is what
        # the run was asked for and not what the board's file says now.
        target = runjob.form_target(job.form)
        if target is None:
            return  # a flow with nothing to judge against; the numbers are it
        payload = runjob.score(dump, target)
    except Exception as exc:
        # Scoring is a convenience laid beside the numbers; a run nobody can
        # score still has a report to read.
        log.write(f"could not score the report: {exc}\n")
        return
    if payload:
        log.write(f"against {payload['target']}: {payload['overall']}\n")


def _phase(sim_dir, job, phase):
    """The run moved on. Re-read first: the file is the exchange, and a stop
    posted from another process may have changed something since."""
    current = jobs.read(sim_dir, job.id) or job
    jobs.write(sim_dir, current._replace(phase=phase))


def _finish(sim_dir, job, state, error):
    current = jobs.read(sim_dir, job.id) or job
    jobs.write(
        sim_dir,
        current._replace(state=state, error=error, ended=time.time()),
    )
