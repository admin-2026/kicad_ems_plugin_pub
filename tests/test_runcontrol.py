"""Unit tests for antenna_plugin.sim.runcontrol -- the policy around the three
things that can be asked of a running solver: stop it, sample it, kill it.

The cooperative requests travel through the solver's --control file (appended
request lines the solver polls), so delivery is the same on every OS and is
tested here for real, against a temp file. What the policy layer owes its
callers:

  * a request only reaches a process that is still running;
  * a request that could not be posted comes back False -- the caller
    (RunSection._stop_run) has to know it must fall back to killing, and
    would otherwise wait forever for a report nobody is writing;
  * posted lines are exactly what the solver's ControlFileReader parses:
    whole lines, appended, never rewriting what came before;
  * kill is best effort and never raises.

    python3 tests/test_runcontrol.py   (or pytest)
"""

import importlib
import os
import pathlib
import sys
import tempfile
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
runcontrol = importlib.import_module("antenna_plugin.sim.runcontrol")


class FakeProc:
    """A Popen stand-in: alive until it 'exits' or is killed."""

    def __init__(self, alive=True, raises=None):
        self.pid = 4711
        self._alive = alive
        self._raises = raises
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        if self._raises:
            raise self._raises
        self.killed = True
        self._alive = False


def _read(path):
    with open(path, "rb") as f:
        return f.read()


# --- state ------------------------------------------------------------------
def test_alive_tracks_the_process():
    assert runcontrol.alive(FakeProc())
    assert not runcontrol.alive(FakeProc(alive=False))
    assert not runcontrol.alive(None)


def test_kill_is_best_effort():
    proc = FakeProc()
    assert runcontrol.kill(proc) is True and proc.killed
    # Already gone, never launched, or refusing to die: never an exception.
    assert runcontrol.kill(FakeProc(alive=False)) is False
    assert runcontrol.kill(None) is False
    assert runcontrol.kill(FakeProc(raises=OSError("gone"))) is False


# --- the control file -------------------------------------------------------
def test_the_control_file_sits_next_to_the_yaml():
    got = runcontrol.control_path(os.path.join("some", "run", "pcb.yaml"))
    want = os.path.join(os.path.abspath(os.path.join("some", "run")), "run.ctl")
    assert got == want


def test_requests_append_whole_lines():
    with tempfile.TemporaryDirectory() as tmp:
        ctl = os.path.join(tmp, "run.ctl")
        proc = FakeProc()
        assert runcontrol.request_sample(proc, ctl) is True
        assert _read(ctl) == b"sample\n"
        # Appended, not rewritten: the solver has consumed the first line by
        # its own offset and must never see the file shrink mid-run. And no
        # CRLF, whatever OS wrote it -- one parser on the other end.
        assert runcontrol.request_stop(proc, ctl) is True
        assert _read(ctl) == b"sample\nstop\n"


def test_no_live_process_means_nothing_is_posted():
    with tempfile.TemporaryDirectory() as tmp:
        ctl = os.path.join(tmp, "run.ctl")
        assert runcontrol.request_stop(None, ctl) is False
        assert runcontrol.request_sample(FakeProc(alive=False), ctl) is False
        # A request that wasn't delivered leaves no line behind to replay
        # into some later run.
        assert not os.path.exists(ctl)


def test_an_unpostable_request_reports_false():
    # No channel (a launch without --control: the wizard scan): honest False,
    # the caller falls back to killing.
    assert runcontrol.request_stop(FakeProc(), None) is False
    # A channel that can't be written (run directory gone): False, not a
    # pretence that the solver will react.
    gone = os.path.join(tempfile.gettempdir(), "no-such-dir-4711", "run.ctl")
    assert runcontrol.request_sample(FakeProc(), gone) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
