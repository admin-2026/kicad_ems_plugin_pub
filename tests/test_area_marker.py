"""Unit tests for antenna_plugin.markers.area_marker's pure helpers (no KiCad).

Covers the marker's local shape, decoding placed segments back into
area + feed edge + feed position — under translation and any rotation (the
off-grid residual is recovered as rot_deg/pivot) — the pinning that lands a
dragged feed arrow back on the rectangle, and the validation errors. The
package is assembled by
hand around the real modules because antenna_plugin/__init__ imports
pcbnew:  python3 tests/test_area_marker.py
"""

import math
import pathlib

from bare_package import load

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Register a bare package (skipping antenna_plugin/__init__, which imports
# pcbnew) so area_marker's relative import of feed_marker works.
area_marker = load("markers.area_marker")
markergeom = load("emkit.markers.markergeom")


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


# --------------------------------------------------------------------------- #
# Reading the feed point where it lies
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


# --------------------------------------------------------------------------- #
# Pinning a dragged feed arrow back onto the rectangle
# --------------------------------------------------------------------------- #
def _drag(segments, first, dx, dy):
    """Move ``segments[first:]`` by (dx, dy) -- the user dragging the feed
    arrow off its edge, with the rectangle left where it is."""
    return segments[:first] + [
        ((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)) for (a, b) in segments[first:]
    ]


def test_pin_feed_takes_the_edge_the_drop_is_nearest():
    area = (-15.0, -6.0, 15.0, 6.0)
    for point, edge in (
        ((0.0, 5.0), "bottom"),
        ((0.0, -5.0), "top"),
        ((-14.0, 0.0), "left"),
        ((14.0, 0.0), "right"),
    ):
        pinned = area_marker.pin_feed(area, point, tri_w_mm=2.0)
        assert pinned["edge"] == edge, point
        # The base centre lands *on* that edge, and the apex points inward.
        segs = area_marker._decode_segments(
            area_marker._rect_segments(area) + pinned["segments"]
        )
        assert segs["edge"] == edge and segs["feed"] == (
            round(pinned["feed"][0], 3),
            round(pinned["feed"][1], 3),
        )


def test_pin_feed_keeps_the_position_along_the_edge():
    area = (0.0, 0.0, 40.0, 10.0)
    pinned = area_marker.pin_feed(area, (30.0, 9.4), tri_w_mm=2.0)
    assert pinned["edge"] == "bottom"
    assert math.isclose(pinned["feed"][0], 30.0)  # kept its x
    assert pinned["feed"][1] == 10.0  # squared onto the edge
    assert math.isclose(pinned["frac"], 0.75)


def test_pin_feed_clamps_a_drop_past_the_corner():
    area = (0.0, 0.0, 40.0, 10.0)
    pinned = area_marker.pin_feed(area, (200.0, 9.0), tri_w_mm=4.0)
    assert pinned["edge"] == "bottom"
    assert pinned["feed"][0] < 40.0 - 2.0  # the triangle stays off the corner
    area_marker._decode_segments(
        area_marker._rect_segments(area) + pinned["segments"]
    )  # ... and so the marker still decodes


def test_repin_squares_a_dragged_arrow_back_onto_the_edge():
    """The drag half of the marker: the arrow is dropped 3 mm inside the area
    and 4 mm along it, and the repin puts it back on the edge under the drop."""
    placed = _place(area_marker._local_segments(30.0, 12.0, 0.3), dx=100.0, dy=50.0)
    dragged = _drag(placed, 4, 4.0, -3.0)
    arrow, dots, pinned = area_marker.repin_geometry(dragged)
    assert pinned["edge"] == "bottom"
    repinned = area_marker._decode_segments(dragged[:4] + arrow)
    assert repinned["feed"] == (98.0, 56.0)  # 94 + 4, back on the edge
    assert dots[0][0] == (98.0, 56.0)  # the dot rides with it


def test_repin_moves_the_feed_to_another_edge():
    """Drag the arrow across the rectangle and the feed edge follows: the
    marker feeds from wherever the user put the arrow."""
    placed = area_marker._local_segments(30.0, 12.0, 0.5)
    dragged = _drag(placed, 4, -14.0, -6.0)  # over to the left edge
    arrow, _dots, pinned = area_marker.repin_geometry(dragged)
    assert pinned["edge"] == "left"
    assert area_marker._decode_segments(placed[:4] + arrow)["edge"] == "left"


def test_repin_follows_an_edge_that_was_dragged():
    """The other drag: the user pulls the rectangle's bottom edge up (a corner
    handle), leaving the arrow behind. The repin lands it on the edge's new
    place, at the same position along it."""
    placed = area_marker._local_segments(30.0, 20.0, 0.3)
    shallow = area_marker._rect_segments((-15.0, -10.0, 15.0, 2.0)) + placed[4:]
    arrow, _dots, pinned = area_marker.repin_geometry(shallow)
    assert pinned["edge"] == "bottom"
    d = area_marker._decode_segments(shallow[:4] + arrow)
    assert d["feed"] == (-6.0, 2.0)  # same x, the edge's new y
    assert math.isclose(d["frac"], 0.3, abs_tol=1e-6)


def test_repin_keeps_the_drawn_triangle_width_unless_given_one():
    placed = area_marker._local_segments(30.0, 12.0, 0.3, tri_w_mm=4.0)
    arrow, _dots, _pinned = area_marker.repin_geometry(_drag(placed, 4, 1.0, -1.0))
    kept = area_marker._decode_segments(placed[:4] + arrow)
    assert math.isclose(kept["tri_w_mm"], 4.0, abs_tol=1e-6)
    arrow, _dots, _pinned = area_marker.repin_geometry(placed, tri_w_mm=1.5)
    asked = area_marker._decode_segments(placed[:4] + arrow)
    assert math.isclose(asked["tri_w_mm"], 1.5, abs_tol=1e-6)


def test_repin_writes_back_in_the_board_frame_of_a_rotated_marker():
    """Pinning happens in the rectangle's own frame; what comes back is board
    frame, so a marker the user turned off-grid keeps its rotation and its
    arrow still decodes as attached and inward-pointing."""
    turned = markergeom.rotate_segments(
        _place(area_marker._local_segments(30.0, 12.0, 0.3), dx=100.0, dy=50.0),
        18.0,
        (100.0, 50.0),
    )
    dragged = _drag(turned, 4, 2.0, -2.0)
    arrow, _dots, _pinned = area_marker.repin_geometry(dragged)
    d = area_marker._decode_segments(dragged[:4] + arrow)
    assert math.isclose(d["rot_deg"], 18.0, abs_tol=1e-3)
    assert d["edge"] == "bottom"
    assert math.isclose(d["w_mm"], 30.0, abs_tol=1e-3)


def test_repin_rejects_a_marker_that_is_not_one():
    try:
        area_marker.repin_geometry(area_marker._local_segments(30.0, 12.0, 0.3)[:6])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "rectangle + a feed" in str(exc), str(exc)


# --------------------------------------------------------------------------- #
# Squaring an outline a drag pulled out of shape
# --------------------------------------------------------------------------- #
def _rect_corners(x0, y0, x1, y1, deg=0.0):
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [markergeom.rotate_pt(p, deg, (0.0, 0.0)) for p in corners]


def _is_square(corners):
    for i in range(4):
        a, b, c = corners[i - 1], corners[i], corners[(i + 1) % 4]
        u = (a[0] - b[0], a[1] - b[1])
        v = (c[0] - b[0], c[1] - b[1])
        if abs(u[0] * v[0] + u[1] * v[1]) > 1e-6:
            return False
    return True


def test_square_outline_leaves_a_rectangle_exactly_alone():
    for deg in (0.0, 90.0, 31.5):
        corners = _rect_corners(-15.0, -6.0, 15.0, 6.0, deg)
        assert area_marker.square_outline(corners) == corners, deg


def test_square_outline_reads_a_dragged_corner_as_a_rectangle_drag():
    """One vertex moved: the corner opposite it anchors, the dragged corner
    stays exactly where it was dropped, and the two beside it follow — which is
    what KiCad's own rectangle handles do."""
    for deg in (0.0, 25.0, -40.0):
        corners = _rect_corners(0.0, 0.0, 30.0, 12.0, deg)
        dragged = list(corners)
        dragged[2] = (corners[2][0] + 4.0, corners[2][1] - 3.0)
        squared = area_marker.square_outline(dragged)
        assert _is_square(squared), deg
        assert squared[0] == corners[0], deg  # the anchor did not move
        for got, want in zip(squared[2], dragged[2]):
            assert math.isclose(got, want, abs_tol=1e-9), deg


def test_square_outline_reads_a_dragged_edge_too():
    """Two corners moving together is an edge drag, and squares up the same
    way: the edge lands where it was dropped and the other three sides
    follow."""
    corners = _rect_corners(0.0, 0.0, 30.0, 12.0)
    dragged = [(0.0, -4.0), (30.0, -4.0), (30.0, 12.0), (0.0, 12.0)]
    squared = area_marker.square_outline(dragged)
    assert _is_square(squared)
    assert squared == dragged  # already a rectangle: nothing to square
    assert corners != dragged


def test_square_outline_falls_back_to_the_bounding_box():
    """Two independent drags: no single corner explains the shape, so the area
    becomes the box around what was drawn rather than an error."""
    corners = [(0.0, 0.0), (30.0, 2.0), (28.0, 12.0), (-1.0, 9.0)]
    squared = area_marker.square_outline(corners)
    assert _is_square(squared)
    assert len(squared) == 4


def test_square_outline_squares_a_polygon_that_grew_a_corner():
    """KiCad's polygon editor can *add* a vertex; five corners is not a
    rectangle drag either, and squares up the same way."""
    corners = [(0.0, 0.0), (15.0, -2.0), (30.0, 0.0), (30.0, 12.0), (0.0, 12.0)]
    squared = area_marker.square_outline(corners)
    assert len(squared) == 4 and _is_square(squared)


# --------------------------------------------------------------------------- #
# The marker's whole rotation, in the degrees KiCad means
# --------------------------------------------------------------------------- #
def test_feed_angle_is_zero_for_a_marker_as_placed():
    d = area_marker._decode_segments(area_marker._local_segments(30.0, 12.0, 0.3))
    assert area_marker.feed_angle_deg(d) == 0.0


def test_feed_angle_counts_counter_clockwise_on_screen():
    """KiCad's own convention, so the field reads like a footprint's angle. A
    quarter turn counter-clockwise carries the bottom (feed) edge round to the
    right-hand side; the test's own _place turns the other way, so its quarter
    turns count 270, 180, 90."""
    local = area_marker._local_segments(30.0, 12.0, 0.3)
    for turns, angle in ((0, 0.0), (1, 270.0), (2, 180.0), (3, 90.0)):
        d = area_marker._decode_segments(_place(local, quarter_turns=turns))
        assert area_marker.feed_angle_deg(d) == angle, turns


def test_feed_angle_carries_the_off_grid_residual():
    turned = markergeom.rotate_segments(  # 30 deg clockwise on screen
        area_marker._local_segments(30.0, 12.0, 0.3), 30.0
    )
    d = area_marker._decode_segments(turned)
    assert math.isclose(area_marker.feed_angle_deg(d), 330.0, abs_tol=1e-3)


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
