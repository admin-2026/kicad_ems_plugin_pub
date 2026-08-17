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
from bare_package import ROOT, load, run_module_tests  # noqa: E402

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


def test_the_page_looks_for_the_file_this_module_writes():
    """The name is a convention on both sides: the report page names it in its
    boot config and resolves it beside the dump it was pointed at. Nothing
    passes it between them, so only this can catch a rename."""
    report_js = (ROOT / "antenna_plugin" / "viewer" / "js" / "report.js").read_text(
        encoding="utf-8"
    )
    assert f"meta: '{run_verdicts.FILENAME}'" in report_js


if __name__ == "__main__":
    run_module_tests(globals())
