"""Unit tests for the meandered monopole design (no KiCad, no wx).

What makes it this antenna rather than the inverted-F next door: **one** pin on
the feed edge, a run straight in to a first turn at the level the knob names,
and a stack of legs parallel to that edge marching away from the pour -- the
short one first, because the feed is not at a corner.

Plus the length staying exactly as long as asked however it is folded, the
capacity that bounds a scan, and the single-pad footprint.

    python3 tests/test_meander.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

footprints = load("design.footprints")
geometry = load("design.geometry")
registry = load("design.registry")

DESIGN = registry.by_key("meander")

# A 40 x 16 mm area at the origin, KiCad mm (Y down: the feed edge is y = 16).
AREA = (0.0, 0.0, 40.0, 16.0)


def _v(length, width=1.0, turn=3.0):
    return {"length": length, "width": width, "turn": turn}


def _solve(frac=0.25, **kw):
    return DESIGN.solve(AREA, "bottom", frac, _v(**kw))


def _points(geo):
    return list(geo.paths[0].points)


def _fails(**kw):
    """The message ``solve`` refuses these values with."""
    try:
        _solve(**kw)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"expected ValueError for {kw}")


# --------------------------------------------------------------------------- #
# One pin, a run in, then a stack
# --------------------------------------------------------------------------- #
def test_solve_runs_in_to_the_turn_then_stacks_legs():
    # Feed at 25 % of a 40 mm edge, half = 1.0 -> feed x = 10, so the near
    # border is 9 mm behind it and a full leg spans 38 mm.
    geo = _solve(length=60.0, turn=3.0)
    pts = _points(geo)
    assert geo.feed == (10.0, 16.0)
    assert geo.inward == (0, -1)
    # In from the feed by the turn, and that is the only inward-only segment
    # before the stack starts.
    assert pts[0] == (10.0, 16.0)
    assert pts[1] == (10.0, 13.0)
    # The first leg is the short one: back to the near border (x = 1.0), not
    # across the whole area.
    assert pts[2] == (1.0, 13.0)
    # ... and it is the *near* one, so the stack then runs toward the roomier
    # side.
    assert pts[4][0] > pts[3][0]


def test_the_antenna_has_exactly_one_pin_and_no_ground_stub():
    # A monopole touches the pour once. A second path, or a ground stub on the
    # one it has, would make it something else entirely.
    geo = _solve(length=60.0)
    assert len(geo.paths) == 1
    assert geo.paths[0].stub == geometry.FEED_STUB
    assert DESIGN.footprint_pads(geo) == (("1", geo.feed),)


def test_legs_run_parallel_to_the_feed_edge_and_jogs_run_away_from_it():
    geo = _solve(length=80.0)
    pts = _points(geo)
    # Segment 0 is the run in; after it the run alternates leg / jog. Every
    # leg is horizontal (parallel to the bottom feed edge), every jog vertical.
    for i, (a, b) in enumerate(zip(pts[1:], pts[2:])):
        if i % 2 == 0:
            assert a[1] == b[1] and a[0] != b[0], i  # a leg
        else:
            assert a[0] == b[0] and a[1] != b[1], i  # a jog
            assert b[1] < a[1], i  # ... always further from the feed edge


def test_every_full_leg_spans_the_area():
    # The width is held while the length sweeps: only the first leg is short.
    geo = _solve(length=120.0)
    pts = _points(geo)
    legs = [abs(b[0] - a[0]) for a, b in zip(pts[1:], pts[2:])][::2]
    assert legs[0] == 9.0  # the lead-in, feed to the near border
    assert all(math.isclose(x, 38.0) for x in legs[1:-1]), legs
    assert legs[-1] <= 38.0 + 1e-9  # the last stops where the length ran out


# --------------------------------------------------------------------------- #
# The length is what it says
# --------------------------------------------------------------------------- #
def test_the_drawn_length_is_exactly_the_length_asked_for():
    for length in (10.0, 13.0, 20.0, 45.5, 60.0, 99.0, 140.0):
        geo = _solve(length=length)
        assert math.isclose(geometry.path_length(_points(geo)), length, abs_tol=1e-9), (
            length
        )
        assert geo.total_mm == round(length, 4), length


def test_the_run_in_and_the_arm_add_up_to_the_length():
    geo = _solve(length=60.0, turn=3.0)
    m = geo.metrics
    assert m["turn_mm"] == 3.0
    assert math.isclose(m["turn_mm"] + m["arm_mm"], 60.0, abs_tol=1e-9)


def test_a_short_antenna_runs_straight_in_without_turning():
    # Shorter than the depth behind the turn: there is nothing to fold, so the
    # wire simply passes through where its turn would have been.
    geo = _solve(length=8.0, turn=3.0)
    assert geo.metrics["crossings"] == 0
    xs = {x for x, _y in _points(geo)}
    assert xs == {10.0}  # straight in from the feed, no leg at all
    assert "straight" in DESIGN.describe(geo)


# --------------------------------------------------------------------------- #
# Where the knob puts the antenna
# --------------------------------------------------------------------------- #
def test_the_turn_is_the_antennas_closest_approach_to_the_feed_edge():
    """The knob's label as an assertion. Every full leg comes back to exactly
    this level, so over a sweep the nearest copper is the turn itself -- never
    nearer, whatever the length does behind it.

    The pin is not in it: the feed point sits *on* the edge, which is what
    makes it a pin. What the knob promises is about the wire it feeds."""
    for length in (20.0, 33.0, 47.0, 60.0, 88.0, 130.0):
        geo = _solve(length=length, turn=3.0)
        closest = min(16.0 - y for _x, y in _points(geo)[1:])
        assert math.isclose(closest, 3.0, abs_tol=1e-9), (length, closest)


def test_the_stack_spreads_over_the_whole_depth_behind_the_turn():
    # Held while the length sweeps, like the width: the run reaches as far from
    # the pour as the area allows at every length, and the leg count is what
    # absorbs the difference.
    seen = set()
    for length in (60.0, 80.0, 100.0, 130.0):
        geo = _solve(length=length, turn=3.0)
        assert min(y for _x, y in _points(geo)) == 1.0, length  # the far border
        assert geo.metrics["stack_mm"] == 12.0, length  # 15 deep - the 3 turn
        seen.add(geo.metrics["crossings"])
    assert len(seen) > 1  # the count really is what moved


def test_a_later_turn_costs_the_arm_and_moves_nothing_else():
    # Long enough that both have full legs behind the last one -- a leg is
    # reported short when it *is* the last one, which says nothing about width.
    a = _solve(length=120.0, turn=3.0)
    b = _solve(length=120.0, turn=5.0)
    assert b.metrics["arm_mm"] == a.metrics["arm_mm"] - 2.0
    # The stack still fills what is left of the depth, and still spans the area.
    assert (a.metrics["stack_mm"], b.metrics["stack_mm"]) == (12.0, 10.0)
    assert b.metrics["leg_mm"] == a.metrics["leg_mm"] == 38.0


def test_the_lead_in_follows_the_feed_along_its_edge():
    # Slide the feed and the short first leg tracks the border behind it; the
    # legs after it still span the whole area.
    for frac, lead in ((0.25, 9.0), (0.5, 19.0), (0.75, 9.0)):
        geo = _solve(frac=frac, length=90.0)
        assert geo.metrics["lead_mm"] == lead, frac
        assert geo.metrics["leg_mm"] == 38.0, frac


def test_a_feed_against_the_border_has_no_lead_in_at_all():
    # Nothing to run back to: the stack starts at the feed and every leg runs
    # to the roomier side. It must not draw a zero-length first leg.
    geo = DESIGN.solve(AREA, "bottom", 0.0, _v(60.0))
    assert geo.metrics["lead_mm"] == 0.0
    pts = _points(geo)
    assert all(a != b for a, b in zip(pts, pts[1:]))
    assert geo.feed == (1.0, 16.0)
    assert pts[2] == (39.0, 13.0)  # straight across to the far border


# --------------------------------------------------------------------------- #
# What it refuses, and why
# --------------------------------------------------------------------------- #
def test_a_turn_inside_the_pour_clearance_is_refused():
    msg = _fails(length=60.0, turn=0.5)
    assert "ground pour" in msg and "0.75 mm" in msg


def test_a_turn_past_the_far_border_is_refused():
    msg = _fails(length=60.0, turn=15.5)
    assert "nothing to fold into" in msg and "deep" in msg


def test_an_antenna_shorter_than_its_run_in_is_refused():
    msg = _fails(length=2.0, turn=3.0)
    assert "nothing left to fold" in msg


def test_an_area_too_narrow_for_a_leg_is_refused():
    # 2 mm of width between the keepouts at a 1.25 mm pitch is a leg; 1 mm is
    # not, and folding into it would lay the wire back inside its own width.
    try:
        DESIGN.solve((0.0, 0.0, 3.0, 16.0), "bottom", 0.5, _v(60.0))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "buy no length" in str(exc) or "too narrow" in str(exc)


def test_a_length_past_the_capacity_is_refused_and_the_capacity_itself_is_not():
    cap = DESIGN.capacity_mm(AREA, "bottom", 0.25, _v(0.0))
    DESIGN.solve(AREA, "bottom", 0.25, _v(cap))  # exactly fits
    try:
        DESIGN.solve(AREA, "bottom", 0.25, _v(cap * 1.5))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_capacity_grows_with_the_area():
    small = DESIGN.capacity_mm((0.0, 0.0, 30.0, 12.0), "bottom", 0.25, _v(0.0))
    big = DESIGN.capacity_mm((0.0, 0.0, 40.0, 16.0), "bottom", 0.25, _v(0.0))
    assert big > small


# --------------------------------------------------------------------------- #
# Every edge, since the marker rotates
# --------------------------------------------------------------------------- #
def test_it_lays_out_from_every_edge():
    square = (0.0, 0.0, 30.0, 30.0)
    for edge, axis, want in (
        ("bottom", 1, 30.0),
        ("top", 1, 0.0),
        ("left", 0, 0.0),
        ("right", 0, 30.0),
    ):
        geo = DESIGN.solve(square, edge, 0.25, _v(80.0))
        assert math.isclose(geo.feed[axis], want), edge
        assert math.isclose(geometry.path_length(_points(geo)), 80.0, abs_tol=1e-9), (
            edge
        )
        assert geo.metrics["edge"] == edge


# --------------------------------------------------------------------------- #
# Footprint
# --------------------------------------------------------------------------- #
def test_footprint_name_and_single_pad():
    geo = _solve(length=30.6)
    assert footprints.item_name(DESIGN, 2.45, 30.6) == "Meandered_Monopole_2G45_30p6mm"
    text = footprints.sexpr(DESIGN, geo, _v(30.6), 2.45)
    assert text.count("(") == text.count(")")
    assert text.count("(pad ") == 1
    assert '(pad "1" smd custom (at 0 0) (size 1 1)' in text
    # One pad is one net: there is nothing shorted, so no net tie is declared.
    assert "net_tie_pad_groups" not in text
    assert text.count("gr_poly") == len(_points(geo)) - 1


if __name__ == "__main__":
    run_module_tests(globals())
