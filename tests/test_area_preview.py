"""Unit tests for the wizard's drawn antenna preview (markers.preview) against
a minimal fake pcbnew board.

The preview is the candidate the Scan rows describe, drawn on the board -- on
the feed copper layer while the candidate fits the area, on the area marker's
own User layer while it doesn't. It is a **footprint of its own**, beside the
area marker rather than inside it, so the user selects and deletes the sketch
and the area it was solved in separately; these tests pin that separation (the
marker is never written to, and clearing takes the preview footprint off the
board rather than emptying the marker).

It is also the one thing the plugin draws that survives a board save: reopened,
its shapes belong to KiCad -- the editor's view, the connectivity graph, the
selection and the undo stack all point at them -- so unlinking one from a
plugin frees an object KiCad still uses and takes the editor down with it (the
crash these tests pin: open a board whose preview was saved with it, switch to
a designer, the wizard redraws the candidate).

So what is asserted here is *identity*, not just geometry: a redraw must reuse
the shapes already on the footprint, and everything unlinked -- the surplus a
shorter candidate leaves, and the footprint a clear takes off the board -- must
never be freed (``thisown`` cleared). The fakes below record every Remove so
the tests can hold the line.

The package is assembled by hand around the real modules because
antenna_plugin/__init__ imports pcbnew:  python3 tests/test_area_preview.py
"""

import pathlib
import sys
import types

from bare_package import load

_ROOT = pathlib.Path(__file__).resolve().parents[1]

preview = load("emkit.markers.preview")
area_marker = load("markers.area_marker")


# --------------------------------------------------------------------------- #
# A fake KiCad: the board, the footprints and the graphics the preview writes
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


class _FakeText:
    """A footprint's hidden reference/value text: no ``GetShape``, so the item
    walks must never take it for a drawn shape."""

    def __init__(self):
        self.visible = True

    def SetVisible(self, visible):
        self.visible = visible


class _FakeFootprint:
    """A placed footprint: an ordered list of graphics, an anchor, and a log of
    everything ever unlinked from it (the tests' whole point)."""

    def __init__(self, board=None):
        self.board = board
        self.thisown = True
        self.name = None
        self.reference = None
        self.value = None
        self.attributes = None
        self.position = (0, 0)
        self.orientation = 0.0
        self._text = (_FakeText(), _FakeText())
        self._items = []
        self.removed = []

    # -- identity
    def SetFPID(self, fpid):
        self.name = fpid

    def GetFPID(self):
        return self

    def GetLibItemName(self):
        return self.name

    def SetReference(self, reference):
        self.reference = reference

    def SetValue(self, value):
        self.value = value

    def Reference(self):
        return self._text[0]

    def Value(self):
        return self._text[1]

    def SetAttributes(self, attrs):
        self.attributes = attrs

    # -- placement
    def SetPosition(self, pos):
        self.position = pos

    def GetPosition(self):
        return self.position

    def GetOrientationDegrees(self):
        return self.orientation

    def SetOrientationDegrees(self, deg):
        self.orientation = deg

    # -- graphics
    def GraphicalItems(self):
        return list(self._items)

    def Add(self, item):
        self._items.append(item)

    def Remove(self, item):
        self._items.remove(item)
        self.removed.append(item)


class _FakeBoard:
    """A board the preview footprint is added to and taken off again, keeping
    a log of both."""

    def __init__(self):
        self._footprints = []
        self.removed = []

    def GetFootprints(self):
        return list(self._footprints)

    def Add(self, fp):
        self._footprints.append(fp)

    def Remove(self, fp):
        self._footprints.remove(fp)
        self.removed.append(fp)


