"""``run`` -- start a simulation, and deal with one that is already going.

Five topics, and **each has its own page**: ``run <topic> --help`` is that
topic's manual and lists the flags that topic takes, which is not the same set
for any two of them. What is here is what they share.

**Started detached, always.** A solve is minutes -- 429 s for a small board on
a coarse mesh, measured -- so there is no foreground mode to offer, and
detaching is the default rather than a flag. Everything after ``run start`` is
somebody asking a file what became of that job, which is what makes the id it
answers the only handle there is.

**And nothing here is the solver's parent.** ``stop`` and ``sample`` append a
line to the control file the solver polls, which is why that channel was a
file rather than a signal in the first place: they reach a run started by
another shell, by a session that has since closed, or by the window.
"""

import os
import subprocess
import sys
import time

from ... import formparams, settings
from ...sim import (
    diagnostics,
    hostos,
    jobs,
    launch,
    runcontrol,
    runlock,
    simulate,
)
from .. import kicad

NAME = "run"
HELP = "Start a simulation, or deal with one already going"

# Where the launcher is, from here: agent/verbs/ -> agent/ -> emkit/.
LAUNCHER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "run_agent.py",
)


def _job_arg(parser):
    """``--job``, on every topic that asks about a run rather than making
    one."""
    parser.add_argument(
        "--job",
        default=None,
        help=(
            "Which run, by the id run start answered (e.g. 20260905-162223); "
            "the newest run of this board by default"
        ),
    )


def _start_args(parser):
    parser.add_argument(
        "--grid-only",
        action="store_true",
        help="Stop after the meshing pass — the cheap way to check the lattice",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help=(
            "The settings file this run is built from; the board's own "
            "simulation/settings.yaml by default. Point it at a copy you "
            "edited — the window rewrites its own"
        ),
    )
    # This run only. What a machine does by default is `docker on` / `off`,
    # and neither of these writes anything down: a caller confining one run
    # should not silently change what the next one does.
    container = parser.add_mutually_exclusive_group()
    container.add_argument(
        "--docker",
        dest="docker",
        action="store_const",
        const=True,
        default=None,
        help="Run the solver inside a container for this run, whatever this "
        "machine is set to",
    )
    container.add_argument(
        "--no-docker",
        dest="docker",
        action="store_const",
        const=False,
        help="Run the solver natively for this run (refused where no native "
        "solver ships)",
    )


def _log_args(parser):
    _job_arg(parser)
    parser.add_argument(
        "--since",
        type=int,
        default=0,
        help="The line to resume from (the offset a previous log returned)",
    )
    parser.add_argument(
        "--severity",
        choices=diagnostics.SEVERITIES,
        default=None,
        help=(
            "Show only the solver's own diagnostics at this severity or louder "
            "— 'warning' is every warning and error it printed. The whole log "
            "by default; either way the count is reported"
        ),
    )


