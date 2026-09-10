"""Unit tests for antenna_plugin.sim.runsession -- the session that drives one
solver invocation: it watches the solver's stdout for the sets of outputs it
writes, and carries the stop / sample requests to it (appended to the run's
control file, which the solver is launched with and polls).

Two layers again:
  * the marker watch and the session's own state, against a scripted launcher
    (no binary, no processes);
  * the whole chain -- a stand-in solver that prints what the real one prints
    and polls its --control file the way the real one does is sampled mid-run
    and then stopped, driven through the real ``simulate.run_exe``. The
    channel is a file on every OS, so nothing here is platform-gated.

    python3 tests/test_runsession.py   (or pytest)
"""

import os
import pathlib
import sys
import tempfile
import threading
import time

from bare_package import load

_ROOT = pathlib.Path(__file__).resolve().parents[1]
runsession = load("emkit.sim.runsession")
runcontrol = load("emkit.sim.runcontrol")

# What a solver prints around one set of outputs (the shapes the session
# watches for), plus the noise it prints in between.
_SAMPLE_BANNER = (
    "--- Report sample: 3850 / 33856 steps, 2.27 of 20.00 ns simulated (running) ---"
)
_WROTE = "Wrote outputs to /tmp/sim/"

# Every scripted run drives a "config" in this directory, so the control file
# the session derives from it lands here too -- never in the checkout.
_TMP = tempfile.TemporaryDirectory()
_YAML = os.path.join(_TMP.name, "pcb.yaml")
_CTL = runcontrol.control_path(_YAML)


class FakeProc:
    def __init__(self):
        self.pid = 4711
        self.alive = True
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.killed = True
        self.alive = False


def _scripted(lines, proc=None):
    """A stand-in for simulate.run_exe that replays ``lines``."""
    calls = []

    def runner(
        exe, yaml_path, grid_only=False, on_line=None, on_proc=None, control=None
    ):
        calls.append((exe, yaml_path, grid_only, control))
        if on_proc:
            on_proc(proc or FakeProc())
        for line in lines:
            on_line(line)

    return runner, calls


def _session(lines, proc=None):
    logged, outputs = [], []
    runner, calls = _scripted(lines, proc)
    s = runsession.RunSession(
        on_line=logged.append, on_outputs=outputs.append, runner=runner
    )
    return s, logged, outputs, calls


# --- the marker watch -----------------------------------------------------
def test_every_line_is_forwarded_in_order():
    s, logged, _out, calls = _session(["  step 1000 / 33856", _WROTE, "done"])
    assert s.run("monopole", _YAML) is True
    assert logged == ["  step 1000 / 33856", _WROTE, "done"]
    assert calls == [("monopole", _YAML, False, _CTL)]


def test_a_final_set_of_outputs_is_reported():
    s, _log, outputs, _calls = _session(["  step 1000 / 33856", _WROTE])
    s.run("monopole", _YAML)
    assert outputs == [False]  # False = the run's final outputs
    assert s.samples_written == 0


def test_a_sample_is_reported_as_one():
    s, _log, outputs, _calls = _session(
        ["  step 500 / 33856", _SAMPLE_BANNER, _WROTE, "  step 1000 / 33856", _WROTE]
    )
    s.run("monopole", _YAML)
    # The banner marks the set that follows it as a sample; the run's own
    # final outputs later are not one.
    assert outputs == [True, False]
    assert s.samples_written == 1


def test_indented_markers_still_count():
    s, _log, outputs, _calls = _session(["   " + _SAMPLE_BANNER, "  " + _WROTE])
    s.run("monopole", _YAML)
    assert outputs == [True]


def test_the_grid_pass_writes_nothing():
    s, _log, outputs, calls = _session(["Wrote pcb_grid.html"])
    s.run("monopole", _YAML, grid_only=True)
    assert outputs == [] and calls[0][2] is True


def test_a_stale_control_file_is_cleared_before_launch():
    # A leftover "stop" from an earlier run in the same folder would end the
    # new run at the solver's first poll -- the launch must start it absent.
    with open(_CTL, "wb") as f:
        f.write(b"stop\n")
    s, _log, _out, calls = _session([_WROTE])
    s.run("monopole", _YAML)
    assert not os.path.exists(_CTL)
    assert calls[0][3] == _CTL  # and the solver was told where it is


# --- requests -------------------------------------------------------------
def test_stop_reaches_the_process_and_closes_the_session():
    proc = FakeProc()
    s, _log, _out, calls = _session([_WROTE], proc)
    s.run("monopole", _YAML)
    assert s.request_stop() is True and s.stop_requested
    with open(_CTL, "rb") as f:
        assert f.read() == b"stop\n"
    # A stopped session refuses to start another phase, so a request that
    # lands between two solver processes can't be lost.
    assert s.run("monopole", _YAML) is False
    assert len(calls) == 1