class _FakePcbnew(types.ModuleType):
    """Enough pcbnew for the preview: KiCad 7+ shaped (a PCB_SHAPE with no
    FP_SHAPE and no SetLocalCoord, so no local-coordinate sync)."""

    FromMM = staticmethod(lambda mm: int(round(mm * 1e6)))
    ToMM = staticmethod(lambda iu: iu / 1e6)
    VECTOR2I = staticmethod(lambda x, y: (x, y))
    LIB_ID = staticmethod(lambda lib, name: name)
    SHAPE_T_SEGMENT = 0
    SHAPE_T_POLYGON = 4
    F_Cu, B_Cu = 0, 31
    PCB_SHAPE = _FakeShape
    FOOTPRINT = _FakeFootprint


_FAKE_PCBNEW = _FakePcbnew("pcbnew")
for _n in range(1, 10):  # User.1 .. User.9, the area marker's own
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


def _area_marker(board):
    """An area marker on the board, drawn the way area_marker draws one: line
    segments on a User layer. The preview must never touch it."""
    fp = _FakeFootprint(board)
    fp.SetFPID(area_marker.MARKER_NAME)
    outline = _FakeShape(fp)
    outline.SetShape(_FAKE_PCBNEW.SHAPE_T_SEGMENT)
    outline.SetLayer(_USER_1)
    fp.Add(outline)
    board.Add(fp)
    return fp


def _run(segments, board=None, layer=_FakePcbnew.F_Cu, width=0.5):
    """Draw ``segments`` (a list of ((x0,y0),(x1,y1)) mm pairs) onto ``board``,
    creating one carrying an area marker when none is given. Returns the
    board."""
    if board is None:
        board = _FakeBoard()
        _area_marker(board)
    _with_fake_pcbnew(lambda: preview.draw(board, segments, layer, width))
    return board


def _fp(board):
    """The board's one preview footprint."""
    fps = _with_fake_pcbnew(lambda: preview.preview_footprints(board))
    assert len(fps) == 1
    return fps[0]


def _shapes(board):
    return _with_fake_pcbnew(lambda: preview.items(_fp(board)))


def _markers(board):
    return [fp for fp in board.GetFootprints() if fp.name == area_marker.MARKER_NAME]


# Three candidates of different shapes: a straight run, a bent one, a longer
# bent one -- the counts a slider nudge moves between.
_STRAIGHT = [((0.0, 0.0), (10.0, 0.0))]
_BENT = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 6.0))]
_FOLDED = _BENT + [((10.0, 6.0), (4.0, 6.0)), ((4.0, 6.0), (4.0, 1.0))]


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def test_draw_puts_one_filled_copper_polygon_per_segment():
    board = _run(_BENT)
    polys = _shapes(board)
    assert len(polys) == 2
    for poly, seg in zip(polys, _BENT):
        assert poly.shape == _FAKE_PCBNEW.SHAPE_T_POLYGON
        assert poly.layer == _FAKE_PCBNEW.F_Cu
        assert poly.filled is True
        assert poly.width == 0  # only the fill shows
        assert poly.corners_mm() == preview._rect_corners(seg, 0.5)


def test_zero_length_segments_are_skipped():
    board = _run([((2.0, 2.0), (2.0, 2.0))] + _STRAIGHT)
    assert len(_shapes(board)) == 1


def test_a_candidate_with_nothing_to_draw_leaves_no_empty_footprint():
    """Nothing drawable at all clears instead of placing an empty footprint --
    which would be an invisible item to click and one more thing saved with the
    board."""
    board = _run(_BENT)
    _run([((2.0, 2.0), (2.0, 2.0))], board=board)
    assert not _with_fake_pcbnew(lambda: preview.exists(board))
    empty = _FakeBoard()
    _area_marker(empty)
    _run([], board=empty)
    assert not _with_fake_pcbnew(lambda: preview.exists(empty))


def test_the_preview_is_its_own_board_only_footprint():
    """The point of the split: the sketch is an item of its own, so it can be
    clicked and deleted without touching the area marker."""
    board = _run(_BENT)
    fp = _fp(board)
    assert fp is not _markers(board)[0]
    assert fp.name == preview.PREVIEW_NAME and fp.reference == "PREVIEW"
    assert not fp.Reference().visible and not fp.Value().visible
    assert len(board.GetFootprints()) == 2


