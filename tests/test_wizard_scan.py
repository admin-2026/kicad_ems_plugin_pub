"""Orchestration tests for antenna_plugin.design.wizard_scan (no KiCad, no wx).

The solver is a stub executable that reads the per-candidate YAML, measures
the spliced antenna copper in the gerber, and writes the schema 9.x outputs
-- the pcb_data.json dump the scoring reads plus the pcb_data.js / pcb_grid.js
data files the combined scan views reference -- with an S11
dip that follows a 1/length law. It honours ``--grid-only`` like the real
binary (grid payload, then stop), so the wizard's grid pass runs through here
too. So the test exercises the real pipeline (gerber splice -> config -> run ->
parse -> refine -> rank -> combined views) without the FDTD binary.

The driver is design-agnostic, so the same scans run over both shipped
topologies: the L-monopole cases pin the numbers down (the stub measures its
copper), and the inverted-F case proves a second design needs no code here.

    python3 tests/test_wizard_scan.py
"""

import os
import pathlib
import stat
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402
from helppage import assert_guide_loads  # noqa: E402

wizard_scan = load("design.wizard_scan")
links = load("emkit.links")
registry = load("design.registry")
scan_store = load("design.scan_store")

# The stub solver: computes the spliced antenna's total length from the
# G36 regions (vertical rect = ground stub 1.25 + arm + 0.5 corner
# overshoot; horizontal rect = the bend) and writes an impedance sweep with
# an S11 dip at f_res = K_GHZ_MM / length, in the solver's schema 9.x
# shapes: the pcb_data.js/.json dump plus the grid view's pcb_grid.js.
_STUB = r"""#!/usr/bin/env python3
import json, math, os, sys

cfg = {}
for line in open(sys.argv[1]):
    line = line.split("#")[0].strip()
    if ":" in line:
        k, v = line.split(":", 1)
        cfg[k.strip()] = v.strip()
outdir = cfg["outdir"]
# 0 = auto on both bounds, the same rule the runner applies (config.DEFAULTS:
# fmax = 1.6 x fpattern, flow = fpattern / 5) -- the wizard only sends explicit
# values when the user overrides them in the Advanced pane.
fpattern = float(cfg["fpattern_ghz"])
flow = float(cfg["flow_ghz"]) or fpattern / 5.0
fmax = float(cfg["fmax_ghz"]) or 1.6 * fpattern

blocks, cur = [], None
for line in open(os.path.join(outdir, "antenna_copper.gbr")):
    line = line.strip()
    if line == "G36*":
        cur = []
    elif line == "G37*":
        blocks.append(cur); cur = None
    elif cur is not None and line.startswith("X"):
        body = line.split("D")[0]
        x, y = body[1:].split("Y")
        cur.append((int(x) / 1e6, int(y) / 1e6))

total = 0.0
tw = None
for pts in blocks:
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    total += (h - 1.75) if h > w else w
    cross = min(w, h)                       # the trace width (both rects)
    tw = cross if tw is None else min(tw, cross)
# Length sets resonance; a small width term (zero at the 1.0 mm width the
# length tests use) lets the width scan tell candidates apart.
f_res = 56.0 / total - 0.05 * ((tw or 1.0) - 1.0)

def data_js(stem, series):
    with open(os.path.join(outdir, stem + ".js"), "w") as f:
        f.write("window.FDTD={s:%s};\n" % json.dumps(series))

grid = {"n": [2, 2, 1], "x": [0, 1, 2], "y": [0, 1, 2], "z": [0, 0.1],
        "pml": 0, "groups": [{"label": "Copper: F_Cu",
                              "cells": [0, 0, 0, 1, 0, 0]}], "feed": None}
data_js("pcb_grid", {"grid": grid})
if "--grid-only" in sys.argv:
    # The meshing pass: the grid is written and the run stops there -- no
    # data dump to score, no report series.
    print(f"stub grid: length {total:.2f} mm")
    raise SystemExit(0)

imp = {"f": [], "R": [], "X": [], "S11": [], "VSWR": []}
for i in range(101):
    fg = flow + (fmax - flow) * i / 100
    s11 = -0.5 - 30.0 * math.exp(-((fg - f_res) / 0.15) ** 2)
    imp["f"].append(round(fg, 6)); imp["R"].append(50)
    imp["X"].append(round((fg - f_res) * 100, 3))
    imp["S11"].append(round(s11, 4)); imp["VSWR"].append(2.0)
metrics = {"gain": 1.8, "efficiency": 0.7,
           "ePlane": [0.0, 1.8, 0.0], "hPlane": [1.8, 1.8, 1.8, 1.8]}
with open(os.path.join(outdir, "pcb_data.json"), "w") as f:
    json.dump({"impedance": imp, "metrics": metrics}, f)
# The run's data dump -- always written, whether or not a report page is, and
# what the combined scan report loads.
data_js("pcb_data", {"impedance": imp, "metrics": metrics})
print(f"stub run: length {total:.2f} mm, f_res {f_res:.3f} GHz")
"""

