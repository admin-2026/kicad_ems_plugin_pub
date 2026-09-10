"""Unit tests for antenna_plugin.sim.runinfo -- the ``run`` series the solver
ships in every report/data file (how far the solve actually got).

Pure stdlib, no KiCad and no binary: the data files are written by hand here.
Register a bare package (skipping antenna_plugin/__init__, which imports
pcbnew) so the module's package-relative home resolves:

    python3 tests/test_runinfo.py   (or pytest)
"""

import json
import pathlib
import tempfile

from bare_package import load

_ROOT = pathlib.Path(__file__).resolve().parents[1]
runinfo = load("emkit.sim.runinfo")

# A finished 20 ns run, exactly as RunSeries.cpp writes it.
_DONE = {
    "steps": 33856,
    "plannedSteps": 33856,
    "timeNs": 19.9998,
    "plannedTimeNs": 19.9998,
    "dtPs": 0.59073,
    "ringDownDb": -80.4,
    "stop": "fixed length",
    "partial": False,
    "sample": 0,
    "text": "33856 / 33856 steps, 20.00 of 20.00 ns simulated, "
    "ring-down -80.4 dB (fixed length)",
}
# The same run interrupted at 2.27 ns, before any ring-down window closed.
_INTERRUPTED = dict(
    _DONE,
    steps=3850,
    timeNs=2.2743,
    ringDownDb=None,
    stop="interrupted",
    partial=True,
    text="3850 / 33856 steps, 2.27 of 20.00 ns simulated (interrupted)",
)
# The second mid-run sample of that same run.
_SAMPLE = dict(
    _INTERRUPTED,
    stop="running",
    sample=2,
    text="3850 / 33856 steps, 2.27 of 20.00 ns simulated (running)",
)


def _js(run=_DONE, other=True):
    """A solver data file (`pcb_report.js` / `pcb_data.js`): one JS assignment
    whose outer object has unquoted keys -- not JSON, which is exactly why the
    series is lifted out with a regex."""
    series = {"run": run}
    if other:
        series["impedance"] = {"f": [1, 2], "r": [50, 51]}
    body = ",".join(f'"{k}":{json.dumps(v)}' for k, v in series.items())
    return "window.FDTD={s:{" + body + "}};\n"


def test_parses_a_finished_run():
    info = runinfo.parse(_js())
    assert info.steps == 33856 and info.planned_steps == 33856
    assert info.time_ns == 19.9998 and info.planned_time_ns == 19.9998
    assert info.dt_ps == 0.59073
    assert info.ring_down_db == -80.4
    assert info.stop == "fixed length"
    assert info.partial is False and info.sample == 0
    assert info.progress == 1.0


def test_parses_an_interrupted_run():
    info = runinfo.parse(_js(_INTERRUPTED))
    assert info.partial is True and info.stop == "interrupted"
    assert round(info.progress, 3) == 0.114
    # No ring-down window closed yet: that is "not measured", never 0 dB.
    assert info.ring_down_db is None


def test_parses_a_mid_run_sample():
    info = runinfo.parse(_js(_SAMPLE))
    assert info.sample == 2 and info.stop == "running" and info.partial


def test_json_dump_is_read_the_same_way():
    # pcb_data.json is the bare object; the same series, no assignment.
    info = runinfo.parse(json.dumps({"run": _DONE, "pattern": {"d": [1]}}))
    assert info.steps == 33856 and info.stop == "fixed length"


def test_no_run_series_is_none():
    # An output from a binary older than 1.1.0 -- nothing is invented for it.
    assert runinfo.parse('window.FDTD={s:{"impedance":{"f":[1]}}};') is None
    assert runinfo.parse("") is None
    assert runinfo.parse(None) is None


def test_unparseable_series_is_none():
    assert runinfo.parse('{"run":{"steps":,}}') is None


def test_missing_fields_stay_none():
    info = runinfo.parse('{"run":{"stop":"capped"}}')
    assert info.stop == "capped"
    assert info.steps is None and info.time_ns is None
    assert info.ring_down_db is None and info.progress is None
    assert info.text == ""


def test_non_numeric_fields_are_dropped_not_guessed():
    info = runinfo.parse('{"run":{"steps":"lots","timeNs":true}}')
    assert info.steps is None and info.time_ns is None


def test_summary_prefers_the_solvers_own_text():
    assert runinfo.parse(_js()).summary() == _DONE["text"]


def test_summary_falls_back_to_the_numbers():
    info = runinfo.parse(_js(dict(_INTERRUPTED, text="")))
    assert info.summary() == (
        "2.27 of 20.00 ns simulated, ring-down not measured yet (interrupted)"
    )
    done = runinfo.parse(_js(dict(_DONE, text="")))
    assert done.summary() == ("20.00 ns simulated, ring-down -80.4 dB (fixed length)")
    sample = runinfo.parse(_js(dict(_SAMPLE, text="")))
    assert "snapshot 2" in sample.summary()
    assert runinfo.parse('{"run":{}}').summary() == ""


def test_label_is_short_and_says_what_is_missing():
    assert runinfo.parse(_js()).label() == "20.00 ns"
    assert runinfo.parse(_js(_INTERRUPTED)).label() == "2.27/20.00 ns · interrupted"
    assert runinfo.parse(_js(_SAMPLE)).label() == "2.27/20.00 ns · snapshot 2"
    assert runinfo.parse('{"run":{"sample":3}}').label() == "snapshot 3"
    assert runinfo.parse('{"run":{}}').label() == ""


def test_read_reads_a_runs_dump():
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "pcb_data.js").write_text(_js(_INTERRUPTED), encoding="utf-8")
        assert runinfo.read(d / "pcb_data.js").stop == "interrupted"
        # A bare-JSON dump carries the same series, so one parser covers both.
        (d / "pcb_data.json").write_text(_js(_SAMPLE), encoding="utf-8")
        assert runinfo.read(d / "pcb_data.json").sample == 2
        # A file that isn't there, and one that carries no run series, both say
        # nothing rather than guessing.
        assert runinfo.read(d / "nope.js") is None
        # The grid dump is one of those: a mesh is not a record of anything, so
        # a grid preview stays unlabelled even with the run's dump beside it.
        (d / "pcb_grid.js").write_text('window.FDTD={s:{"grid":{}}};', encoding="utf-8")
        assert runinfo.read(d / "pcb_grid.js") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
