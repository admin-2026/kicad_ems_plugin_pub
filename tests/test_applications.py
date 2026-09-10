"""The design target: the built-in table, and the ones the user saves.

This product's own kind of saved entry, so it is held to its kind's contract
here rather than in the core's ``test_userlib`` -- which covers the shared
machinery (the file, the naming rules, the merged picker) over the kinds the
core itself has. What is left for this file is what only a design target can
say: which fields make one, which it may leave free, and what it refuses.

The plugin package's __init__ imports pcbnew, so it is loaded through the
bare package to stay runnable off-KiCad:  python3 tests/test_applications.py
"""

import json
import math
import pathlib
import tempfile

from bare_package import load

applications = load("applications.db")
Applications = applications.Applications
Catalog = load("applications.catalog").Catalog
UserStore = load("emkit.userlib.store").UserStore


def _catalog(directory):
    """A design-target catalog over a temporary file."""
    return Catalog(UserStore(Catalog.FILENAME, directory))


def _saved(directory, name="Wi-Fi 6E low", f0=6.1, bw=500.0, z=50.0):
    cat = _catalog(directory)
    cat.save(name, f0_ghz=f0, bandwidth_mhz=bw, impedance_ohm=z)
    return cat


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


# --------------------------------------------------------------------------- #
# The ones the user saved
# --------------------------------------------------------------------------- #
def test_a_saved_target_keeps_its_own_file_and_its_typed_numbers():
    with tempfile.TemporaryDirectory() as td:
        _saved(td)
        assert [p.name for p in pathlib.Path(td).iterdir()] == ["applications.json"]
        assert json.loads((pathlib.Path(td) / Catalog.FILENAME).read_text()) == [
            {
                "name": "Wi-Fi 6E low",
                "f0_ghz": 6.1,
                "bandwidth_mhz": 500.0,
                "impedance_ohm": 50.0,
                "return_loss_db": None,
            }
        ]


def test_a_saved_target_comes_back_as_a_target():
    # A fresh reader, and the band is rebuilt from the frequency and the
    # bandwidth by the same call a live Custom pick goes through -- so a saved
    # target and a typed one can never be built by different rules.
    with tempfile.TemporaryDirectory() as td:
        _saved(td)
        app = _catalog(td).get("Wi-Fi 6E low")
        assert app.f0_ghz == 6.1 and app.impedance_ohm == 50.0
        assert app.bandwidth_mhz == 500.0  # derived from the band it was stored as
        assert abs(app.band_start_ghz - 5.85) < 1e-9
        assert "6.1 GHz" in app.spec_line and "50 Ω" in app.spec_line


def test_only_the_frequency_makes_a_target():
    # A band, an impedance and a return loss it wasn't given stay unset (shown,
    # not judged, never defaulted); a frequency it wasn't given is a refusal
    # that says what to type, and nothing is written.
    with tempfile.TemporaryDirectory() as td:
        cat = _catalog(td)
        cat.save("Bare", f0_ghz=0.433, bandwidth_mhz=None, impedance_ohm=None)
        app = _catalog(td).get("Bare")
        assert app.band is None and app.impedance_ohm is None
        assert app.return_loss_db is None
        try:
            cat.save("No frequency", f0_ghz=0, bandwidth_mhz=100.0)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "pattern frequency" in str(exc)
        assert cat.saved_names() == ["Bare"]


def test_a_record_with_no_frequency_is_skipped_rather_than_offered():
    # The same rule, one layer down: a file somebody hand-edited into nonsense
    # loses that row instead of putting a target in the picker that cannot say
    # what it is.
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / Catalog.FILENAME
        path.write_text(json.dumps([{"name": "No frequency", "bandwidth_mhz": 100.0}]))
        assert _catalog(td).saved() == []


def test_no_saved_target_can_shadow_a_builtin_or_the_sentinel():
    with tempfile.TemporaryDirectory() as td:
        cat = _catalog(td)
        for taken in ("Wi-Fi 5 GHz", Catalog.CUSTOM):
            try:
                cat.save(taken, f0_ghz=2.45)
                assert False, f"expected ValueError for {taken}"
            except ValueError as exc:
                assert "built-in" in str(exc)


def test_a_saved_target_joins_the_picker_and_is_picked_like_a_builtin():
    with tempfile.TemporaryDirectory() as td:
        cat = _saved(td)
        assert cat.choices() == list(cat.builtin_names()) + [
            "Wi-Fi 6E low",
            cat.CUSTOM,
        ]
        assert cat.is_user("Wi-Fi 6E low") and not cat.is_user("Wi-Fi 5 GHz")
        assert cat.get("Wi-Fi 5 GHz").f0_ghz == 5.5


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