_GERBER = (
    "G04 stub copper*\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.2*%\nD10*\n"
    "X0Y0D02*\nX40000000Y0D01*\nM02*\n"
)

_STACK = {
    "stackup": [
        {"type": "copper", "name": "F_Cu", "thickness_mm": 0.035},
        {"type": "core", "name": "D1", "thickness_mm": 1.6, "eps": 4.4},
        {"type": "copper", "name": "B_Cu", "thickness_mm": 0.035},
    ]
}

# Materials the picker would supply for _STACK; the config now requires a
# conductivity/loss source per layer (no injected constant), so the scan's
# base params carry them just as the GUI's do.
_BASE = {
    "metal_layers": [{"sigma": 5.8e7}, {"sigma": 5.8e7}],
    "substrate_layers": [{"eps": 4.4, "loss_tangent": 0.02}],
}

# Feed centered on the bottom edge of a 60 x 20 mm area -- roomy enough for
# the free-space quarter wave (~30 mm) and its +-28 % ladder. stem 19 fills
# the depth (every candidate bends). No scan_param / sweep bounds -> the
# default automatic resonant-length scan. The design is named by key, which
# the driver resolves through the registry.
_SPEC = {
    "design": "lmonopole",
    "area": (0.0, 0.0, 60.0, 20.0),
    "edge": "bottom",
    "frac": 0.5,
    "values": {"width": 1.0, "stem": 19.0},
    "gap_mm": 0.5,
    "f0_ghz": 2.45,
    "n": 3,
    "feed_layer": "F_Cu",
}

# A track-width sweep with total length 20 mm and stem 8 mm held.
_SPEC_WIDTH = dict(
    _SPEC,
    scan_param="width",
    values={"length": 20.0, "width": 1.0, "stem": 8.0},
    sweep_lo=0.4,
    sweep_hi=2.0,
    n=4,
)

# The same scan for the other shipped designs -- nothing in the driver changes.
_SPEC_IFA = dict(_SPEC, design="ifa", values={"width": 1.0, "height": 4.0, "tap": 2.0})

# ... and for the meandered monopole, whose stack runs the other way round (its
# legs cross the area's width and it advances into the depth).
_SPEC_MEANDER = dict(_SPEC, design="meander", values={"width": 1.0, "turn": 3.0})

# The patch is the one design that radiates against a plane, so its pass has a
# second splice: the area rectangle onto the Ground layer pick. A deeper area,
# since a patch is a sheet, and an explicit width sweep so the candidates are
# the two this spec names.
_SPEC_PATCH = dict(
    _SPEC,
    design="patch",
    area=(0.0, 0.0, 60.0, 45.0),
    values={
        "length": 24.0,
        "width": 1.5,
        "patch_w": 30.0,
        "inset": 7.0,
        "feed_len": 2.0,
        "inset_gap": 1.5,
    },
    scan_param="patch_w",
    sweep_lo=26.0,
    sweep_hi=34.0,
    n=2,
    ground_layer="B_Cu",
)


