"""Unit tests for antenna_plugin.markers.area_checks' pure helpers (no KiCad).

Covers the axis-aligned overlap primitives (point / segment / polygon vs
rectangle, with half-width inflation), the clip-to-area step and the
antenna-overlap check built on it (checks 2+3), the outward probe bands and
opposite-edge map that drive check 4, the check registry the banner runs, the
board->derotated-frame mapping that lets the checks work in the marker's own
axes, and that every area-check id ships a self-contained help page. The board
walks run against a minimal fake pcbnew board (below); a live board isn't
needed.

The package is assembled by hand around the real modules because
antenna_plugin/__init__ imports pcbnew:  python3 tests/test_area_checks.py
"""

import importlib
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
from helppage import assert_guide_loads  # noqa: E402

ac = importlib.import_module("antenna_plugin.markers.area_checks")
markergeom = importlib.import_module("antenna_plugin.markers.markergeom")
simulate = importlib.import_module("antenna_plugin.sim.simulate")

RECT = (0.0, 0.0, 10.0, 10.0)


# --------------------------------------------------------------------------- #
# Point / segment / polygon vs rectangle
# --------------------------------------------------------------------------- #
def test_point_in_rect_includes_the_border():
    assert ac._point_in_rect((5, 5), RECT)
    assert ac._point_in_rect((0, 0), RECT)  # corner counts
    assert not ac._point_in_rect((10.1, 5), RECT)


def test_segment_hits_rect():
    assert ac._seg_hits_rect((2, 2), (3, 3), RECT)  # wholly inside
    assert ac._seg_hits_rect((-5, 5), (5, 5), RECT)  # crosses an edge
    assert ac._seg_hits_rect((-5, -5), (15, 15), RECT)  # passes through
    assert not ac._seg_hits_rect((-5, -5), (-1, -1), RECT)  # clear outside


def test_polygon_overlap_covers_containment_both_ways():
    surrounding = [(-1, -1), (20, -1), (20, 20), (-1, 20)]
    assert ac._poly_hits_rect(surrounding, RECT)  # rect inside poly
    tiny_inside = [(4, 4), (6, 4), (6, 6), (4, 6)]
    assert ac._poly_hits_rect(tiny_inside, RECT)  # poly inside rect
    far = [(100, 100), (110, 100), (110, 110)]
    assert not ac._poly_hits_rect(far, RECT)
    assert not ac._poly_hits_rect([(0, 0), (1, 1)], RECT)  # <3 pts: not a poly


def test_half_width_and_radius_inflate_the_test():
    # A via 1 mm outside the edge with a 2 mm radius reaches in; 4 mm out misses.
    assert ac._shape_hits_rect(("point", ((11, 5), 2.0)), RECT)
    assert not ac._shape_hits_rect(("point", ((14, 5), 2.0)), RECT)
    # A track centreline 0.5 mm outside with a 1 mm half-width overlaps.
    assert ac._shape_hits_rect(("seg", ((10.5, 2), (10.5, 8), 1.0)), RECT)
    assert not ac._shape_hits_rect(("seg", ((12, 2), (12, 8), 1.0)), RECT)


# --------------------------------------------------------------------------- #
# Probe bands + opposite edge (check 4 geometry)
# --------------------------------------------------------------------------- #
def test_outward_band_sits_just_outside_each_edge():
    # Y-down: "bottom" is max Y, so its band is below the rectangle.
    assert ac._outward_band(RECT, "bottom", 2) == (0, 10, 10, 12)
    assert ac._outward_band(RECT, "top", 2) == (0, -2, 10, 0)
    assert ac._outward_band(RECT, "left", 2) == (-2, 0, 0, 10)
    assert ac._outward_band(RECT, "right", 2) == (10, 0, 12, 10)


def test_opposite_edges_pair_up():
    assert ac._OPPOSITE == {
        "bottom": "top",
        "top": "bottom",
        "left": "right",
        "right": "left",
    }


