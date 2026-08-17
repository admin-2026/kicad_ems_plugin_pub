"""Unit tests for antenna_plugin.sim.hostos -- the little that still differs
per OS about running the bundled solver: the binary's name and its launch
flags. (Reaching a running solver is deliberately NOT here any more: stop and
sample requests go through the solver's --control file, identical on every
OS -- tests/test_runcontrol.py.)

    python3 tests/test_hostos.py   (or pytest)
"""

import importlib
import os
import pathlib
import subprocess
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
hostos = importlib.import_module("antenna_plugin.sim.hostos")

# CREATE_NO_WINDOW only exists in subprocess on Windows, so the flag the
# module asks for there has to be stated here to test for it.
_CREATE_NO_WINDOW = 0x08000000


def test_the_binary_is_named_per_os():
    # The running OS's own convention first; the other name stays as a
    # fallback, because both do occur (CreateProcess doesn't insist on the
    # extension, and WSL runs a .exe through its interop layer).
    if os.name == "nt":
        assert hostos.exe_names("monopole") == ("monopole.exe", "monopole")
    else:
        assert hostos.exe_names("monopole") == ("monopole", "monopole.exe")


def test_only_windows_adds_launch_flags():
    had = hasattr(subprocess, "CREATE_NO_WINDOW")
    if not had:
        # POSIX: nothing to add.
        assert hostos.launch_kwargs() == {}
        subprocess.CREATE_NO_WINDOW = _CREATE_NO_WINDOW  # stand in for it
    try:
        # Windows: keep a console window from flashing up under a GUI host.
        assert hostos.launch_kwargs() == {"creationflags": subprocess.CREATE_NO_WINDOW}
    finally:
        if not had:
            del subprocess.CREATE_NO_WINDOW


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
