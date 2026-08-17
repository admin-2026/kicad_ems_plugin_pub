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


def test_score_collects_every_result_field():
    got = measure.score(DUMP, 2.4)
    assert set(got) == {"f_res_ghz", "s11_db", "bw_mhz", "r_ohm", "x_ohm"}
    assert got["s11_db"] == -20.0
    assert (got["r_ohm"], got["x_ohm"]) == (50.0, 0.0)
    assert 2.39 < got["f_res_ghz"] < 2.45
    assert got["bw_mhz"] > 0


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
