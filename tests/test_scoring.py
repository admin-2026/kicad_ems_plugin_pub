"""Unit tests for antenna_plugin.design.scoring (pure, no KiCad, no wx).

Loaded through the bare package so it runs off-KiCad:  python3 tests/test_scoring.py
"""

import math

from bare_package import load

scoring = load("design.scoring")

# A BLE-like target: 2.4-2.4835 GHz, 50 ohm, better-than-10 dB return loss.
_BLE = scoring.Target(
    f0_ghz=2.45, band_ghz=(2.400, 2.4835), impedance_ohm=50.0, return_loss_db=10.0
)
# A hand-typed frequency with no application: only f0 is known, everything
# else unspecified (None) -- those properties must be shown, not judged.
_FREE = scoring.Target(
    f0_ghz=2.45, band_ghz=None, impedance_ohm=None, return_loss_db=None
)


def _result(**kw):
    base = {
        "f_res_ghz": None,
        "s11_db": None,
        "bw_mhz": None,
        "r_ohm": None,
        "x_ohm": None,
    }
    base.update(kw)
    return base


def test_target_derives_vswr_and_bandwidth():
    assert math.isclose(_BLE.vswr, 1.925, abs_tol=1e-3)
    assert math.isclose(_BLE.required_bw_mhz, 83.5, abs_tol=1e-6)
    # Unspecified target fields derive nothing (no injected value).
    assert _FREE.required_bw_mhz is None
    assert _FREE.vswr is None


def test_return_loss_pass_warn_fail():
    assert scoring.return_loss(_result(s11_db=-14.0), _BLE).status == scoring.PASS
    assert scoring.return_loss(_result(s11_db=-8.0), _BLE).status == scoring.WARN
    assert scoring.return_loss(_result(s11_db=-4.0), _BLE).status == scoring.FAIL
    assert scoring.return_loss(_result(), _BLE).status == scoring.NONE


def test_vswr_shares_return_loss_status_and_shows_target():
    # Same S11 -> return loss and VSWR must agree (two views of one number).
    r = _result(s11_db=-8.0)
    assert scoring.vswr(r, _BLE).status == scoring.return_loss(r, _BLE).status
    v = scoring.vswr(r, _BLE)
    assert v.status == scoring.WARN
    assert "≤1.92" in v.text  # desired VSWR shown on a warn


def test_warn_and_fail_show_desired_beside_simulated():
    v = scoring.return_loss(_result(s11_db=-8.0), _BLE)
    assert "8" in v.text and "≥10" in v.text
    # A pass shows only the simulated value, no target.
    p = scoring.return_loss(_result(s11_db=-14.0), _BLE)
    assert "≥" not in p.text


def test_bandwidth_against_required_span():
    assert scoring.bandwidth(_result(bw_mhz=120), _BLE).status == scoring.PASS
    assert scoring.bandwidth(_result(bw_mhz=70), _BLE).status == scoring.WARN
    assert scoring.bandwidth(_result(bw_mhz=20), _BLE).status == scoring.FAIL
    # Without a band the value is shown but not judged.
    assert scoring.bandwidth(_result(bw_mhz=50), _FREE).status == scoring.NONE


def test_resonance_in_band_vs_out():
    assert scoring.resonance(_result(f_res_ghz=2.44), _BLE).status == scoring.PASS
    assert scoring.resonance(_result(f_res_ghz=2.55), _BLE).status == scoring.WARN
    assert scoring.resonance(_result(f_res_ghz=3.2), _BLE).status == scoring.FAIL
    assert scoring.resonance(_result(), _BLE).status == scoring.NONE


def test_resonance_without_band_uses_f0_tolerance():
    # f0 is always a real input, so resonance is judged even for a free target.
    assert scoring.resonance(_result(f_res_ghz=2.46), _FREE).status == scoring.PASS
    assert scoring.resonance(_result(f_res_ghz=2.55), _FREE).status == scoring.WARN
    assert scoring.resonance(_result(f_res_ghz=3.0), _FREE).status == scoring.FAIL


def test_unspecified_target_shows_value_without_a_verdict():
    # A free target must not invent 50 ohm / 10 dB: return loss, VSWR and
    # impedance are shown (measured) but carry no pass/warn/fail.
    r = _result(s11_db=-8.0, r_ohm=20, x_ohm=30)
    rl = scoring.return_loss(r, _FREE)
    assert rl.status == scoring.NONE and "8" in rl.text and "≥" not in rl.text
    v = scoring.vswr(r, _FREE)
    assert v.status == scoring.NONE and "≤" not in v.text
    z = scoring.impedance(r, _FREE)
    assert z.status == scoring.NONE and "20" in z.text and "~" not in z.text
    # Only resonance (judged against f0) contributes to overall.
    assert (
        scoring.evaluate(_result(f_res_ghz=2.46, s11_db=-8.0), _FREE)["overall"]
        == scoring.PASS
    )


def test_impedance_distance():
    assert scoring.impedance(_result(r_ohm=52, x_ohm=3), _BLE).status == scoring.PASS
    assert scoring.impedance(_result(r_ohm=35, x_ohm=15), _BLE).status == scoring.WARN
    assert scoring.impedance(_result(r_ohm=12, x_ohm=40), _BLE).status == scoring.FAIL
    assert scoring.impedance(_result(), _BLE).status == scoring.NONE


def test_evaluate_overall_is_worst_measured():
    # Great match but resonates well out of band -> overall fail.
    r = _result(s11_db=-20.0, bw_mhz=120, f_res_ghz=3.2, r_ohm=50, x_ohm=0)
    v = scoring.evaluate(r, _BLE)
    assert v["return_loss"].status == scoring.PASS
    assert v["resonance"].status == scoring.FAIL
    assert v["overall"] == scoring.FAIL

    # All-good candidate.
    good = _result(s11_db=-18.0, bw_mhz=120, f_res_ghz=2.44, r_ohm=49, x_ohm=2)
    assert scoring.evaluate(good, _BLE)["overall"] == scoring.PASS

    # Nothing measured -> overall none (not fail).
    assert scoring.evaluate(_result(), _BLE)["overall"] == scoring.NONE


def test_target_from_spec_maps_fields_without_defaults():
    t = scoring.target_from_spec(
        {
            "f0_ghz": 2.45,
            "band_ghz": [2.4, 2.4835],
            "impedance_ohm": 50.0,
            "return_loss_db": 10.0,
        }
    )
    assert t.band_ghz == (2.4, 2.4835) and t.impedance_ohm == 50.0
    # A spec with only a frequency leaves the rest None (never defaulted).
    free = scoring.target_from_spec({"f0_ghz": 3.5})
    assert free.band_ghz is None and free.impedance_ohm is None
    assert free.return_loss_db is None


def test_serialize_for_html_views():
    r = _result(s11_db=-8.0, bw_mhz=120, f_res_ghz=2.44, r_ohm=50, x_ohm=0)
    s = scoring.serialize(r, _BLE)
    assert s["overall"] == scoring.WARN  # return loss/vswr warn
    assert s["overall_glyph"] == scoring.GLYPH[scoring.WARN]
    # One entry per property, in table order, each carrying its glyph + text.
    assert [p["key"] for p in s["props"]] == [k for k, _l, _f in scoring.PROPERTIES]
    rl = next(p for p in s["props"] if p["key"] == "return_loss")
    assert rl["status"] == scoring.WARN and rl["glyph"] == "⚠"
    assert "≥10" in rl["text"] and rl["label"] == "Return loss"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