def test_feed_axis_bands_separate_source_from_radiating():
    # Feed on the bottom edge: copper just below is ground (source), copper just
    # above backs the radiating edge. A shape in one band must not hit the other.
    source = ac._outward_band(RECT, "bottom", ac.PROBE_MM)
    radiating = ac._outward_band(RECT, ac._OPPOSITE["bottom"], ac.PROBE_MM)
    pour_below = ("poly", [(0, 10.5), (10, 10.5), (10, 11.5), (0, 11.5)])
    assert ac._shape_hits_rect(pour_below, source)
    assert not ac._shape_hits_rect(pour_below, radiating)


# --------------------------------------------------------------------------- #
# Clip-to-area (the antenna-overlap check's inside/outside split)
# --------------------------------------------------------------------------- #
def test_inside_area_clips_the_stubs_and_outside_copper_away():
    # A stem reaching out through the bottom (feed) edge: only the inside part
    # survives, inset by the edge slack -- and by the wider feed-edge band at
    # the edge the pins sit on.
    rects = ac._inside_area([(4.0, 5.0, 6.0, 12.0)], RECT, "bottom")
    assert rects == [(4.0, 5.0, 6.0, 10.0 - ac.FEED_EDGE_SLACK_MM)]
    # Copper wholly outside the area (the pour the stub lands on) vanishes.
    assert ac._inside_area([(4.0, 10.0, 6.0, 12.0)], RECT, "bottom") == []


def test_inside_area_tolerates_copper_flush_with_the_edge():
    # A pour edge on an area edge (or a grid-snap hair over it) is the normal
    # area-against-the-pour layout, not an overlap worth warning about. On the
    # three edges the design keeps its border off, the slack is the thin one.
    assert (
        ac._inside_area([(-2.0, 5.0, 0.0 + ac.EDGE_SLACK_MM, 8.0)], RECT, "bottom")
        == []
    )
    # Reaching measurably deeper does count.
    assert ac._inside_area([(-2.0, 5.0, 1.0, 8.0)], RECT, "bottom")


def test_inside_area_leaves_the_feed_edge_connection_band_unjudged():
    # The pins land *on* the feed edge and the area is routinely drawn hanging
    # over the pour so they reach it: copper within the feed-edge band is the
    # connection, not an obstruction (the false positive that fired on every
    # candidate). Copper deeper than the band still counts.
    band = ac.FEED_EDGE_SLACK_MM
    for edge, rect in (
        ("bottom", (4.0, 10.0 - band, 6.0, 12.0)),
        ("top", (4.0, -2.0, 6.0, band)),
        ("left", (-2.0, 4.0, band, 6.0)),
        ("right", (10.0 - band, 4.0, 12.0, 6.0)),
    ):
        assert ac._inside_area([rect], RECT, edge) == [], edge
    assert ac._inside_area([(4.0, 10.0 - band - 0.5, 6.0, 12.0)], RECT, "bottom")


def test_any_hit_pairs_every_shape_with_every_rect():
    rects = [(0, 0, 2, 2), (8, 8, 10, 10)]
    assert ac._any_hit([("point", ((9, 9), 0.1))], rects)
    assert not ac._any_hit([("point", ((5, 5), 0.1))], rects)
    assert not ac._any_hit([], rects) and not ac._any_hit(
        [("point", ((9, 9), 0.1))], []
    )


# --------------------------------------------------------------------------- #
# _first_hit's reduction (_near_span): the same answers as testing every shape
# against every rect, without walking a pour's every vertex per rect
# --------------------------------------------------------------------------- #
def _naive_first_hit(shapes, rects):
    """What _first_hit means, stated the slow way: rect by rect, shape by
    shape, exact test every time."""
    for r in rects:
        if any(ac._shape_hits_rect(s, r) for s in shapes):
            return r
    return None