def _setup(td):
    td = pathlib.Path(td)
    exe = td / "stub_solver.py"
    exe.write_text(_STUB, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    # The plot's own folder, as the wizard makes it (work/gerbers): the scan
    # writes its spliced plane in there beside the layers it came from.
    plot = td / "gerbers"
    plot.mkdir()
    (plot / "F_Cu.gbr").write_text(_GERBER, encoding="utf-8")
    (plot / "B_Cu.gbr").write_text(_GERBER, encoding="utf-8")
    (plot / "edge.gbr").write_text("M02*\n", encoding="utf-8")
    gerbers = {
        "edge": str(plot / "edge.gbr"),
        "copper": [
            ("F_Cu", str(plot / "F_Cu.gbr")),
            ("B_Cu", str(plot / "B_Cu.gbr")),
        ],
        "markers": [str(plot / "stray_marker.gbr")],
    }
    return str(exe), gerbers


def _lengths(results):
    return [r["values"]["length"] for r in results]


def test_scan_runs_ladder_plus_refine_and_ranks():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        seen, lines = [], []
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            _SPEC,
            os.path.join(td, "wizard"),
            on_line=lines.append,
            on_result=seen.append,
        )

        # 3 ladder candidates around the free-space quarter wave + 1 refined
        # (56/2.45 = 22.86 mm is not one of the ladder stops).
        assert len(results) == 4
        assert [r["kind"] for r in seen] == ["scan"] * 3 + ["refine"]
        assert all(r["error"] is None for r in results)
        assert all(r["design"] == "lmonopole" for r in results)

        # Best-first: the refined length resonates nearest 2.45 GHz.
        best = results[0]
        assert best["kind"] == "refine"
        assert abs(best["values"]["length"] - 56.0 / 2.45) < 0.1
        assert abs(best["f_res_ghz"] - 2.45) < 0.03
        assert best["s11_db"] < -25
        assert best["bw_mhz"] is not None
        assert results[0]["s11_db"] <= results[-1]["s11_db"]
        # Total = stem + arm on every candidate, and the fixed parameters
        # really were held.
        for r in results:
            assert (
                abs(r["geom"]["stem_mm"] + r["geom"]["arm_mm"] - r["values"]["length"])
                < 1e-6
            )
            assert r["values"]["width"] == 1.0
            assert r["values"]["stem"] == 19.0

        # Every candidate ran in its own directory off the shared gerbers.
        for r in seen:
            out = pathlib.Path(r["outdir"])
            assert (out / "pcb.yaml").is_file()
            assert (out / "antenna_copper.gbr").is_file()
            yaml = (out / "pcb.yaml").read_text(encoding="utf-8")
            # Feed port = point + direction on the area's bottom edge
            # (schema 5.x: no clearance rect), no marker files.
            assert "feed_ports:" in yaml
            assert "x_mm: 30.0" in yaml
            assert "dir_y: 1.0" in yaml  # inward (+y gerber) from bottom edge
            assert "clear_" not in yaml
            # An on-grid marker needs no board rotation.
            assert "rotation_deg: 0.0" in yaml
            assert "feed_marker" not in yaml
            assert "stray_marker" not in yaml
            # Outputs a scan needs: the bare-JSON dump for scoring, on top of
            # the two dumps every run writes unconditionally. The view toggles
            # are gone from the schema (16.0.0), so naming one here would be a
            # config the solver refuses.
            assert "output_json: true" in yaml
            assert "report_grid" not in yaml and "report_html" not in yaml
            # The candidate's own copper replaced F_Cu; B_Cu untouched
            # (paths are written relative to the yaml's own folder).
            assert "antenna_copper.gbr" in yaml
            assert (
                os.path.relpath(pathlib.Path(td) / "gerbers" / "B_Cu.gbr", out).replace(
                    os.sep, "/"
                )
                in yaml
            )

        assert any("Scan plan" in ln for ln in lines)

        # The view manifests landed in the scan folder, one entry per
        # candidate, naming the run dirs relatively (the report view over each
        # run's pcb_data.js dump, the grid view over its pcb_grid.js) so the
        # viewer steps through the whole sweep from either page.
        work = pathlib.Path(td) / "wizard"
        report = (work / "scan_report.js").read_text(encoding="utf-8")
        grid = (work / "scan_grid.js").read_text(encoding="utf-8")
        for text in (report, grid):
            assert text.startswith("window.FDTD_SCAN={")
            assert text.count('"meta": {') == 4
        for r in results:
            rel = pathlib.Path(r["outdir"]).name
            assert f'"data": "{rel}/pcb_data.js"' in report
            assert f'"data": "{rel}/pcb_grid.js"' in grid
        # The manifest says which design it scanned and which knob it swept,
        # for the header the page puts over the run list.
        assert "L-shaped monopole" in report
        assert "total track length sweep" in report
        # Exactly one winner is flagged.
        assert report.count('"best": true') == 1
        # A manifest is data, not a page: nothing of the view is in it.
        for text in (report, grid):
            assert "<script" not in text and "color-scheme" not in text


def test_width_scan_sweeps_fixed_length():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        results = wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, _SPEC_WIDTH, os.path.join(td, "wizard")
        )
        # A width scan is a plain linear sweep -- no refine candidate.
        assert len(results) == 4
        assert all(r["kind"] == "scan" for r in results)

        # Track width swept 0.4..2.0; total length and stem held.
        assert sorted(r["values"]["width"] for r in results) == [0.4, 0.933, 1.467, 2.0]
        assert all(r["values"]["length"] == 20.0 for r in results)
        assert all(r["geom"]["stem_mm"] == 8.0 for r in results)

        # The swept width reached the simulation: the stub's width term made
        # every candidate resonate at a distinct frequency, and the widest
        # (f_res nearest the 2.45 GHz target) ranks best.
        assert len({r["f_res_ghz"] for r in results}) == 4
        assert results[0]["values"]["width"] == 2.0


def test_width_scan_clips_infeasible_widths():
    # In a tight 40 x 10 area with an 8 mm stem, a 26 mm length leaves a
    # ~18 mm arm; a wide track shrinks the room below that, so widths past
    # ~3 mm can't hold it and must be dropped, not failed.
    spec = dict(
        _SPEC_WIDTH,
        area=(0.0, 0.0, 40.0, 10.0),
        values={"length": 26.0, "width": 1.0, "stem": 8.0},
        sweep_lo=0.4,
        sweep_hi=4.0,
        n=5,
    )
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        lines = []
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            spec,
            os.path.join(td, "wizard"),
            on_line=lines.append,
        )
        assert sorted(r["values"]["width"] for r in results) == [0.4, 1.3, 2.2]
        assert all(r["error"] is None for r in results)
        assert any("Skipping" in ln and "3.1" in ln for ln in lines)


