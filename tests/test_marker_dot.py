"""Unit tests for the markers' board-side reshape against a minimal fake
pcbnew footprint: the feed-point dot (the filled circle
feed_marker._rewrite_marker keeps on the stem/triangle joint) and the
feed-holding slide the area marker's height reshape ends in
(area_marker.update_marker's ``hold_feed``, which moves the footprint so the
feed point stays on the board where the user put it).

Three things have to hold for the dot, and none of them show up in the pure
geometry tests (test_feed_marker / test_area_marker):

* it stays out of the decode -- the feed is recovered from the marker's line
  segments, so a circle among the graphics must not reach _segment_points_mm;
* a marker drawn before the dot existed gains one when the sliders reshape it,
  on the marker's own layer;
* a reshape reuses the circle already there rather than replacing it -- the
  use-after-free rule every shape on a placed marker follows (see
  feed_marker._detach_item and test_area_preview).

The package is assembled by hand around the real modules because
antenna_plugin/__init__ imports pcbnew:  python3 tests/test_marker_dot.py
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
feed_marker = importlib.import_module("antenna_plugin.markers.feed_marker")


# --------------------------------------------------------------------------- #
# A fake KiCad: the footprint graphics a marker reshape writes, and no more
# --------------------------------------------------------------------------- #
class _Pt:
    def __init__(self, x=0, y=0):
        self.x, self.y = int(x), int(y)


class _FakeShape:
    """A stand-in for a footprint PCB_SHAPE, KiCad 7+ shaped (no
    SetLocalCoord). ``thisown`` is the SWIG flag that must never be left True
    on a detached shape."""

    def __init__(self, parent=None):
        self.parent = parent
        self.thisown = True
        self.shape = None
        self.start = _Pt()
        self.end = _Pt()
        self.layer = None
        self.filled = None
        self.width = None
        self.writes = 0

    def SetShape(self, shape):
        self.shape = shape

    def SetStart(self, pt):
        self.start = pt
        self.writes += 1

    def SetEnd(self, pt):
        self.end = pt

    def SetLayer(self, layer):
        self.layer = layer

    def SetFilled(self, filled):
        self.filled = filled

    def SetWidth(self, width):
        self.width = width

    def GetLayer(self):
        return self.layer

    def GetShape(self):
        return self.shape

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def center_mm(self):
        return (self.start.x / 1e6, self.start.y / 1e6)

    def radius_mm(self):
        return (self.end.x - self.start.x) / 1e6


class _FakeFootprint:
    """A placed marker at a fixed position: its graphics, its orientation and
    a log of everything ever unlinked from it."""

    def __init__(self, x_mm=100.0, y_mm=50.0):
        self._items = []
        self.removed = []
        self._pos = _Pt(x_mm * 1e6, y_mm * 1e6)
        self._orient = 0.0

    def GraphicalItems(self):
        return list(self._items)

    def Add(self, item):
        self._items.append(item)

    def Remove(self, item):
        self._items.remove(item)
        self.removed.append(item)

    def GetPosition(self):
        return self._pos

    def SetPosition(self, pt):
        """Move the footprint, graphics and all -- FOOTPRINT::SetPosition
        carries every child shape along, which is what makes it the safe way to
        slide a placed marker (nothing is unlinked or rewritten)."""
        dx, dy = pt.x - self._pos.x, pt.y - self._pos.y
        self._pos = pt
        for item in self._items:
            for end in (item.GetStart(), item.GetEnd()):
                end.x, end.y = end.x + dx, end.y + dy

    def GetOrientationDegrees(self):
        return self._orient

    def SetOrientationDegrees(self, deg):
        self._orient = deg


class _FakePcbnew(types.ModuleType):
    FromMM = staticmethod(lambda mm: int(round(mm * 1e6)))
    ToMM = staticmethod(lambda iu: iu / 1e6)
    VECTOR2I = staticmethod(_Pt)
    SHAPE_T_SEGMENT = 0
    SHAPE_T_CIRCLE = 3
    SHAPE_T_POLYGON = 4
    F_Cu, B_Cu = 0, 31
    PCB_SHAPE = _FakeShape


_FAKE_PCBNEW = _FakePcbnew("pcbnew")
for _n in range(1, 10):  # User.1 .. User.9, the marker's own
    setattr(_FAKE_PCBNEW, f"User_{_n}", 50 + _n)
_USER_1, _USER_2 = _FAKE_PCBNEW.User_1, _FAKE_PCBNEW.User_2


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


def _legacy_marker(segments, layer=_USER_1):
    """A placed marker as an older plugin drew it: line segments only, no
    feed-point dot."""
    fp = _FakeFootprint()
    for (x0, y0), (x1, y1) in segments:
        seg = _FakeShape(fp)
        seg.SetShape(_FAKE_PCBNEW.SHAPE_T_SEGMENT)
        seg.SetLayer(layer)
        seg.SetStart(
            _Pt((fp.GetPosition().x + x0 * 1e6), (fp.GetPosition().y + y0 * 1e6))
        )
        seg.SetEnd(
            _Pt((fp.GetPosition().x + x1 * 1e6), (fp.GetPosition().y + y1 * 1e6))
        )
        fp.Add(seg)
    return fp


def _dots(fp):
    return _with_fake_pcbnew(lambda: feed_marker._circle_items(fp))


# --------------------------------------------------------------------------- #
# The dot never reaches the decode
# --------------------------------------------------------------------------- #
def test_the_decode_reads_the_segments_only():
    fp = _legacy_marker(feed_marker._local_segments(1.0))
    _with_fake_pcbnew(lambda: feed_marker.update_marker(fp, None, 1.0))
    assert len(_dots(fp)) == 1
    # Five segments in, five segments out: the circle is not one of them, so
    # the arrow decode sees exactly what it did before the dot existed.
    pts = _with_fake_pcbnew(lambda: feed_marker._segment_points_mm(fp))
    assert len(pts) == 5
    x, y, width, dx, dy = feed_marker._decode_segments(pts)
    assert (round(x, 6), round(y, 6)) == (100.0, 50.0)
    assert round(width, 6) == 1.0 and (round(dx), round(dy)) == (0, -1)


# --------------------------------------------------------------------------- #
# Reshaping: the dot is added once, then reused and moved
# --------------------------------------------------------------------------- #
def test_a_marker_without_a_dot_gains_one_on_its_own_layer():
    fp = _legacy_marker(feed_marker._local_segments(1.0))
    _with_fake_pcbnew(lambda: feed_marker.update_marker(fp, None, 2.0))
    dots = _dots(fp)
    assert len(dots) == 1
    dot = dots[0]
    assert dot.shape == _FAKE_PCBNEW.SHAPE_T_CIRCLE
    assert dot.layer == _USER_1  # the layer the segments are on
    assert dot.filled is True and dot.width == 0
    # On the feed point: the marker's origin, in board mm.
    assert dot.center_mm() == (100.0, 50.0)
    radius = feed_marker._local_dots(2.0)[0][1]
    assert round(dot.radius_mm(), 6) == round(radius, 6)


def test_a_reshape_reuses_the_dot_and_never_frees_it():
    fp = _legacy_marker(feed_marker._local_segments(1.0))
    _with_fake_pcbnew(lambda: feed_marker.update_marker(fp, None, 1.0))
    before = _dots(fp)[0]
    _with_fake_pcbnew(lambda: feed_marker.update_marker(fp, _USER_2, 3.0))
    after = _dots(fp)
    assert [id(d) for d in after] == [id(before)]  # the same C++ object
    assert fp.removed == []
    assert after[0].layer == _USER_2  # ... moved with the rest
    assert after[0].radius_mm() > 0


def test_the_area_markers_dot_follows_the_feed_along_the_edge():
    fp = _legacy_marker(area_marker._local_segments(30.0, 12.0, 0.2))
    _with_fake_pcbnew(lambda: area_marker.update_marker(fp, 30.0, 12.0, 0.2))
    left = _dots(fp)[0].center_mm()
    _with_fake_pcbnew(lambda: area_marker.update_marker(fp, 30.0, 12.0, 0.8))
    right = _dots(fp)[0].center_mm()
    assert fp.removed == []  # reused, not replaced
    assert right[0] > left[0]  # moved along the feed edge
    assert right[1] == left[1] == 50.0 + 6.0  # ... staying on the edge
    # Both sit on the stem/triangle joint the segments were rewritten to.
    joint = area_marker._local_segments(30.0, 12.0, 0.8)[8][0]
    assert right == (100.0 + joint[0], 50.0 + joint[1])


# --------------------------------------------------------------------------- #
# A deeper area: the marker moves, the feed does not
# --------------------------------------------------------------------------- #
def _area_marker(w_mm=30.0, h_mm=12.0, frac=0.2):
    """A placed area marker with its feed-point dot already on it (the first
    reshape is what adds one to a marker drawn before the dot existed)."""
    fp = _legacy_marker(area_marker._local_segments(w_mm, h_mm, frac))
    _with_fake_pcbnew(lambda: area_marker.update_marker(fp, w_mm, h_mm, frac))
    return fp


def _decoded(fp):
    pts = _with_fake_pcbnew(lambda: feed_marker._segment_points_mm(fp))
    return area_marker._decode_segments(pts)


def test_a_deeper_area_holds_the_feed_and_slides_the_marker():
    """``hold_feed``: the rectangle is drawn about the marker's own origin, so
    the marker itself is what moves -- the feed point (and its dot) stay on the
    board where the user lined them up, and the extra depth all lands on the
    far edge."""
    fp = _area_marker()
    feed = _dots(fp)[0].center_mm()
    assert feed[1] == 50.0 + 6.0  # the feed edge of a 12 mm deep area
    edge_y = _decoded(fp)["area"][3]

    pos = _with_fake_pcbnew(
        lambda: area_marker.update_marker(fp, 30.0, 20.0, 0.2, hold_feed=True)
    )
    assert pos == (100.0, 46.0)  # slid by half the 8 mm the area gained
    assert _dots(fp)[0].center_mm() == feed  # the feed point did not move
    d = _decoded(fp)
    assert d["h_mm"] == 20.0 and d["w_mm"] == 30.0
    assert d["area"][3] == edge_y  # ... the feed edge is where it was
    assert fp.removed == []  # the footprint moved; no shape was unlinked


def test_a_deeper_area_without_the_hold_keeps_the_marker_where_it_is():
    """The default: the marker's position is kept and the feed edge is what
    moves -- what every other reshape (a width, a triangle, a layer move)
    wants, since none of them touch the feed edge."""
    fp = _area_marker()
    feed = _dots(fp)[0].center_mm()
    pos = _with_fake_pcbnew(lambda: area_marker.update_marker(fp, 30.0, 20.0, 0.2))
    assert pos == (100.0, 50.0)
    assert _dots(fp)[0].center_mm() == (feed[0], 50.0 + 10.0)


def test_the_hold_leaves_a_marker_with_no_feed_arrow_where_it_is():
    """Nothing to hold -- a marker edited out of shape carries no feed arrow to
    measure the slide from: the reshape stands, the marker stays put, and the
    caller's own decode is what reports the breakage."""
    fp = _area_marker()
    before = _dots(fp)[0].center_mm()
    rect_only = area_marker._local_segments(30.0, 12.0, 0.2)[:4]
    held = _with_fake_pcbnew(lambda: area_marker._shift_to_held_feed(fp, rect_only))
    assert held == (100.0, 50.0)
    assert _dots(fp)[0].center_mm() == before


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