def _pour(x0, y0, x1, y1, steps=60):
    """A pour-like outline with many vertices along its edges -- the shape
    whose vertex count the reduction is there to stop paying per rect."""
    pts = []
    for i in range(steps):
        pts.append((x0 + (x1 - x0) * i / steps, y0))
    for i in range(steps):
        pts.append((x1, y0 + (y1 - y0) * i / steps))
    for i in range(steps):
        pts.append((x1 - (x1 - x0) * i / steps, y1))
    for i in range(steps):
        pts.append((x0, y1 - (y1 - y0) * i / steps))
    return ("poly", pts)


def test_a_pour_covering_the_rects_is_still_a_hit():
    # No edge of it comes anywhere near them, so the reduction answers the
    # whole set with one containment test -- it must answer "inside".
    rects = [(40 + i, 40, 40.5 + i, 45) for i in range(5)]
    assert ac._first_hit([_pour(0, 0, 100, 100)], rects) == rects[0]


def test_a_pour_the_rects_sit_outside_is_no_hit():
    rects = [(200 + i, 200, 200.5 + i, 205) for i in range(5)]
    assert ac._first_hit([_pour(0, 0, 100, 100)], rects) is None


def test_a_pour_edge_between_the_rects_hits_only_the_ones_it_reaches():
    # The pour's top edge runs at y=10: the rect below it overlaps, the one
    # above it does not, and the answer is the first rect that does.
    pour = _pour(0, 10, 100, 100)
    assert ac._first_hit([pour], [(20, 0, 21, 5)]) is None
    assert ac._first_hit([pour], [(20, 0, 21, 5), (30, 11, 31, 15)]) == (30, 11, 31, 15)


def test_a_degenerate_polygon_hits_nothing():
    for pts in ([], [(1, 1)], [(1, 1), (2, 2)]):
        assert ac._first_hit([("poly", pts)], [(0, 0, 10, 10)]) is None


def test_the_reduction_answers_exactly_as_the_naive_pairing_does():
    """The reduction is an optimisation, so it may not change a single answer:
    fuzz it against the definition over pours, tracks and vias in every
    relation to the rectangles (covering, crossing, touching, clear)."""
    import random

    rng = random.Random(20260813)
    for _ in range(300):
        shapes = []
        for _ in range(rng.randint(1, 4)):
            x0, x1 = sorted((rng.uniform(-20, 40), rng.uniform(-20, 40)))
            y0, y1 = sorted((rng.uniform(-20, 40), rng.uniform(-20, 40)))
            shapes.append(_pour(x0, y0, x1 + 0.1, y1 + 0.1, steps=8))
        for _ in range(rng.randint(0, 3)):
            a = (rng.uniform(-10, 30), rng.uniform(-10, 30))
            b = (a[0] + rng.uniform(-8, 8), a[1] + rng.uniform(-8, 8))
            shapes.append(("seg", (a, b, rng.choice((0.0, 0.5)))))
        for _ in range(rng.randint(0, 3)):
            p = (rng.uniform(-10, 30), rng.uniform(-10, 30))
            shapes.append(("point", (p, rng.choice((0.0, 0.4)))))
        rects = []
        for _ in range(rng.randint(1, 6)):
            x, y = rng.uniform(0, 20), rng.uniform(0, 20)
            rects.append((x, y, x + rng.uniform(0.1, 3), y + rng.uniform(0.1, 3)))
        assert ac._first_hit(shapes, rects) == _naive_first_hit(shapes, rects)


# --------------------------------------------------------------------------- #
# Board -> derotated frame
# --------------------------------------------------------------------------- #
def test_to_local_undoes_the_marker_rotation():
    # rot_deg maps the derotated frame back onto the board; _to_local applies
    # its inverse, so a board point comes back into the derotated frame.
    board_pt = ("point", ((0.0, -5.0), 0.0))
    (p, _r) = ac._to_local(board_pt, 90.0, (0.0, 0.0))[1]
    assert abs(p[0] - (-5.0)) < 1e-9 and abs(p[1] - 0.0) < 1e-9


