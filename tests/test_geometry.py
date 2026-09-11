"""Unit tests for antenna_plugin.design.geometry -- the planar engine every
antenna design is built on (no KiCad, no wx).

Covers the area's edge frame, the serpentine meander builder, centerline ->
copper rectangles (corner squaring and stubs), the off-grid rotation, the
G36-region gerber splice, and the Geometry's own copper / preview / feed
views. All of it design-independent: the geometries here are hand-built, so a
failure points at this module and not at a topology.

    python3 tests/test_geometry.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

geometry = load("design.geometry")

# A 20 x 8 mm area at (10, 30)..(30, 38), KiCad mm (Y down: "bottom" = max Y).
AREA = (10.0, 30.0, 30.0, 38.0)


def _close(a, b, tol=1e-9):
    return math.hypot(a[0] - b[0], a[1] - b[1]) < tol


# --------------------------------------------------------------------------- #
# Edge frame
# --------------------------------------------------------------------------- #
def test_edge_frame_bottom_places_feed_and_rooms():
    # half = trace 1.0 / 2 + BORDER 0.5 = 1.0.
    fr = geometry.edge_frame(AREA, "bottom", 0.25, 1.0)
    assert fr.feed == (15.0, 38.0)
    assert fr.inward == (0, -1)
    assert fr.tangent == (1, 0)  # more room to the +x side
    assert fr.depth_mm == 7.0  # 8 deep - 1 half
    assert fr.room_mm == 14.0  # 29 - 15
    assert fr.back_mm == 4.0  # 15 - 11


def test_edge_frame_tangent_follows_the_roomier_side():
    fr = geometry.edge_frame(AREA, "bottom", 0.75, 1.0)
    assert fr.tangent == (-1, 0)
    assert (fr.room_mm, fr.back_mm) == (14.0, 4.0)


def test_edge_frame_left_edge_swaps_the_axes():
    fr = geometry.edge_frame(AREA, "left", 0.5, 1.0)
    assert fr.feed == (10.0, 34.0)
    assert fr.inward == (1, 0)
    assert fr.tangent in ((0, 1), (0, -1))
    assert fr.depth_mm == 19.0  # 20 wide - 1 half


def test_edge_frame_clamps_the_feed_into_the_edge_span():
    fr = geometry.edge_frame(AREA, "bottom", 0.0, 1.0)
    assert fr.feed == (11.0, 38.0)  # x0 + half
    assert fr.back_mm == 0.0


def test_edge_frame_rejects_a_too_small_area():
    for area, want in (
        ((0, 0, 1.5, 8), "too narrow"),
        ((0, 0, 20, 0.4), "too shallow"),
    ):
        try:
            geometry.edge_frame(area, "bottom", 0.5, 1.0)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert want in str(exc)


def test_edge_frame_rejects_an_unknown_edge():
    try:
        geometry.edge_frame(AREA, "diagonal", 0.5, 1.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unknown edge" in str(exc)


# --------------------------------------------------------------------------- #
# Walking a centerline
# --------------------------------------------------------------------------- #
def test_step_and_path_length():
    assert geometry.step((1.0, 2.0), (0, -1), 3.0) == (1.0, -1.0)
    assert geometry.opposite((0, -1)) == (0, 1)
    assert math.isclose(geometry.path_length([(0, 0), (3, 0), (3, 4)]), 7.0)


# --------------------------------------------------------------------------- #
# Meander
# --------------------------------------------------------------------------- #
RIGHT, UP = (1, 0), (0, -1)  # KiCad Y-down: "up" is into the area


def test_meander_straight_when_it_fits():
    run = geometry.meander_run((0.0, 0.0), RIGHT, UP, 8.0, 10.0, 5.0, 1.25)
    assert run.points == [(8.0, 0.0)]
    assert (run.crossings, run.folds, run.cross, run.tail, run.advance) == (
        0,
        0,
        0.0,
        0.0,
        8.0,
    )


def test_meander_folds_and_keeps_the_length_exact():
    # 30 mm of centerline into 10 mm of room: 20 mm must come from folds,
    # and 5 mm-deep ones buy 2 x 5 each -> 2 folds.
    start = (0.0, 0.0)
    run = geometry.meander_run(start, RIGHT, UP, 30.0, 10.0, 5.0, 1.25)
    pts = run.points
    assert run.crossings == 4 and run.cross == run.tail == 5.0
    assert run.advance == 10.0 and run.lead == 0.0
    assert math.isclose(geometry.path_length([start] + pts), 30.0, abs_tol=1e-9)
    # 2 folds cross the band 4 times with 3 forward legs between them.
    assert len(pts) == 7
    assert _close(pts[-1], (10.0, 0.0))
    # Every fold reaches `depth` into the area and no further.
    assert min(y for _x, y in pts) == -5.0


def test_meander_starts_and_ends_toward_the_start_edge():
    # The run crosses the band before travelling at all and finishes on a
    # crossing too, so both its first and its last segment point at the edge
    # `start` sits on -- toward the feed, not away from it.
    start = (0.0, 0.0)
    pts = geometry.meander_run(start, RIGHT, UP, 30.0, 10.0, 5.0, 1.25).points
    assert _close(pts[0], (0.0, -5.0))  # straight up, at the feed
    assert _close(pts[1], (10 / 3, -5.0))  # along the back of the area
    assert _close(pts[2], (10 / 3, 0.0))  # the first fold, back toward it
    assert _close(pts[-2], (10.0, -5.0))  # and the last one ends the run,
    assert _close(pts[-1], (10.0, 0.0))  # tip pointing back at the edge


def test_meander_rides_the_far_border_and_keeps_the_whole_room():
    # Where the remainder is a tail in its own right, nothing gives at all:
    # every full crossing runs the whole band, so the run's far side rests on
    # the far border, *and* it still travels the whole room. What absorbs the
    # length is the crossing count -- half a fold at a time, the last crossing
    # taking the remainder.
    start = (0.0, 0.0)
    seen = []
    for length in (20.0, 30.0, 40.0, 47.0):
        run = geometry.meander_run(start, RIGHT, UP, length, 10.0, 5.0, 1.25)
        assert run.cross == 5.0, length  # every full crossing to the border
        assert min(y for _x, y in run.points) == -5.0, length
        assert run.advance == 10.0, length  # ... and the whole room, every time
        assert max(x for x, _y in run.points) == 10.0, length
        assert 0 < run.tail <= run.cross + 1e-9, length
        assert math.isclose(
            geometry.path_length([start] + run.points), length, abs_tol=1e-9
        ), length
        seen.append((run.crossings, run.tail))
    # More length is another crossing of the band, and the tail is the part of
    # one the length does not fill (47 mm asks for half a fold more than 6).
    assert seen == [(2, 5.0), (4, 5.0), (6, 5.0), (8, 2.0)]


def test_meander_holds_the_room_and_the_border_across_a_fold_boundary():
    # The regression this rule exists for: a length sweep walking over the
    # point where another crossing appears must change nothing but the length.
    # Every length from "just fits straight" upward travels the whole room,
    # and every one with a band to spare puts its folds on the far border --
    # fold boundaries included, where the depth used to dip under it and creep
    # back over the next millimetre of the sweep.
    start, room, band, pitch = (0.0, 0.0), 29.0, 7.0, 1.25
    tops = []
    for i in range(281):  # 29.0 -> 57.0 mm in 0.1 mm steps
        length = 29.0 + i * 0.1
        run = geometry.meander_run(start, RIGHT, UP, length, room, band, pitch)
        assert math.isclose(
            geometry.path_length([start] + run.points), length, abs_tol=1e-9
        ), length
        assert run.advance == room, length  # the whole width, at every length
        top = min(y for _x, y in run.points)
        assert top >= -band - 1e-9, length  # ... and never past the border
        tops.append(round(top, 9))
    # From a band over the room on (36 mm here), the far side of the run is the
    # far border and stays there -- through the boundaries at 40.1 and 47.1 mm.
    assert set(tops[70:]) == {-band}
    # Below that the run cannot reach the border at all (climbing the band
    # costs the whole band), so it steps up by what it has spare: the one
    # window where the far side moves, and it moves with the length exactly.
    assert tops[:70] == [round(-0.1 * i, 9) for i in range(70)]


def _walk(start, points, steps=400):
    """A run resampled at ``steps`` equal fractions of its own length -- the
    view that compares two runs of different lengths (and different point
    counts) as *shapes*: fraction f of the one against fraction f of the
    other."""
    pts = [start] + list(points)
    legs = [(a, b, math.dist(a, b)) for a, b in zip(pts, pts[1:])]
    total = sum(d for _a, _b, d in legs)
    out = []
    for k in range(steps + 1):
        want, run = total * k / steps, 0.0
        for a, b, d in legs:
            if run + d >= want - 1e-12 and d > 0:
                f = (want - run) / d
                out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
                break
            run += d
        else:
            out.append(pts[-1])
    return out


def test_meander_peels_a_new_crossing_off_the_far_corner():
    # The regression: a crossing used to be dropped into the *middle* of the
    # run, with the room re-divided evenly under it -- so a fold that sat at
    # x = 29 in one candidate sat at x = 14.5 in the next, 14 mm away, for a
    # hair of extra length. It grows out of the run's tip instead: a hair past
    # the boundary the run is the run it was, plus a nub in the far corner.
    start, room, band, pitch = (0.0, 0.0), 29.0, 7.0, 1.25
    before = geometry.meander_run(start, RIGHT, UP, 50.0, room, band, pitch)
    after = geometry.meander_run(start, RIGHT, UP, 50.0005, room, band, pitch)
    assert (before.crossings, after.crossings) == (3, 4)
    # Every corner the shorter run had is within a hair of where it was --
    # and the closer the two lengths, the smaller the hair: the hand-over is
    # a slide off this layout, not a step away from it.
    for a, b in zip(before.points, after.points):
        assert math.dist(a, b) < 0.05, (a, b)
    # ... and the two points the new crossing brings are that nub, hard in the
    # corner the run used to end in.
    assert _close(after.points[-2], (room, -band))
    assert _close(after.points[-1], (room, -band + 0.0005))


def test_meander_folds_are_all_the_same_width_bar_a_whisker():
    # What the run looks like for all but a sliver of the sweep: one regular
    # comb. The newborn crossing is the only narrow one, and only while it is
    # turning out -- a fraction of a track pitch of depth, after which the run
    # is even and stays even for the rest of the cycle.
    start, room, band, pitch = (0.0, 0.0), 29.0, 7.0, 1.25
    turnout = geometry.FOLD_TURNOUT_PITCHES * pitch
    step, uneven = 0.01, 0
    for i in range(701):  # one full fold cycle, 43 -> 50 mm (3 crossings)
        run = geometry.meander_run(start, RIGHT, UP, 43.0 + i * step, room, band, pitch)
        legs = geometry.meander_legs(run.crossings, run.tail, run.advance, pitch)
        if run.tail >= turnout:  # turned out: the comb is regular
            assert max(legs) - min(legs) < 1e-9, run.tail
        else:
            uneven += 1
    # ... and that is a sliver: the hand-over is over while the new fold is a
    # quarter of a millimetre deep, so it costs a quarter millimetre of the
    # 7 mm cycle -- under 4% of the candidates of a sweep.
    assert uneven == round(turnout / step) - 1 == 24  # the cycle opens at c = 2
    assert uneven / 700 < 0.04, uneven


def test_meander_slides_with_the_length_instead_of_jumping():
    # The rule the peeling exists for, over a whole sweep: 0.01 mm more length
    # moves no part of the run more than a fraction of a millimetre. The
    # fastest a fold ever moves is while the newest one is turning out -- the
    # whole hand-over inside a quarter millimetre of depth, ~115 mm per mm --
    # so nothing may move more than ~1.2 mm per step. Against the 14.5 mm the
    # even division jumped at every boundary, which is the whole point: this
    # is a slide a finer sweep resolves, not a step no sweep can.
    start, room, band, pitch = (0.0, 0.0), 29.0, 7.0, 1.25
    prev, worst = None, 0.0
    for i in range(3001):  # 29.05 -> 59.05 mm, over four fold boundaries
        length = 29.05 + i * 0.01
        run = geometry.meander_run(start, RIGHT, UP, length, room, band, pitch)
        walk = _walk(start, run.points)
        if prev is not None:
            worst = max(worst, max(math.dist(a, b) for a, b in zip(prev, walk)))
        prev = walk
    assert worst < 1.7, worst


def test_meander_legs_share_the_whole_span_and_go_even_once_turned_out():
    # A newborn crossing takes its room from the folds in front of it, a hair
    # at a time, and stops taking once it has an even share: the legs always
    # sum to the whole span, and they are even from the turnout depth on --
    # which is nearly all of the cycle, and is the layout the *next* crossing
    # is born out of.
    pitch = 1.25
    turnout = geometry.FOLD_TURNOUT_PITCHES * pitch
    for crossings in range(1, 9):
        for tail in (0.001, 0.1, 0.25, 3.5, 7.0):
            legs = geometry.meander_legs(crossings, tail, 29.0, pitch)
            assert len(legs) == max(1, crossings - 1), crossings
            assert math.isclose(sum(legs), 29.0, abs_tol=1e-9), (crossings, tail)
            assert all(leg >= 0 for leg in legs), (crossings, tail)
            if tail >= turnout:  # turned out: one regular comb
                assert max(legs) - min(legs) < 1e-9, (crossings, tail)
        # A hair into the next crossing: the legs of the even layout, exactly
        # where it left them, plus the newborn one -- still empty. (Below two
        # crossings there is no new leg to open: the second crossing turns the
        # first run's forced travel leg into a real one, in place.)
        even = geometry.meander_legs(crossings, turnout, 29.0, pitch)
        born = geometry.meander_legs(crossings + 1, 1e-9, 29.0, pitch)
        assert len(born) == max(1, crossings), crossings
        for a, b in zip(even, born):
            assert math.isclose(a, b, abs_tol=1e-6), crossings
        if len(born) > len(even):
            assert born[-1] < 1e-6, crossings


def _layouts(length, room, band, pitch):
    """Every crossing count that can lay ``length`` while holding the full room
    *and* the full band -- the enumeration meander_plan's arithmetic is checked
    against.

    A run of ``c`` crossings lays ``c - 1`` forward legs sharing the room, and
    the crossings supply ``length - room`` between them: every one of them the
    whole band deep, with the last taking what is left over. So the count is
    the only free variable, and the tail is what absorbs a length the two do
    not divide -- down to a hair, and never past the band. (A run with less
    than a band to spend has the single crossing that is a step, not a
    fold.)"""
    if band < pitch:  # a crossing thinner than the track is not copper
        return {}
    out = {}
    across = length - room
    depth = min(band, across)
    for c in range(1, 60):
        tail = across - (c - 1) * depth
        if 1e-9 < tail <= depth + 1e-9:
            if room >= (c - 1) * pitch - 1e-9:  # the legs clear the pitch
                out[c] = (round(depth, 4), round(tail, 4), round(room, 4))
    return out


def test_meander_is_the_fewest_crossings_at_the_full_room_and_band():
    # count -> tail, and nothing else, as an executable rule rather than
    # prose: over a grid of runs, the count is the fewest that can lay the
    # length across the whole room with every full crossing on the far border,
    # and the last crossing takes the remainder however small it is.
    grid = [
        (length, room, band, pitch)
        for length in (13.0, 20.0, 30.6, 39.2, 47.0)
        for room in (8.2, 10.0, 12.47, 29.0)
        for band in (1.5, 3.0, 3.905, 5.0, 8.5)
        for pitch in (0.45, 0.7, 1.25, 2.25)
    ]
    checked = 0
    for length, room, band, pitch in grid:
        if length <= room:
            continue  # straight: its own test above
        want = _layouts(length, room, band, pitch)
        expect = (min(want), want[min(want)]) if want else None
        try:
            run = geometry.meander_run((0.0, 0.0), RIGHT, UP, length, room, band, pitch)
        except ValueError:
            # Refusing is only right when nothing could have been laid.
            assert expect is None, (length, room, band, pitch, expect)
            continue
        assert expect is not None, (length, room, band, pitch)
        crossings, layout = expect
        assert run.crossings == crossings, (
            length,
            room,
            band,
            pitch,
            run.crossings,
            sorted(want),
        )
        assert (run.cross, run.tail, run.advance) == layout, (
            length,
            room,
            band,
            pitch,
        )
        checked += 1
    assert checked > 100, checked  # the grid really does exercise the rule


def test_meander_a_run_with_less_than_a_band_to_spare_steps_up():
    # 3 mm over the room and a 5 mm band: no layout reaches the far border
    # (climbing the band costs the whole band, whether or not the run comes
    # back), so the run makes the one crossing it can afford -- a step up off
    # the near side -- and travels the whole room at that level. Nothing is
    # given up but the height of the step, which is the length itself.
    start = (0.0, 0.0)
    run = geometry.meander_run(start, RIGHT, UP, 13.0, 10.0, 5.0, 1.25)
    assert run.crossings == 1 and run.folds == 0
    assert run.cross == run.tail == 3.0 and run.advance == 10.0
    assert run.points == [(0.0, -3.0), (10.0, -3.0)]
    # A hair more room to spend and it is a fold: the step becomes a full
    # crossing of the band and the remainder starts the next one.
    run = geometry.meander_run(start, RIGHT, UP, 15.1, 10.0, 5.0, 1.25)
    assert run.crossings == 2 and run.cross == 5.0
    assert math.isclose(run.tail, 0.1) and run.advance == 10.0


def test_meander_lets_the_last_crossing_be_thinner_than_the_track():
    # What gives in the window right after a crossing is added: the tail, and
    # only the tail. A 0.1 mm stub is copper inside the corner it grows out of
    # -- it buys less length than it measures -- but the alternatives are
    # narrowing the antenna or lifting its folds off the border, and those
    # move every candidate around it in a sweep. It is gone again 5 mm later.
    start = (0.0, 0.0)
    run = geometry.meander_run(start, RIGHT, UP, 20.1, 10.0, 5.0, 1.25)
    assert run.crossings == 3 and run.cross == 5.0 and run.advance == 10.0
    assert math.isclose(run.tail, 0.1)
    assert math.isclose(geometry.path_length([start] + run.points), 20.1, abs_tol=1e-9)
    # The folds are on the border either side of the boundary, and the tip is
    # what moves: a hair off the near side here, the whole band later.
    assert min(y for _x, y in run.points) == -5.0
    assert math.isclose(run.points[-1][1], -0.1)
    run = geometry.meander_run(start, RIGHT, UP, 25.0, 10.0, 5.0, 1.25)
    assert run.crossings == 3 and run.cross == run.tail == 5.0
    assert min(y for _x, y in run.points) == -5.0 and run.advance == 10.0


# --------------------------------------------------------------------------- #
# The lead-in crossing (a run entering its band part way across)
# --------------------------------------------------------------------------- #
def test_meander_lead_in_is_short_and_every_crossing_after_it_is_full():
    # A serpentine whose crossings run parallel to the feed edge starts where
    # the feed is, which is not at a border: its first crossing reaches the
    # near one only (3 of the 5 mm band) and the rest span the whole band.
    start = (0.0, 0.0)
    run = geometry.meander_run(start, RIGHT, UP, 28.0, 10.0, 5.0, 1.25, lead_mm=3.0)
    assert run.lead == 3.0
    # 18 mm across the band: 3 for the lead, then 5 + 5 + 5.
    assert run.crossings == 4 and run.cross == run.tail == 5.0
    reaches = [abs(b[1] - a[1]) for a, b in zip([start] + run.points, run.points)]
    assert [round(r, 4) for r in reaches if r] == [3.0, 5.0, 5.0, 5.0]
    assert math.isclose(geometry.path_length([start] + run.points), 28.0, abs_tol=1e-9)


def test_meander_lead_in_leaves_the_length_and_the_advance_exact():
    # The lead is one more thing held while the length sweeps: it is where the
    # run entered, not a knob, so every candidate keeps the same first crossing
    # and the same whole advance -- only the count and the tip move.
    start = (0.0, 0.0)
    for length in (14.0, 18.5, 21.0, 27.3, 33.0, 40.0):
        run = geometry.meander_run(
            start, RIGHT, UP, length, 10.0, 5.0, 1.25, lead_mm=3.0
        )
        assert run.lead == 3.0, length
        assert run.advance == 10.0, length
        assert math.isclose(
            geometry.path_length([start] + run.points), length, abs_tol=1e-9
        ), length


def test_meander_without_a_lead_is_exactly_what_it_always_was():
    # The default has to be the old function point for point -- the inverted-F
    # never passes a lead, and its numbers are pinned by tests/test_ifa.py.
    start = (0.0, 0.0)
    for length in (8.0, 13.0, 20.1, 30.0, 47.0):
        plain = geometry.meander_run(start, RIGHT, UP, length, 10.0, 5.0, 1.25)
        explicit = geometry.meander_run(
            start, RIGHT, UP, length, 10.0, 5.0, 1.25, lead_mm=None
        )
        assert plain == explicit, length
        assert plain.lead == 0.0, length


def test_meander_a_lead_of_nothing_collapses_instead_of_drawing_a_stub():
    # A feed sitting on the border enters at the band's edge, so there is no
    # lead-in crossing at all. It must not become a zero-length first segment
    # (path_rects raises on one); the run is simply the full-crossing layout.
    start = (0.0, 0.0)
    plain = geometry.meander_run(start, RIGHT, UP, 30.0, 10.0, 5.0, 1.25)
    for lead in (0.0, 1e-12):
        run = geometry.meander_run(
            start, RIGHT, UP, 30.0, 10.0, 5.0, 1.25, lead_mm=lead
        )
        assert run == plain, lead
    assert all(a != b for a, b in zip([start] + plain.points, plain.points))


def test_meander_a_run_that_ends_inside_its_lead_in_has_one_crossing():
    # 2 mm across the band with a 3 mm lead: the run stops part way through
    # the crossing it entered on. That crossing is the only one, so it is the
    # tail -- there is no separate lead left to report.
    start = (0.0, 0.0)
    run = geometry.meander_run(start, RIGHT, UP, 12.0, 10.0, 5.0, 1.25, lead_mm=3.0)
    assert run.crossings == 1 and run.lead == 0.0
    assert run.cross == run.tail == 2.0
    assert run.points == [(0.0, -2.0), (10.0, -2.0)]


def test_meander_lead_in_slides_across_the_boundary_without_jumping():
    # The property the whole turnout exists for, now with a lead in front of
    # it: the boundaries are where the count changes, so the runs are compared
    # as shapes (_walk) rather than point by point. A lead-in must not put a
    # step back into a sweep the turnout took it out of.
    start, prev, worst = (0.0, 0.0), None, 0.0
    for i in range(2001):  # 13 -> 33 mm, across several crossing boundaries
        run = geometry.meander_run(
            start, RIGHT, UP, 13.0 + i * 0.01, 10.0, 5.0, 1.25, lead_mm=3.0
        )
        walk = _walk(start, run.points)
        if prev is not None:
            worst = max(worst, max(math.dist(a, b) for a, b in zip(prev, walk)))
        prev = walk
    assert worst < 1.7, worst


def test_meander_rejects_a_lead_wider_than_the_band():
    try:
        geometry.meander_run((0.0, 0.0), RIGHT, UP, 30.0, 10.0, 5.0, 1.25, lead_mm=6.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "outside the area" in str(exc)


def test_meander_rejects_an_area_too_shallow_to_fold():
    try:
        geometry.meander_run((0.0, 0.0), RIGHT, UP, 30.0, 10.0, 0.5, 1.25)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "too shallow to meander" in str(exc)


def test_meander_rejects_folds_that_do_not_fit_the_pitch():
    # 3 mm of room can hold one fold at a 1.25 mm pitch (needs 2.5 mm of
    # span); asking for 40 mm needs many more legs than that.
    try:
        geometry.meander_run((0.0, 0.0), RIGHT, UP, 40.0, 3.0, 2.0, 1.25)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "track pitch" in str(exc)


# --------------------------------------------------------------------------- #
# Centerline -> copper rectangles
# --------------------------------------------------------------------------- #
def test_path_rects_single_segment_is_flat_ended():
    assert geometry.path_rects([(0.0, 0.0), (0.0, -5.0)], 0.5) == [
        (-0.5, -5.0, 0.5, 0.0)
    ]


def test_path_rects_back_extension_is_the_stub():
    (x0, y0, x1, y1) = geometry.path_rects(
        [(0.0, 0.0), (0.0, -5.0)], 0.5, back_ext=1.25
    )[0]
    assert (y0, y1) == (-5.0, 1.25)  # pushed out behind the start


def test_path_rects_square_the_corners_once():
    # A bend: the incoming segment overshoots the joint by a half-width so the
    # corner is filled; the outgoing one starts exactly at the joint (the
    # corner must be covered once, not twice).
    r1, r2 = geometry.path_rects([(0.0, 0.0), (0.0, -4.0), (5.0, -4.0)], 0.5)
    assert r1 == (-0.5, -4.5, 0.5, 0.0)
    assert r2 == (0.0, -4.5, 5.0, -3.5)


def test_seg_rect_rejects_a_diagonal_segment():
    try:
        geometry.seg_rect((0.0, 0.0), (1.0, 1.0), 0.5)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "axis-aligned" in str(exc)


# --------------------------------------------------------------------------- #
# Geometry: copper, preview, feed
# --------------------------------------------------------------------------- #
def _geo(stub=geometry.FEED_STUB):
    """A hand-built two-segment candidate fed from the bottom edge."""
    return geometry.Geometry(
        paths=(geometry.Path(((20.0, 38.0), (20.0, 33.0)), stub),),
        feed=(20.0, 38.0),
        inward=(0, -1),
        total_mm=5.0,
        metrics={},
    )


def test_copper_rects_apply_each_stub_kind():
    # Feed stub: half the gap plus the ground stub past the feed point.
    assert _geo().copper_rects(1.0, 0.5) == [(19.5, 33.0, 20.5, 39.25)]
    # Ground stub: just the ground stub.
    assert _geo(geometry.GROUND_STUB).copper_rects(1.0, 0.5) == [
        (19.5, 33.0, 20.5, 39.0)
    ]
    assert _geo(geometry.NO_STUB).copper_rects(1.0, 0.5) == [(19.5, 33.0, 20.5, 38.0)]
    # The footprint drops the stubs -- the user's own copper connects there.
    assert _geo().copper_rects(1.0, 0.5, include_stub=False) == [
        (19.5, 33.0, 20.5, 38.0)
    ]


def test_copper_rects_cover_every_path():
    geo = geometry.Geometry(
        paths=(
            geometry.Path(((0.0, 0.0), (0.0, -3.0)), geometry.GROUND_STUB),
            geometry.Path(((2.0, 0.0), (2.0, -3.0)), geometry.FEED_STUB),
        ),
        feed=(2.0, 0.0),
        inward=(0, -1),
        total_mm=3.0,
        metrics={},
    )
    rects = geo.copper_rects(1.0, 0.5)
    assert len(rects) == 2
    assert rects[0][3] == 1.0  # ground stub, 1.0 mm past
    assert rects[1][3] == 1.25  # feed stub, + half the gap


def test_a_path_that_states_its_own_width_is_drawn_at_it():
    """What lets one candidate be a millimetre of microstrip and a rectangle
    thirty across (design/patch.py): the design's track width is the default,
    never an override."""
    geo = geometry.Geometry(
        paths=(
            geometry.Path(((0.0, 0.0), (0.0, -3.0)), geometry.FEED_STUB),
            geometry.Path(((0.0, -3.0), (0.0, -9.0)), geometry.NO_STUB, 30.0),
        ),
        feed=(0.0, 0.0),
        inward=(0, -1),
        total_mm=9.0,
        metrics={},
    )
    track, body = geo.copper_rects(1.0, 0.5)
    assert track == (-0.5, -3.0, 0.5, 1.25)  # the design's width, + the stub
    assert body == (-15.0, -9.0, 15.0, -3.0)  # its own, and it meets the track
    # The width travels with the path, so a wider track leaves the body alone.
    assert geo.copper_rects(2.0, 0.5)[1] == body


def test_preview_polys_are_the_copper_on_the_board():
    """The preview draws the candidate's own copper rather than a stroked
    centerline (markers.preview.draw), so per-path widths reach the board --
    stubs off, since a sketch of the port's reach into the pour is not
    something anybody fabricates."""
    geo = _geo()
    (poly,) = geo.preview_polys(1.0)
    assert poly == [(19.5, 33.0), (20.5, 33.0), (20.5, 38.0), (19.5, 38.0)]
    # ... and rotated onto the board, exactly as the copper rects are.
    turned = geo.preview_polys(1.0, 90.0, (20.0, 38.0))
    want = geometry.candidate_polys(
        geo.copper_rects(1.0, 0.0, include_stub=False), 90.0, (20.0, 38.0)
    )
    assert turned == want


def test_centerline_segments_follow_the_points():
    geo = geometry.Geometry(
        paths=(geometry.Path(((0.0, 0.0), (0.0, -4.0), (5.0, -4.0))),),
        feed=(0.0, 0.0),
        inward=(0, -1),
        total_mm=9.0,
        metrics={},
    )
    assert geo.centerline_segments() == [
        ((0.0, 0.0), (0.0, -4.0)),
        ((0.0, -4.0), (5.0, -4.0)),
    ]


def test_centerline_segments_rotate_about_the_pivot():
    markergeom = load("emkit.markers.markergeom")
    geo = _geo()
    pivot = (20.0, 34.0)
    ((a, b),) = geo.centerline_segments(90.0, pivot)
    for got, src in ((a, (20.0, 38.0)), (b, (20.0, 33.0))):
        assert _close(got, markergeom.rotate_pt(src, 90.0, pivot))


def test_feed_dict_is_in_the_gerber_frame():
    # Inward from the bottom edge is -y in KiCad -> +y in the gerber frame;
    # schema 5.x carries only the point + direction.
    assert _geo().feed_dict() == {"x": 20.0, "y": -38.0, "dir_x": 0, "dir_y": 1}


def test_feed_dict_rotated_marker_frame():
    # An area marker rotated 30 deg (KiCad Y-down math-CCW) about the feed
    # point: the point stays put, the inward direction rotates with it.
    feed = _geo().feed_dict(rot_deg=30.0, pivot=(20.0, 38.0))
    assert (feed["x"], feed["y"]) == (20.0, -38.0)
    assert math.isclose(feed["dir_x"], math.sin(math.radians(30)), abs_tol=1e-4)
    assert math.isclose(feed["dir_y"], math.cos(math.radians(30)), abs_tol=1e-4)


# --------------------------------------------------------------------------- #
# Gerber splice
# --------------------------------------------------------------------------- #
GERBER = (
    "%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.2*%\nD10*\n"
    "X1000000Y-2000000D02*\nX3000000Y-2000000D01*\nM02*\n"
)


def test_candidate_polys_rotate_about_pivot():
    polys = geometry.candidate_polys([(0.0, 0.0, 2.0, 1.0)], 90.0, pivot=(0.0, 0.0))
    got = [(round(x, 6), round(y, 6)) for x, y in polys[0]]
    assert got == [(0.0, 0.0), (0.0, 2.0), (-1.0, 2.0), (-1.0, 0.0)]


def test_splice_copper_adds_regions_before_m02():
    polys = geometry.candidate_polys(_geo().copper_rects(1.0, 0.5))
    out = geometry.splice_copper(GERBER, polys, "lmonopole")
    assert out.endswith("M02*\n")
    body = out[: out.rfind("M02*")]
    assert "G36*" in body and "G37*" in body
    assert "lmonopole candidate copper" in body
    # KiCad rect (19.5, 33.0, 20.5, 39.25) -> gerber Y negated: every corner
    # appears, and the region closes back on its first point.
    assert "X19500000Y-33000000D02*" in body
    assert "X20500000Y-39250000D01*" in body
    assert body.count("X19500000Y-33000000") == 2
    # The original strokes survive.
    assert "X1000000Y-2000000D02*" in out


def test_splice_copper_rejects_odd_format():
    try:
        geometry.splice_copper(
            "%FSLAX35Y35*%\nM02*\n", geometry.candidate_polys([(0, 0, 1, 1)])
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "coordinate format" in str(exc)


def test_splice_copper_needs_an_end_of_file_marker():
    try:
        geometry.splice_copper(
            "%FSLAX46Y46*%\n%MOMM*%\n", geometry.candidate_polys([(0, 0, 1, 1)])
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "M02*" in str(exc)


if __name__ == "__main__":
    run_module_tests(globals())