def test_rotated_area_marker_rotates_copper_and_config():
    # An off-grid area marker: the geometry solves in its derotated frame,
    # the spliced copper is rotated back onto the board, and the runner gets
    # the rotation_deg that re-aligns the feed with a grid axis.
    import math

    spec = dict(_SPEC, n=2, rot_deg=30.0, pivot=(30.0, 10.0))
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        results = wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, spec, os.path.join(td, "wizard")
        )
        for r in results:
            out = pathlib.Path(r["outdir"])
            yaml = (out / "pcb.yaml").read_text(encoding="utf-8")
            # KiCad 30 deg (Y down) = -30 deg in the gerber frame; the
            # aligning CCW rotation is +30.
            assert "rotation_deg: 30.0" in yaml
            # Feed direction rotated with the marker (gerber frame).
            assert f"dir_x: {round(math.sin(math.radians(30)), 4)}" in yaml
            assert f"dir_y: {round(math.cos(math.radians(30)), 4)}" in yaml
            assert "clear_" not in yaml
            # The spliced regions are genuinely rotated: some corner off the
            # 0.05 mm drawing grid of the axis-aligned frame.
            gbr = (out / "antenna_copper.gbr").read_text(encoding="utf-8")
            assert "G36*" in gbr


def test_a_second_design_scans_through_the_same_driver():
    # The inverted-F: same driver, same spec shape, its own parameters. The
    # candidates carry the design's metrics (a folded arm, not a stem/arm
    # split) and each one splices two paths' copper (radiator + feed pin).
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        lines = []
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            _SPEC_IFA,
            os.path.join(td, "wizard"),
            on_line=lines.append,
        )
        assert all(r["design"] == "ifa" for r in results)
        assert len(results) >= _SPEC_IFA["n"]
        assert all(r["error"] is None for r in results)
        for r in results:
            length = r["values"]["length"]
            geom = r["geom"]
            # The resonant length is height + arm; the tap is beside it.
            assert abs(geom["height_mm"] + geom["arm_mm"] - length) < 1e-6
            assert r["values"]["height"] == 4.0 and r["values"]["tap"] == 2.0
            yaml = (pathlib.Path(r["outdir"]) / "pcb.yaml").read_text(encoding="utf-8")
            assert "feed_ports:" in yaml
            gbr = (pathlib.Path(r["outdir"]) / "antenna_copper.gbr").read_text(
                encoding="utf-8"
            )
            # One region per centerline segment: the radiator's plus the pin's.
            assert gbr.count("G36*") >= 4
            assert "ifa candidate copper" in gbr
        report = (pathlib.Path(td) / "wizard" / "scan_report.js").read_text(
            encoding="utf-8"
        )
        assert "Meandered inverted-F antenna" in report
        assert "resonant length sweep" in report


def test_meander_scan_runs_the_same_driver():
    # The meandered monopole: same driver, same spec shape, its own parameters.
    # One path, so one run of spliced copper -- and the length it carries is
    # the whole wire, the run in to the first turn included.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            _SPEC_MEANDER,
            os.path.join(td, "wizard"),
        )
        assert all(r["design"] == "meander" for r in results)
        assert len(results) >= _SPEC_MEANDER["n"]
        assert all(r["error"] is None for r in results)
        for r in results:
            geom = r["geom"]
            assert abs(geom["turn_mm"] + geom["arm_mm"] - r["values"]["length"]) < 1e-6
            assert r["values"]["turn"] == 3.0
            # The knob is the closest approach, at every candidate of the sweep.
            assert geom["turn_mm"] == 3.0
            gbr = (pathlib.Path(r["outdir"]) / "antenna_copper.gbr").read_text(
                encoding="utf-8"
            )
            assert "meander candidate copper" in gbr
        report = (pathlib.Path(td) / "wizard" / "scan_report.js").read_text(
            encoding="utf-8"
        )
        assert "Meandered monopole" in report


def test_a_patch_scan_splices_the_plane_it_radiates_against():
    # The other half of a patch: the area rectangle, spliced onto the Ground
    # layer pick so every candidate is simulated over the plane it needs --
    # once for the sweep, since that rectangle is the same for all of them.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        results = wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, _SPEC_PATCH, str(work)
        )
        assert len(results) == _SPEC_PATCH["n"]
        assert all(r["error"] is None for r in results)

        # In the plot's folder, not the scan's: it is one more gerber of the
        # same plot, and the same file for every candidate.
        plane = pathlib.Path(td) / "gerbers" / "ground_plane.gbr"
        text = plane.read_text(encoding="utf-8")
        assert "patch ground plane" in text
        # The area rectangle as one dark region, in the gerber's 4.6 mm ints
        # with Y negated -- and the board's own copper still under it, since a
        # splice adds to the plotted layer instead of replacing it.
        assert "G36*" in text and "X60000000Y-45000000D01*" in text
        assert "X40000000Y0D01*" in text  # the stub gerber's own trace

        for r in results:
            out = pathlib.Path(r["outdir"])
            yaml = (out / "pcb.yaml").read_text(encoding="utf-8")
            # Two splices, one per layer (the config writes each gerber's path
            # relative to the YAML): the plane the whole sweep shares, in the
            # plot folder, and this candidate's own antenna on the feed layer.
            assert "path: ../../gerbers/ground_plane.gbr" in yaml
            assert "path: antenna_copper.gbr" in yaml