def test_to_local_is_identity_for_a_grid_aligned_marker():
    seg = ("seg", ((3.0, 4.0), (7.0, 4.0), 0.2))
    out = ac._to_local(seg, 0.0, (1.0, 2.0))
    assert out[1][0] == (3.0, 4.0) and out[1][1] == (7.0, 4.0)
    assert out[1][2] == 0.2


def test_area_board_bbox_grows_with_rotation_and_pad():
    marker = {"area": (0.0, 0.0, 10.0, 4.0), "rot_deg": 0.0, "pivot": (5.0, 2.0)}
    assert ac._area_board_bbox(marker, 1.0) == (-1.0, -1.0, 11.0, 5.0)
    # A 90-degree marker swaps the rectangle's extents about the pivot.
    marker["rot_deg"] = 90.0
    x0, y0, x1, y1 = ac._area_board_bbox(marker, 0.0)
    assert round(x1 - x0, 6) == 4.0 and round(y1 - y0, 6) == 10.0


# --------------------------------------------------------------------------- #
# Copper drawn as board graphics (PCB_SHAPE) is seen, not just zones/tracks
# --------------------------------------------------------------------------- #
class _Pt:
    def __init__(self, x_mm, y_mm):
        self.x, self.y = int(x_mm * 1e6), int(y_mm * 1e6)


class _Box:
    def __init__(self, x_mm, y_mm, w_mm, h_mm):
        self._x, self._y = int(x_mm * 1e6), int(y_mm * 1e6)
        self._w, self._h = int(w_mm * 1e6), int(h_mm * 1e6)

    def GetX(self):
        return self._x

    def GetY(self):
        return self._y

    def GetWidth(self):
        return self._w

    def GetHeight(self):
        return self._h


class _FakeShape:
    """A minimal stand-in for a rectangle PCB_SHAPE on a copper layer."""

    def __init__(self, layer, x0, y0, x1, y1):
        self._layer = layer
        self._a, self._b = _Pt(x0, y0), _Pt(x1, y1)

    def GetShape(self):
        return _FAKE_PCBNEW.SHAPE_T_RECT

    def GetWidth(self):
        return 0

    def GetStart(self):
        return self._a

    def GetEnd(self):
        return self._b

    def GetLayer(self):
        return self._layer

    def GetBoundingBox(self):
        return _Box(
            min(self._a.x, self._b.x) / 1e6,
            min(self._a.y, self._b.y) / 1e6,
            abs(self._b.x - self._a.x) / 1e6,
            abs(self._b.y - self._a.y) / 1e6,
        )


class _FakeText:
    """A footprint's reference text on a copper layer: no GetShape, so the
    walk must leave it alone."""

    def __init__(self, layer):
        self._layer = layer

    def GetLayer(self):
        return self._layer


class _FakeFPID:
    def __init__(self, name):
        self._name = name

    def GetLibItemName(self):
        return self._name


class _FakeChain:
    def __init__(self, pts_mm):
        self._pts = [_Pt(x, y) for x, y in pts_mm]

    def PointCount(self):
        return len(self._pts)

    def CPoint(self, i):
        return self._pts[i]


class _FakePolySet:
    def __init__(self, polys_mm):
        self._outlines = [_FakeChain(p) for p in polys_mm]

    def OutlineCount(self):
        return len(self._outlines)

    def Outline(self, i):
        return self._outlines[i]


class _FakePad:
    """A pad with a real outline, the way the generated antenna's custom pad
    has one: ``GetEffectivePolygon`` takes no argument on KiCad 8 and a layer
    from 9 on, and this fake answers to the no-argument call."""

    def __init__(self, layer, polys_mm, bbox):
        self._layer = layer
        self._polys = _FakePolySet(polys_mm)
        self._bbox = bbox

    def IsOnLayer(self, layer_id):
        return layer_id == self._layer

    def GetEffectivePolygon(self):
        return self._polys

    def GetBoundingBox(self):
        return self._bbox