def test_the_footprint_is_anchored_on_what_it_draws():
    """Its origin sits in the middle of the sketch -- not at the board origin,
    where an anchor nowhere near the drawing would be a stray click target."""
    board = _run(_BENT)
    corners = [c for seg in _BENT for c in preview._rect_corners(seg, 0.5)]
    xs, ys = [x for (x, _) in corners], [y for (_, y) in corners]
    want = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    assert _fp(board).position == tuple(_FakePcbnew.FromMM(v) for v in want)


def test_a_redraw_re_anchors_and_squares_the_footprint():
    """The shapes go in board coordinates, so a preview the user rotated or
    dragged has to be squared and re-anchored first -- otherwise KiCad's own
    orientation would rotate the candidate a second time."""
    board = _run(_STRAIGHT)
    fp = _fp(board)
    fp.SetOrientationDegrees(90)
    fp.SetPosition((123, 456))
    _run(_STRAIGHT, board=board)
    assert fp.orientation == 0
    assert fp.position != (123, 456)
    assert _shapes(board)[0].corners_mm() == preview._rect_corners(_STRAIGHT[0], 0.5)


# --------------------------------------------------------------------------- #
# Redrawing: the shapes on the footprint are reused, never rebuilt
# --------------------------------------------------------------------------- #
def test_redraw_reuses_the_shapes_already_on_the_footprint():
    """The reported crash: a preview loaded off the board is redrawn the moment
    a designer page is shown. Same shape count -> the footprint's item list
    must not be touched at all, and no second preview footprint appears."""
    board = _run(_BENT)
    fp = _fp(board)
    before = _shapes(board)
    _run([((0.0, 0.0), (12.0, 0.0)), ((12.0, 0.0), (12.0, 7.0))], board=board)
    after = _shapes(board)
    assert [id(p) for p in after] == [id(p) for p in before]
    assert fp.removed == [] and board.removed == []
    assert len(board.GetFootprints()) == 2  # the marker and the one preview
    # ... and they carry the new candidate, not the old one.
    assert after[0].corners_mm() == preview._rect_corners(
        ((0.0, 0.0), (12.0, 0.0)), 0.5
    )
    assert all(p.writes == 2 for p in after)


def test_redraw_adds_only_what_a_longer_candidate_needs():
    board = _run(_BENT)
    before = _shapes(board)
    _run(_FOLDED, board=board)
    after = _shapes(board)
    assert len(after) == 4
    assert [id(p) for p in after[:2]] == [id(p) for p in before]
    assert _fp(board).removed == []


def test_redraw_detaches_only_the_surplus_and_never_frees_it():
    board = _run(_FOLDED)
    fp = _fp(board)
    before = _shapes(board)
    _run(_STRAIGHT, board=board)
    after = _shapes(board)
    assert len(after) == 1
    assert id(after[0]) == id(before[0])
    # The three the shorter candidate no longer needs are unlinked -- and left
    # for KiCad to keep pointing at, never freed.
    assert [id(p) for p in fp.removed] == [id(p) for p in before[1:]]
    assert all(p.thisown is False for p in fp.removed)


def test_redraw_follows_the_feed_layer():
    board = _run(_BENT)
    _run(_BENT, board=board, layer=_FAKE_PCBNEW.B_Cu)
    assert [p.layer for p in _shapes(board)] == [_FAKE_PCBNEW.B_Cu] * 2
    assert _fp(board).removed == []


def test_a_candidate_that_does_not_fit_is_drawn_on_the_marker_layer():
    """The wizard moves the preview off copper and onto the area marker's own
    layer when the candidate stops fitting the area (and back again when it
    fits). The preview is found by shape, not by layer, so the same shapes are
    reused across that move -- and the marker's own segments are still not
    preview."""
    board = _run(_BENT)
    before = _shapes(board)
    _run(_BENT, board=board, layer=_USER_1)  # ... no longer fits
    moved = _shapes(board)
    assert [id(p) for p in moved] == [id(p) for p in before]
    assert [p.layer for p in moved] == [_USER_1] * 2
    assert _fp(board).removed == []
    _run(_BENT, board=board)  # ... fits again
    assert [p.layer for p in _shapes(board)] == [_FAKE_PCBNEW.F_Cu] * 2


