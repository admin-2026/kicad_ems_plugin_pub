"""The import guard: who gets a toolbar button registered for them.

The package's ``__init__`` registers an ``ActionPlugin`` on import. That is
right under KiCad and wrong everywhere else -- and "everywhere else" now
includes the command line, which runs on KiCad's *own* interpreter, so "is
pcbnew importable" cannot be the question. What is asked instead is who called
(emkit/kicad/hosted.py), and the bias is to register: a stray line on stderr
beats a missing toolbar button.

    python3 tests/test_hosted.py   (or pytest)
"""

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import PKG, load, run_module_tests  # noqa: E402

hosted = load("emkit.kicad.hosted")


def test_a_python_dash_m_run_is_not_kicad():
    # runpy is on the stack for the whole of the import `python -m` triggers.
    assert hosted.hosted(["antenna_plugin", "runpy", "__main__"]) is False
    assert hosted.hosted(["antenna_plugin", "runpy._run_module_as_main"]) is False


def test_kicads_loader_is_kicad():
    assert hosted.hosted(["antenna_plugin", "pcbnew", "__main__"]) is True


def test_a_caller_nobody_recognises_still_gets_the_button():
    # The whole bias: a plugin that fails to appear is worse than a stray line
    # on stderr, so anything unidentified counts as KiCad.
    assert hosted.hosted(["antenna_plugin", "some_launcher", "__main__"]) is True
    assert hosted.hosted([]) is True


def test_the_live_stack_is_what_is_read_by_default():
    assert hosted.caller_modules()[0] == __name__
    assert hosted.hosted() in (True, False)


def test_a_python_dash_m_run_of_this_package_says_nothing_at_all():
    """The end of it, for real: import the package with ``python -m`` in a
    plain Python that has no pcbnew. Before the guard this was an ImportError
    on the way to a failed assertion; with it, it is silence -- which is what
    every verb's output depends on."""
    out = subprocess.run(
        [sys.executable, "-m", f"{PKG.name}.emkit.versions"],
        cwd=str(PKG.parent),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout == ""
    assert out.stderr == ""


if __name__ == "__main__":
    run_module_tests(globals())
