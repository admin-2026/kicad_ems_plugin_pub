"""Unit tests for the wizard's drawn antenna preview (area_marker.draw_antenna
/ clear_antenna) against a minimal fake pcbnew footprint.

The preview is the one thing the plugin draws inside the area marker -- on the
feed copper layer while the candidate fits the area, on the marker's own User
layer while it doesn't -- and the one thing that survives a board save:
reopened, its shapes belong to KiCad -- the editor's view, the connectivity
graph, the selection and the undo stack all point at them -- so unlinking one
from a plugin frees an object KiCad still uses and takes the editor down with
it (the crash these tests pin: open a board whose marker already carries a
preview, switch to a designer, the wizard redraws the candidate).

So what is asserted here is *identity*, not just geometry: a redraw must reuse
the shapes already on the marker, and the surplus a shorter candidate leaves
must be detached without ever being freed (``thisown`` cleared). The fake
footprint below records every Remove so the tests can hold the line.

The package is assembled by hand around the real modules because
antenna_plugin/__init__ imports pcbnew:  python3 tests/test_area_preview.py
"""

import importlib
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]

_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
area_marker = importlib.import_module("antenna_plugin.markers.area_marker")


# --------------------------------------------------------------------------- #
# A fake KiCad: the footprint graphics draw_antenna writes, and nothing else
# --------------------------------------------------------------------------- #
class _FakeShape:
    """A stand-in for a footprint PCB_SHAPE: the setters the preview writes,
    plus the ``thisown`` flag every SWIG proxy carries -- True is "Python will
    free the C++ object", which is exactly what must not happen here."""

    def __init__(self, parent=None):
        self.parent = parent
        self.thisown = True
        self.shape = None
        self.points = []
        self.layer = None
        self.filled = None
        self.width = None
        self.writes = 0  # how often this shape was rewritten

    # -- setters the preview uses
    def SetShape(self, shape):
        self.shape = shape

    def SetPolyPoints(self, points):
        self.points = list(points)
        self.writes += 1

    def SetLayer(self, layer):
        self.layer = layer

    def SetFilled(self, filled):
        self.filled = filled

    def SetWidth(self, width):
        self.width = width

    # -- readers the item walk uses
    def GetLayer(self):
        return self.layer

    def GetShape(self):
        return self.shape

    def corners_mm(self):
        """The polygon back in KiCad mm, for comparing against _rect_corners."""
        return [(x / 1e6, y / 1e6) for (x, y) in self.points]


class _FakeFootprint:
    """A placed marker: an ordered list of graphics, and a log of everything
    ever unlinked from it (the tests' whole point)."""

    def __init__(self):
        self._items = []
        self.removed = []

    def GraphicalItems(self):
        return list(self._items)

    def Add(self, item):
        self._items.append(item)

    def Remove(self, item):
        self._items.remove(item)
        self.removed.append(item)


class _FakePcbnew(types.ModuleType):
    """Enough pcbnew for the preview: KiCad 7+ shaped (a PCB_SHAPE with no
    FP_SHAPE and no SetLocalCoord, so no local-coordinate sync)."""

    FromMM = staticmethod(lambda mm: int(round(mm * 1e6)))
    VECTOR2I = staticmethod(lambda x, y: (x, y))
    SHAPE_T_SEGMENT = 0
    SHAPE_T_POLYGON = 4
    F_Cu, B_Cu = 0, 31
    PCB_SHAPE = _FakeShape


_FAKE_PCBNEW = _FakePcbnew("pcbnew")
for _n in range(1, 10):  # User.1 .. User.9, the marker's own
    setattr(_FAKE_PCBNEW, f"User_{_n}", 50 + _n)
_USER_1 = _FAKE_PCBNEW.User_1


def _with_fake_pcbnew(fn):
    saved = sys.modules.get("pcbnew")
    sys.modules["pcbnew"] = _FAKE_PCBNEW
    try:
        return fn()
    finally:
        if saved is None:
            del sys.modules["pcbnew"]
        else:
            sys.modules["pcbnew"] = saved


def _run(segments, fp=None, layer=_FakePcbnew.F_Cu, width=0.5):
    """Draw ``segments`` (a list of ((x0,y0),(x1,y1)) mm pairs) into ``fp``,
    creating a marker with the usual User-layer outline shape when none is
    given. Returns the footprint."""
    if fp is None:
        fp = _FakeFootprint()
        outline = _FakeShape(fp)  # the marker's own rectangle/arrow
        outline.SetShape(_FAKE_PCBNEW.SHAPE_T_SEGMENT)
        outline.SetLayer(_USER_1)
        fp.Add(outline)
    _with_fake_pcbnew(lambda: area_marker.draw_antenna(fp, segments, layer, width))
    return fp


def _preview(fp):
    return _with_fake_pcbnew(lambda: area_marker.antenna_items(fp))


# Three candidates of different shapes: a straight run, a bent one, a longer
# bent one -- the counts a slider nudge moves between.
_STRAIGHT = [((0.0, 0.0), (10.0, 0.0))]
_BENT = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 6.0))]
_FOLDED = _BENT + [((10.0, 6.0), (4.0, 6.0)), ((4.0, 6.0), (4.0, 1.0))]


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def test_draw_puts_one_filled_copper_polygon_per_segment():
    fp = _run(_BENT)
    polys = _preview(fp)
    assert len(polys) == 2
    for poly, seg in zip(polys, _BENT):
        assert poly.shape == _FAKE_PCBNEW.SHAPE_T_POLYGON
        assert poly.layer == _FAKE_PCBNEW.F_Cu
        assert poly.filled is True
        assert poly.width == 0  # only the fill shows
        assert poly.corners_mm() == area_marker._rect_corners(seg, 0.5)


