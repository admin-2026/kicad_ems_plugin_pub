"""Unit tests for the meandered inverted-F design (no KiCad, no wx).

The three pieces that make it an inverted-F -- a short pin on the ground side
of the feed, a feed pin tapped onto the arm's spine, and an arm that folds to
fit -- plus the resonant path (the feed pin's own run, tap excluded) staying
exactly as long as asked, the capacity that bounds a scan, and the two-pad
footprint.

    python3 tests/test_ifa.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

footprints = load("design.footprints")
geometry = load("design.geometry")
registry = load("design.registry")

DESIGN = registry.by_key("ifa")

# A 40 x 12 mm area at the origin, KiCad mm (Y down: the feed edge is y = 12).
AREA = (0.0, 0.0, 40.0, 12.0)


def _v(length, width=1.0, height=4.0, tap=2.0):
    return {"length": length, "width": width, "height": height, "tap": tap}


def _solve(frac=0.25, **kw):
    return DESIGN.solve(AREA, "bottom", frac, _v(**kw))


def _radiator(geo):
    return list(geo.paths[0].points)


def _feed_pin(geo):
    return list(geo.paths[1].points)


def _resonant_mm(geo):
    """The resonant path as laid out: the feed pin up to the arm, then the arm
    on to the open tip. The short pin and the tap crossbar (the radiator's
    first two segments) are the match, and are not in it."""
    return geometry.path_length(_feed_pin(geo)) + geometry.path_length(
        _radiator(geo)[2:]
    )


# --------------------------------------------------------------------------- #
# The three pieces
# --------------------------------------------------------------------------- #
def test_solve_lays_out_short_pin_feed_pin_and_arm():
    # Feed at 25 % of a 40 mm edge, half = 1.0 -> feed x = 10, room to +x.
    geo = _solve(length=20.0, height=4.0, tap=2.0)
    assert geo.feed == (10.0, 12.0)
    assert geo.inward == (0, -1)

    short, short_top, feed_top, tip = _radiator(geo)
    assert short == (8.0, 12.0)  # tap behind the feed, on the edge
    # A 20 mm length runs straight in the 29 mm of room, so nothing folds
    # behind the arm and it is lifted off the 4 mm minimum height onto the far
    # border (y = 12 - 11); the rise is paid for out of the arm.
    assert short_top == (8.0, 1.0)  # up the height it is drawn at
    assert feed_top == (10.0, 1.0)  # the tap, along the spine
    assert tip == (19.0, 1.0)  # arm = 20 - 11 = 9 mm (the tap is not in it)

    # The feed pin branches off the spine at the port.
    assert _feed_pin(geo) == [(10.0, 12.0), (10.0, 1.0)]
    # The radiator ties to the pour, the feed pin is the port.
    assert geo.paths[0].stub == geometry.GROUND_STUB
    assert geo.paths[1].stub == geometry.FEED_STUB


def test_resonant_path_is_exactly_the_requested_length():
    for length in (14.0, 20.0, 33.0, 47.0):
        geo = _solve(length=length, height=4.0, tap=2.0)
        assert math.isclose(_resonant_mm(geo), length, abs_tol=1e-9), length
        assert geo.total_mm == length


def test_the_tap_moves_the_short_pin_and_nothing_else():
    # The feed-to-short spacing is the match, not the resonator: sweeping it
    # leaves the resonant side (height + arm, folds included) untouched, so a
    # tap scan is a match scan. Straight and meandered alike.
    for length in (20.0, 47.0):
        geos = [_solve(length=length, height=4.0, tap=t) for t in (1.5, 3.0, 4.5)]
        for geo in geos:
            assert math.isclose(_resonant_mm(geo), length, abs_tol=1e-9)
            m, m0 = geo.metrics, geos[0].metrics
            assert (m["height_mm"], m["arm_mm"]) == (m0["height_mm"], m0["arm_mm"])
            assert m["folds"] == m0["folds"]
            assert m["fold_depth_mm"] == m0["fold_depth_mm"]
            # Same arm copper, in the same place: only the short pin moved.
            assert _radiator(geo)[2:] == _radiator(geos[0])[2:]
            assert _feed_pin(geo) == _feed_pin(geos[0])
        assert [geo.metrics["tap_mm"] for geo in geos] == [1.5, 3.0, 4.5]
        assert [_radiator(geo)[0][0] for geo in geos] == [8.5, 7.0, 5.5]


def test_arm_meanders_when_it_is_longer_than_the_room():
    # room = (40 - 1) - 10 = 29 mm; an arm of 43 mm (47 - 4) needs folds.
    geo = _solve(length=47.0, height=4.0, tap=2.0)
    m = geo.metrics
    assert m["arm_mm"] == 43.0
    assert m["folds"] >= 1 and m["fold_depth_mm"] > 0
    # Folds run into the area, never past its far border (depth 12 - half 1
    # = 11, minus the 4 mm height leaves 7).
    ys = [y for _x, y in _radiator(geo)]
    assert min(ys) >= 12.0 - 11.0 - 1e-9
    assert max(ys) == 12.0  # the ground contact on the edge


def test_a_length_sweep_keeps_the_arm_at_the_area_sides_and_far_border():
    # What a resonant-length scan is for: the candidates must differ in length
    # and nothing else. The arm rides the area's far border (y = 12 - 11 = 1)
    # at every length -- lifted onto it while it is short enough to run
    # straight, carried onto it by its first crossing once it folds -- and it
    # spans the area's full width (room = (40 - 1) - 10 = 29 mm) at every
    # length that can fill the room at all, fold boundaries included (which
    # used to pull the run's far end in, and then its folds off the border,
    # for a millimetre or so of the sweep either side).
    room = 29.0
    for i in range(351):  # 33 -> 68 mm resonant length in 0.1 mm steps
        length = 33.0 + i * 0.1
        geo = _solve(length=length, height=4.0, tap=2.0)
        assert math.isclose(_resonant_mm(geo), length, abs_tol=1e-9), length
        assert min(y for _x, y in _radiator(geo)) == 1.0, length
        # Straight and short of the full width until the length can pay for
        # the 11 mm climb and the whole 29 mm room (40 mm); full width after.
        want = min(length - 11.0, room)
        assert math.isclose(geo.metrics["span_mm"], want, abs_tol=1e-9), length


def test_a_length_sweep_redraws_the_antenna_instead_of_rebuilding_it():
    # The other half of what a length scan needs: not just the same width and
    # the same fold depth throughout, but the same antenna *drawing* -- one
    # that slides as the length grows. A fold used to be dropped into the
    # middle of the arm the moment the length asked for it, with the room
    # re-divided under the ones already there: 0.01 mm more length moved a
    # fold 14.5 mm sideways, and the two neighbouring candidates in a sweep
    # were different antennas. Now the new fold opens out of the tip and the
    # rest slide over to meet it, so no corner moves more than a fraction of
    # a millimetre per step.
    # It holds across the lift's own boundary too (40 mm here, where a lifted
    # straight arm hands over to a folded one), which is why the fit is judged
    # after the lift and not before: the two layouts meet on the same drawing.
    prev, worst = None, 0.0
    for i in range(4001):  # 30 -> 70 mm in 0.01 mm steps, four fold boundaries
        pts = _radiator(_solve(length=30.0 + i * 0.01, height=4.0, tap=2.0))
        if prev is not None:
            # Corner for corner as far as the shorter drawing goes, and the
            # corners a new fold brings measured against the tip it grew out
            # of. (A fold is never dropped, so the count only ever rises.)
            assert len(pts) >= len(prev), i
            moved = [math.dist(a, b) for a, b in zip(prev, pts)]
            moved += [math.dist(p, prev[-1]) for p in pts[len(prev) :]]
            worst = max(worst, max(moved))
        prev = pts
    assert worst < 1.2, worst


def test_a_length_sweep_draws_folds_of_one_width():
    # The arm is a regular comb, not a comb with a runt tooth on the end: the
    # newest fold turns out to the others' width as it deepens (over one track
    # pitch of it), so all but a sliver of the candidates in a sweep have
    # every fold the same width. The runt used to be the norm -- the last fold
    # took only the share its depth had reached, so it was narrower than the
    # rest in every candidate but the one ending a cycle exactly.
    same = 0
    for i in range(4001):  # 30 -> 70 mm, the same sweep as above
        pts = _radiator(_solve(length=30.0 + i * 0.01, height=4.0, tap=2.0))
        # The arm's folds, measured off the copper: the spacing between
        # consecutive crossings of the band (the pins are not part of it).
        xs = sorted({round(x, 6) for x, _y in pts[2:]})
        widths = [b - a for a, b in zip(xs, xs[1:])]
        same += len(widths) < 2 or max(widths) - min(widths) < 1e-4
    assert same / 4001 > 0.95, same / 4001


def test_an_arm_with_nothing_to_fold_is_lifted_onto_the_far_border():
    # The height knob is a minimum, not a level. An arm with no full fold
    # behind it would otherwise be drawn down at that minimum, hugging the pour
    # with the area empty above it -- and a length scan stepping down would
    # only push it further into the pour. It is drawn as far off the feed edge
    # as the area allows instead: on the far border (y = 12 - 11 = 1), which is
    # where a folded arm rides anyway. The climb is paid for out of the arm, so
    # the resonant length is still exactly what was asked for.
    #
    # 40 mm is the longest length that fits: the 11 mm climb plus the whole
    # 29 mm room.
    for length in (14.0, 20.0, 26.0, 33.0, 35.0, 40.0):
        geo = _solve(length=length, height=4.0, tap=2.0)
        m = geo.metrics
        assert m["crossings"] == 0, length  # straight: nothing to fold
        assert m["height_mm"] == 11.0, length  # the whole depth, not the 4 asked
        assert m["arm_mm"] == length - 11.0, length
        # Nothing but the pins' feet is off the far border.
        assert {y for _x, y in _radiator(geo)[1:]} == {1.0}, length
        assert math.isclose(_resonant_mm(geo), length, abs_tol=1e-9), length


def test_the_lift_never_leaves_less_arm_than_the_track_is_wide():
    # A length that cannot pay for the whole rise keeps what arm it has: lifted
    # any further the arm would be shorter than the track is wide, which is not
    # an arm but the corner the riser turns through.
    m = _solve(length=8.0, height=4.0, tap=2.0).metrics
    assert (m["height_mm"], m["arm_mm"]) == (7.0, 1.0)  # 3 mm of the 7 spare
    # A narrower track is a shorter arm to spare, so it lifts further.
    m = _solve(length=8.0, width=0.3, height=4.0, tap=2.0).metrics
    assert (m["height_mm"], m["arm_mm"]) == (7.7, 0.3)  # depth = 12 - 0.65
    # ... and a length with no arm to spare at all is not lifted.
    m = _solve(length=5.0, height=4.0, tap=6.0).metrics
    assert (m["height_mm"], m["arm_mm"]) == (4.0, 1.0)


def test_the_lift_hands_over_to_the_folds_without_a_step():
    # Why the fit is judged *after* the lift and not before: the longest lifted
    # arm is one that just fills the room from the far border (11 + 29 = 40 mm
    # here), and the shortest folded one is the same full-width arm on the same
    # border with a hair of a fold turning down off its tip. So the length
    # sweep crosses the hand-over the way it crosses a fold boundary -- the tip
    # moves and nothing else does.
    #
    # (Judged before the lift, the boundary would have fallen at 33 mm instead,
    # where an arm that just fills the room from the *minimum* height still
    # has 7 mm of climb in hand: the sweep would have dropped the arm from the
    # border to the height in one candidate and spent the next 7 mm of it
    # climbing back.)
    straight, folded = _solve(length=40.0), _solve(length=40.01)
    assert straight.metrics["crossings"] == 0 and folded.metrics["crossings"] == 2
    assert (straight.metrics["height_mm"], straight.metrics["arm_mm"]) == (11.0, 29.0)
    assert _radiator(straight) == [(8.0, 12.0), (8.0, 1.0), (10.0, 1.0), (39.0, 1.0)]
    # The same four corners, and a fifth 0.01 mm off the tip of the fourth.
    assert _radiator(folded)[:4] == _radiator(straight)
    tip = _radiator(folded)[4]
    assert tip[0] == 39.0 and math.isclose(tip[1], 1.01, abs_tol=1e-9)
    assert _feed_pin(folded) == _feed_pin(straight)


def test_both_pins_rise_to_the_arm_and_the_tap_is_flush_with_it():
    # One 7 mm-deep fold: the arm sits 4 + 7 = 11 mm off the edge, so both
    # pins run the whole 11 mm and the tap between their tops is level with
    # the first fold -- short pin, tap and first leg are one straight run.
    geo = _solve(length=47.0, height=4.0, tap=2.0)
    assert geo.metrics["folds"] == 1 and geo.metrics["fold_depth_mm"] == 7.0

    short, short_top, feed_top, fold, tip = _radiator(geo)
    assert short == (8.0, 12.0)  # tap behind the feed, on the edge
    assert short_top == (8.0, 1.0)  # up the height *and* the fold
    assert feed_top == (10.0, 1.0)  # the tap, flush with the fold
    assert fold == (39.0, 1.0)  # on along the same line, then
    assert tip == (39.0, 8.0)  # down to the height: the tip
    assert _feed_pin(geo) == [(10.0, 12.0), (10.0, 1.0)]

    # Moving the tap up the pins costs nothing: same segments, so the
    # resonant path is still exactly what was asked for.
    assert math.isclose(_resonant_mm(geo), 47.0, abs_tol=1e-9)


def test_a_height_sweep_moves_the_folds_near_end_not_the_antennas_width():
    # The bandwidth knob must not double as a size knob: sweeping the height
    # moves the level the folds turn *down* to, and the antenna keeps its
    # width. So the run travels the area's full width (span 29 mm) at every
    # height, and the folds reach for the far border (y = 12 - 11 = 1) with
    # whatever the length has left once the room is paid for.
    heights = (2.0, 4.0, 6.0, 8.0)
    geos = [_solve(length=47.0, height=h, tap=2.0) for h in heights]
    for geo, height in zip(geos, heights):
        ys = [y for _x, y in _radiator(geo)]
        assert min(ys) == 1.0, height  # on the far border, whatever the height
        # ... and nothing comes closer to the feed edge than the height,
        assert max(y for y in ys if y < 12.0) <= 12.0 - height + 1e-9, height
        assert math.isclose(_resonant_mm(geo), 47.0, abs_tol=1e-9), height
    # The full crossings turn back down to the height exactly; the last one
    # stops wherever the length runs out, which at h = 2 is 2 mm short of it.
    near = [max(y for _x, y in _radiator(geo) if y < 12.0) for geo in geos]
    assert near == [8.0, 8.0, 6.0, 4.0]
    # The crossing count absorbs the sweep in halves, and the room is kept
    # whole throughout -- that is what a length scan needs held.
    assert [geo.metrics["crossings"] for geo in geos] == [2, 2, 3, 4]
    assert [geo.metrics["span_mm"] for geo in geos] == [29.0, 29.0, 29.0, 29.0]
    # So the fold depth is exactly the band the height leaves behind the arm,
    # and what takes up the slack is the last crossing.
    depths = [geo.metrics["fold_depth_mm"] for geo in geos]
    assert depths == [9.0, 7.0, 5.0, 3.0]
    assert depths == [11.0 - height for height in heights]


def test_metrics_report_the_split():
    # The height reported is the one the arm is drawn at (here lifted off the
    # 4 mm minimum onto the far border), not the knob's own value.
    m = _solve(length=20.0, height=4.0, tap=2.0).metrics
    assert (m["height_mm"], m["tap_mm"], m["arm_mm"]) == (11.0, 2.0, 9.0)
    assert m["folds"] == 0
    # height + arm is the resonant length; the tap is quoted outside that sum.
    assert "height 11 + arm 9 mm, 2 mm tap (straight)" == DESIGN.describe(
        _solve(length=20.0, height=4.0, tap=2.0)
    )
    # A folded arm sits at the minimum, and reports the folds behind it.
    assert "height 4 + arm 43 mm, 2 mm tap, 1 fold(s) 7 mm deep" == DESIGN.describe(
        _solve(length=47.0, height=4.0, tap=2.0)
    )


def test_height_is_capped_to_the_area_depth():
    # depth = 12 - 1 = 11; a 99 mm height caps there and the arm takes the
    # rest of the requested length.
    geo = _solve(length=20.0, height=99.0, tap=2.0)
    assert geo.metrics["height_mm"] == 11.0
    assert geo.metrics["arm_mm"] == 9.0
    assert math.isclose(_resonant_mm(geo), 20.0, abs_tol=1e-9)


def test_the_arm_never_runs_its_copper_over_the_feed_edge():
    # The feed edge is the one border the antenna may cross -- the pins do --
    # so it carries no keepout, and nothing but this stops a low arm from
    # laying its copper over it and merging with the ground pour. Every height
    # the design accepts must keep the copper on the antenna's own side of the
    # edge (the pins' stubs are the deliberate exception, hence no stub here).
    for width in (0.3, 1.0, 2.0):
        for height in (0.1, 0.2, 0.4, 0.75, 1.0, 1.5, 3.0):
            for length in (14.0, 20.0, 30.6, 44.0):
                try:
                    geo = _solve(length=length, width=width, height=height)
                except ValueError:
                    continue  # refused, which is a fine way to be safe
                over = [
                    r
                    for r in geo.copper_rects(width, 0.3, include_stub=False)
                    if r[3] > 12.0 + 1e-9
                ]
                assert not over, (width, height, length, over[:1])


def test_a_height_that_would_short_the_arm_to_the_pour_is_refused():
    # A 1 mm track hangs 0.5 mm below its centerline: at a 0.4 mm height its
    # copper is already over the feed edge and into the pour, shorting out the
    # very gap the knob exists to open. Refused, not quietly drawn -- and not
    # quietly raised either (no silent defaults).
    try:
        _solve(length=30.0, width=1.0, height=0.4)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "clear the ground pour" in str(exc)
        assert "0.75 mm" in str(exc)  # half the track + the track gap

    # The threshold follows the track: a narrow one may sit lower. (Measured on
    # a length that has to fold, since that is where the height is the level
    # the folds turn down to -- a shorter one is lifted off it.)
    assert _solve(length=60.0, width=0.3, height=0.4).metrics["height_mm"] == 0.4
    # ... and the first height that clears a 1 mm track is drawn as asked.
    assert _solve(length=60.0, width=1.0, height=0.75).metrics["height_mm"] == 0.75


# --------------------------------------------------------------------------- #
# What it refuses, and why
# --------------------------------------------------------------------------- #
def test_tap_under_one_track_pitch_is_refused():
    # Two pins 0.5 mm apart at a 1 mm track width would be one pin.
    try:
        _solve(length=20.0, tap=0.5)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "merge the two pins" in str(exc)


def test_tap_wider_than_the_room_behind_the_feed_is_refused():
    # Feed at 5 % of the edge leaves ~1 mm behind it.
    try:
        _solve(frac=0.05, length=20.0, tap=8.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "behind the feed" in str(exc)


def test_length_swallowed_by_the_height_is_refused():
    try:
        _solve(length=4.0, height=4.0, tap=2.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "nothing left for its arm" in str(exc)
    # ... and a tap wider than the length is not the same thing: it is not in
    # the resonant path, so it costs the arm nothing.
    assert _solve(length=5.0, height=4.0, tap=6.0).metrics["arm_mm"] == 1.0


def test_solve_rejects_nonpositive_values():
    for values, want in (
        (_v(20.0, height=0.0), "height"),
        (_v(20.0, tap=0.0), "feed-to-short"),
        (_v(20.0, width=0.0), "track width"),
        (_v(0.0), "resonant length"),
    ):
        try:
            DESIGN.solve(AREA, "bottom", 0.25, values)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert want in str(exc)


def test_too_narrow_an_area_raises():
    try:
        DESIGN.solve((0, 0, 1.5, 12), "bottom", 0.5, _v(20.0))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "too narrow" in str(exc)


# --------------------------------------------------------------------------- #
# Capacity
# --------------------------------------------------------------------------- #
def test_capacity_is_the_longest_length_that_solves():
    values = _v(0.0, height=4.0, tap=2.0)
    cap = DESIGN.capacity_mm(AREA, "bottom", 0.25, values)
    geo = _solve(length=cap, height=4.0, tap=2.0)  # exactly fits
    assert math.isclose(_resonant_mm(geo), cap, abs_tol=1e-6)
    try:
        _solve(length=cap + 1.0, height=4.0, tap=2.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_capacity_without_room_to_fold_is_the_straight_run():
    # A height that fills the area leaves nothing to fold into: capacity is
    # just the height plus the straight room (the tap is not in it).
    values = _v(0.0, height=99.0, tap=2.0)
    cap = DESIGN.capacity_mm(AREA, "bottom", 0.25, values)
    assert math.isclose(cap, 11.0 + 29.0)
    wider = DESIGN.capacity_mm(AREA, "bottom", 0.25, _v(0.0, height=99.0, tap=5.0))
    assert math.isclose(cap, wider)  # a wider tap costs the arm nothing


# --------------------------------------------------------------------------- #
# Footprint
# --------------------------------------------------------------------------- #
def test_footprint_has_a_feed_pad_and_a_ground_pad():
    geo = _solve(length=20.0, height=4.0, tap=2.0)
    pads = DESIGN.footprint_pads(geo)
    assert [n for n, _pt in pads] == ["1", "2"]
    assert pads[0][1] == geo.feed
    assert pads[1][1] == (8.0, 12.0)  # the short pin
    text = footprints.sexpr(DESIGN, geo, _v(20.0, height=4.0, tap=2.0), 2.45)
    assert text.count("(") == text.count(")")
    assert '(pad "1" smd custom (at 0 0)' in text
    assert '(pad "2" smd rect (at -2 0)' in text  # 2 mm behind the feed
    # One primitive per centerline segment of both paths, all of them on the
    # feed pad -- the ground pin is a plain square inside that copper, which is
    # a short between two nets and so has to be declared as a net tie.
    assert text.count("gr_poly") == 4
    assert '(net_tie_pad_groups "1, 2")' in text
    assert footprints.item_name(DESIGN, 2.45, 30.6) == "Meandered_IFA_2G45_30p6mm"


if __name__ == "__main__":
    run_module_tests(globals())