# What each topic is, what it takes, and its own manual. A topic's flags are
# nobody else's: --since means nothing to `start`, and printing it there is how
# a caller comes to try it. The description is what `run <topic> --help`
# prints, which is why the paragraphs that are about one topic live in this
# table rather than in the module docstring above -- the docstring is the page
# for what all five share, and repeating either in the other would be two
# copies of the same manual.
_TOPICS = (
    (
        "start",
        "Prepare this board and launch a solve; answers a job id",
        """Everything a run needs doing to a board, then a detached solver.

The board work happens here -- the pre-flight the window puts in its banner,
the stackup, the gerbers, the ports, the config -- which is the half that
needs KiCad's Python; the waiting is handed to a worker that needs only the
binary. The parameters come from the settings file (--settings, or the
board's own), because the form *is* the run: this starts the run the window
would start off the same file, not a second derivation of it.

--grid-only stops after the meshing pass. It writes the lattice and no
report, costs seconds rather than minutes, and is the cheap way to find out
that the board was wrong.

A second run on the same board is refused by name. Both would write one
pcb.yaml, overwrite the same dumps and poll one control file, so a stop meant
for one would end the other -- what the window prevents by turning its Run
button into Stop. Anything else in flight is reported and not refused: two
solvers on one machine only make each other slower, which is a cost the
window has a dialog for and a command line has nobody to ask about.""",
        _start_args,
    ),
    (
        "status",
        "What a job is doing, or the last few",
        """What became of a run: its state, its phase, how long it has been going,
and what it was aimed at.

--job asks about one; without it, the last few runs of this board. A job
whose process is gone without having written an ending is reported lost
rather than running, because nothing will ever finish it. A run started from
the *window* keeps no job record and so has no state to report -- its numbers
are still readable with `results show --job <id>`.""",
        _job_arg,
    ),
    (
        "log",
        "The solver's output since an offset, or just its warnings",
        """The solver's own output, and -- asked for or not -- what the run warned
about.

A warning is not news, it is a state. The solver prints what it makes of the
board once, at meshing time, in the middle of a flood of step lines, so a
poller reading with --since scrolls past it in one chunk and never meets it
again. So the whole log is scanned for diagnostics on every call and they are
reported beside whatever stretch was asked for. Pre-flight cannot cover this
ground: it answers before a solver has been launched.

--since is a line count, and every read answers with the offset to pass next
time. --severity narrows the stretch itself to the diagnostics at that level
or louder, which is the log worth reading when the flood is not. The count
reported beside it covers every severity the log holds, notes included --
which is more than the warnings listed under it.

One line differs from the log on disk. Before it starts stepping the solver
offers Ctrl-C and a signal to a pid, which is true for somebody running the
binary by hand and not for a run started here: this one is detached from the
shell that asked for it. That line is shown as `run sample` and `run stop`,
the two requests that do reach it.""",
        _log_args,
    ),
    (
        "sample",
        "Write a report from the record so far and keep stepping",
        """A report out of a run that is still going, without ending it.

The request is a line in the control file the solver polls, so it is posted
rather than served: a few times a second later, one more report is written
and the run keeps stepping. Every report overwrites the last, and is scored
like any other -- a snapshot of a run that has not converged reads as exactly
that (`results show`).""",
        _job_arg,
    ),
    (
        "stop",
        "End a run early and still get its report",
        """Stop is cooperative, and it still writes a report.

Worth saying outright, because to a reader who has not been told, "stop"
reads as "throw away": the solver ends the run early and writes its report
from the record simulated so far. Only a mesh pass, which has no results yet,
is killed outright.

Posted to the control file like a sample, so this reaches a run started by
another shell, by a session that has since closed, or by the window.""",
        _job_arg,
    ),
)

# The topic names, off the table, so the two cannot disagree -- the guide
# prints these and the parser offers them.
TOPICS = tuple(name for name, _help, _description, _adder in _TOPICS)


def add_arguments(parser):
    """One parser per topic. ``run start --help`` is then start's own manual
    and start's own flags, rather than five topics' worth of both -- which is
    what a reader got when the topic was one positional among a verb's whole
    set of options."""
    topics = parser.add_subparsers(dest="topic", required=True, metavar="<topic>")
    for name, help_text, description, add_flags in _TOPICS:
        sub = topics.add_parser(name, help=help_text, description=description)
        kicad.add_board_arg(sub)
        add_flags(sub)


def run(args):
    return {
        "start": _start,
        "status": _status,
        "log": _log,
        "sample": _sample,
        "stop": _stop,
    }[args.topic](args)