def test_zero_length_segments_are_skipped():
    fp = _run([((2.0, 2.0), (2.0, 2.0))] + _STRAIGHT)
    assert len(_preview(fp)) == 1


# --------------------------------------------------------------------------- #
# Redrawing: the shapes on the marker are reused, never rebuilt
# --------------------------------------------------------------------------- #
def test_redraw_reuses_the_shapes_already_on_the_marker():
    """The reported crash: a marker carrying a preview loaded off the board is
    redrawn the moment a designer page is shown. Same shape count -> the
    footprint's item list must not be touched at all."""
    fp = _run(_BENT)
    before = _preview(fp)
    _run([((0.0, 0.0), (12.0, 0.0)), ((12.0, 0.0), (12.0, 7.0))], fp=fp)
    after = _preview(fp)
    assert [id(p) for p in after] == [id(p) for p in before]
    assert fp.removed == []
    # ... and they carry the new candidate, not the old one.
    assert after[0].corners_mm() == area_marker._rect_corners(
        ((0.0, 0.0), (12.0, 0.0)), 0.5
    )
    assert all(p.writes == 2 for p in after)


def test_redraw_adds_only_what_a_longer_candidate_needs():
    fp = _run(_BENT)
    before = _preview(fp)
    _run(_FOLDED, fp=fp)
    after = _preview(fp)
    assert len(after) == 4
    assert [id(p) for p in after[:2]] == [id(p) for p in before]
    assert fp.removed == []


def test_redraw_detaches_only_the_surplus_and_never_frees_it():
    fp = _run(_FOLDED)
    before = _preview(fp)
    _run(_STRAIGHT, fp=fp)
    after = _preview(fp)
    assert len(after) == 1
    assert id(after[0]) == id(before[0])
    # The three the shorter candidate no longer needs are unlinked -- and left
    # for KiCad to keep pointing at, never freed.
    assert [id(p) for p in fp.removed] == [id(p) for p in before[1:]]
    assert all(p.thisown is False for p in fp.removed)


def test_redraw_follows_the_feed_layer():
    fp = _run(_BENT)
    _run(_BENT, fp=fp, layer=_FAKE_PCBNEW.B_Cu)
    assert [p.layer for p in _preview(fp)] == [_FAKE_PCBNEW.B_Cu] * 2
    assert fp.removed == []


def test_a_candidate_that_does_not_fit_is_drawn_on_the_marker_layer():
    """The wizard moves the preview off copper and onto the marker's own layer
    when the candidate stops fitting the area (and back again when it fits).
    The preview is found by shape, not by layer, so the same shapes are reused
    across that move -- and the marker's own segments are still not preview."""
    fp = _run(_BENT)
    before = _preview(fp)
    _run(_BENT, fp=fp, layer=_USER_1)  # ... no longer fits
    moved = _preview(fp)
    assert [id(p) for p in moved] == [id(p) for p in before]
    assert [p.layer for p in moved] == [_USER_1] * 2
    assert fp.removed == []
    assert fp.GraphicalItems()[0].layer == _USER_1  # the outline, untouched
    assert fp.GraphicalItems()[0].writes == 0
    _run(_BENT, fp=fp)  # ... fits again
    assert [p.layer for p in _preview(fp)] == [_FAKE_PCBNEW.F_Cu] * 2


def test_a_preview_on_the_marker_layer_is_still_cleared():
    """It is not copper, but it is still the preview: the scan's strip-and-plot
    and the footprint step must take it off like any other."""
    fp = _run(_FOLDED, layer=_USER_1)
    assert len(_preview(fp)) == 4
    assert _with_fake_pcbnew(lambda: area_marker.clear_antenna(fp)) == 4
    assert _preview(fp) == []
    assert len(fp.GraphicalItems()) == 1  # the marker's own drawing


# --------------------------------------------------------------------------- #
# Clearing
# --------------------------------------------------------------------------- #
def test_clear_takes_every_shape_off_without_freeing_it():
    fp = _run(_FOLDED)
    polys = _preview(fp)
    assert _with_fake_pcbnew(lambda: area_marker.clear_antenna(fp)) == 4
    assert _preview(fp) == []
    assert [id(p) for p in fp.removed] == [id(p) for p in polys]
    assert all(p.thisown is False for p in polys)


def test_clear_reports_nothing_to_clear():
    fp = _run([])
    assert _with_fake_pcbnew(lambda: area_marker.clear_antenna(fp)) == 0
    assert fp.removed == []


def test_a_cleared_marker_draws_again_from_scratch():
    """The footprint step clears the preview for good; a later area tweak that
    redraws one must still work off an empty marker."""
    fp = _run(_BENT)
    _with_fake_pcbnew(lambda: area_marker.clear_antenna(fp))
    _run(_BENT, fp=fp)
    assert len(_preview(fp)) == 2


# --------------------------------------------------------------------------- #
# The marker's own drawing is not the preview
# --------------------------------------------------------------------------- #
def test_the_marker_outline_is_never_touched():
    """The preview is filled polygons and the marker's own drawing is line
    segments; drawing, redrawing and clearing the one must leave the other
    alone -- decoding and the sliders read those segments back -- and that has
    to hold even when both are on the same layer (a candidate that doesn't
    fit)."""
    fp = _run(_FOLDED)
    outline = fp.GraphicalItems()[0]
    assert outline.layer == _USER_1
    _run(_STRAIGHT, fp=fp)
    _with_fake_pcbnew(lambda: area_marker.clear_antenna(fp))
    assert fp.GraphicalItems() == [outline]
    assert outline.writes == 0 and outline.thisown is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