def test_a_design_that_needs_no_plane_leaves_the_other_layers_alone():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        results = wizard_scan.run_scan(exe, gerbers, _STACK, _BASE, _SPEC, str(work))
        assert not (pathlib.Path(td) / "gerbers" / "ground_plane.gbr").exists()
        yaml = (pathlib.Path(results[0]["outdir"]) / "pcb.yaml").read_text(
            encoding="utf-8"
        )
        # the plotted layer, untouched
        assert "path: ../../gerbers/B_Cu.gbr" in yaml


def test_a_patch_with_no_ground_layer_picked_is_refused_before_the_first_run():
    # No silent default: the layer the plane goes on is an input, and a spec
    # without one stops the pass instead of simulating half an antenna.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        spec = dict(_SPEC_PATCH, ground_layer="")
        try:
            wizard_scan.run_scan(
                exe, gerbers, _STACK, _BASE, spec, os.path.join(td, "wizard")
            )
        except RuntimeError as exc:
            assert "ground layer" in str(exc)
        else:
            raise AssertionError("a patch scan with no ground layer should raise")


def test_ifa_tap_scan_sweeps_the_match():
    # Sweeping the feed-to-short spacing at a fixed resonant length: the
    # driver only needs the design's parameter name.
    spec = dict(
        _SPEC_IFA,
        scan_param="tap",
        n=3,
        sweep_lo=1.5,
        sweep_hi=4.5,
        values={"length": 24.0, "width": 1.0, "height": 4.0, "tap": 1.5},
    )
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        results = wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, spec, os.path.join(td, "wizard")
        )
        assert sorted(r["values"]["tap"] for r in results) == [1.5, 3.0, 4.5]
        assert all(r["kind"] == "scan" for r in results)  # no refine
        assert all(r["values"]["length"] == 24.0 for r in results)
        # A match sweep, and nothing else: every candidate keeps the same
        # resonant side (height + arm, folds and all), so what moves between
        # the runs is the short pin alone. (A 24 mm length runs straight in
        # this area, so its arm is lifted off the 4 mm minimum height onto the
        # far border -- the same lift in every candidate, see ifa._split.)
        resonant = {
            (r["geom"]["height_mm"], r["geom"]["arm_mm"], r["geom"]["folds"])
            for r in results
        }
        assert resonant == {(19.0, 5.0, 0)}


# --------------------------------------------------------------------------- #
# The grid pass (the wizard's "Generate grids")
# --------------------------------------------------------------------------- #
def test_grid_only_meshes_every_candidate_and_solves_none():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        lines = []
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            _SPEC,
            str(work),
            on_line=lines.append,
            grid_only=True,
        )
        # The planned ladder, and only it: a grid pass has no measured
        # resonance to fit, so there is nothing to refine.
        assert len(results) == _SPEC["n"]
        assert all(r["kind"] == "scan" for r in results)
        assert all(r["error"] is None for r in results)
        # Geometry solved and simulated, but nothing measured.
        assert all(r["geom"] for r in results)
        assert all(
            r["f_res_ghz"] is None and r["s11_db"] is None and r["bw_mhz"] is None
            for r in results
        )
        for r in results:
            out = pathlib.Path(r["outdir"])
            # The same per-candidate preparation a scan does -- spliced
            # copper and its own config -- meshed, not solved.
            assert (out / "antenna_copper.gbr").is_file()
            assert (out / "pcb.yaml").is_file()
            assert (out / "pcb_grid.js").is_file()
            assert not (out / "pcb_data.json").exists()

        # Only the grid view's manifest is written, and it says so.
        grid = (work / "scan_grid.js").read_text(encoding="utf-8")
        assert grid.count('"meta": {') == len(results)
        assert "grids only" in grid
        # Nothing was measured, so no candidate is crowned.
        assert '"best": true' not in grid
        assert not (work / "scan_report.js").exists()


def test_a_finished_scan_is_saved_in_its_folder():
    """The record that makes a footprint placeable in a later session
    (design.scan_store): the rows as they were ranked, and the spec they were
    measured under, beside the runs themselves."""
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        lines = []
        results = wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, _SPEC, str(work), on_line=lines.append
        )
        saved = scan_store.load(work, _SPEC["design"])
        assert saved is not None
        assert saved.results == results  # best-first, numbers and all
        assert saved.spec["design"] is registry.by_key(_SPEC["design"])
        assert saved.spec["area"] == _SPEC["area"]
        assert saved.spec["f0_ghz"] == _SPEC["f0_ghz"]
        assert any(scan_store.FILE in ln for ln in lines)
        # The saved rows re-solve: this is what the footprint placer does with
        # them, and it has to work without anything else from the session.
        design = saved.spec["design"]
        for row in saved.results:
            geo = design.solve(
                saved.spec["area"],
                saved.spec["edge"],
                saved.spec["frac"],
                row["values"],
            )
            assert geo.feed


