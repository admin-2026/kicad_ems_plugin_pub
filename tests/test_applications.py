"""Unit tests for antenna_plugin.applications.db (pure, no KiCad).

The plugin package's __init__ imports pcbnew, so load the module by path to
keep these runnable off-KiCad:  python3 tests/test_applications.py
"""

import importlib.util
import math
import pathlib

_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "antenna_plugin"
    / "applications"
    / "db.py"
)
_spec = importlib.util.spec_from_file_location("applications", _SRC)
applications = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(applications)
Applications = applications.Applications


def test_ble_reproduces_old_pattern_frequency():
    # BLE was the default pick and filled 2.45 GHz.
    assert Applications.get("Bluetooth / BLE (2.4 GHz)").f0_ghz == 2.45


def test_every_app_has_a_spec():
    for app in (Applications.get(n) for n in Applications.names()):
        assert app.band_start_ghz < app.band_end_ghz
        assert app.f0_ghz > 0
        assert app.impedance_ohm == 50.0  # equals the feed port resistance
        assert app.return_loss_db > 0


def test_bandwidth_spans_the_band_edges():
    ble = Applications.get("Bluetooth / BLE (2.4 GHz)")
    assert math.isclose(ble.bandwidth_mhz, (2.4835 - 2.400) * 1000)


def test_vswr_derives_from_return_loss():
    # A 10 dB return loss is the familiar ~1.92:1 (better than 2:1).
    ble = Applications.get("Bluetooth / BLE (2.4 GHz)")
    assert ble.return_loss_db == 10.0
    assert math.isclose(ble.vswr, 1.9250, abs_tol=1e-3)


def test_vswr_return_loss_round_trip():
    for vswr in (1.5, 2.0, 3.0):
        rl = applications.return_loss_from_vswr(vswr)
        assert math.isclose(applications.vswr_from_return_loss(rl), vswr)


def test_2_to_1_vswr_is_about_9_54_db():
    assert math.isclose(applications.return_loss_from_vswr(2.0), 9.542, abs_tol=1e-3)


def test_gps_is_specified_tighter():
    assert Applications.get("GPS L1 (1.575 GHz)").return_loss_db == 15.0


def test_choices_expose_custom_sentinel_last():
    choices = Applications.choices()
    assert choices[-1] == Applications.CUSTOM
    assert "Wi-Fi 5 GHz" in choices


def test_custom_and_unknown_have_no_spec():
    assert Applications.get(Applications.CUSTOM) is None
    assert Applications.get("Nonexistent radio") is None


def test_custom_synthesizes_band_from_frequency_and_bandwidth():
    # 2.45 GHz ± 50 MHz (half of a 100 MHz bandwidth) = 2.40..2.50 GHz.
    app = Applications.custom(f0_ghz=2.45, bandwidth_mhz=100.0, impedance_ohm=50.0)
    assert app.name == Applications.CUSTOM
    assert app.f0_ghz == 2.45
    assert math.isclose(app.band_start_ghz, 2.40)
    assert math.isclose(app.band_end_ghz, 2.50)
    assert math.isclose(app.bandwidth_mhz, 100.0)
    assert app.impedance_ohm == 50.0
    assert app.return_loss_db is None  # no user-set match target


def test_custom_leaves_missing_or_bad_fields_free():
    # Blank / non-positive entries stay None (shown, not judged), and the
    # band-derived properties tolerate the free band.
    app = Applications.custom(f0_ghz=None, bandwidth_mhz=0.0, impedance_ohm=-5.0)
    assert app.band is None
    assert app.band_start_ghz is None
    assert app.bandwidth_mhz is None
    assert app.impedance_ohm is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