class _FakeBoxOnlyPad(_FakePad):
    """A pad on a build whose ``GetEffectivePolygon`` binding does not answer:
    the walk must fall back to the bounding box, not drop the pad."""

    def GetEffectivePolygon(self):
        raise TypeError("no matching function for overloaded call")


class _FakeFootprint:
    """A footprint carrying copper as pads and/or graphics -- named so the
    marker skip can be exercised."""

    def __init__(self, name, graphics=(), pads=()):
        self._fpid = _FakeFPID(name)
        self._graphics = list(graphics)
        self._pads = list(pads)

    def GetFPID(self):
        return self._fpid

    def Pads(self):
        return self._pads

    def GraphicalItems(self):
        return self._graphics


class _FakeBoard:
    """Two enabled copper layers (F_Cu = 0, B_Cu = 31) and copper drawn only
    as PCB_SHAPE graphics, on the board or inside footprints -- enough board
    for the check walk."""

    def __init__(self, drawings, footprints=()):
        self._drawings = drawings
        self._footprints = list(footprints)

    def GetTracks(self):
        return []

    def Zones(self):
        return []

    def GetFootprints(self):
        return self._footprints

    def GetDrawings(self):
        return self._drawings

    def GetCopperLayerCount(self):
        return 2

    def IsLayerEnabled(self, _layer_id):
        return True


class _FakePcbnew(types.ModuleType):
    ToMM = staticmethod(lambda iu: iu / 1e6)
    SHAPE_T_SEGMENT, SHAPE_T_RECT = 0, 1
    SHAPE_T_CIRCLE, SHAPE_T_ARC, SHAPE_T_POLYGON = 2, 3, 4
    F_Cu, B_Cu = 0, 31  # simulate.copper_layers reads these

    class PCB_VIA:  # nothing in the fake board is a via
        pass

    PCB_SHAPE = _FakeShape


_FAKE_PCBNEW = _FakePcbnew("pcbnew")


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


def test_copper_drawn_as_a_graphic_is_detected():
    # Regression: copper poured as a filled rectangle graphic (a PCB_SHAPE with
    # no net) must be seen, not only zones/tracks/pads. A rectangle drawn under
    # the area rectangle overlaps it.
    board = _FakeBoard([_FakeShape(layer=31, x0=5, y0=5, x1=35, y1=25)])
    clip = (-100, -100, 100, 100)
    shapes = _with_fake_pcbnew(lambda: list(ac._copper_shapes(board, 31, clip)))
    assert shapes and shapes[0][0] == "poly"
    area = (10.0, 10.0, 30.0, 20.0)
    assert any(ac._shape_hits_rect(s, area) for s in shapes)
    # A shape on another layer is ignored.
    assert _with_fake_pcbnew(lambda: list(ac._copper_shapes(board, 0, clip))) == []


def test_copper_inside_a_footprint_is_detected():
    # Regression: an antenna the plugin placed on an earlier run is a footprint
    # whose copper is fp_poly graphics on the feed layer (footprints.sexpr), so
    # a walk that only looks at board drawings and pads sees nothing of it and
    # the overlap warning never fires.
    from antenna_plugin.markers import area_marker

    board = _FakeBoard(
        [],
        [
            _FakeFootprint(
                "L_Monopole_2G45_23p6mm", [_FakeShape(0, 5, 5, 35, 25), _FakeText(0)]
            )
        ],
    )
    clip = (-100, -100, 100, 100)
    shapes = _with_fake_pcbnew(lambda: list(ac._copper_shapes(board, 0, clip)))
    # The reference text alongside it has no GetShape and is skipped.
    assert len(shapes) == 1 and shapes[0][0] == "poly"
    assert any(ac._shape_hits_rect(s, (10.0, 10.0, 30.0, 20.0)) for s in shapes)

    # ... but the wizard's own preview, drawn on the feed layer inside the area
    # marker, is a sketch of the candidate being judged, not copper it hits.
    marker = _FakeBoard(
        [], [_FakeFootprint(area_marker.MARKER_NAME, [_FakeShape(0, 5, 5, 35, 25)])]
    )
    assert _with_fake_pcbnew(lambda: list(ac._copper_shapes(marker, 0, clip))) == []