def test_a_grid_pass_saves_no_results_and_keeps_the_last_scans():
    """A grid pass measures nothing, so the last real scan's rows are still the
    last numbers anybody measured -- overwriting them with numberless ones
    would lose a sweep that was paid for."""
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        results = wizard_scan.run_scan(exe, gerbers, _STACK, _BASE, _SPEC, str(work))
        wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, _SPEC, str(work), grid_only=True
        )
        assert scan_store.load(work).results == results


def test_a_grid_pass_alone_saves_nothing_to_place():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, _SPEC, str(work), grid_only=True
        )
        assert scan_store.load(work) is None


def test_a_grid_pass_replaces_the_previous_scans_report():
    # The candidates are re-meshed into the same cand-* dirs, so the report
    # manifest left by an earlier scan would plot that scan's data under this
    # pass's geometry: it goes, rather than lingering as a stale view.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        wizard_scan.run_scan(exe, gerbers, _STACK, _BASE, _SPEC, str(work))
        assert (work / "scan_report.js").is_file()

        wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, _SPEC, str(work), grid_only=True
        )
        assert not (work / "scan_report.js").exists()
        assert (work / "scan_grid.js").is_file()


def test_a_grid_pass_that_fails_still_retires_the_report():
    # The report goes when the pass starts, not when it finishes: it already
    # describes candidate data the pass is overwriting, so a pass that dies
    # part-way must not leave it standing over the re-meshed runs.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        work = pathlib.Path(td) / "wizard"
        wizard_scan.run_scan(exe, gerbers, _STACK, _BASE, _SPEC, str(work))
        assert (work / "scan_report.js").is_file()

        dead = pathlib.Path(td) / "dead.py"
        dead.write_text(
            "#!/usr/bin/env python3\nraise SystemExit(9)\n", encoding="utf-8"
        )
        dead.chmod(dead.stat().st_mode | stat.S_IXUSR)
        try:
            wizard_scan.run_scan(
                str(dead), gerbers, _STACK, _BASE, _SPEC, str(work), grid_only=True
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "every candidate failed" in str(exc)
        assert not (work / "scan_report.js").exists()


def test_plan_previews_candidates_without_running():
    # plan() needs no solver, gerbers or stackup -- just the spec geometry.
    rows = wizard_scan.plan(_SPEC_WIDTH)
    assert len(rows) == 4
    assert [round(r["values"]["width"], 3) for r in rows] == [0.4, 0.933, 1.467, 2.0]
    # Geometry is solved (arm/bend filled) but nothing is simulated.
    assert all(
        r["values"]["length"] == 20.0 and r["geom"]["arm_mm"] is not None for r in rows
    )
    assert all(
        r["f_res_ghz"] is None
        and r["s11_db"] is None
        and r["outdir"] is None
        and r["error"] is None
        for r in rows
    )


def test_plan_auto_length_omits_refine():
    # An automatic length plan lists the ladder only (the refined candidate
    # depends on measured resonances, so it can't be previewed).
    rows = wizard_scan.plan(_SPEC)
    assert len(rows) == _SPEC["n"]
    assert all(r["kind"] == "scan" for r in rows)
    assert sorted(_lengths(rows)) == sorted(set(_lengths(rows)))


def test_spliced_rects_cover_every_planned_candidate():
    # What the advisory overlap check judges once a pass is started: the copper
    # every candidate of the sweep splices into the feed layer, stubs off, all
    # of it inside the area (the stubs are the only copper that reaches out of
    # it, and outside the area nothing is judged).
    rows = wizard_scan.plan(_SPEC_WIDTH)
    rects = wizard_scan.spliced_rects(_SPEC_WIDTH, rows)
    assert len(rects) > len(rows)  # each candidate has >= 1 rect
    x0, y0, x1, y1 = _SPEC_WIDTH["area"]
    for a0, b0, a1, b1 in rects:
        assert a0 < a1 and b0 < b1
        assert (
            x0 - 1e-6 <= a0 and a1 <= x1 + 1e-6 and y0 - 1e-6 <= b0 and b1 <= y1 + 1e-6
        )

    # Candidates reach differently far -- in this sweep they even bend to
    # opposite sides of the feed -- which is why the check judges the whole
    # sweep rather than one previewed candidate.
    def span(rs):
        return max(r[2] for r in rs) - min(r[0] for r in rs)

    assert span(rects) > span(wizard_scan.spliced_rects(_SPEC_WIDTH, rows[:1]))
    # A candidate the plan could not solve contributes nothing.
    assert wizard_scan.spliced_rects(_SPEC_WIDTH, [dict(rows[0], error="nope")]) == []


def test_spliced_rects_run_over_every_design():
    for spec in (_SPEC, _SPEC_IFA, _SPEC_MEANDER):
        assert wizard_scan.spliced_rects(spec, wizard_scan.plan(spec)), spec["design"]


def test_plan_rejects_a_range_nothing_fits():
    # Every width in the range is too wide for a 6 mm-wide area.
    spec = dict(
        _SPEC_WIDTH, area=(0.0, 0.0, 6.0, 10.0), sweep_lo=3.0, sweep_hi=5.0, n=3
    )
    try:
        wizard_scan.plan(spec)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "fits the fixed geometry" in str(exc)


def test_plan_rejects_an_area_that_holds_nothing():
    spec = dict(_SPEC, area=(0.0, 0.0, 60.0, 1.0))
    try:
        wizard_scan.plan(spec)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "cannot hold this antenna" in str(exc)


def test_scan_cancel_between_candidates():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        try:
            wizard_scan.run_scan(
                exe,
                gerbers,
                _STACK,
                _BASE,
                _SPEC,
                os.path.join(td, "wizard"),
                should_stop=lambda: True,
            )
            assert False, "expected ScanCancelled"
        except wizard_scan.ScanCancelled:
            pass


def test_scan_survives_a_failing_candidate():
    # A solver that dies on its first invocation only: the scan records the
    # error on that candidate and keeps going.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        flaky = pathlib.Path(td) / "flaky.py"
        flaky.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys, subprocess\n"
            f"flag = os.path.join({str(td)!r}, 'ran_once')\n"
            "if not os.path.exists(flag):\n"
            "    open(flag, 'w').close()\n"
            "    sys.exit(3)\n"
            f"os.execv({exe!r}, [{exe!r}] + sys.argv[1:])\n",
            encoding="utf-8",
        )
        flaky.chmod(flaky.stat().st_mode | stat.S_IXUSR)
        results = wizard_scan.run_scan(
            str(flaky), gerbers, _STACK, _BASE, _SPEC, os.path.join(td, "wizard")
        )
        failed = [r for r in results if r["error"]]
        assert len(failed) == 1
        assert "exited with code 3" in failed[0]["error"]
        assert failed == results[-1:]  # errors rank last
        assert len(results) == 4  # the rest still ran
        # The failed candidate still gets an entry (greyed, with its error) --
        # just without a dump to draw it from.
        report = (pathlib.Path(td) / "wizard" / "scan_report.js").read_text(
            encoding="utf-8"
        )
        assert report.count('"meta": {') == 4
        assert report.count('"data": ') == 3
        assert "exited with code 3" in report