def test_sample_keeps_the_session_open():
    proc = FakeProc()
    s, _log, _out, calls = _session([_WROTE], proc)
    s.run("monopole", _YAML)
    assert s.request_sample() is True
    assert s.samples_requested == 1 and not s.stop_requested
    with open(_CTL, "rb") as f:
        assert f.read() == b"sample\n"
    assert s.run("monopole", _YAML) is True
    assert len(calls) == 2


def test_requests_to_a_dead_process_report_false():
    proc = FakeProc()
    s, _log, _out, _calls = _session([_WROTE], proc)
    s.run("monopole", _YAML)
    proc.alive = False
    assert s.request_stop() is False and not s.stop_requested
    assert s.request_sample() is False
    # A session with no process yet has nothing to reach either.
    fresh = runsession.RunSession(runner=lambda *a, **k: None)
    assert fresh.request_stop() is False and fresh.request_sample() is False


def test_kill_closes_the_session():
    proc = FakeProc()
    s, _log, _out, calls = _session([_WROTE], proc)
    s.run("monopole", _YAML)
    assert s.kill() is True and proc.killed
    assert s.run("monopole", _YAML) is False
    assert len(calls) == 1


def test_a_process_that_starts_after_a_kill_is_killed_too():
    # The window between "kill the session" and "the next phase launched a
    # process": whoever attaches it finds the session closed.
    late = FakeProc()
    s = runsession.RunSession()
    s.kill()
    s.attach(late)
    assert late.killed


def test_running_follows_the_process():
    proc = FakeProc()
    s = runsession.RunSession()
    assert s.running is False
    s.attach(proc)
    assert s.running is True
    proc.alive = False
    assert s.running is False


# --- the whole chain, over a real process and control file -----------------
# A stand-in for the solver, printing what the real one prints and consuming
# its --control file the way the real ControlFileReader does: only complete
# lines, each acted on once. A sample request writes a banner plus a set of
# outputs and the run continues; a stop request writes one final set and
# exits 0 (never a kill's non-zero).
_FAKE_SOLVER = f"""
import sys, time

ctl = sys.argv[sys.argv.index("--control") + 1]
consumed = 0
print("ready", flush=True)
for _ in range(400):
    try:
        with open(ctl, "rb") as f:
            data = f.read()
    except OSError:
        data = b""
    complete = data[:data.rfind(b"\\n") + 1]
    fresh, consumed = complete[consumed:], len(complete)
    for line in fresh.splitlines():
        if line == b"sample":
            print({_SAMPLE_BANNER!r}, flush=True)
            print({_WROTE!r}, flush=True)
        elif line == b"stop":
            print("Run: 3850 / 33856 steps (interrupted)", flush=True)
            print({_WROTE!r}, flush=True)
            sys.exit(0)
    time.sleep(0.05)
print({_WROTE!r}, flush=True)
"""


def _run_fake_solver():
    """Drive the stand-in solver through the real run_exe on a worker thread,
    exactly as the GUI does, and wait until it is up. Returns the session, the
    outputs it saw, the errors run_exe raised, and the thread."""
    outputs, errors, ready = [], [], threading.Event()

    def on_line(line):
        if line.strip() == "ready":
            ready.set()

    session = runsession.RunSession(on_line=on_line, on_outputs=outputs.append)
    script = pathlib.Path(_TMP.name) / "fake_solver.py"
    script.write_text(_FAKE_SOLVER, encoding="utf-8")

    def drive():
        # The GUI's worker catches this the same way (a killed solver exits
        # non-zero, which run_exe raises on).
        try:
            session.run(sys.executable, str(script))
        except Exception as exc:
            errors.append(exc)

    # run_exe builds [exe, yaml_path, --control ...]; with the interpreter as
    # the "binary" and the script as its "config" that is a real, streamed
    # subprocess reached through a real control file.
    thread = threading.Thread(target=drive, daemon=True)
    thread.start()
    assert ready.wait(30), "the stand-in solver never started"
    return session, outputs, errors, thread


def test_sampling_and_stopping_a_real_process():
    session, outputs, errors, thread = _run_fake_solver()
    try:
        assert session.request_sample() is True
        _wait_for(lambda: len(outputs) == 1)
        assert outputs == [True] and session.samples_written == 1
        # The solve is still going -- that is the whole point of a sample.
        assert session.running

        assert session.request_stop() is True
        thread.join(timeout=30)
        assert not thread.is_alive(), "the stopped solver never exited"
        # The stop produced one more set of outputs: the run's final ones,
        # and the solver exited cleanly (a stop is not a failure).
        assert outputs == [True, False]
        assert session.samples_written == 1
        assert errors == []
    finally:
        session.kill()


def test_killing_a_real_process_writes_nothing():
    session, outputs, errors, thread = _run_fake_solver()
    assert session.kill() is True
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert outputs == []
    # A killed solver exits non-zero; the caller hears about it and maps it to
    # its own "cancelled".
    assert len(errors) == 1 and "exited with code" in str(errors[0])


def _wait_for(pred, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the solver")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
