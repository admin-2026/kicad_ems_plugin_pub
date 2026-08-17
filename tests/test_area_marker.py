"""Unit tests for antenna_plugin.markers.area_marker's pure helpers (no KiCad).

Covers the marker's local shape, decoding placed segments back into
area + feed edge + feed position — under translation and any rotation (the
off-grid residual is recovered as rot_deg/pivot) — the slider-fraction
recovery and the validation errors. The package is assembled by
hand around the real modules because antenna_plugin/__init__ imports
pcbnew:  python3 tests/test_area_marker.py
"""

import importlib
import math
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Register a bare package (skipping antenna_plugin/__init__, which imports
# pcbnew) so area_marker's relative import of feed_marker works.
_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
area_marker = importlib.import_module("antenna_plugin.markers.area_marker")
markergeom = importlib.import_module("antenna_plugin.markers.markergeom")


def _place(segments, dx=0.0, dy=0.0, quarter_turns=0):
    """Rigid-place local segments like the editor would: rotate about the
    origin in 90-degree steps, then translate."""

    def xf(p):
        x, y = p
        for _ in range(quarter_turns % 4):
            x, y = -y, x
        return (round(x + dx, 6), round(y + dy, 6))

    return [(xf(a), xf(b)) for (a, b) in segments]


# --------------------------------------------------------------------------- #
# Local shape
# --------------------------------------------------------------------------- #
def test_local_segments_shape():
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    assert len(segs) == 9
    # The first segment is the bottom edge (max Y in the Y-down local
    # frame), drawn -x -> +x: the local-fraction hint relies on it.
    assert segs[0] == ((-15.0, 6.0), (15.0, 6.0))
    # The base is drawn as two halves meeting at the base centre on the
    # bottom edge at 30 %; segs[4]/[5] share that centre, segs[8] is the stem.
    base_c = segs[4][0]
    assert base_c == segs[5][0] == segs[8][0]
    assert base_c[1] == 6.0
    assert math.isclose(base_c[0], -15.0 + 0.3 * 30.0)
    # The two slopes rise to a single apex pointing inward (-Y locally).
    apex = segs[6][1]
    assert apex == segs[7][1]
    assert apex[1] < 6.0
    # The stem runs back out through the edge (past max Y).
    assert segs[8][1][1] > 6.0


def test_local_segments_clamps_triangle_off_corners():
    segs = area_marker._local_segments(30.0, 12.0, 0.0)
    (bl, br) = segs[4][1], segs[5][1]
    assert min(bl[0], br[0]) > -15.0  # never touches the corner
    d = area_marker._decode_segments(segs)
    assert 0.0 < d["frac"] < 0.2


def test_local_segments_rejects_tiny_area():
    try:
        area_marker._local_segments(1.0, 12.0, 0.5)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "at least" in str(exc)


def test_triangle_fits_a_shallow_area():
    # h = 2 mm: the apex must still land strictly inside.
    segs = area_marker._local_segments(30.0, 2.0, 0.5)
    d = area_marker._decode_segments(segs)
    assert d["edge"] == "bottom" and d["h_mm"] == 2.0


def test_explicit_triangle_width_sets_the_base_and_decodes_back():
    # The visual feed-width slider drives the triangle base width; it does
    # not move the feed point (base midpoint) or change the decoded area.
    auto = area_marker._decode_segments(area_marker._local_segments(30.0, 12.0, 0.3))
    wide = area_marker._decode_segments(
        area_marker._local_segments(30.0, 12.0, 0.3, tri_w_mm=4.0)
    )
    assert math.isclose(wide["tri_w_mm"], 4.0, abs_tol=1e-6)
    assert wide["tri_w_mm"] > auto["tri_w_mm"]
    assert wide["feed"] == auto["feed"] and wide["area"] == auto["area"]
    assert math.isclose(wide["frac"], 0.3, abs_tol=1e-6)


def test_explicit_triangle_width_clamped_to_fit_the_edge():
    # A base wider than the area is clamped so it stays between the corners.
    d = area_marker._decode_segments(
        area_marker._local_segments(6.0, 12.0, 0.5, tri_w_mm=50.0)
    )
    assert d["tri_w_mm"] <= 6.0


def test_dot_marks_the_feed_point_on_the_edge():
    # One dot, on the joint between the stem and the triangle: the base
    # centre on the feed edge, which is what the decode calls the feed point.
    for frac in (0.1, 0.5, 0.9):
        segs = area_marker._local_segments(30.0, 12.0, frac, tri_w_mm=4.0)
        dots = area_marker._local_dots(30.0, 12.0, frac, tri_w_mm=4.0)
        assert len(dots) == 1
        (center, radius) = dots[0]
        assert center == segs[8][0]  # the stem/triangle joint
        assert center[1] == 6.0  # on the bottom edge
        assert 0.05 <= radius <= 0.4
        # ... and it stays out of the decode, which only reads segments.
        assert area_marker._decode_segments(segs)["feed"] == (
            round(center[0], 3),
            round(center[1], 3),
        )


# --------------------------------------------------------------------------- #
# The feed arrow's stem (outward; decoding ignores it)
# --------------------------------------------------------------------------- #
def test_stem_is_half_the_base_width_and_points_outward():
    segs = area_marker._local_segments(30.0, 12.0, 0.3, tri_w_mm=4.0)
    (base_c, tail) = segs[8]  # the stem
    assert base_c[1] == 6.0 and tail[1] > 6.0  # outward, past the edge
    assert math.isclose(tail[1] - base_c[1], 4.0 / 2)  # half the base width
    # Decoding ignores the outward tail: the feed point is the base centre.
    d = area_marker._decode_segments(segs)
    assert math.isclose(d["tri_w_mm"], 4.0, abs_tol=1e-6)
    assert d["feed"] == (round(base_c[0], 3), round(base_c[1], 3))


# --------------------------------------------------------------------------- #
# Decode: identity, translation, rotations
# --------------------------------------------------------------------------- #
def test_decode_identity():
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    d = area_marker._decode_segments(segs)
    assert d["area"] == (-15.0, -6.0, 15.0, 6.0)
    assert d["edge"] == "bottom"
    assert math.isclose(d["frac"], 0.3, abs_tol=1e-6)
    assert d["w_mm"] == 30.0 and d["h_mm"] == 12.0
    assert d["feed"] == (-6.0, 6.0)


def test_decode_translated():
    segs = _place(area_marker._local_segments(30.0, 12.0, 0.3), dx=100.0, dy=50.0)
    d = area_marker._decode_segments(segs)
    assert d["area"] == (85.0, 44.0, 115.0, 56.0)
    assert d["edge"] == "bottom"
    assert d["feed"] == (94.0, 56.0)


def test_decode_all_rotations():
    # One quarter turn (x, y) -> (-y, x) maps the bottom edge (max Y) onto
    # min X = "left"; the feed fraction follows the edge's own direction
    # (from its smaller coordinate), so 0.3 flips to 0.7 when the local
    # left-to-right runs against it.
    local = area_marker._local_segments(30.0, 12.0, 0.3)
    expect = {0: ("bottom", 0.3), 1: ("left", 0.3), 2: ("top", 0.7), 3: ("right", 0.7)}
    for turns, (edge, frac) in expect.items():
        d = area_marker._decode_segments(
            _place(local, dx=40.0, dy=40.0, quarter_turns=turns)
        )
        assert d["edge"] == edge, f"{turns} turns"
        assert math.isclose(d["frac"], frac, abs_tol=1e-6), f"{turns} turns"
        assert d["w_mm"] == 30.0 and d["h_mm"] == 12.0
        # The slider's local fraction is rotation-invariant.
        assert math.isclose(
            area_marker._local_frac(
                _place(local, dx=40.0, dy=40.0, quarter_turns=turns), d
            ),
            0.3,
            abs_tol=1e-4,
        ), f"{turns} turns"


def test_local_frac_none_when_segments_reordered():
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    d = area_marker._decode_segments(segs)
    shuffled = [segs[1], segs[0]] + segs[2:]  # bottom edge no longer first
    assert area_marker._local_frac(shuffled, d) is None


# --------------------------------------------------------------------------- #
# Holding the feed point through a reshape
# --------------------------------------------------------------------------- #
def test_feed_point_mm_reads_the_arrow_where_it_lies():
    """Unlike the decode's ``feed``, this is unrounded and underotated -- it
    answers in the frame it is given, which is the board's."""
    segs = _place(area_marker._local_segments(30.0, 12.0, 0.3), dx=100.0, dy=50.0)
    assert area_marker.feed_point_mm(segs) == (94.0, 56.0)
    off_grid = markergeom.rotate_segments(segs, 12.5, (100.0, 50.0))
    turned = markergeom.rotate_pt((94.0, 56.0), 12.5, (100.0, 50.0))
    for got, want in zip(area_marker.feed_point_mm(off_grid), turned):
        assert math.isclose(got, want, abs_tol=1e-9)


def test_feed_point_mm_rejects_segments_with_no_arrow():
    rect_only = area_marker._local_segments(30.0, 12.0, 0.3)[:4]
    try:
        area_marker.feed_point_mm(rect_only)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "single feed arrow" in str(exc), str(exc)


def test_hold_shift_is_half_the_depth_the_area_gained():
    """The rectangle grows about the marker's own origin, so half of every
    millimetre of depth lands on the feed edge: sliding the marker back by this
    puts the feed where it was and the whole change on the far edge."""
    before = area_marker._local_segments(30.0, 12.0, 0.3)
    after = area_marker._local_segments(30.0, 20.0, 0.3)
    assert area_marker.hold_shift_mm(before, after) == (0.0, -4.0)
    # Shallower moves it the other way, and a width change (the feed stays on
    # its edge, at the fraction the section re-aims) needs no shift at all.
    shallower = area_marker._local_segments(30.0, 6.0, 0.3)
    assert area_marker.hold_shift_mm(before, shallower) == (0.0, 3.0)
    assert area_marker.hold_shift_mm(before, before) == (0.0, 0.0)


def test_hold_shift_follows_a_rotated_marker():
    """The shift is measured in the frame the segments are in, so a marker the
    user turned (R) is slid along its own feed normal, not the board's y."""
    for deg in (30.0, 90.0, -127.5):
        before = markergeom.rotate_segments(
            area_marker._local_segments(30.0, 12.0, 0.3), deg
        )
        after = markergeom.rotate_segments(
            area_marker._local_segments(30.0, 20.0, 0.3), deg
        )
        want = markergeom.rotate_pt((0.0, -4.0), deg)
        for got, expected in zip(area_marker.hold_shift_mm(before, after), want):
            assert math.isclose(got, expected, abs_tol=1e-9), deg


# --------------------------------------------------------------------------- #
# Validation errors
# --------------------------------------------------------------------------- #
def _expect_value_error(segs, needle):
    try:
        area_marker._decode_segments(segs)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert needle in str(exc), str(exc)


def test_decode_rejects_incomplete_marker():
    # A broken marker (a rectangle with only part of the feed arrow) has no
    # rectangle + arrow pairing to decode.
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    _expect_value_error(segs[:6], "rectangle + a feed")


def test_decode_recovers_off_grid_rotation():
    # A 30-degree rotation decodes: the area comes back in the derotated
    # frame with the residual rot_deg/pivot that map it onto the board.
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    segs = [
        (
            (a[0] * c - a[1] * s + 40.0, a[0] * s + a[1] * c + 50.0),
            (b[0] * c - b[1] * s + 40.0, b[0] * s + b[1] * c + 50.0),
        )
        for (a, b) in area_marker._local_segments(30.0, 12.0, 0.3)
    ]
    d = area_marker._decode_segments(segs)
    assert math.isclose(d["rot_deg"], 30.0, abs_tol=1e-3)
    assert d["pivot"] == (40.0, 50.0)  # the rectangle centre
    assert d["edge"] == "bottom"
    assert math.isclose(d["frac"], 0.3, abs_tol=1e-4)
    assert math.isclose(d["w_mm"], 30.0, abs_tol=1e-3)
    assert math.isclose(d["h_mm"], 12.0, abs_tol=1e-3)
    # Derotated frame: the area is the local rectangle about the pivot.
    assert d["area"] == (25.0, 44.0, 55.0, 56.0)
    # The feed point sits in the derotated frame too: the local base
    # midpoint (-6, 6) about the pivot.
    assert d["feed"] == (34.0, 56.0)


def test_on_grid_markers_report_zero_rotation():
    local = area_marker._local_segments(30.0, 12.0, 0.3)
    for turns in range(4):
        d = area_marker._decode_segments(
            _place(local, dx=40.0, dy=40.0, quarter_turns=turns)
        )
        assert d["rot_deg"] == 0.0, f"{turns} turns"


def test_decode_rejects_detached_triangle():
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    # Push the triangle off the rectangle's edge.
    tri = [((x0, y0 + 3.0), (x1, y1 + 3.0)) for ((x0, y0), (x1, y1)) in segs[4:]]
    _expect_value_error(segs[:4] + tri, "not attached")


def test_decode_rejects_outward_arrow():
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    # Mirror the whole feed arrow about the bottom edge (y=6): a valid arrow
    # that points out of the area instead of into it.
    feed = [((x0, 12.0 - y0), (x1, 12.0 - y1)) for ((x0, y0), (x1, y1)) in segs[4:]]
    _expect_value_error(segs[:4] + feed, "point into")


def test_decode_rejects_open_arrow():
    segs = area_marker._local_segments(30.0, 12.0, 0.3)
    (a, b) = segs[6]  # a slope; shift its apex end
    broken = segs[:6] + [(a, (b[0] + 1.0, b[1] - 1.0))] + segs[7:]
    _expect_value_error(broken, "regenerate")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