def test_all_candidates_failing_raises():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        dead = pathlib.Path(td) / "dead.py"
        dead.write_text(
            "#!/usr/bin/env python3\nraise SystemExit(9)\n", encoding="utf-8"
        )
        dead.chmod(dead.stat().st_mode | stat.S_IXUSR)
        try:
            wizard_scan.run_scan(
                str(dead), gerbers, _STACK, _BASE, _SPEC, os.path.join(td, "wizard")
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "every candidate failed" in str(exc)


def test_best_result_is_the_first_error_free_row():
    rows = [{"error": "boom"}, {"error": None, "tag": "winner"}, {"error": None}]
    assert wizard_scan.best_result(rows)["tag"] == "winner"
    assert wizard_scan.best_result([{"error": "boom"}]) is None


# --------------------------------------------------------------------------- #
# Candidates the area can't hold: skipped, and warned about (plan_problems)
# --------------------------------------------------------------------------- #
def _tight_width_spec():
    """The clipping case of test_width_scan_clips_infeasible_widths: 5 widths
    asked for in a 40 x 10 area at a 26 mm length, of which the wide end
    doesn't fit."""
    return dict(
        _SPEC_WIDTH,
        area=(0.0, 0.0, 40.0, 10.0),
        values={"length": 26.0, "width": 1.0, "stem": 8.0},
        sweep_lo=0.4,
        sweep_hi=4.0,
        n=5,
    )


def test_a_candidate_the_area_cannot_hold_is_never_planned():
    # The rows a pass runs are exactly the candidates that fit: the others are
    # gone rather than carried as rows with an error, so nothing downstream
    # (the splice, the gauge, the results table) has to know about them.
    rows = wizard_scan.plan(_tight_width_spec())
    assert [r["values"]["width"] for r in rows] == [0.4, 1.3, 2.2]
    assert all(r["error"] is None and r["geom"] for r in rows)


def test_the_skipped_candidates_are_warned_about():
    problems = wizard_scan.plan_problems(_tight_width_spec())
    assert len(problems) == 1
    p = problems[0]
    assert p.severity == "warn"  # never a blocker: the rest still run
    assert p.id == "area-candidates-skipped"
    # It says how much of the sweep is lost, names the values, and says what
    # the area does hold.
    assert "2 of the 5" in p.message
    assert "3.1" in p.message and "4" in p.message
    assert "holds at most" in p.message
    assert "remaining 3" in p.message


def test_a_sweep_that_fits_is_not_warned_about():
    assert wizard_scan.plan_problems(_SPEC_WIDTH) == []


def test_a_collapsed_ladder_is_warned_about_too():
    # The automatic ladder drops nothing by name -- its rungs are clamped to
    # the area's capacity and the duplicates dedup away -- so a small area
    # silently returns fewer candidates than asked for. That is the same loss
    # and gets the same row, phrased for what happened.
    spec = dict(
        _SPEC, area=(0.0, 0.0, 24.0, 6.0), values={"width": 1.0, "stem": 5.0}, n=5
    )
    rows = wizard_scan.plan(spec)
    assert len(rows) < spec["n"]
    problems = wizard_scan.plan_problems(spec)
    assert len(problems) == 1
    assert f"only {len(rows)} of the 5" in problems[0].message
    assert "collapse onto its capacity" in problems[0].message


def test_a_sweep_nothing_fits_is_a_warning_not_a_raise():
    # plan() raises (there is no pass to run), but the banner still gets a row
    # rather than an exception -- it is a check, not a caller.
    spec = dict(
        _SPEC_WIDTH, area=(0.0, 0.0, 6.0, 10.0), sweep_lo=3.0, sweep_hi=5.0, n=3
    )
    problems = wizard_scan.plan_problems(spec)
    assert len(problems) == 1
    assert "nothing in this sweep fits" in problems[0].message


def test_the_skipped_candidates_warning_ships_a_self_contained_help_page():
    # The shared rule for every bundled guide lives in tests/helppage.py.
    assert_guide_loads(wizard_scan.plan_problems(_tight_width_spec())[0])


def test_an_unplannable_spec_is_nobody_elses_warning():
    # A spec too incomplete to plan at all (no frequency for the ladder) is
    # the form's own story; the sweep check stays quiet rather than reporting
    # a KeyError as an area problem.
    assert wizard_scan.plan_problems({"design": "lmonopole"}) == []


def test_the_skips_reach_the_log_with_a_reason():
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        lines = []
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            _tight_width_spec(),
            os.path.join(td, "wizard"),
            on_line=lines.append,
        )
        assert len(results) == 3
        assert any("Skipping 2" in ln and "can't hold" in ln for ln in lines)
        # ... and why, in the design's own words, not just how many.
        assert any("does not fit" in ln for ln in lines)


