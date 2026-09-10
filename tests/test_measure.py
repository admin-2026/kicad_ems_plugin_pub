"""Unit tests for antenna_plugin.design.measure -- reading a finished run's
behaviour out of the solver's schema 9.x pcb_data.json dump (no KiCad, no wx).

    python3 tests/test_measure.py
"""

import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

measure = load("design.measure")


def _dump(f, r, x, s11):
    return json.dumps(
        {
            "pattern": {"freqGHz": 2.45},
            "impedance": {"f": f, "R": r, "X": x, "S11": s11, "VSWR": [1.0] * len(f)},
        }
    )


DUMP = _dump(
    [2.0, 2.2, 2.4, 2.6, 2.8],
    [10, 20, 50, 90, 120],
    [-50, -25, 0, 30, 60],
    [-2, -6, -20, -8, -3],
)


def test_parse_and_interpolate():
    rows = measure.parse_impedance(DUMP)
    assert len(rows) == 5
    assert measure.s11_at(rows, 2.4) == -20
    assert math.isclose(measure.s11_at(rows, 2.5), -14.0)
    assert measure.s11_at(rows, 1.0) == -2  # clamped below band
    assert measure.s11_at(rows, 9.9) == -3  # clamped above band


def test_z_at_interpolates_both_parts():
    rows = measure.parse_impedance(DUMP)
    r, x = measure.z_at(rows, 2.5)
    assert math.isclose(r, 70.0) and math.isclose(x, 15.0)


def test_resonance_parabolic():
    rows = measure.parse_impedance(DUMP)
    f = measure.resonance(rows)
    # Parabola through (-6, -20, -8): vertex slightly right of 2.4.
    assert 2.39 < f < 2.45


def test_resonance_at_band_edge_is_none():
    rows = measure.parse_impedance(
        _dump([2.0, 2.2, 2.4], [1, 1, 1], [1, 1, 1], [-30, -20, -10])
    )
    assert measure.resonance(rows) is None


def test_bandwidth_crossings():
    rows = measure.parse_impedance(DUMP)
    bw = measure.bandwidth_mhz(rows)
    # -10 dB crossings: 2.2 + 0.2*(4/14) = 2.2571 and 2.4 + 0.2*(10/12)
    # = 2.5667 -> 309.5 MHz.
    assert math.isclose(
        bw, (2.4 + 0.2 * 10 / 12 - (2.2 + 0.2 * 4 / 14)) * 1000, abs_tol=0.2
    )
    assert measure.bandwidth_mhz(rows, thresh_db=-25) is None


# Two dips, and the deeper one is not the antenna: the shape of every real
# patch sweep this got wrong. A 2.44 GHz patch swept to 3.9 GHz resonates at
# 2.47 (-29 dB) and rings again near the top of the sweep (-33 dB), and the
# tenths-of-a-dB wander at the bottom end is local minima all the way down.
TWO_DIPS = _dump(
    [0.50, 0.60, 0.70, 2.40, 2.47, 2.55, 3.20, 3.69, 3.90],
    [5, 5, 5, 31, 54, 75, 20, 51, 30],
    [-90, -85, -80, -5, 1, -20, -40, 2, -30],
    [-0.3, -0.2, -0.3, -6, -29, -7, -0.6, -33, -4],
)


def test_the_resonance_is_the_dip_the_target_asks_about_not_the_deepest():
    """The bug this fixes: a working 2.44 GHz patch was reported as resonating
    at 3.69 GHz, because a deeper dip lived at the top of a sweep that runs
    well past the band. The deepest point is still the answer when no target
    says which one is being asked about."""
    rows = measure.parse_impedance(TWO_DIPS)
    assert 2.4 < measure.resonance(rows, 2.44) < 2.5
    assert 3.6 < measure.resonance(rows) < 3.8  # no target: the deepest


def test_ripple_is_not_a_resonance():
    """Every wiggle in the -0.3 dB wander at the bottom of the sweep is a local
    minimum, and one of them is nearer 0.8 GHz than either real dip is. Only a
    dip that reaches the match threshold may answer."""
    rows = measure.parse_impedance(TWO_DIPS)
    assert 2.4 < measure.resonance(rows, 0.8) < 2.5


def test_an_antenna_that_matches_nowhere_still_reports_where_it_came_closest():
    """No dip reaches -10 dB, so there is no matched dip to prefer -- and
    answering "no resonance" would hide the one fact there is. The deepest
    point is reported, exactly as before this rule existed."""
    rows = measure.parse_impedance(
        _dump([2.0, 2.2, 2.4, 2.6, 2.8], [5] * 5, [-40] * 5, [-2, -4, -7, -3, -1])
    )
    assert 2.35 < measure.resonance(rows, 2.44) < 2.5
    assert measure.bandwidth_mhz(rows, 2.44) is None