# --------------------------------------------------------------------------- #
# start
# --------------------------------------------------------------------------- #
def _start(args):
    from .... import runjob

    board = kicad.board(args.board)
    sim_dir = str(simulate.output_dir(board))

    # Read up here, before the checks rather than beside the work: some of the
    # blockers below are about what these parameters ask for (the solder mask
    # is only required to state a material by a run that includes it), so the
    # banner's own question cannot be asked without them.
    #
    # The form is the file, and the translation is the one both frontends use
    # (emkit.formparams), so this run is the run the window would start off
    # the same form -- not a second derivation of it.
    form_path = args.settings or settings.path(sim_dir)
    form = _form(args, form_path)
    params = formparams.params(form)
    params["outdir"] = sim_dir

    # What this run is aiming at, and the form is the only place it comes
    # from: the same field the window's picker writes. Resolved before
    # anything is plotted or written, so a form naming a target this install
    # no longer has costs no work -- and None for a flow that judges nothing.
    target = runjob.form_target(form)

    # The same blockers the window's banner shows, refused here rather than
    # halfway through plotting gerbers for a run that cannot start.
    blocker = next(
        (p for p in simulate.preflight(board, params) if p.severity == "block"), None
    )
    if blocker is not None:
        raise RuntimeError(f"{blocker.id}: {blocker.message}")

    # A run already going on *this* board is a collision, not a cost: see the
    # module docstring. Refused before anything is plotted or written.
    live = next((j for j in jobs.recent(sim_dir) if j.state == jobs.RUNNING), None)
    if live is not None:
        raise RuntimeError(
            f"job {live.id} is already running on this board, and a second run "
            "here would overwrite its config and its dumps and share its "
            "control file.\n"
            f"Wait for it, or end it early and keep its report:\n"
            f"  run stop --board {args.board}"
        )

    # Everything *else* in flight is said rather than asked: a command line
    # has nobody to have the window's conversation with. Read before the claim
    # this run's worker will add.
    also_running = runlock.labels(sim_dir)

    # Asked here as well as in the worker, and asked *first*: a container
    # that is not ready is a sentence with a fix in it, and the caller is
    # standing right here to read it. Found in the worker instead, it would be
    # a line in a log file the caller has to go and find.
    launcher = launch.prepare(getattr(args, "docker", None))
    notes = []
    stack = simulate.collect_stackup(board)
    gerbers = simulate.plot_gerbers(board, os.path.join(sim_dir, "gerbers"))
    runjob.apply_ports(board, params, note=notes.append)
    yaml_path = os.path.join(sim_dir, "pcb.yaml")
    simulate.write_config(gerbers, stack, params, yaml_path)

    # The stamp is the job id, and the id names the one folder this run writes
    # into -- its record, its log and its dumps (sim.jobs). So every verb after
    # this one takes the same --job, and none of them looks anything up.
    job_id = time.strftime("%Y%m%d-%H%M%S")
    # Written *before* the worker exists, with no pid yet: the worker's first
    # act is to read this file, so writing it afterwards would be a race it
    # loses on a fast machine. It fills in its own pid, and until it does a
    # job with no pid reads as starting rather than as lost.
    jobs.write(
        sim_dir,
        jobs.Job(
            id=job_id,
            state=jobs.RUNNING,
            pid=0,
            board=os.path.abspath(args.board),
            form=form,
            grid_only=bool(args.grid_only),
            docker=getattr(args, "docker", None),
            started=time.time(),
        ),
    )
    _spawn(sim_dir, job_id)
    # Everything below this line runs *after* a solve has been started. A
    # rendering path that falls through without returning would start the run
    # and then die printing it, which is exactly what happened once.
    return {
        "job": job_id,
        "sim_dir": sim_dir,
        "settings": str(form_path),
        "config": yaml_path,
        "solver": launcher.exe,
        "target": _aim(target),
        "grid_only": bool(args.grid_only),
        "board_notes": notes,
        "also_running": list(also_running),
        "startup_grace_s": jobs.STARTUP_GRACE_S,
    }


def _aim(target):
    """A design target's name, or ``''`` for a flow that judges nothing. The
    only thing a run's own payload says about it -- the spec it stands for
    belongs to the verdict table (``results show``)."""
    return "" if target is None else target.name


def _recorded_aim(form):
    """What the run a job records was aiming at, read back out of the form it
    was started from -- the only place a target ever comes from.

    ``''`` for a flow that judges nothing, and for a form whose pick this
    install can no longer resolve: a job that was started before a saved target
    was deleted is still a job, and a status table must not fail over the label
    on one of its rows."""
    from .... import runjob

    try:
        return _aim(runjob.form_target(form))
    except ValueError:
        return ""


