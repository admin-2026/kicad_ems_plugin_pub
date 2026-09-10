"""The run log: a solver warning does not scroll away.

The bug this holds shut is not a crash. The solver says what it made of the
board once, at meshing time -- ``WARNING [GND-004]: ...`` -- and then prints
thousands of step lines over it, so by the time anybody looks the line is gone
off the top of the control (the log keeps its newest MAX_LINES and drops the
rest). Pre-flight's banner is empty and honest all the while: it reads the
board and answers before a solver has been launched.

So two things are asserted here, and the second is the one that matters:

  * a diagnostic line is written in a different weight from the flood;
  * the standing line under the log names every diagnostic the *run* has
    printed, and is still there after the lines themselves have been trimmed
    away.

wx is a stand-in (wx_stub), so nothing here proves a pixel. What it proves is
what the section decides: which lines are loud, what the standing line says,
and when the form is relaid out for it.

    python3 tests/test_log_section.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: E402  (installs the empty wx / pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

log_section = load("emkit.gui.sections.log")
wx = wx_stub.wx

WARNING = "WARNING [GND-004]: port 1: the feed direction points toward +x"
ERROR = "error [FEED-016]: port 1: the feed point sits on 5.75 mm of copper"
STEP = "step 1000  |E| 1.2e-03"


class _Page:
    """The handful of things a section asks its page for."""

    def __init__(self):
        self.scroll = wx.Panel(None)
        self.relayouts = 0

    def register_wrap(self, _label):
        pass

    def _relayout_scroll(self):
        self.relayouts += 1


def _section():
    page = _Page()
    return log_section.LogSection(page, wx.BoxSizer(wx.VERTICAL)), page


def _appends(ctrl):
    """Record what reaches the control, one entry per AppendText call -- which
    is how the batching is read back: a run of same-weight lines is one call."""
    written = []
    ctrl.AppendText = written.append
    return written


# --------------------------------------------------------------------------- #
# Which lines are loud
# --------------------------------------------------------------------------- #
def test_a_diagnostic_is_marked_and_the_flood_is_not():
    section, _page = _section()
    for text in (STEP, WARNING, STEP):
        section.log(text)
    assert [loud for _text, loud in section.ctrl._shown] == [False, True, False]


def test_lines_of_one_weight_are_written_in_one_call():
    """A batch of a thousand step lines must stay one AppendText: the log is
    drained by a single CallAfter precisely so a fast solver cannot flood the
    event queue, and a call per line would put the flood back."""
    section, _page = _section()
    ctrl = section.ctrl
    written = _appends(ctrl)
    ctrl._write([(STEP, False), (STEP, False), (WARNING, True), (STEP, False)])
    assert written == [f"{STEP}\n{STEP}\n", f"{WARNING}\n", f"{STEP}\n"]


# --------------------------------------------------------------------------- #
# The standing line
# --------------------------------------------------------------------------- #
def test_the_standing_line_names_what_the_run_warned_about():
    section, page = _section()
    assert section.standing == ""  # a run that has said nothing says nothing
    before = page.relayouts
    section.log(STEP)
    assert section.standing == "" and page.relayouts == before
    section.log(WARNING)
    section.log(ERROR)
    assert section.standing == "⚠ 1 error and 1 warning in this run — " + (
        "GND-004, FEED-016"
    )
    assert page.relayouts > before, "the line appeared; the form was not relaid out"


def test_the_line_outlives_the_lines_it_is_about():
    """The whole point. The warning is printed once, at meshing time, and the
    solve then prints past MAX_LINES of steps over it -- so the log control no
    longer holds it at all, and the standing line is the only thing left that
    knows."""
    section, _page = _section()
    section.log(WARNING)
    for _ in range(log_section.MAX_LINES + 1):
        section.log(STEP)
    assert WARNING not in section.ctrl.GetValue()  # trimmed off the top
    assert WARNING not in [text for text, _loud in section.ctrl._shown]
    assert "GND-004" in section.standing


def test_an_unchanged_line_does_not_relayout_the_form():
    """It is rebuilt from the whole list on every flush, and this section takes
    the page's spare height -- so a line that says what it already said must
    not move the form under the reader's pointer once per solver line."""
    section, page = _section()
    section.log(WARNING)
    settled = page.relayouts
    for _ in range(20):
        section.log(STEP)
    assert page.relayouts == settled


def test_a_new_run_starts_with_a_clean_slate():
    """The page clears the log at the top of a run (RunSection); the standing
    line is about the run that is starting, not the one before it."""
    section, _page = _section()
    section.log(WARNING)
    section.ctrl.Clear()
    assert section.standing == ""
    assert section.ctrl._shown == [] and section.ctrl._found == []


def test_many_diagnostics_are_counted_rather_than_listed():
    """One line under a log, not a report: the log above holds every message
    in full, and the tooltip carries them for a reader who has scrolled away."""
    section, _page = _section()
    for index in range(log_section.NAMED + 3):
        section.log(f"WARNING [GND-{index:03d}]: something about port 1")
    assert "and 3 more" in section.standing
    assert f"{log_section.NAMED + 3} warnings" in section.standing


def test_a_failure_with_no_id_is_counted_without_being_named():
    """What the run flow writes when something breaks on this side of the
    binary: it is in the same log and it is an error, but there is no
    catalogue id to name, and "— error" would read as one."""
    section, _page = _section()
    section.log("ERROR: could not plot the gerbers")
    assert section.standing == "⚠ 1 error in this run"


if __name__ == "__main__":
    run_module_tests(globals())