def test_a_pad_is_read_as_its_outline_not_its_bounding_box():
    # The generated antenna is one custom pad shaped like the radiator (that is
    # how its copper carries a net and can be routed to), so reading pads as
    # bounding boxes would claim the whole rectangle a meander reaches around
    # and warn about copper nowhere near it.
    ell = [(5, 5), (6, 5), (6, 25), (35, 25), (35, 24), (5, 24)]
    box = _Box(5, 5, 30, 20)
    board = _FakeBoard(
        [],
        [_FakeFootprint("Meandered_IFA_2G45_26p4mm", pads=[_FakePad(0, [ell], box)])],
    )
    clip = (-100, -100, 100, 100)
    shapes = _with_fake_pcbnew(lambda: list(ac._copper_shapes(board, 0, clip)))
    assert len(shapes) == 1 and shapes[0][0] == "poly"
    # Inside the bounding box, but in the L's empty corner: not copper.
    assert not any(ac._shape_hits_rect(s, (20.0, 10.0, 30.0, 20.0)) for s in shapes)
    # Over the arm itself: copper.
    assert any(ac._shape_hits_rect(s, (5.5, 10.0, 8.0, 12.0)) for s in shapes)

    # A build whose GetEffectivePolygon binding does not answer still sees the
    # pad, as the box it can get.
    boxed = _FakeBoard([], [_FakeFootprint("X", pads=[_FakeBoxOnlyPad(0, [ell], box)])])
    shapes = _with_fake_pcbnew(lambda: list(ac._copper_shapes(boxed, 0, clip)))
    assert len(shapes) == 1
    assert any(ac._shape_hits_rect(s, (20.0, 10.0, 30.0, 20.0)) for s in shapes)


def test_pcb_shape_rectangle_and_segment_decode():
    def run():
        kinds = ac._shape_kind_ids()
        tom = _FAKE_PCBNEW.ToMM

        def mm(pt):
            return (tom(int(pt.x)), tom(int(pt.y)))

        rect = _FakeShape(0, 1, 2, 9, 8)
        geoms = list(ac._pcb_shape_geoms(rect, kinds, mm, tom))
        assert geoms == [("poly", [(1.0, 2.0), (9.0, 2.0), (9.0, 8.0), (1.0, 8.0)])]

    _with_fake_pcbnew(run)


# --------------------------------------------------------------------------- #
# The checks against a fake board, through the CheckContext they all share
# --------------------------------------------------------------------------- #
_FRAME = {
    "area": (0.0, 0.0, 20.0, 10.0),
    "edge": "bottom",
    "rot_deg": 0.0,
    "pivot": (10.0, 5.0),
}


def test_antenna_overlap_warns_on_feed_layer_metal_under_the_antenna():
    # Copper drawn on F_Cu where the antenna's stem runs: one warning naming
    # the layer, from both the registry-facing and the place-time entry.
    board = _FakeBoard([_FakeShape(layer=0, x0=4, y0=4, x1=6, y1=6)])
    rects = [(5.0, 2.0, 5.5, 9.0)]  # the stem, marker frame
    problems = _with_fake_pcbnew(
        lambda: ac.antenna_problems(board, "F_Cu", _FRAME, rects)
    )
    assert [p.id for p in problems] == ["area-antenna-overlap"]
    assert "F_Cu" in problems[0].message
    assert all(p.severity == "warn" for p in problems)


