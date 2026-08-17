"""The saved scan: a finished sweep's rows, kept in its folder and read back.

design/scan_store.py is what makes a footprint placeable in a later session --
the results the chooser ranks used to live only in the open window. So what
these check is the round trip (the rows and the frame they were measured in
come back as they went in, design object included) and, just as much, what the
reader refuses: a file from another version, another design, or one too thin to
place from must never half-load into copper nobody checked.

Pure -- no wx, no KiCad, no solver: a scan spec, a temp folder and the real
designs.

    python3 tests/test_scan_store.py
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
scan_store = load("design.scan_store")
wizard_scan = load("design.wizard_scan")

F0 = 2.45


def _spec(design):
    """A scan spec as the wizard's Scan section builds it (gui/sections/scan.py
    ``_spec``): the marker's frame, the sweep and the desired spec."""
    w, h = design.area_hint_mm(F0)
    values = design.default_values(F0)
    return {
        "design": design,
        "area": (0.0, 0.0, w, h),
        "edge": "bottom",
        "frac": 0.3,
        "rot_deg": 0.0,
        "pivot": (0.0, 0.0),
        "gap_mm": 0.5,
        "scan_param": design.LENGTH_KEY,
        "values": values,
        "sweep_lo": None,
        "sweep_hi": None,
        "f0_ghz": F0,
        "n": 3,
        "feed_layer": "F_Cu",
        "band_ghz": [2.4, 2.4835],
        "impedance_ohm": 50.0,
        "return_loss_db": 10.0,
    }


def _results(spec):
    """A finished scan's rows: the planner's real candidates (values + geom)
    with numbers on them, which is the shape run_scan saves."""
    rows = wizard_scan.plan(spec)
    for i, row in enumerate(rows):
        row.update(
            {
                "f_res_ghz": F0 + 0.01 * i,
                "s11_db": -20.0 + i,
                "bw_mhz": 180.0,
                "r_ohm": 48.0,
                "x_ohm": -2.0,
                "outdir": f"/some/where/cand-{i + 1:02d}",
            }
        )
    return rows


def _folder():
    return pathlib.Path(tempfile.mkdtemp(prefix="scan_store_"))


# --------------------------------------------------------------------------- #
# The round trip
# --------------------------------------------------------------------------- #
def test_a_saved_scan_comes_back_row_for_row():
    for design in registry.DESIGNS:
        spec = _spec(design)
        results = _results(spec)
        folder = _folder()
        scan_store.save(folder, results, spec)
        saved = scan_store.load(folder)
        assert saved is not None, design.key
        assert saved.results == results, design.key
        assert saved.when, design.key  # when the scan finished, for the wizard
        assert saved.path == folder / scan_store.FILE, design.key


def test_the_frame_comes_back_as_the_gui_built_it():
    """The placer re-solves a candidate in the spec's own frame, so what comes
    back has to be that dict: the design as its object (not a key) and the
    geometry as tuples, JSON having written every one of them as a list."""
    for design in registry.DESIGNS:
        spec = _spec(design)
        saved_dir = _folder()
        scan_store.save(saved_dir, _results(spec), spec)
        back = scan_store.load(saved_dir).spec
        assert back["design"] is design, design.key
        assert back["area"] == spec["area"], design.key
        assert back["pivot"] == spec["pivot"], design.key
        for key in ("edge", "frac", "gap_mm", "f0_ghz", "feed_layer"):
            assert back[key] == spec[key], (design.key, key)
        # The desired spec travels too, or a restored candidate could not be
        # scored against the target it was scanned for.
        for key in ("band_ghz", "impedance_ohm", "return_loss_db"):
            assert back[key] == spec[key], (design.key, key)


def test_a_spec_carrying_only_the_design_key_saves_too():
    """A headless scan may hand the driver ``design='ifa'``; the file names the
    design either way."""
    design = registry.DESIGNS[0]
    spec = dict(_spec(design), design=design.key)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    assert payload["design"] == design.key
    assert scan_store.load(folder).spec["design"] is design


def test_the_next_scan_replaces_the_last():
    """One folder describes one scan, the way its combined views do."""
    design = registry.DESIGNS[0]
    spec = _spec(design)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    second = _results(spec)[:1]
    scan_store.save(folder, second, spec)
    assert scan_store.load(folder).results == second


# --------------------------------------------------------------------------- #
# What the reader refuses
# --------------------------------------------------------------------------- #
def test_a_folder_with_no_saved_scan_is_not_an_error():
    assert scan_store.load(_folder()) is None


def _refused(folder, **payload):
    """Write ``payload`` as the folder's saved scan and return why loading it
    was refused."""
    (folder / scan_store.FILE).write_text(json.dumps(payload), encoding="utf-8")
    try:
        scan_store.load(folder, payload.get("design"))
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"loaded {payload!r} instead of refusing it")


def test_a_file_from_another_version_is_refused():
    design = registry.DESIGNS[0]
    spec = _spec(design)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    payload["version"] = scan_store.VERSION + 1
    why = _refused(folder, **payload)
    assert "another version" in why


def test_a_scan_of_another_design_is_refused():
    """The scan folder is per design, so this is a folder somebody moved --
    and its rows would place the wrong antenna."""
    a, b = registry.DESIGNS[0], registry.DESIGNS[1]
    spec = _spec(a)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    try:
        scan_store.load(folder, b.key)
    except ValueError as exc:
        assert a.key in str(exc) and b.key in str(exc)
    else:
        raise AssertionError("loaded another design's scan")


def test_a_design_this_build_does_not_have_is_refused():
    design = registry.DESIGNS[0]
    spec = _spec(design)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    payload["design"] = "spiral"
    payload["spec"]["design"] = "spiral"
    why = _refused(folder, **payload)
    assert "spiral" in why


def test_a_file_with_no_results_is_refused():
    design = registry.DESIGNS[0]
    spec = _spec(design)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    payload["results"] = []
    assert "no scan results" in _refused(folder, **payload)


def test_a_candidate_without_geometry_is_refused():
    """Every row is placed by re-solving its ``values``; a row without them is
    not a candidate, and guessing one would be inventing copper."""
    design = registry.DESIGNS[0]
    spec = _spec(design)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    payload["results"][0].pop("values")
    assert "no geometry" in _refused(folder, **payload)


def test_a_spec_too_thin_to_place_from_is_refused():
    """The frame is what a candidate is re-solved in: without it there is
    nothing to place, and nothing to default to either."""
    design = registry.DESIGNS[0]
    spec = _spec(design)
    folder = _folder()
    scan_store.save(folder, _results(spec), spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    payload["spec"].pop("area")
    assert "area" in _refused(folder, **payload)


def test_a_corrupt_file_says_so_rather_than_raising_json():
    folder = _folder()
    (folder / scan_store.FILE).write_text("{not json", encoding="utf-8")
    try:
        scan_store.load(folder)
    except ValueError as exc:
        assert "readable JSON" in str(exc)
    else:
        raise AssertionError("loaded a corrupt file")


if __name__ == "__main__":
    run_module_tests(globals())
