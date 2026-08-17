"""The area sliders' upper end: the board's own Edge.Cuts outline (no KiCad,
real wx stubbed).

An antenna area bigger than the board it has to sit on can never be placed, so
the wizard's Area width / height sliders stop at the board outline's span --
width at its span in x, height at its span in y. A board with no outline drawn
yet (or no board at all) has nothing to measure against, and the sliders keep
their default 2 .. 200 mm range.

What is pinned here: where the cap comes from (the Edge.Cuts bounding box, not
the board's whole bounding box, which every footprint and silk line grows), that
it survives the ways a value can be set (drag, typed readout, the design's
starter size), and that it is re-measured on refresh -- the outline can be drawn
or resized while the wizard is open.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_area_range.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
area_section = load("gui.sections.area")

wx = wx_stub.wx
pcbnew = sys.modules["pcbnew"]
pcbnew.ToMM = lambda nm: nm / 1e6

F0 = 2.45
FULL = area_section.SIDE_RANGE  # 2 .. 200 mm, in tenths


# --------------------------------------------------------------------------- #
# A fake KiCad board: an Edge.Cuts bounding box, and no footprints on it
# --------------------------------------------------------------------------- #
class _Box:
    def __init__(self, w_mm, h_mm):
        self._w, self._h = int(w_mm * 1e6), int(h_mm * 1e6)

    def GetWidth(self):
        return self._w

    def GetHeight(self):
        return self._h


class _Board:
    """Only what the area section asks a board: the outline's extent, and the
    footprints it looks for its marker among (never any -- the sliders' range
    is what these tests are about)."""

    def __init__(self, w_mm, h_mm):
        self.outline = _Box(w_mm, h_mm)

    def GetBoardEdgesBoundingBox(self):
        return self.outline

    def GetFootprints(self):
        return []


def _open(board):
    """Put ``board`` in the editor (None = no board open)."""
    pcbnew.GetBoard = lambda: board


class _Host:
    def target_freq_ghz(self, default=None):
        return F0

    def marker_layer_n(self):
        return 2


class _Page:
    def __init__(self, design):
        self.design = design
        self.scroll = None
        self.host = _Host()
        self.scan = None  # built after this section

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def refresh_area_checks(self):
        pass


def _section(board=None, design=None):
    """An Area section built against ``board`` (None = no board open), with the
    marker-layer picker the Advanced pane would add -- refresh_status names the
    layer through it."""
    _open(board)
    page = _Page(design or registry.DESIGNS[0])
    section = area_section.AreaSection(page, wx.BoxSizer())
    section.build_layer_picker(None, wx.FlexGridSizer())
    return section


def _ends(section):
    """The two side sliders' (width, height) upper ends, in slider units."""
    return (section.w.slider.GetMax(), section.h.slider.GetMax())


# --------------------------------------------------------------------------- #
# Where the cap comes from
# --------------------------------------------------------------------------- #
def test_no_board_keeps_the_full_range():
    section = _section(None)
    assert _ends(section) == (FULL[1], FULL[1])
    assert section.w.slider.GetMin() == FULL[0]


def test_no_outline_keeps_the_full_range():
    """Nothing drawn on Edge.Cuts: pcbnew answers a degenerate edge box (the
    same "no outline" the pre-flight blocks Run on), so there is nothing to
    cap against."""
    section = _section(_Board(0, 0))
    assert _ends(section) == (FULL[1], FULL[1])
    assert "No Edge.Cuts outline" in section.w.slider.tooltip


def test_the_outline_caps_each_side_on_its_own_axis():
    section = _section(_Board(40.0, 25.0))
    assert _ends(section) == (400, 250)  # tenths of a mm
    assert "40 mm" in section.w.slider.tooltip
    assert "in x" in section.w.slider.tooltip
    assert "25 mm" in section.h.slider.tooltip
    assert "in y" in section.h.slider.tooltip


def test_a_board_wider_than_the_range_caps_nothing():
    section = _section(_Board(500.0, 300.0))
    assert _ends(section) == (FULL[1], FULL[1])


def test_a_board_smaller_than_the_floor_does_not_invert_the_range():
    """A 1 mm board is under the 2 mm smallest side: the range keeps its floor
    rather than ending below its start."""
    section = _section(_Board(1.0, 0.5))
    assert _ends(section) == (FULL[0], FULL[0])
    assert section.w.slider.GetMin() == FULL[0]


def test_the_cap_rounds_down_to_stay_inside_the_board():
    section = _section(_Board(37.49, 20.06))
    assert _ends(section) == (374, 200)


# --------------------------------------------------------------------------- #
# What the cap holds against
# --------------------------------------------------------------------------- #
def test_the_starter_size_is_clamped_to_a_small_board():
    """The starting rectangle is the design's suggestion for the frequency,
    which on a board smaller than that suggestion has to give way."""
    for design in registry.DESIGNS:
        hint_w, hint_h = design.area_hint_mm(F0)
        section = _section(_Board(hint_w / 2.0, hint_h / 2.0), design)
        assert section.w_mm() <= hint_w / 2.0, design.key
        assert section.h_mm() <= hint_h / 2.0, design.key


def test_a_typed_value_is_clamped_to_the_board():
    """The readouts take a typed value straight -- through the same range the
    slider is capped to."""
    section = _section(_Board(30.0, 18.0))
    section.w._readout.type("120")
    section.h._readout.type("120")
    assert (section.w_mm(), section.h_mm()) == (30.0, 18.0)


def test_an_outline_drawn_later_caps_on_the_next_refresh():
    """The wizard stays open while the board is edited: a board opened (or an
    outline drawn / resized) after the section was built lands on refresh."""
    section = _section(None)
    section.w.set_value(150.0)
    section.h.set_value(150.0)

    _open(_Board(60.0, 45.0))
    section.refresh()
    assert _ends(section) == (600, 450)
    assert (section.w_mm(), section.h_mm()) == (60.0, 45.0)  # clamped down


def test_a_bigger_outline_gives_the_range_back():
    section = _section(_Board(20.0, 20.0))
    assert _ends(section) == (200, 200)
    _open(_Board(90.0, 70.0))
    section.refresh()
    assert _ends(section) == (900, 700)
    section.w._readout.type("85")
    assert section.w_mm() == 85.0


def test_the_board_going_away_restores_the_full_range():
    section = _section(_Board(20.0, 20.0))
    _open(None)
    section.refresh()
    assert _ends(section) == (FULL[1], FULL[1])


if __name__ == "__main__":
    run_module_tests(globals())
