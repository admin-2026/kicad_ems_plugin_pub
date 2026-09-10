"""The job file: what a detached run says about itself to a caller that is not
waiting for it.

The two answers worth pinning are the ones a poller acts on. A job whose
worker is gone must not read "running" -- nothing will ever write its ending,
so a caller would wait forever for a result that cannot arrive. And a job that
has been written but whose worker has not reported in yet must read "running"
*briefly*: a worker that never starts at all (the wrong interpreter, a package
it cannot import) dies into DEVNULL and says nothing, which is the failure the
startup grace exists for.

    python3 tests/test_jobs.py   (or pytest)
"""

import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

jobs = load("emkit.sim.jobs")
simulate = load("emkit.sim.simulate")


def _tmp(name):
    import tempfile

    return tempfile.mkdtemp(prefix=f"jobs_{name}_")


def _job(**fields):
    base = {
        "id": "20260902-141133",
        "state": jobs.RUNNING,
        "pid": 0,
        "board": "/tmp/board.kicad_pcb",
        "started": time.time(),
    }
    base.update(fields)
    return jobs.Job(**base)


def _dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


def test_a_job_round_trips():
    sim = _tmp("roundtrip")
    # The form rides in the file whole -- it is what the worker reads back to
    # score the reports -- so the round trip has to carry a nested dict too.
    written = _job(
        pid=1,
        state=jobs.DONE,
        form={"app": "Wi-Fi 2.4 GHz", "freq": "2.44"},
        phase="solve",
    )
    jobs.write(sim, written)
    assert jobs.read(sim, written.id) == written


def test_a_run_keeps_everything_it_produced_in_one_folder():
    """The record and the log live where the dumps are archived, under the id
    ``run start`` answered. That is what lets every verb take the same
    ``--job <id>`` and none of them look anything up."""
    sim = _tmp("onefolder")
    written = _job(pid=1)
    folder = simulate.run_results_dir(sim, written.id)
    jobs.write(sim, written)
    assert pathlib.Path(jobs.path(sim, written.id)).parent == folder
    assert pathlib.Path(jobs.log_path(sim, written.id)).parent == folder


def test_a_run_the_window_started_is_not_reported_as_a_job():
    """The window archives its dumps into a run folder like anything else and
    keeps no record in it. A listing that counted those would report jobs with
    no state, no pid and no ending."""
    sim = _tmp("windowrun")
    folder = simulate.run_results_dir(sim, "20260903-090000")
    folder.mkdir(parents=True)
    dump = folder / simulate.DUMPS[simulate.REPORT]
    dump.write_text("window.FDTD={}", encoding="utf-8")
    assert jobs.recent(sim) == []


def test_there_is_no_such_job():
    assert jobs.read(_tmp("none"), "20260101-000000") is None


def test_a_half_written_file_is_not_evidence_of_anything_running():
    sim = _tmp("corrupt")
    written = _job(pid=1)
    path = jobs.write(sim, written)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"id": "2026')
    assert jobs.read(sim, written.id) is None


def test_a_job_whose_process_is_gone_is_lost_not_running():
    sim = _tmp("lost")
    written = _job(pid=_dead_pid())
    jobs.write(sim, written)
    job = jobs.read(sim, written.id)
    assert job.state == jobs.LOST
    assert "wrote no ending" in job.error


def test_a_job_that_has_not_reported_a_pid_yet_is_still_starting():
    sim = _tmp("starting")
    written = _job(pid=0, started=time.time())
    jobs.write(sim, written)
    assert jobs.read(sim, written.id).state == jobs.RUNNING


def test_a_worker_that_never_started_is_lost_after_the_grace():
    # The startup grace is the whole guard against a job stuck at "running"
    # forever because the child died before it could say anything.
    sim = _tmp("nostart")
    written = _job(pid=0, started=time.time() - jobs.STARTUP_GRACE_S - 1)
    jobs.write(sim, written)
    job = jobs.read(sim, written.id)
    assert job.state == jobs.LOST
    assert "never started" in job.error


def test_a_finished_job_is_never_second_guessed():
    # Its pid is long gone; the last write is the answer.
    sim = _tmp("finished")
    written = _job(pid=_dead_pid(), state=jobs.DONE, ended=time.time())
    jobs.write(sim, written)
    assert jobs.read(sim, written.id).state == jobs.DONE


def test_the_newest_jobs_come_back_first():
    sim = _tmp("recent")
    for stamp in ("20260901-090000", "20260902-090000", "20260903-090000"):
        jobs.write(sim, _job(id=stamp, pid=1, state=jobs.DONE))
    assert [j.id for j in jobs.recent(sim)] == [
        "20260903-090000",
        "20260902-090000",
        "20260901-090000",
    ]
    assert [j.id for j in jobs.recent(sim, limit=1)] == ["20260903-090000"]


def test_recent_on_a_board_that_has_never_run():
    assert jobs.recent(_tmp("norecent")) == []


# --------------------------------------------------------------------------- #
# the log
# --------------------------------------------------------------------------- #
def test_the_log_is_read_from_an_offset():
    sim = _tmp("log")
    written = _job(pid=1)
    jobs.write(sim, written)
    with open(jobs.log_path(sim, written.id), "w", encoding="utf-8") as handle:
        handle.write("one\ntwo\nthree\n")
    whole = jobs.log_lines(sim, written.id)
    stretch = jobs.resume(whole)
    assert stretch.lines == ["one", "two", "three"]
    assert (stretch.first, stretch.next) == (0, 3)
    caught_up = jobs.resume(whole, since=stretch.next)
    assert caught_up.lines == [] and caught_up.next == 3
    assert jobs.resume(whole, since=2).lines == ["three"]
    # An offset from before the file was truncated, or a caller's nonsense:
    # neither may throw a poller off the end of the log, and neither may make
    # `first` claim lines that were never read.
    assert jobs.resume(whole, since=99) == ([], 3, 3)
    assert jobs.resume(whole, since=-5) == (whole, 0, 3)


def test_two_jobs_write_two_logs():
    # A run and a scan are allowed at once, so one truncating log per board
    # would have the two workers fighting over one file.
    sim = _tmp("twologs")
    assert jobs.log_path(sim, "a") != jobs.log_path(sim, "b")


def test_a_job_with_no_log_yet_reads_as_no_lines():
    assert jobs.log_lines(_tmp("nolog"), "20260101-000000") == []


if __name__ == "__main__":
    run_module_tests(globals())