def test_antenna_overlap_ignores_the_pour_the_stub_lands_on():
    # The ground pour just outside (and flush with) the feed edge: the stub
    # copper crossing out of the area onto it must not warn -- outside the
    # area is deliberately not judged.
    board = _FakeBoard([_FakeShape(layer=0, x0=-5, y0=10, x1=25, y1=14)])
    stem_with_reach = [(5.0, 2.0, 5.5, 11.0)]  # runs out through the edge
    problems = _with_fake_pcbnew(
        lambda: ac.antenna_problems(board, "F_Cu", _FRAME, stem_with_reach)
    )
    assert problems == []


def test_antenna_overlap_ignores_a_pour_hanging_over_the_feed_edge():
    # Regression: the feed point sits exactly ON the feed edge, so the
    # candidate's copper reaches it -- and the area is routinely placed
    # hanging a little over the pour, so the pour reaches a hair inside. That
    # combination used to warn on every candidate of every scan. A pour 0.5 mm
    # into the area at the feed edge is the connection, not an obstruction.
    board = _FakeBoard([_FakeShape(layer=0, x0=-5, y0=9.5, x1=25, y1=14)])
    stem = [(5.0, 2.0, 5.5, 10.0)]  # up against the feed edge
    assert (
        _with_fake_pcbnew(lambda: ac.antenna_problems(board, "F_Cu", _FRAME, stem))
        == []
    )
    # A pour flooding the whole area (the case worth warning about) still
    # warns -- the band only blinds the check to the first millimetre.
    flooded = _FakeBoard([_FakeShape(layer=0, x0=-5, y0=0, x1=25, y1=14)])
    assert [
        p.id
        for p in _with_fake_pcbnew(
            lambda: ac.antenna_problems(flooded, "F_Cu", _FRAME, stem)
        )
    ] == ["area-antenna-overlap"]


def test_antenna_overlap_names_where_the_metal_is():
    # The warning points at a board-frame spot the user can go and look at:
    # here the stem's judged part, centred at (5.25, 5.5) in the marker frame
    # and unrotated.
    board = _FakeBoard([_FakeShape(layer=0, x0=4, y0=4, x1=6, y1=6)])
    problems = _with_fake_pcbnew(
        lambda: ac.antenna_problems(board, "F_Cu", _FRAME, [(5.0, 2.0, 5.5, 9.0)])
    )
    assert "around (5.25, 5.50) mm" in problems[0].message


def test_antenna_overlap_follows_the_marker_rotation():
    # A 90-degree frame: board copper that lands under the antenna only once
    # mapped into the derotated frame. rot_deg maps local -> board, so put the
    # copper at the local rect's rotated position.
    frame = dict(_FRAME, rot_deg=90.0, pivot=(0.0, 0.0))
    local = (4.0, 4.0, 6.0, 6.0)
    corners = [
        markergeom.rotate_pt(p, 90.0, (0.0, 0.0))
        for p in ((local[0], local[1]), (local[2], local[3]))
    ]
    (bx0, by0), (bx1, by1) = corners
    board = _FakeBoard(
        [
            _FakeShape(
                layer=0,
                x0=min(bx0, bx1),
                y0=min(by0, by1),
                x1=max(bx0, bx1),
                y1=max(by0, by1),
            )
        ]
    )
    rects = [(3.5, 3.5, 6.5, 6.5)]
    hit = _with_fake_pcbnew(lambda: ac.antenna_problems(board, "F_Cu", frame, rects))
    assert [p.id for p in hit] == ["area-antenna-overlap"]
    # The same board copper misses an unrotated frame (it sits at negative x).
    assert (
        _with_fake_pcbnew(lambda: ac.antenna_problems(board, "F_Cu", _FRAME, rects))
        == []
    )


