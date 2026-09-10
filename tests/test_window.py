"""The window builds: every page, every section, off KiCad.

Pressing the toolbar button constructs one object graph -- the shell, its
pages, and every section on them -- and any name that graph gets wrong is an
"X failed to open" box with a KiCad log line behind it. It is also the widest
piece of the plugin no test touched: the sections were covered one at a time,
each with a fake page that answered exactly what that section asked for, so a
section asking its *real* page for something it does not have went unnoticed
until the window was opened. ``page.form.update_hint`` was that.

So this builds the real shell on the wx stand-in and looks at what came out.
It asserts very little about the result on purpose: what it is for is that
constructing it raises nothing, and the assertions are only enough to prove
the graph is the plugin's rather than an empty stub.

Not a substitute for wx: no layout happens, nothing is drawn, and a stub
control answers for a real one. What it does prove is that every section this
product composes can be built beside the others it is composed with.

    python3 tests/test_window.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_pcbnew  # noqa: E402,F401  (a pcbnew with a board in it)
import wx_stub  # noqa: E402,F401  (installs the empty wx / pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

shell_module = load("gui.shell")
core_shell = load("emkit.gui.shell")


def _shell():
    """This product's window, built the way its ``gui.show`` builds it."""
    classes = [
        value
        for value in vars(shell_module).values()
        if isinstance(value, type)
        and issubclass(value, core_shell.Shell)
        and value is not core_shell.Shell
    ]
    assert len(classes) == 1, f"one window per plugin, found {classes}"
    return classes[0](None)


def test_the_window_builds():
    window = _shell()
    assert window._pages, "a window with no pages"
    # The first is the primary page: the log, the viewers and the settings are
    # its, and the shell hands the others to it.
    assert window.primary is window._pages[0]


def test_every_page_is_built_and_named():
    for page in _shell()._pages:
        assert page.tab_label, f"{type(page).__name__} has no tab label"
        assert page.tab_icon, f"{type(page).__name__} has no tab icon"


def test_the_primary_page_answers_what_the_run_flow_asks_of_it():
    """The core's run section reads these off the page it is on. A page that
    composes the flow without them is a Run button that raises."""
    page = _shell().primary
    for name in ("form", "run", "results", "speed", "banner", "log_ctrl"):
        assert getattr(page, name, None) is not None, name


def test_the_about_page_is_there_and_is_last():
    """It pins itself to the foot of the sidebar, which is a claim about the
    page rather than about the window -- so the window has to hold one."""
    pages = _shell()._pages
    assert pages[-1].tab_at_bottom
    assert pages[-1].tab_label == "About"


if __name__ == "__main__":
    run_module_tests(globals())
