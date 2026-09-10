"""The application object a command line has to make for itself.

pcbnew's C++ side assumes something has constructed a wxApp: a board load or
save reaches ``wxStandardPaths::Get()``, which asks it for its traits and
asserts when there is none -- ``create wxApp before calling this``, which on a
build with assertions live kills the command before it prints a line. The
window inherits KiCad's; every verb goes through ``agent.kicad.pcbnew()``, so
that is where the headless half makes one.

    python3 tests/test_agent_wx_app.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

kicad = load("emkit.agent.kicad")


def test_the_door_to_pcbnew_makes_the_app_first():
    """Not a detail of ``board()`` or of any one verb: whatever reaches pcbnew
    reaches it through here, and the assert fires on the first call that
    touches wx, not on the import."""
    called = []
    real = kicad.wx_app
    kicad.wx_app = lambda: called.append(True)
    try:
        try:
            kicad.pcbnew()
        except RuntimeError:
            pass  # no pcbnew on this Python -- the message is another test's
    finally:
        kicad.wx_app = real
    assert called, "pcbnew() reached the module without settling wx first"


class _Wx:
    """The three names ``wx_app`` uses, recording what it did with them. A
    stand-in rather than the real wx because the suite already installs a wx
    of its own (``wx_stub``), and because the branch worth testing is the one
    on a machine that has no application object yet -- which a process running
    tests, under either wx, is not."""

    LOG_Warning = 3

    def __init__(self):
        self.made = 0
        self.level = None
        self.Log = self
        self.AppConsole = self._console

    def GetApp(self):
        return None

    def _console(self):
        self.made += 1
        return f"app {self.made}"

    def SetLogLevel(self, level):
        self.level = level


def test_it_is_a_console_app_made_once_and_it_quietens_wx():
    """``AppConsole``, not ``App``: a display-less machine gets one too, and
    on a display-full one nothing must appear on screen. Made once, because wx
    allows one per process -- and the logging wx starts doing once it has
    somewhere to put it is not this program's output."""
    fake = _Wx()
    saved = sys.modules.get("wx"), kicad._app
    sys.modules["wx"] = fake
    kicad._app = None
    try:
        kicad.wx_app()
        kicad.wx_app()
    finally:
        real, kicad._app = saved
        if real is None:
            del sys.modules["wx"]
        else:
            sys.modules["wx"] = real
    assert fake.made == 1, "one app per process, and this made another"
    assert fake.level == fake.LOG_Warning, "pcbnew's debug chatter is not output"


if __name__ == "__main__":
    run_module_tests(globals())