def test_antenna_overlap_needs_a_candidate_and_a_known_layer():
    ctx = ac.CheckContext(None, _FRAME, "F_Cu", 0, antenna_rects=None)
    assert ac._antenna_overlap_problems(ctx) == []  # nothing solved: quiet
    board = _FakeBoard([_FakeShape(layer=0, x0=4, y0=4, x1=6, y1=6)])
    assert (
        _with_fake_pcbnew(  # not a copper layer
            lambda: ac.antenna_problems(board, "In7_Cu", _FRAME, [(5.0, 2.0, 5.5, 9.0)])
        )
        == []
    )


def test_feed_axis_check_reads_the_outward_bands():
    # A pour just below the bottom (feed) edge grounds the port and shields
    # nothing; an empty board leaves the feed edge open.
    pour = _FakeShape(layer=0, x0=-5, y0=10.2, x1=25, y1=14)
    grounded = ac.CheckContext(_FakeBoard([pour]), _FRAME, "F_Cu", 0)
    assert _with_fake_pcbnew(lambda: ac._feed_axis_problems(grounded)) == []
    open_ctx = ac.CheckContext(_FakeBoard([]), _FRAME, "F_Cu", 0)
    ids = [p.id for p in _with_fake_pcbnew(lambda: ac._feed_axis_problems(open_ctx))]
    assert ids == ["area-feed-open"]


def test_stacked_copper_names_the_other_layer():
    board = _FakeBoard([_FakeShape(layer=31, x0=5, y0=5, x1=15, y1=8)])
    ctx = ac.CheckContext(board, _FRAME, "F_Cu", 0)
    problems = _with_fake_pcbnew(lambda: ac._stacked_copper_problems(ctx))
    assert [p.id for p in problems] == ["area-stacked-copper"]
    assert "B_Cu" in problems[0].message


def test_the_context_walks_each_layer_once():
    # local_shapes caches per layer, so however many checks probe a layer the
    # board is walked once -- the cost bound the registry design leans on.
    board = _FakeBoard([_FakeShape(layer=0, x0=4, y0=4, x1=6, y1=6)])
    walks = []
    original = board.GetDrawings
    board.GetDrawings = lambda: walks.append(1) or original()
    ctx = ac.CheckContext(board, _FRAME, "F_Cu", 0)
    _with_fake_pcbnew(lambda: (ctx.local_shapes(0), ctx.local_shapes(0)))
    assert len(walks) == 1


def test_the_registry_runs_every_board_only_check():
    # The overlap check is deliberately not in CHECKS: its copper comes from
    # the caller (a started pass, or the footprint being placed), not from the
    # board, so it runs through antenna_problems instead.
    assert ac.CHECKS == (ac._feed_axis_problems, ac._stacked_copper_problems)
    assert ac._antenna_overlap_problems not in ac.CHECKS
    # No area marker on the board: area_problems reports nothing (the area
    # section itself surfaces the missing marker).
    board = _FakeBoard([])
    assert _with_fake_pcbnew(lambda: ac.area_problems(board, "F_Cu")) == []


def test_area_problems_never_warns_about_an_antenna_by_itself():
    # Copper right under where an antenna would go is the overlap check's
    # business, and area_problems has no antenna to judge: whatever it
    # reports, it is not that warning.
    board = _FakeBoard([_FakeShape(layer=0, x0=4, y0=4, x1=6, y1=6)])
    ids = _with_fake_pcbnew(lambda: [p.id for p in ac.area_problems(board, "F_Cu")])
    assert "area-antenna-overlap" not in ids


# --------------------------------------------------------------------------- #
# Help pages ship and are self-contained
# --------------------------------------------------------------------------- #
def test_each_area_check_id_ships_a_self_contained_help_page():
    for pid, title in (
        ("area-antenna-overlap", "Antenna overlaps copper in the area"),
        ("area-feed-open", "Feed edge has no ground"),
        ("area-radiating-shielded", "Radiating edge is shielded"),
        ("area-stacked-copper", "Copper stacked over the area"),
    ):
        # The shared rule for every bundled guide lives in tests/helppage.py.
        assert_guide_loads(simulate.Problem(pid, "warn", "msg", title=title))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
