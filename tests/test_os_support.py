"""The OS gate (antenna_plugin.sim.os_support): macOS is refused, and it is
refused where every launch goes through.

Delete this file with the gate -- see the module's own header for the rest of
what goes with it.

    python3 tests/test_os_support.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

os_support = load("sim.os_support")
simulate = load("sim.simulate")


def test_a_supported_host_is_not_gated():
    """The check is silent where a build exists -- and silence is the whole
    contract: nothing else in the plugin branches on it."""
    for platform in ("linux", "linux2", "win32", "cygwin"):
        assert os_support.check(platform) is None
        assert os_support.host_name(platform) is None


def test_macos_is_named():
    assert os_support.host_name("darwin") == "macOS"
    # sys.platform is "darwin" bare today, but the prefix match means a
    # future "darwin24" would still be caught rather than silently allowed.
    assert os_support.host_name("darwin24") == "macOS"


def test_the_refusal_says_which_os_and_why():
    try:
        os_support.check("darwin")
    except os_support.UnsupportedHost as exc:
        text = str(exc)
    else:
        raise AssertionError("macOS was not refused")
    assert "macOS" in text
    # It names the systems that do work, so the message is an answer and not
    # just a "no", and it says the plugin itself is still usable here.
    assert "Linux" in text and "Windows" in text
    assert "Drawing" in text


def test_it_is_a_runtime_error():
    """The GUI's run/scan paths catch Exception and print str(exc); the type
    exists for the one caller that tells this apart from a missing file."""
    assert issubclass(os_support.UnsupportedHost, RuntimeError)


def test_the_refusal_carries_a_table_cell_version_of_itself():
    """One refusal, both lengths: a caller that caught it never re-derives the
    OS and cannot end up saying two different things."""
    try:
        os_support.check("darwin")
    except os_support.UnsupportedHost as exc:
        assert exc.os_name == "macOS"
        assert exc.short == "not built for macOS"
        # The About page's rows carry versions, never paths (test_versions).
        assert "/" not in exc.short and "\\" not in exc.short
        assert exc.short in str(exc) or "macOS" in str(exc)


def test_locate_is_the_gate():
    """Every launch -- run, scan, the version probe -- reaches the binary
    through locate(), so gating it there covers all of them. Checked by making
    the real call refuse: the module-level hook is what the gate hangs on."""
    real_check = os_support.check
    try:
        os_support.check = lambda: real_check("darwin")
        try:
            simulate.locate()
        except os_support.UnsupportedHost:
            pass
        else:
            raise AssertionError("locate() handed out an executable on macOS")
    finally:
        os_support.check = real_check
    # ... and with the gate back to this host's truth, locate() is whatever it
    # was: on a checkout with the binaries present it finds one.
    assert simulate.os_support.check is real_check


def test_the_about_page_says_it_rather_than_not_found():
    """A plugin installed perfectly on a Mac is not one missing a file, and
    the Simulator row is where a user goes to check."""
    versions = load("versions")
    real_check = os_support.check
    try:
        os_support.check = lambda: real_check("darwin")
        assert versions.solver_version() == "not built for macOS"
    finally:
        os_support.check = real_check


if __name__ == "__main__":
    run_module_tests(globals())
