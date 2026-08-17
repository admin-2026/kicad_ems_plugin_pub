"""Unit tests for antenna_plugin.design.sizing -- how long to make the antenna
and which lengths to try (no KiCad, no wx).

    python3 tests/test_sizing.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

sizing = load("design.sizing")


def test_quarter_wave_estimate():
    # Free-space quarter wave at 2.45 GHz is about 3 cm.
    est = sizing.quarter_wave_mm(2.45)
    assert math.isclose(est, 299.792458 / 2.45 / 4, rel_tol=1e-9)
    assert 30.0 < est < 31.0


def test_quarter_wave_rejects_a_nonpositive_frequency():
    try:
        sizing.quarter_wave_mm(0.0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "positive" in str(exc)


def test_ladder_spans_and_clips():
    lengths = sizing.ladder(20.0, 23.0, 5)
    assert lengths[0] == round(20 * sizing.LADDER_LO, 2)
    assert lengths[-1] == 23.0  # clipped to capacity
    assert len(lengths) == 5

    # A tiny capacity collapses the ladder to fewer unique candidates.
    assert sizing.ladder(20.0, 10.0, 5) == [10.0]


def test_snap_never_rounds_back_over_the_capacity():
    # 34.7563 mm of capacity rounds to 34.76 -- a candidate the area cannot
    # actually hold, which then fails to solve by a hundredth of a mm.
    assert sizing.snap(99.0, 34.7563) == 34.75
    assert sizing.snap(34.7563, 34.7563) == 34.75
    assert sizing.snap(12.3456, 99.0) == 12.35  # plain rounding below it
    assert sizing.ladder(30.0, 34.7563, 5)[-1] <= 34.7563
    assert sizing.refine_total([(20.0, 3.0)], 1.0, 34.7563) <= 34.7563


def test_ladder_needs_a_candidate():
    try:
        sizing.ladder(20.0, 23.0, 0)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "at least one" in str(exc)


def test_sweep_values_linear():
    assert sizing.sweep_values(0.4, 2.0, 4) == [0.4, 0.933, 1.467, 2.0]
    assert sizing.sweep_values(2.0, 0.4, 3) == [0.4, 1.2, 2.0]  # reversed ok
    assert sizing.sweep_values(1.0, 1.0, 3) == [1.0]  # dedup
    assert sizing.sweep_values(0.5, 1.5, 1) == [1.0]  # single = mid


def test_refine_total_inverse_law():
    # Perfect 1/L data: k = L * f = 60 -> at f0 = 2.4, L* = 25.
    pairs = [(20.0, 3.0), (30.0, 2.0)]
    assert sizing.refine_total(pairs, 2.4, 100.0) == 25.0
    assert sizing.refine_total([(20.0, 3.0)], 2.4, 100.0) == 25.0
    assert sizing.refine_total([], 2.4, 100.0) is None
    assert sizing.refine_total([(20.0, None)], 2.4, 100.0) is None


def test_refine_total_uses_pairs_nearest_target():
    # Real-solver data where k = L * f drifts with length: the two pairs
    # bracketing 2.45 GHz must drive the answer; the far 13.4 mm one (whose
    # k is ~7 % smaller) must not drag it short.
    pairs = [(13.4, 3.8513), (18.62, 2.9046), (23.83, 2.345)]
    val = sizing.refine_total(pairs, 2.45, 100.0)
    assert 22.4 < val < 22.9
    # Capacity still clips.
    assert sizing.refine_total(pairs, 2.45, 20.0) == 20.0


if __name__ == "__main__":
    run_module_tests(globals())