def test_a_preview_on_the_marker_layer_is_still_cleared():
    """It is not copper, but it is still the preview: the scan's strip-and-plot
    and the footprint step must take it off like any other."""
    board = _run(_FOLDED, layer=_USER_1)
    assert len(_shapes(board)) == 4
    assert _with_fake_pcbnew(lambda: preview.clear(board)) == 1
    assert not _with_fake_pcbnew(lambda: preview.exists(board))


# --------------------------------------------------------------------------- #
# Clearing
# --------------------------------------------------------------------------- #
def test_clear_takes_the_whole_footprint_off_without_freeing_it():
    """Nothing invisible is left behind -- an emptied husk would still be an
    item to click and a footprint to save -- and the footprint that goes is
    leaked, not freed: KiCad may still point at one it loaded."""
    board = _run(_FOLDED)
    fp = _fp(board)
    assert _with_fake_pcbnew(lambda: preview.clear(board)) == 1
    assert board.removed == [fp] and fp.thisown is False
    assert _with_fake_pcbnew(lambda: preview.preview_footprints(board)) == []
    assert not _with_fake_pcbnew(lambda: preview.exists(board))


def test_clear_reports_nothing_to_clear():
    board = _FakeBoard()
    _area_marker(board)
    assert _with_fake_pcbnew(lambda: preview.clear(board)) == 0
    assert board.removed == []


def test_clear_takes_a_duplicated_preview_off_too():
    """A user who copy-pasted the preview has two; the strip before a gerber
    plot has to leave neither behind, since both are copper."""
    board = _run(_BENT)
    extra = _FakeFootprint(board)
    extra.SetFPID(preview.PREVIEW_NAME)
    board.Add(extra)
    assert _with_fake_pcbnew(lambda: preview.clear(board)) == 2
    assert len(board.removed) == 2
    assert _markers(board)  # the marker stays


def test_a_cleared_board_draws_again_from_scratch():
    """The footprint step clears the preview for good; a later area tweak that
    redraws one must build a fresh footprint rather than fail on the missing
    one."""
    board = _run(_BENT)
    _with_fake_pcbnew(lambda: preview.clear(board))
    _run(_BENT, board=board)
    assert len(_shapes(board)) == 2
    assert len(board.GetFootprints()) == 2


# --------------------------------------------------------------------------- #
# The area marker is a separate item and is never touched
# --------------------------------------------------------------------------- #
def test_the_area_marker_is_never_touched():
    """Drawing, redrawing and clearing the preview must leave the marker's own
    drawing alone -- decoding and the sliders read those segments back -- and
    that has to hold even when both are on the same layer (a candidate that
    doesn't fit)."""
    board = _run(_FOLDED, layer=_USER_1)
    marker = _markers(board)[0]
    outline = marker.GraphicalItems()[0]
    _run(_STRAIGHT, board=board)
    _with_fake_pcbnew(lambda: preview.clear(board))
    assert marker.GraphicalItems() == [outline]
    assert outline.layer == _USER_1
    assert outline.writes == 0 and outline.thisown is True
    assert marker.removed == [] and marker not in board.removed


def test_the_preview_survives_the_marker_being_deleted():
    """The other half of the split: Del on the area marker is the user's, and
    it leaves the sketch standing (the wizard then has no area to solve
    against, which the Scan section reports -- it does not reach in here)."""
    board = _run(_BENT)
    fp = _fp(board)
    board.Remove(_markers(board)[0])
    assert _with_fake_pcbnew(lambda: preview.preview_footprints(board)) == [fp]
    assert _shapes(board)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
