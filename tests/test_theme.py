"""The shared section frame (no KiCad, real wx stubbed).

Every group of controls in the window is built by gui.theme -- a heading over a
hairline rule -- so what a page looks like is one function, not a habit each
section keeps up on its own. Two things about it are worth pinning:

* a section's *step number* comes from the page (the designers number their
  sections 1..7; the simulate view builds several of the same sections and
  numbers none of them), so the same section reads "2 · Scan" on one page and
  "Scan" on the other;
* the frame is a heading plus a rule, and nested groups drop the rule -- that
  is what keeps one page from showing two weights of the same device.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_theme.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

theme = load("emkit.gui.theme")
base = load("emkit.gui.sections.base")
wx = wx_stub.wx


class _Page:
    """A page, as far as a Section reads one: the window its widgets parent on."""

    scroll = wx.Panel()

    def register_wrap(self, label):
        pass


def _heading(box):
    return box.items[0].GetLabel()


# --------------------------------------------------------------------------- #
# The frame
# --------------------------------------------------------------------------- #
def test_a_section_is_a_heading_over_a_rule():
    box = theme.section_box(_Page.scroll, "Run")
    assert _heading(box) == "Run"
    assert isinstance(box.items[1], wx.StaticLine)


def test_a_group_inside_a_section_drops_the_rule():
    # One rule per level: the sections of the page carry them, the groups
    # inside the Advanced pane don't.
    box = theme.group_box(_Page.scroll, "Mesh")
    assert _heading(box) == "Mesh"
    assert not any(isinstance(item, wx.StaticLine) for item in box.items)


# --------------------------------------------------------------------------- #
# Step numbers
# --------------------------------------------------------------------------- #
def test_the_page_numbers_a_section_not_the_section_itself():
    numbered = base.Section(_Page(), step=2).box("Scan")
    plain = base.Section(_Page()).box("Scan")
    assert _heading(numbered) == "2 · Scan"
    assert _heading(plain) == "Scan"


def test_a_step_of_zero_is_still_a_number():
    # None is "this page numbers nothing", which a falsy step must not be
    # mistaken for.
    assert theme.numbered("Scan", 0) == "0 · Scan"
    assert theme.numbered("Scan", None) == "Scan"


if __name__ == "__main__":
    run_module_tests(globals())