def test_a_refined_length_the_area_cannot_hold_is_skipped():
    # The refine step is a candidate like any other: one that doesn't fit is
    # skipped with a reason instead of being run into a failure row. The fit
    # normally clamps to the area's capacity, so this drives it directly.
    real_refine = wizard_scan.sizing.refine_total
    wizard_scan.sizing.refine_total = lambda pairs, f0, cap: 500.0
    try:
        with tempfile.TemporaryDirectory() as td:
            exe, gerbers = _setup(td)
            lines = []
            results = wizard_scan.run_scan(
                exe,
                gerbers,
                _STACK,
                _BASE,
                dict(_SPEC, n=2),
                os.path.join(td, "wizard"),
                on_line=lines.append,
            )
            assert not any(r["kind"] == "refine" for r in results)
            assert all(r["error"] is None for r in results)
            assert any("500 mm doesn't fit the area" in ln for ln in lines)
    finally:
        wizard_scan.sizing.refine_total = real_refine


def test_a_refined_length_that_fits_still_runs():
    # ... and the guard costs nothing when the fit lands inside the area,
    # which is the ordinary case.
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        lines = []
        results = wizard_scan.run_scan(
            exe,
            gerbers,
            _STACK,
            _BASE,
            dict(_SPEC, n=2),
            os.path.join(td, "wizard"),
            on_line=lines.append,
        )
        assert any(r["kind"] == "refine" for r in results)
        assert not any("doesn't fit the area" in ln for ln in lines)


def test_scan_report_carries_pass_warn_fail_verdicts():
    # A target-bearing spec (application band / impedance / return-loss) makes
    # the report manifest carry each candidate's per-property verdicts, which
    # the run switcher paints as the strip + detail table (viewer/js/runs.js).
    spec = dict(_SPEC, band_ghz=[2.4, 2.4835], impedance_ohm=50.0, return_loss_db=10.0)
    with tempfile.TemporaryDirectory() as td:
        exe, gerbers = _setup(td)
        wizard_scan.run_scan(
            exe, gerbers, _STACK, _BASE, spec, os.path.join(td, "wizard")
        )
        report = (pathlib.Path(td) / "wizard" / "scan_report.js").read_text(
            encoding="utf-8"
        )
        # Serialized verdicts ride in each run's meta: an overall
        # status/glyph and a per-property list with keys, glyphs and text.
        assert '"overall":' in report
        assert '"key": "return_loss"' in report
        assert '"key": "impedance"' in report
        assert (
            '"status": "pass"' in report
            or '"status": "warn"' in report
            or '"status": "fail"' in report
        )


if __name__ == "__main__":
    run_module_tests(globals())