def _form(args, form_path):
    """The saved form this run is built from, or a refusal that says where one
    comes from. A board nobody has opened the window on has no settings file,
    and the answer to that is a starter written here rather than a run
    assembled out of guesses."""
    try:
        return settings.read(form_path)
    except RuntimeError as exc:
        if args.settings:
            raise  # a file the caller named: its own message is the answer
        raise RuntimeError(
            f"{exc}\n"
            "That file is the form a run is made of. The window writes it "
            "whenever it closes or starts a run; with no window, write a "
            "starter and fill in what it leaves blank:\n"
            f"  settings init --board {args.board}"
        ) from None


def _spawn(sim_dir, job_id):
    """Launch the worker and let go of it.

    Detached on purpose: the shell that started the run may be gone long
    before the solve ends, and the run should not go with it. The per-OS half
    of that is ``hostos.launch_kwargs(detached=True)`` -- ``start_new_session``
    is POSIX-only, and Windows needs its own flags or the child stays in the
    console it was started from.

    Every stream is closed. The solver's own output goes to the job's log,
    which is the only place a detached process can usefully put a flood -- and
    a child that dies before it can write anything is caught by the job file's
    startup grace instead of sitting at "running" forever.
    """
    return subprocess.Popen(
        [sys.executable, LAUNCHER, "--worker", sim_dir, job_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hostos.launch_kwargs(detached=True),
    )


# --------------------------------------------------------------------------- #
# status / log
# --------------------------------------------------------------------------- #
def _status(args):
    sim_dir = kicad.sim_dir(args.board)
    if args.job:
        job = jobs.read(sim_dir, args.job)
        if job is None:
            raise RuntimeError(f"no job {args.job} under {sim_dir}")
        found = [job]
    else:
        found = jobs.recent(sim_dir)
    return {
        "sim_dir": sim_dir,
        "jobs": [_job(job) for job in found],
        "also_running": _others(sim_dir, found),
    }


def _others(sim_dir, listed):
    """What is in flight on this board *besides* the jobs in the table.

    Every run leaves a claim (``runlock``) and the claim names the pid the
    job file already names, so the unfiltered list said "also running" about
    the very run the caller asked about -- read, fairly, as the concurrency
    warning the rest of this verb spends its words on. Matched on the pid,
    which is the one thing the two records share.

    What survives is what a job file cannot show: a run or a scan started
    from the *window*, which writes no job of its own.
    """
    mine = {job.pid for job in listed if job.state == jobs.RUNNING and job.pid}
    return [claim.label for claim in runlock.live(sim_dir) if claim.pid not in mine]


def _log(args):
    """The log, and -- always, asked for or not -- what the run warned about.

    A solver warning is one line in a flood of step lines, printed once, at
    meshing time. A poller reading with ``--since`` scrolls past it in the
    first chunk and never sees it again, which is how a board that pre-flight
    called clean gets simulated with its ground warning unread. So the
    diagnostics are scanned over the *whole* log on every call and reported
    beside whatever stretch was asked for: standing, not a chunk's news.

    ``--severity`` narrows the stretch itself to those lines -- the flood is
    what an agent cannot afford to read, and this is the log worth reading.

    ``counts`` is over every severity the whole log holds and ``diagnostics``
    over the loud half of it. Both come out of one scan: counting only what
    was reported would answer ``note: 0`` about a log that printed forty of
    them, which is the reading a caller asking ``--severity note`` would
    least expect.
    """
    sim_dir = kicad.sim_dir(args.board)
    job = _pick(sim_dir, args.job, running_only=False)
    whole = jobs.log_lines(sim_dir, job.id)  # read once; sliced and scanned below
    stretch = jobs.resume(whole, args.since)
    shown = [runcontrol.restate_signal_hint(text) for text in stretch.lines]
    if args.severity:
        shown = [
            one.text
            for one in diagnostics.scan(
                shown, minimum=args.severity, start=stretch.first
            )
        ]
    every = diagnostics.scan(whole, minimum=diagnostics.NOTE)
    found = diagnostics.at_least(every, diagnostics.WARNING)
    return {
        "job": job.id,
        "state": job.state,
        "lines": shown,
        "severity": args.severity or "",
        "read_from": stretch.first,
        # What to pass as --since next time. A line count into the whole log,
        # so it survives the file growing between two reads -- and is unchanged
        # by --severity, which narrows what is shown and never what was read.
        "next": stretch.next,
        "diagnostics": [one._asdict() for one in found],
        "counts": diagnostics.counts(every),
    }


# --------------------------------------------------------------------------- #
# sample / stop
# --------------------------------------------------------------------------- #
def _sample(args):
    return _request(args, "sample")


def _stop(args):
    return _request(args, "stop")


# What each request leaves the caller waiting for. The solver polls the
# control file a few times a second, so a posted request is not a served one,
# and the two wait for different things -- saying which is what stops a caller
# polling for the wrong one.
#
# A noun phrase, not a sentence: the key is called "next" and means *what is
# awaited*, and the line that prints it supplies the verb ("waiting for ...").
# Written as a clause it produced "waiting for one more report is written and
# the run keeps stepping".
AWAITING = {
    "stop": "the run to end and write its report from the record so far",
    "sample": "one more report to be written; the run keeps stepping",
}


def _request(args, what):
    """Post a cooperative request to a running job's solver.

    Both go through the control file, so this reaches a run started by the
    window, by another shell, or by a session that has since closed.
    """
    sim_dir = kicad.sim_dir(args.board)
    job = _pick(sim_dir, args.job, running_only=True)
    control = runcontrol.control_path(os.path.join(sim_dir, "pcb.yaml"))
    line = runcontrol.STOP if what == "stop" else runcontrol.SAMPLE
    posted = runcontrol.post(control, line)
    return {
        "job": job.id,
        "requested": what,
        "posted": posted,
        "next": AWAITING[what],
        "state": job.state,
    }


def _pick(sim_dir, job_id, running_only):
    if job_id:
        job = jobs.read(sim_dir, job_id)
        if job is None:
            raise RuntimeError(_no_job(sim_dir, job_id))
    else:
        found = jobs.recent(sim_dir)
        if running_only:
            found = [j for j in found if j.state == jobs.RUNNING]
        if not found:
            raise RuntimeError(
                "nothing is running on this board"
                if running_only
                else f"no runs on this board yet ({simulate.results_dir(sim_dir)})"
            )
        job = found[0]
    if running_only and job.state != jobs.RUNNING:
        raise RuntimeError(f"job {job.id} is {job.state}, not running")
    return job


def _no_job(sim_dir, job_id):
    """Why there is no such job -- and the one case where the id is perfectly
    good and the answer is still no.

    A run started from the *window* archives its outputs under its stamp like
    any other, but the window keeps no job record, so there is nothing here to
    report a state from. That is a different thing from a typo, and a caller
    told "no job" about a folder it can see would reasonably not believe us.
    """
    if os.path.isdir(str(simulate.run_results_dir(sim_dir, job_id))):
        return (
            f"{job_id} is a run of this board, but not one started from a "
            "command line -- the window keeps no job record, so this side "
            "knows nothing about how it went.\n"
            f"Its numbers are readable:\n"
            f"  results show --job {job_id}"
        )
    return f"no job {job_id} under {simulate.results_dir(sim_dir)}"


def _job(job):
    return {
        "id": job.id,
        "state": job.state,
        "phase": job.phase,
        "pid": job.pid,
        "target": _recorded_aim(job.form),
        "grid_only": job.grid_only,
        "elapsed_s": round(job.elapsed_s(), 1),
        "error": job.error,
    }


# --------------------------------------------------------------------------- #
# lines
# --------------------------------------------------------------------------- #
def lines(payload):
    if "lines" in payload:
        return _log_lines(payload)
    if "jobs" in payload:
        return _status_lines(payload)
    if "requested" in payload:
        if not payload["posted"]:
            # Nothing was appended, so there is nothing on its way and nothing
            # to wait for: the run directory is gone or the control file is
            # unwritable (runcontrol.post).
            return [
                f"{payload['requested']}: could not reach the run — its "
                "control file could not be written, so nothing was asked of it"
            ]
        return [f"{payload['requested']}: requested — waiting for {payload['next']}"]
    return _start_lines(payload)


def _log_lines(payload):
    out = list(payload["lines"])
    if payload["severity"] and not out:
        # Never an empty answer: "nothing" and "nothing yet" are different, and
        # a filtered log that printed no lines at all reads as a broken filter.
        out.append(
            f"No {payload['severity']} or louder in "
            + (
                "the log — it has nothing new in it."
                if payload["read_from"] == payload["next"]
                else f"lines {payload['read_from'] + 1}–{payload['next']} of the log."
            )
        )
    out.append("")
    out.extend(_diagnostic_lines(payload))
    out.append(
        f"{payload['job']} is {payload['state']}; resume with --since {payload['next']}"
    )
    return out


# How many diagnostics the standing summary spells out before it says how many
# more there are. Enough for a board with something wrong at every port,
# short enough that the summary never becomes the flood it exists to escape.
SHOWN = 5


def _diagnostic_lines(payload):
    """What this run has warned about, over the whole log rather than the
    stretch just read -- see :func:`_log`. Printed under the log and above the
    resume line, which is the last thing a reader's eye lands on."""
    found = payload["diagnostics"]
    if not found:
        return []
    head = (
        # The loud half of the tally only: the lines listed under this are the
        # warnings and errors, so a count that also swept in the notes would
        # not match what follows it.
        f"⚠ {diagnostics.summary(payload['counts'], diagnostics.WARNING)} in "
        "this run's log, from the solver itself"
    )
    if payload["severity"] and payload["lines"]:
        return [f"{head}.", ""]  # they are the lines above; do not print twice
    # ...but a filtered read that landed on a stretch with none in it still
    # gets them spelled out: a tally of two over an empty answer reads as a
    # contradiction, and the diagnostics it is counting are further up the log.
    out = [f"{head} — pre-flight cannot see these:"]
    for one in found[:SHOWN]:
        out.append(f"  line {one['line']:<6} {one['text'].strip()}")
    rest = found[SHOWN:]  # sliced rather than counted: agent/ does no arithmetic
    if rest:
        out.append(f"  … and {len(rest)} more")
    out.append(
        "  read them from the top with: run log --board <board> --severity warning"
    )
    out.append("")
    return out


def _status_lines(payload):
    if not payload["jobs"]:
        return [f"No runs on this board yet ({payload['sim_dir']})."]
    out = [
        f"{j['id']}  {j['state']:<8} {j['phase'] or '—':<6} "
        f"{j['elapsed_s']:.0f}s{'  ' + j['error'] if j['error'] else ''}"
        for j in payload["jobs"]
    ]
    if payload["also_running"]:
        out.append("")
        # Never a job in the table above (_others drops those), so this is a
        # pass the table cannot show: the window's run or scan, or a job the
        # caller narrowed past with --job. The label names its frontend
        # already, which is where it can be stopped.
        out.append(
            "Also in flight on this board: " + ", ".join(payload["also_running"])
        )
    return out


def _start_lines(payload):
    out = [f"job {payload['job']} started"]
    out.append(f"  form    {payload['settings']}")
    for note in payload["board_notes"]:
        out.append(f"  board   {note}")
    out.append(f"  config  {payload['config']}")
    out.append(f"  solver  {payload['solver']}")
    if payload["target"]:
        out.append(f"  target  {payload['target']}")
    if payload["grid_only"]:
        out.append("  note    grid only — the FDTD solve will not run")
    if payload["also_running"]:
        out.append(
            "  note    also running on this board: "
            + ", ".join(payload["also_running"])
            + " (both will be slower)"
        )
    out.append("")
    out.append("It runs detached; nothing is waiting for it here. Follow it with:")
    out.append("  run status  --board <board>")
    out.append("  run log     --board <board> --since <n>")
    out.append("  run stop    --board <board>   (still writes a report)")
    return out