def test_the_bandwidth_is_measured_across_the_dip_that_was_reported():
    """Resonance and bandwidth are two statements about one feature of the
    sweep. Measured across the deepest dip instead, this answered 3.69 GHz's
    span for 2.47 GHz's resonance -- two frequencies in one table, and no way
    to tell from the table."""
    rows = measure.parse_impedance(TWO_DIPS)
    # The 2.47 dip crosses -10 dB part-way through the 2.40 and 2.55 steps
    # either side of it, so its span fits inside them; the 3.69 dip's crossings
    # are out among 3.20 and 3.90 and its span cannot.
    assert 0 < measure.bandwidth_mhz(rows, 2.44) < (2.55 - 2.40) * 1000
    assert measure.bandwidth_mhz(rows) > (2.55 - 2.40) * 1000


def test_score_measures_every_field_about_the_same_target():
    """The whole result dict comes from one call, so nothing in it can be
    about a different frequency than the rest: the resonance and the bandwidth
    are the target's dip, S11 and Z are read at the target itself."""
    got = measure.score(TWO_DIPS, 2.47)
    assert 2.4 < got["f_res_ghz"] < 2.5
    assert got["s11_db"] == -29.0
    assert (got["r_ohm"], got["x_ohm"]) == (54.0, 1.0)
    assert 0 < got["bw_mhz"] < (2.55 - 2.40) * 1000


def test_score_collects_every_result_field():
    got = measure.score(DUMP, 2.4)
    assert set(got) == {"f_res_ghz", "s11_db", "bw_mhz", "r_ohm", "x_ohm"}
    assert got["s11_db"] == -20.0
    assert (got["r_ohm"], got["x_ohm"]) == (50.0, 0.0)
    assert 2.39 < got["f_res_ghz"] < 2.45
    assert got["bw_mhz"] > 0


# --------------------------------------------------------------------------- #
# The depth the bandwidth is measured at is the target's, not a constant
# --------------------------------------------------------------------------- #
def test_a_free_return_loss_keeps_the_ten_db_convention():
    assert measure.match_db(None) == measure.MATCH_DB
    assert measure.match_db(0) == measure.MATCH_DB


def test_a_targets_return_loss_becomes_the_depth_to_measure_at():
    assert measure.match_db(15) == -15.0
    assert measure.match_db(-15) == -15.0  # however the caller signs it


def test_a_tighter_target_measures_a_narrower_band():
    """The GPS L1 hole: its spec is 15 dB across the band, and the -10 dB span
    is always the wider one -- so scoring the band at a fixed -10 dB passed an
    antenna that never reaches 15 dB anywhere."""
    rows = measure.parse_impedance(DUMP)
    wide = measure.bandwidth_mhz(rows, thresh_db=measure.match_db(None))
    tight = measure.bandwidth_mhz(rows, thresh_db=measure.match_db(15))
    assert tight is not None and tight < wide


def test_score_measures_the_band_at_the_depth_it_is_given():
    rows = measure.parse_impedance(DUMP)
    for rl in (None, 15):
        assert measure.score(DUMP, 2.4, measure.match_db(rl))[
            "bw_mhz"
        ] == measure.bandwidth_mhz(rows, 2.4, measure.match_db(rl))


def test_a_dip_that_never_reaches_the_target_has_no_band_at_it():
    rows = measure.parse_impedance(DUMP)
    assert measure.bandwidth_mhz(rows, thresh_db=measure.match_db(40)) is None


def test_a_tighter_target_does_not_turn_a_resonance_into_none():
    """MATCH_DB stays the noise floor that decides a dip is real. Judging the
    resonance by the spec instead would report an antenna 3 dB short of its
    target as having no resonance at all."""
    rows = measure.parse_impedance(DUMP)
    assert measure.score(DUMP, 2.4, measure.match_db(40))["f_res_ghz"] == (
        measure.resonance(rows, 2.4)
    )


def test_parse_impedance_empty_raises():
    # A dump without an impedance series (the run died before the sweep).
    try:
        measure.parse_impedance('{"pattern": {"freqGHz": 2.45}}')
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "empty" in str(exc)


def test_parse_impedance_reads_the_js_dump_too():
    """Every run writes `pcb_data.js` -- the assignment its report page loads;
    only `output_json` adds the bare `.json` beside it. One reader takes both,
    so scoring a run never depends on which of them is there."""
    js = f"window.FDTD={{s:{DUMP}}};\n"
    assert measure.parse_impedance(js) == measure.parse_impedance(DUMP)
    assert measure.score(js, 2.4)["s11_db"] == -20.0


def test_parse_impedance_garbage_raises():
    try:
        measure.parse_impedance("not json at all")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "data dump" in str(exc)


if __name__ == "__main__":
    run_module_tests(globals())
