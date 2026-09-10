"""Unit tests for antenna_plugin.design.run_verdicts (no KiCad, no wx).

A single run is judged against the design target it was started for, and the
verdicts land in a sidecar beside its dump for the report page to paint. These
cover the three things that can go wrong on the way: judging by different rules
than a scan uses, writing a table for a run that measured nothing, and drifting
apart from the page that reads the file.

    python3 tests/test_run_verdicts.py
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import CORE, load, run_module_tests  # noqa: E402

run_verdicts = load("design.run_verdicts")
scoring = load("design.scoring")


class _App:
    """An applications.Application, as much of one as this module reads (it is
    duck-typed on purpose -- see scoring.target_from_application)."""

    def __init__(
        self,
        name="Wi-Fi 2.4",
        f0_ghz=2.45,
        band=(2.4, 2.4835),
        impedance_ohm=50.0,
        return_loss_db=10.0,
    ):
        self.name = name
        self.f0_ghz = f0_ghz
        self.band = band
        self.impedance_ohm = impedance_ohm
        self.return_loss_db = return_loss_db


def _dump(f, r, x, s11):
    body = json.dumps(
        {
            "pattern": {"freqGHz": 2.45},
            "impedance": {"f": f, "R": r, "X": x, "S11": s11},
        }
    )
    return f"window.FDTD={{s:{body}}};\n"


# A sweep resonating in band, well matched, roughly 50 ohm at f0.
GOOD = _dump(
    [2.30, 2.40, 2.45, 2.50, 2.60],
    [30, 46, 50, 54, 70],
    [-40, -6, 0, 6, 40],
    [-3, -14, -22, -13, -3],
)


def test_a_run_is_scored_by_the_same_rules_as_a_scan_candidate():
    payload = run_verdicts.evaluate(GOOD, _App())
    reference = scoring.serialize(
        {
            "f_res_ghz": 2.45,
            "s11_db": -22.0,
            "bw_mhz": payload_bw(payload),
            "r_ohm": 50.0,
            "x_ohm": 0.0,
        },
        scoring.Target(
            f0_ghz=2.45,
            band_ghz=(2.4, 2.4835),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
    )
    assert payload["overall"] == reference["overall"] == scoring.PASS
    assert [p["key"] for p in payload["props"]] == [
        p["key"] for p in reference["props"]
    ]


def payload_bw(payload):
    """The bandwidth the payload was scored with, back out of its own text --
    so the reference above judges the same measurement, not a guessed one."""
    text = next(p["text"] for p in payload["props"] if p["key"] == "bandwidth")
    return float(text.split()[0])


# The sweep a real 2.44 GHz patch produces, in miniature: it resonates in band
# and is well matched there, and the run also sweeps up to 3.9 GHz, where a
# higher mode rings *deeper* than the antenna does. Scored on the deepest dip,
# this board came back "Resonance 3.69 GHz ✗" -- a failing verdict on an
# antenna that meets its spec.
TWO_DIPS = _dump(
    [2.30, 2.40, 2.45, 2.50, 2.60, 3.20, 3.69, 3.90],
    [30, 46, 50, 54, 70, 20, 51, 30],
    [-40, -6, 0, 6, 40, -40, 2, -30],
    [-3, -14, -22, -13, -3, -0.6, -33, -4],
)


def test_a_deeper_dip_outside_the_band_does_not_become_the_verdict():
    """The bug this pins: an in-band resonance is what the target asked about,
    and a sweep running to 3.9 GHz regularly has something deeper in it. Both
    rows read off the dip -- the resonance and the bandwidth it spans -- must
    be the in-band one, and the run must pass."""
    payload = run_verdicts.evaluate(TWO_DIPS, _App())
    rows = {p["key"]: p for p in payload["props"]}
    assert "2.4" in rows["resonance"]["text"] and "3.6" not in rows["resonance"]["text"]
    assert rows["resonance"]["status"] == scoring.PASS
    assert payload["overall"] == scoring.PASS
    # ...and the bandwidth is that dip's span, not the 3.69 one's, which is
    # bracketed by samples 500 MHz apart and so is far wider than the band.
    assert payload_bw(payload) < (2.60 - 2.30) * 1000


def test_an_antenna_that_resonates_off_target_is_still_reported_off_target():
    """The other half of the same rule, and the one a search restricted to the
    band would have broken: preferring the in-band dip must not mean
    *inventing* one. This sweep matches at 2.20 GHz and nowhere in band, so
    that is what the table says -- the frequency the antenna really has, and a
    fail. Looking only between 2.4 and 2.4835 would have found the shallowest
    point of the skirt in there and called the board passing."""
    off = _dump(
        [2.10, 2.20, 2.30, 2.40, 2.50, 3.69],
        [30, 50, 40, 20, 10, 51],
        [-30, 0, 20, 40, 60, 2],
        [-4, -24, -9, -4, -2, -3],
    )
    rows = {p["key"]: p for p in run_verdicts.evaluate(off, _App())["props"]}
    assert "2.2" in rows["resonance"]["text"]
    assert rows["resonance"]["status"] == scoring.FAIL


def test_each_row_says_which_frequency_it_was_read_at():
    """One table, two kinds of row: the match is read at the target frequency,
    the resonance and its bandwidth wherever the antenna actually resonates.
    Stacked vertically they read as one operating point unless each says."""
    at = {p["key"]: p["at"] for p in run_verdicts.evaluate(TWO_DIPS, _App())["props"]}
    assert at["return_loss"] == at["vswr"] == at["impedance"] == "2.45 GHz"
    # The two that are already a frequency, or are a span around one, name none
    # -- a row saying "2.4712 GHz at 2.45 GHz" would be worse than silent.
    assert at["resonance"] == at["bandwidth"] == ""


def test_the_target_line_names_only_what_the_target_pins_down():
    full = run_verdicts.describe(_App())
    assert "Wi-Fi 2.4" in full and "2.45 GHz" in full
    assert "50 Ω" in full and "≥10 dB" in full
    # A hand-typed frequency with nothing else specified must not grow a
    # default band or a 50 ohm it was never given (design.scoring's rule:
    # shown but not judged, never defaulted).
    bare = run_verdicts.describe(
        _App(name="Custom…", band=None, impedance_ohm=None, return_loss_db=None)
    )
    assert bare == "Custom… · 2.45 GHz"


def test_a_run_with_nothing_to_measure_is_not_judged():
    # A solve that stopped before its first impedance sweep.
    assert run_verdicts.evaluate('window.FDTD={s:{"pattern":{}}};', _App()) is None
    # ... and a target with no frequency to measure at.
    assert run_verdicts.evaluate(GOOD, _App(f0_ghz=None)) is None
    assert run_verdicts.evaluate(GOOD, None) is None


def test_write_leaves_the_sidecar_the_page_loads():
    with tempfile.TemporaryDirectory() as td:
        dump = pathlib.Path(td) / "pcb_data.js"
        dump.write_text(GOOD, encoding="utf-8")
        payload = run_verdicts.write(dump, _App())
        sidecar = dump.parent / run_verdicts.FILENAME
        text = sidecar.read_text(encoding="utf-8")
        # An assignment, not JSON: the page loads it as a classic <script src>.
        head = "window.FDTD_VERDICTS="
        assert text.startswith(head)
        assert json.loads(text[len(head) :].rstrip().rstrip(";")) == payload


def test_write_removes_a_sidecar_it_can_no_longer_stand_behind():
    """A snapshot is scored like any other report and overwrites the previous
    verdicts. If the newest record cannot be judged, the old file must go with
    it -- verdicts belonging to numbers that are no longer there are worse than
    none."""
    with tempfile.TemporaryDirectory() as td:
        dump = pathlib.Path(td) / "pcb_data.js"
        dump.write_text(GOOD, encoding="utf-8")
        assert run_verdicts.write(dump, _App()) is not None
        dump.write_text('window.FDTD={s:{"pattern":{}}};', encoding="utf-8")
        assert run_verdicts.write(dump, _App()) is None
        assert not (dump.parent / run_verdicts.FILENAME).exists()


# A dip that clears 10 dB comfortably and never comes near 15: matched for a
# Wi-Fi target, short for a GPS one.
SHALLOW = _dump(
    [2.30, 2.40, 2.45, 2.50, 2.60],
    [30, 40, 50, 60, 70],
    [-40, -10, 0, 10, 40],
    [-3, -11, -12, -11, -3],
)


def test_a_target_is_scored_on_the_band_it_asks_for_not_on_the_ten_db_one():
    """GPS L1 is specified at 15 dB. Measuring its band at a fixed -10 dB --
    always the wider span -- passed the Bandwidth row on an antenna whose match
    never reaches 15 dB, while the Return loss row beside it failed."""
    tight = run_verdicts.evaluate(
        SHALLOW, _App(name="GPS-like", return_loss_db=15.0, band=(2.44, 2.46))
    )
    rows = {p["key"]: p for p in tight["props"]}
    assert rows["return_loss"]["status"] != scoring.PASS  # 12 dB, wanted 15
    assert rows["bandwidth"]["status"] != scoring.PASS
    # ...and the same sweep against a 10 dB target still passes both.
    loose = run_verdicts.evaluate(
        SHALLOW, _App(name="Wi-Fi-like", return_loss_db=10.0, band=(2.44, 2.46))
    )
    rows = {p["key"]: p for p in loose["props"]}
    assert rows["return_loss"]["status"] == scoring.PASS
    assert rows["bandwidth"]["status"] == scoring.PASS


def test_a_free_return_loss_still_reads_the_band_at_ten_db():
    free = run_verdicts.evaluate(SHALLOW, _App(return_loss_db=None, band=(2.44, 2.46)))
    rows = {p["key"]: p for p in free["props"]}
    assert rows["return_loss"]["status"] == scoring.NONE  # nothing to judge
    assert rows["bandwidth"]["status"] == scoring.PASS


# --------------------------------------------------------------------------- #
# What the numbers were measured against
#
# The solver normalizes the S11/VSWR columns to the port resistance it was
# handed and records it as geometry.zref; three of the five rows are read off
# those columns and then labelled with the *target's* impedance. A run this
# plugin starts now has one number in both places (runjob._port_resistance),
# so these are about the runs it did not start: an archive from before that was
# true, or a hand-edited pcb.yaml.
# --------------------------------------------------------------------------- #
def _with_zref(dump_text, zref):
    body = json.loads(dump_text[len("window.FDTD={s:") : -len("};\n")])
    body["geometry"] = {"zref": zref}
    return f"window.FDTD={{s:{json.dumps(body)}}};\n"


def test_a_run_solved_against_another_impedance_is_not_scored_against_this_one():
    try:
        run_verdicts.evaluate(_with_zref(GOOD, 75.0), _App(impedance_ohm=50.0))
        assert False, "expected a refusal"
    except RuntimeError as exc:
        assert "75" in str(exc) and "50" in str(exc)


def test_the_same_impedance_said_twice_is_not_a_disagreement():
    payload = run_verdicts.evaluate(_with_zref(GOOD, 50.0), _App(impedance_ohm=50.0))
    assert payload["overall"] == scoring.PASS


def test_an_ideal_current_source_has_no_reference_to_disagree_with():
    # The solver writes a null zref when the port is not a resistor.
    payload = run_verdicts.evaluate(_with_zref(GOOD, None), _App(impedance_ohm=50.0))
    assert payload["overall"] == scoring.PASS


def test_a_target_that_names_no_impedance_judges_the_match_on_nothing():
    payload = run_verdicts.evaluate(_with_zref(GOOD, 75.0), _App(impedance_ohm=None))
    assert payload is not None  # scored, just not on the impedance row


def test_a_dump_from_before_zref_was_written_is_scored_as_it_always_was():
    payload = run_verdicts.evaluate(GOOD, _App(impedance_ohm=50.0))
    assert payload["overall"] == scoring.PASS


def test_the_page_looks_for_the_file_this_module_writes():
    """The name is a convention on both sides: the report page names it in its
    boot config and resolves it beside the dump it was pointed at. Nothing
    passes it between them, so only this can catch a rename."""
    report_js = (CORE / "viewer" / "js" / "report.js").read_text(encoding="utf-8")
    assert f"meta: '{run_verdicts.FILENAME}'" in report_js


if __name__ == "__main__":
    run_module_tests(globals())
