"""The update strip's own behaviour (antenna_plugin.update.strip), off KiCad.

Built on the wx stand-in (tests/wx_stub), so this is about the strip's state
machine and not about layout: does it stay invisible until there is something
to say, does it say it once, does ✕ put it away, and -- the point of the whole
feature -- does a check that fails leave the window untouched with only a log
line to show for it.

    python3 tests/test_update_strip.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401  (installs the stand-in wx before the import below)
from bare_package import load, run_module_tests  # noqa: E402

strip_mod = load("emkit.update.strip")
model = load("emkit.update.model")

RELEASE = model.Release(
    version="0.2.0", url="https://example.invalid/releases/0.2.0", name="0.2.0"
)


def _strip(release=RELEASE, current="0.1.0", raises=None):
    """A started strip, its check answered by a stub source, joined -- so the
    outcome has landed by the time the test looks (wx_stub's CallAfter runs
    inline, standing in for the wx thread)."""
    log = []
    strip = strip_mod.UpdateStrip(None, log=log.append)
    source = _raise(raises) if raises is not None else (lambda: release)
    thread = strip.start(current, source=source)
    thread.join(timeout=5)
    return strip, log


def _raise(exc):
    def source():
        raise exc

    return source


def test_a_newer_release_shows_the_strip_with_a_link():
    strip, log = _strip()
    assert strip.shown is True
    labels = [w.GetLabel() for w in strip._sizer.items]
    assert any("0.2.0 is available" in text for text in labels)
    assert any("0.1.0" in text for text in labels), "it says what is installed"
    # The link carries the release URL (as a hyperlink where the host's wx has
    # one, else a button -- the stand-in wx has neither, so this is the
    # fallback path, and the URL is on its tooltip either way).
    assert any(w.tooltip == RELEASE.url for w in strip._sizer.items)
    assert any(RELEASE.url in line for line in log)


def test_an_up_to_date_install_shows_nothing():
    strip, log = _strip(current="0.2.0")
    assert strip.shown is False
    assert log == []


def test_a_failed_check_only_logs():
    """No network, a proxy, a rate limit: the window is exactly as it was."""
    strip, log = _strip(raises=OSError("Name or service not known"))
    assert strip.shown is False
    assert len(log) == 1 and "update check" in log[0]
    assert strip.outcome.status == "failed"


def test_dismissing_puts_it_away():
    strip, _log = _strip()
    strip._on_dismiss()
    assert strip.shown is False


def test_the_check_runs_once_per_window():
    strip, _log = _strip()
    assert strip.start("0.1.0", source=lambda: RELEASE) is None


def test_a_window_closed_mid_check_is_survivable():
    """The answer lands after the widgets are gone: wx raises RuntimeError off
    a destroyed window, and that must die here rather than in the wx loop."""
    strip = strip_mod.UpdateStrip(None)
    strip._current = "0.1.0"

    def boom(_release):
        raise RuntimeError("wrapped C/C++ object has been deleted")

    strip._show_update = boom
    strip._landed(model.Outcome("update", release=RELEASE))
    assert strip.outcome.status == "update"


if __name__ == "__main__":
    run_module_tests(globals())
