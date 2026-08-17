"""Unit tests for the L-shaped monopole design (no KiCad, no wx).

The layout itself -- bend direction, what overflows the area, capacity and the
errors a bad area produces -- plus the footprint it generates. The shared
machinery it rides on has its own tests (test_geometry / test_sizing /
test_measure), and what the wizard *draws* for a candidate that doesn't fit is
design/fit.py's (test_fit.py); the one fit case here is the stem, because it is
the design's own reason for not fitting.

    python3 tests/test_lmonopole.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

fit = load("design.fit")
footprints = load("design.footprints")
registry = load("design.registry")

DESIGN = registry.by_key("lmonopole")

# A 20 x 8 mm area at (10, 30)..(30, 38), KiCad mm (Y down).
AREA = (10.0, 30.0, 30.0, 38.0)


def _v(length, width=1.0, stem=6.0):
    return {"length": length, "width": width, "stem": stem}


def _solve(edge="bottom", frac=0.5, **kw):
    return DESIGN.solve(AREA, edge, frac, _v(**kw))


def _points(geo):
    (path,) = geo.paths
    return list(path.points)


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
# BORDER_MM (0.5) is the fixed border keepout, so half = trace_w/2 + 0.5.
def test_solve_straight_when_stem_covers_it():
    # total 5 <= stem 6 -> the whole length is vertical, no arm.
    geo = _solve(length=5.0, stem=6.0)
    assert _points(geo) == [(20.0, 38.0), (20.0, 33.0)]
    assert geo.metrics["stem_mm"] == 5.0 and geo.metrics["arm_mm"] == 0.0
    assert geo.feed == (20.0, 38.0) and geo.inward == (0, -1)
    assert geo.total_mm == 5.0


def test_solve_stem_sets_bend_point():
    # Feed at 25 % from the left: more room to the right. A 4 mm stem bends
    # 4 mm in, leaving an 8 mm horizontal arm (total 12).
    geo = _solve(frac=0.25, length=12.0, stem=4.0)
    (f, c, e) = _points(geo)
    assert f == (15.0, 38.0)
    assert c == (15.0, 34.0)  # 4 up (inward) from the feed
    assert e == (23.0, 34.0)
    assert geo.metrics["stem_mm"] == 4.0 and geo.metrics["arm_mm"] == 8.0

    # Feed at 75 %: bends left instead.
    geo = _solve(frac=0.75, length=12.0, stem=4.0)
    assert _points(geo)[2] == (17.0, 34.0)


def test_solve_rejects_a_stem_deeper_than_the_area():
    # The area is 8 mm deep, so a centerline may run 7 in (half = 1). A stem
    # past that is not trimmed to fit -- it doesn't fit, and the wizard draws
    # it on the marker layer instead of on copper (see the fit test below).
    try:
        _solve(frac=0.25, length=12.0, stem=99.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "stem does not fit" in str(exc) and "7.0 mm deep" in str(exc)


def test_a_short_antenna_never_reaches_a_too_deep_stem():
    # Only the length actually spent on the stem has to fit the depth: a 4 mm
    # antenna is a 4 mm straight monopole whatever the stem row says.
    geo = _solve(frac=0.25, length=4.0, stem=99.0)
    assert geo.metrics["stem_mm"] == 4.0 and geo.metrics["arm_mm"] == 0.0
    # ... and the first millimetre past the depth is where it stops fitting.
    _solve(frac=0.25, length=7.0, stem=99.0)
    try:
        _solve(frac=0.25, length=7.1, stem=99.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "stem does not fit" in str(exc)


def test_solve_rejects_nonpositive_values():
    for values, want in (
        (_v(5.0, stem=0.0), "stem length"),
        (_v(0.0), "antenna length"),
        (_v(5.0, width=0.0), "track width"),
    ):
        try:
            DESIGN.solve(AREA, "bottom", 0.5, values)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert want in str(exc)


def test_solve_left_edge_straight():
    geo = _solve(edge="left", length=10.0, stem=12.0)
    assert _points(geo) == [(10.0, 34.0), (20.0, 34.0)]
    assert geo.inward == (1, 0)


def test_solve_feed_clamped_to_edge_span():
    geo = _solve(frac=0.0, length=4.0, stem=6.0)
    assert _points(geo)[0] == (11.0, 38.0)  # x0 + half


def test_capacity_and_overflow():
    # A stem that fits the depth: cap = stem(4) + right room(29 - 15 = 14).
    cap = DESIGN.capacity_mm(AREA, "bottom", 0.25, _v(0.0, stem=4.0))
    assert math.isclose(cap, 4.0 + 14.0)
    _solve(frac=0.25, length=cap, stem=4.0)  # exactly fits
    try:
        _solve(frac=0.25, length=cap + 0.1, stem=4.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "does not fit" in str(exc)


def test_capacity_of_a_stem_deeper_than_the_area_is_the_depth():
    # Nothing longer than the depth (7) reaches the bend before the far
    # border, so there is no arm to add the 14 mm of room to.
    cap = DESIGN.capacity_mm(AREA, "bottom", 0.25, _v(0.0, stem=10.0))
    assert math.isclose(cap, 7.0)
    _solve(frac=0.25, length=cap, stem=10.0)  # exactly fits
    try:
        _solve(frac=0.25, length=cap + 0.1, stem=10.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "does not fit" in str(exc)


def test_an_overflowing_stem_has_a_shape_to_draw_on_the_marker_layer():
    """What the wizard shows while the stem row is dragged past the area's
    depth: not an empty marker, but the antenna the user asked for, spilling
    out through the far border (fit.check picks the layer from ``ok``)."""
    state = fit.check(DESIGN, AREA, "bottom", 0.25, _v(12.0, stem=10.0))
    assert not state.ok and state.geo is None
    assert state.preview is state.overflow is not None
    # The stem the user asked for, at full depth -- and it really does leave
    # the rectangle (Y down, so the far border is y0 = 30).
    assert state.overflow.metrics["stem_mm"] == 10.0
    assert state.overflow.total_mm == 12.0
    assert (
        min(y for (a, b) in state.overflow.centerline_segments() for (_x, y) in (a, b))
        < AREA[1]
    )
    assert "shorten the stem" in state.detail


def test_a_stem_that_would_short_the_arm_to_the_pour_is_refused():
    # The arm runs *along* the feed edge at the stem's depth, and a 1 mm track
    # hangs 0.5 mm below its centerline: at a 0.3 mm stem that copper is over
    # the edge and into the ground pour, shorting the antenna out. The feed
    # edge is the one border with no keepout (the feed pin has to cross it),
    # so this is the only thing standing between the arm and the pour.
    try:
        _solve(length=8.0, stem=0.5)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "clear the ground pour" in str(exc)
        assert "0.75 mm" in str(exc)  # half the track + the track gap

    # A straight monopole has no arm to bend into the pour, so a shallow stem
    # is none of this rule's business: the length never reaches the bend.
    assert _solve(length=0.2, stem=0.5).metrics["arm_mm"] == 0.0
    # ... and the threshold follows the track: a 0.3 mm one may sit at 0.5.
    assert _solve(length=8.0, width=0.3, stem=0.5).metrics["stem_mm"] == 0.5


def test_the_arm_never_runs_its_copper_over_the_feed_edge():
    # The same sweep the inverted-F gets: whatever the design accepts must
    # keep its copper on the antenna's side of the feed edge (y = 38 here).
    for width in (0.3, 1.0, 2.0):
        for stem in (0.1, 0.25, 0.5, 0.75, 1.5, 3.0):
            for length in (4.0, 12.0, 20.0):
                try:
                    geo = _solve(length=length, width=width, stem=stem)
                except ValueError:
                    continue  # refused, which is a fine way to be safe
                over = [
                    r
                    for r in geo.copper_rects(width, 0.3, include_stub=False)
                    if r[3] > AREA[3] + 1e-9
                ]
                assert not over, (width, stem, length, over[:1])


def test_too_small_area_raises():
    try:
        DESIGN.solve((0, 0, 1.5, 8), "bottom", 0.5, _v(3.0, stem=4.0))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "too narrow" in str(exc)


def test_describe_reads_as_the_split():
    assert (
        DESIGN.describe(_solve(frac=0.25, length=12.0, stem=4.0)) == "stem 4 + arm 8 mm"
    )


# --------------------------------------------------------------------------- #
# Copper
# --------------------------------------------------------------------------- #
def test_copper_rects_straight_includes_ground_stub():
    rects = _solve(length=5.0, stem=6.0).copper_rects(1.0, 0.5)
    assert len(rects) == 1
    (x0, y0, x1, y1) = rects[0]
    assert (x0, x1) == (19.5, 20.5)
    # From the arm tip (33.0) to the stub end: 38 + 0.25 + 1.0 = 39.25.
    assert (y0, y1) == (33.0, 39.25)


def test_copper_rects_bend_overlaps_corner():
    r1, r2 = _solve(frac=0.25, length=12.0, stem=7.0).copper_rects(1.0, 0.5)
    # Vertical arm overshoots the bend centerline by the half-width.
    assert r1 == (14.5, 30.5, 15.5, 39.25)
    assert r2 == (15.0, 30.5, 20.0, 31.5)


def test_footprint_rects_have_no_stub():
    (x0, y0, x1, y1) = _solve(length=5.0, stem=6.0).copper_rects(
        1.0, 0.5, include_stub=False
    )[0]
    assert (y0, y1) == (33.0, 38.0)


# --------------------------------------------------------------------------- #
# Footprint
# --------------------------------------------------------------------------- #
def test_footprint_name_has_no_dots():
    name = footprints.item_name(DESIGN, 2.45, 23.62)
    assert name == "L_Monopole_2G45_23p6mm"
    assert "." not in name


def test_footprint_sexpr_layout():
    geo = _solve(frac=0.25, length=12.0, stem=7.0)
    text = footprints.sexpr(DESIGN, geo, _v(12.0, stem=7.0), 2.45)
    assert text.count("(") == text.count(")")
    assert '(pad "1" smd custom (at 0 0) (size 1 1)' in text
    assert text.count("gr_poly") == 2
    # One pad, one net: nothing is shorted, so no net tie is declared.
    assert "net_tie_pad_groups" not in text
    # Local frame: the feed point is the origin; the 7 mm stem runs to -Y
    # and overshoots the bend centerline by the 0.5 mm half-width.
    assert "(xy -0.5 -7.5)" in text
    assert "board_only" not in text
    assert "(attr smd exclude_from_pos_files exclude_from_bom)" in text


def test_footprint_straight_single_poly():
    values = _v(5.0, stem=6.0)
    text = footprints.sexpr(DESIGN, _solve(length=5.0, stem=6.0), values, 2.45)
    assert text.count("gr_poly") == 1
    assert text.count("(pad ") == 1  # only the feed


if __name__ == "__main__":
    run_module_tests(globals())
