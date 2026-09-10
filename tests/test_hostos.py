"""What still differs per OS about running the bundled solver: its launch
flags, and whether a pid is still there.

(Reaching a running solver is deliberately NOT here: stop and sample requests
go through the solver's --control file, identical on every OS --
tests/test_runcontrol.py. Neither is *which* binary to launch: a build is per
machine rather than per OS, and choosing between them is tests/test_builds.py.)

Every function takes the OS name, so the branch this machine is not is tested
on the machine it is. That matters more than usual here, because two of the
answers below are ones a Linux-only checkout would otherwise ship broken:
``start_new_session`` is silently ignored on Windows, and ``os.kill(pid, 0)``
*terminates* the process it claims to probe there.

    python3 tests/test_hostos.py   (or pytest)
"""

import os
import subprocess
import sys

from bare_package import CORE, load

hostos = load("emkit.sim.hostos")


# --------------------------------------------------------------------------- #
# launching
# --------------------------------------------------------------------------- #
def test_a_watched_solver_gets_no_flags_on_posix_and_no_window_on_windows():
    assert hostos.launch_kwargs(name="posix") == {}
    no_window = {"creationflags": hostos.CREATE_NO_WINDOW}
    assert hostos.launch_kwargs(name="nt") == no_window


def test_a_detached_worker_is_detached_on_both():
    # The defect this pins: `start_new_session` is POSIX-only and Windows
    # ignores it, leaving the child in the shell's console -- so closing that
    # console would take a seven-minute solve with it, which is the exact
    # thing detaching was for.
    assert hostos.launch_kwargs(detached=True, name="posix") == {
        "start_new_session": True
    }
    windows = hostos.launch_kwargs(detached=True, name="nt")["creationflags"]
    assert windows & hostos.DETACHED_PROCESS
    assert windows & hostos.CREATE_NEW_PROCESS_GROUP


def test_the_flags_are_this_hosts_by_default():
    assert hostos.launch_kwargs() == hostos.launch_kwargs(name=os.name)


# --------------------------------------------------------------------------- #
# liveness
# --------------------------------------------------------------------------- #
def test_this_process_is_alive_and_a_reaped_child_is_not():
    assert hostos.alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    assert hostos.alive(proc.pid) is False


def test_nothing_is_a_pid():
    assert hostos.alive(0) is False
    assert hostos.alive(None) is False
    assert hostos.alive(-1) is False


def test_the_windows_probe_never_signals_the_process():
    """The severe one. On Windows CPython maps every signal but the two
    console events onto TerminateProcess, so ``os.kill(pid, 0)`` kills what it
    measures -- with exit code 0, which then reads as a clean finish. Drive
    the nt branch here and assert os.kill is never reached; there is no
    ctypes.windll on this host, so the unknown answer falls to the bias."""
    called = []
    real_kill = os.kill
    os.kill = lambda *a, **k: called.append(a)
    try:
        assert hostos.alive(os.getpid(), name="nt") is True
    finally:
        os.kill = real_kill
    assert called == []


def test_os_kill_is_named_in_one_module_only():
    """The cheap half of the same test. Every other module reads liveness
    from here, so a copy of the probe growing back somewhere under sim/ is a
    copy that is wrong on Windows again."""
    guilty = [
        path.relative_to(CORE).as_posix()
        for path in sorted((CORE / "sim").rglob("*.py"))
        if "os.kill" in path.read_text(encoding="utf-8")
    ]
    assert guilty == ["sim/hostos.py"], guilty


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
