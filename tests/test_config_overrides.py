"""Unit tests for antenna_plugin.sim.config (pure, no KiCad).

Covers the per-layer material overrides: the metal conductivity has no scalar
fallback (a copper foil with no metal pick blocks the run), while a dielectric
keeps its board-read eps + loss_tangent unless a picked substrate overrides
them -- and only a dielectric with no loss tangent from either source blocks.
Also the written YAML itself: the point + direction feed port, the 0 = auto
mesh/run defaults and the one output key there still is (output_json). Loaded
through the bare package (which stands in for the real ``__init__``, that one
imports pcbnew) rather than by path: the writer imports a sibling of its own
for the cell/ceiling rules, so it needs its place in the package.
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load  # noqa: E402

config = load("config")
core_config = load("emkit.config")


def _stack():
    # F_Cu / core / B_Cu, as collect_stackup produces it: no metal sigma (that
    # comes from the Materials picks), but the core carries the board-read eps
    # and loss_tangent (KiCad's Physical Stackup has both).
    return [
        {"type": "copper", "name": "F_Cu", "thickness_mm": 0.035},
        {
            "type": "core",
            "name": "D1",
            "thickness_mm": 1.6,
            "eps": 4.4,
            "loss_tangent": 0.02,
        },
        {"type": "copper", "name": "B_Cu", "thickness_mm": 0.035},
    ]


# Materials the picker emits for the two-copper/one-core stack; metals are the
# required conductivity source, substrates optionally override the board loss.
_MATERIALS = {
    "metal_layers": [{"sigma": 5.8e7}, {"sigma": 5.8e7}],
    "substrate_layers": [{"eps": 4.4, "loss_tangent": 0.02}],
}


def test_per_layer_metal_and_substrate_win():
    p = {
        "metal_layers": [{"sigma": 3.77e7}, {"sigma": 6.3e7}],
        "substrate_layers": [{"eps": 2.2, "loss_tangent": 0.001}],
    }
    out = core_config._apply_overrides(_stack(), p)
    assert out[0]["sigma"] == 3.77e7  # F_Cu -> aluminium
    assert out[2]["sigma"] == 6.3e7  # B_Cu -> silver
    assert out[1]["eps"] == 2.2 and out[1]["loss_tangent"] == 0.001


def test_board_default_substrate_uses_board_loss():
    # "From board stackup" keeps the board's eps and loss_tangent -- no material
    # needed, no block, no invented number.
    p = {
        "metal_layers": [{"sigma": 5.8e7}, {"sigma": 5.8e7}],
        "substrate_layers": [None],
    }
    out = core_config._apply_overrides(_stack(), p)
    assert out[1]["eps"] == 4.4 and out[1]["loss_tangent"] == 0.02


def test_board_default_substrate_without_board_loss_blocks():
    # If the board gave no loss tangent and no material is picked, the loss has
    # no source at all, so the run blocks with a message naming the dielectric.
    stack = _stack()
    del stack[1]["loss_tangent"]
    p = {
        "metal_layers": [{"sigma": 5.8e7}, {"sigma": 5.8e7}],
        "substrate_layers": [None],
    }
    try:
        core_config._apply_overrides(stack, p)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "D1" in str(exc) and "loss tangent" in str(exc)


def test_missing_materials_block():
    # No metal_layers/substrate_layers (material UI absent): the first copper
    # foil has no conductivity source, so the run blocks rather than defaulting.
    try:
        core_config._apply_overrides(_stack(), {})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "F_Cu" in str(exc) and "metal" in str(exc)


def test_short_metal_list_blocks_uncovered_layer():
    # Fewer picks than copper layers (e.g. a stale dialog): the uncovered layer
    # has no source and blocks -- never a silent fallback.
    p = {"metal_layers": [{"sigma": 3.77e7}], "substrate_layers": [None]}
    try:
        core_config._apply_overrides(_stack(), p)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "B_Cu" in str(exc)


def _write(params, stack=None, overlays=()):
    # Seed the required material picks; individual tests add feed/overrides.
    # ``overlays`` names the overlay gerber roles plot_gerbers resolved for
    # this board (e.g. "paste_top"); each gets a path in the temp folder.
    merged = dict(_MATERIALS)
    merged.update(params)
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        gerbers = {
            "edge": str(td / "edge.gbr"),
            "copper": [("F_Cu", str(td / "F_Cu.gbr"))],
        }
        gerbers.update({role: str(td / f"{role}.gbr") for role in overlays})
        config.write_yaml(
            gerbers, {"stackup": stack or _stack()}, merged, str(td / "pcb.yaml")
        )
        return (td / "pcb.yaml").read_text(encoding="utf-8")


def _entries(text):
    """The emitted stackup as [entry text, ...], one per `- type:` block."""
    body = text[text.index("stackup:") : text.index("# --- copper model")]
    return ["- type:" + e for e in body.split("- type:")[1:]]


_FEED = {"x": 30.0, "y": -38.0, "dir_x": 0.0, "dir_y": 1.0}


def test_yaml_feed_port_is_point_plus_direction():
    text = _write({"feed": dict(_FEED)})
    assert text.startswith(f"config_version: {config.CONFIG_VERSION}\n")
    assert config.CONFIG_VERSION.split(".")[0] == "20"
    body = text[text.index("feed_ports:") :]
    # A port is a point plus a direction and nothing else -- no clearance rect.
    assert "  - x_mm: 30.0" in body
    assert "y_mm: -38.0" in body and "layer: F_Cu" in body
    assert "dir_x: 0.0" in body and "dir_y: 1.0" in body
    assert "clear_" not in text
    assert "gap_mm" not in text and "margin_mm: 0.0" in text  # air margin only


def _paste_stack():
    # What collect_stackup reads off a board with its paste layers enabled:
    # name-only overlays outside the foils, in board order.
    return (
        [{"type": "paste", "name": "F_Paste"}]
        + _stack()
        + [{"type": "paste", "name": "B_Paste"}]
    )


def test_yaml_paste_entries_carry_their_gerber():
    # The ground check identifies pads from the solder paste, so each paste
    # layer rides on its own stackup entry with its gerber, matched to the side
    # by its F./B. name. KiCad plots paste positive (the drawn apertures ARE
    # the pads), so no is_negative.
    text = _write(
        {"feed": dict(_FEED)},
        stack=_paste_stack(),
        overlays=("paste_top", "paste_bottom"),
    )
    entries = _entries(text)
    paste = [e for e in entries if e.startswith("- type: paste")]
    assert len(paste) == 2
    assert "paste_top.gbr" in paste[0] and "name: F_Paste" in paste[0]
    assert "paste_bottom.gbr" in paste[1] and "name: B_Paste" in paste[1]
    # Top paste before the first copper foil, bottom after the last: that
    # position is what tells the runner which side each overlay is on.
    assert entries[0] is paste[0] and entries[-1] is paste[1]
    # Not drawn in the grid (the apertures sit on the copper cells they mark),
    # and never meshed: no thickness/eps/material on an overlay.
    assert all("show_in_grid: false" in e for e in paste)
    assert all("thickness_mm" not in e and "eps" not in e for e in paste)
    assert "is_negative" not in text
    # And no coating: this run did not ask for the mask (include_mask), so the
    # board it solves ends at the copper.
    assert "- type: mask" not in text


def test_yaml_overlay_without_a_gerber_is_omitted():
    # Silk is not plotted (simulate._PLOT_SILK), and a board may have no paste
    # layer at all: an overlay entry with no gerber says nothing to the runner,
    # so it is left out rather than emitted empty. The foils stay put.
    stack = [{"type": "silk", "name": "F_SilkS"}] + _paste_stack()
    text = _write({"feed": dict(_FEED)}, stack=stack, overlays=("paste_top",))
    types = [e.split("\n")[0] for e in _entries(text)]
    assert types == [
        "- type: paste",
        "- type: copper",
        "- type: core",
        "- type: copper",
    ]


def test_yaml_core_carries_loss_tangent():
    # The dielectric loss rides through as loss_tangent, not as a derived
    # conductivity: the core entry has loss_tangent and no sigma.
    text = _write({"feed": dict(_FEED)})
    stackup = text[text.index("stackup:") : text.index("# --- copper model")]
    core = stackup[stackup.index("type: core") :]
    core = core[: core.index("- type") if "- type" in core else len(core)]
    assert "loss_tangent: 0.02" in core
    assert "sigma:" not in core


def test_yaml_defaults_are_auto_zeros():
    text = _write({"feed": dict(_FEED)})
    for key in (
        "time_ns",
        "flow_ghz",
        "fmax_ghz",
        "cell_mm",
        "margin_mm",
        "mesh_ratio",
        "substrate_cell_mm",
        "feature_min_cell_mm",
        "via_min_cell_mm",
        "air_cell_mm",
    ):
        assert f"{key}: 0.0" in text, key
    assert "pml_cells: 0" in text
    assert "rotation_deg: 0.0" in text
    assert "threads: 0" in text


def test_yaml_new_knobs_default_to_auto_zeros():
    # All three knobs added over 9.2.0..9.5.0 have a runner-side auto at 0 (a
    # fraction of RAM for the budget, a disk derived from the port for the
    # radius, min(0.1 mm, fed trace / 2) for the connectivity raster since
    # 9.5.0), so the writer spells the 0 out like every other auto.
    text = _write({"feed": dict(_FEED)})
    assert "mesh_budget_gb: 0.0" in text
    assert "auto_ground_radius_mm: 0.0" in text
    assert "min_raster_mm: 0.0" in text


def test_yaml_cell_ceiling_defaults_to_none_and_writes_as_typed():
    # 17.1.0's ceiling on the base cell: 0 = none, spelled out like every other
    # auto, and a typed one emitted beside the cell it bounds.
    assert "cell_max_mm: 0.0" in _write({"feed": dict(_FEED)})
    text = _write({"feed": dict(_FEED), "cell_mm": 0.2, "cell_max_mm": 0.5})
    assert "cell_mm: 0.2" in text and "cell_max_mm: 0.5" in text


def test_yaml_empty_cell_range_raises():
    # A run asked to start above its own ceiling: no cell satisfies both keys,
    # so neither can be the one that wins (the runner's CFG-042). Refused here,
    # naming both keys, rather than after a run has been prepared.
    try:
        _write({"feed": dict(_FEED), "cell_mm": 0.4, "cell_max_mm": 0.2})
        assert False, "expected RuntimeError for a start above the ceiling"
    except RuntimeError as exc:
        assert "cell_mm" in str(exc) and "cell_max_mm" in str(exc)
    # Equal is a range of one cell, not an empty one.
    assert "cell_max_mm: 0.2" in _write(
        {"feed": dict(_FEED), "cell_mm": 0.2, "cell_max_mm": 0.2}
    )


def test_yaml_feature_floor_above_the_ceiling_raises():
    # An explicit floor coarser than the ceiling can never bind on any lattice
    # the config permits (CFG-043) -- a knob that silently does nothing. The
    # automatic floors derive from the cell and follow the ceiling for free, so
    # only a typed one is checked.
    for key in ("feature_min_cell_mm", "via_min_cell_mm"):
        try:
            _write({"feed": dict(_FEED), "cell_max_mm": 0.2, key: 0.3})
            assert False, f"expected RuntimeError for {key} above the ceiling"
        except RuntimeError as exc:
            assert key in str(exc) and "cell_max_mm" in str(exc)
    assert "cell_max_mm: 0.2" in _write({"feed": dict(_FEED), "cell_max_mm": 0.2})


def test_yaml_min_raster_override():
    # Pinned finer than the auto would derive: written as typed.
    text = _write({"feed": dict(_FEED), "min_raster_mm": 0.02})
    assert "min_raster_mm: 0.02" in text


def test_yaml_new_knob_overrides():
    text = _write(
        {"feed": dict(_FEED), "mesh_budget_gb": 24.0, "auto_ground_radius_mm": 3.5}
    )
    assert "mesh_budget_gb: 24.0" in text
    assert "auto_ground_radius_mm: 3.5" in text


def test_yaml_negative_auto_knob_raises():
    # A negative is a typo, and the runner's reaction to one is uneven (config
    # error / silent auto), so it blocks here naming the field.
    for key in ("min_raster_mm", "mesh_budget_gb", "auto_ground_radius_mm"):
        try:
            _write({"feed": dict(_FEED), key: -1.0})
            assert False, f"expected RuntimeError for {key}"
        except RuntimeError as exc:
            assert key in str(exc) and "negative" in str(exc)


def test_yaml_outputs_are_the_json_flag_alone():
    # A run writes data and nothing else, and always writes both dumps, so
    # output_json is the only output key left. Since 16.0.0 the view toggles
    # are not merely default-on but gone -- naming one is an error the solver
    # would refuse -- and neither they nor the per-quantity report_* keys of
    # older schemas may reappear.
    text = _write({"feed": dict(_FEED)})
    assert "output_json: false" in text
    assert "data_format" not in text
    for gone in (
        "report_grid",
        "report_html",
        "report_summary",
        "report_patterns",
        "report_port_time",
        "report_impedance",
        "report_return_loss",
        "report_vswr",
        "report_css",
    ):
        assert gone not in text, gone


def test_yaml_scan_output_overrides():
    # The wizard scan asks for the bare-JSON dump (output_json) on top of the
    # two dumps every run writes.
    text = _write({"feed": dict(_FEED), "output_json": True})
    assert "output_json: true" in text


def test_yaml_user_values_override_the_autos():
    text = _write(
        {"feed": dict(_FEED), "cell_mm": 0.35, "pml_cells": 12, "rotation_deg": 30.0}
    )
    assert "cell_mm: 0.35" in text
    assert "pml_cells: 12" in text
    assert "rotation_deg: 30.0" in text


def test_yaml_copper_cells_default():
    # 2 cells across the driven copper unless the speed slider's fastest stop
    # (or a hand-typed override) drops it to 1.
    text = _write({"feed": dict(_FEED)})
    assert "copper_cells: 2" in text


def test_yaml_copper_cells_override():
    text = _write({"feed": dict(_FEED), "copper_cells": 1})
    assert "copper_cells: 1" in text


def test_yaml_never_writes_the_renamed_trace_cells():
    # What N divides is an eroded bottleneck, not a chord at the marker, and
    # the knob is named copper_cells for it; the runner REFUSES the older
    # trace_cells (CFG-037) rather than reinterpreting it, so that name must
    # not survive anywhere in the emitted config -- not even from a stale
    # params dict.
    text = _write({"feed": dict(_FEED), "trace_cells": 1})
    assert "trace_cells" not in text
    assert "copper_cells: 2" in text


def test_yaml_feed_snap_to_center_default_on():
    # Spelled out rather than left to the runner's default: a marker names the
    # line to drive, so the point is centered on the copper it drives.
    text = _write({"feed": dict(_FEED)})
    assert "feed_snap_to_center: true" in text


def test_yaml_feed_snap_to_center_off():
    text = _write({"feed": dict(_FEED), "feed_snap_to_center": False})
    assert "feed_snap_to_center: false" in text


def test_yaml_mesh_fit_cell_default_on():
    # The runner's default, spelled out (17.0.0): a lattice over the memory
    # budget is re-resolved at the finest cell that fits rather than refused.
    text = _write({"feed": dict(_FEED)})
    assert "mesh_fit_cell: true" in text


def test_yaml_mesh_fit_cell_off():
    # The Advanced pane's checkbox cleared: back to the refusal, for a run
    # whose mesh must be the one asked for or nothing.
    text = _write({"feed": dict(_FEED), "mesh_fit_cell": False})
    assert "mesh_fit_cell: false" in text


def test_yaml_mesh_fit_cell_is_written_whatever_the_budget():
    # It is a separate key from mesh_budget_gb, not a spelling of one: the
    # budget says how much, this says what happens past it, and a pinned
    # budget must not silently drop the switch.
    for budget in (0.0, 4.0):
        text = _write({"feed": dict(_FEED), "mesh_budget_gb": budget})
        assert "mesh_fit_cell: true" in text
        assert f"mesh_budget_gb: {budget}" in text


def test_yaml_mesh_nudge_default_on():
    # The runner's default, spelled out: the built lattice's nodes slide onto
    # the material edges -- copper and the board outline alike, one key for
    # every material -- at the same cell count. The driven cell moves with the
    # rest, so the feed gap is an output of the mesh, not an input to it.
    text = _write({"feed": dict(_FEED)})
    assert "mesh_nudge: true" in text


def test_yaml_mesh_nudge_off():
    text = _write({"feed": dict(_FEED), "mesh_nudge": False})
    assert "mesh_nudge: false" in text


def test_yaml_has_no_substrate_nudge_key():
    # mesh_nudge governs every material; there is no separate substrate key.
    # The runner refuses that name, so writing it (from a stale settings
    # snapshot, say) would block every run.
    for nudge in (False, True):
        text = _write({"feed": dict(_FEED), "mesh_nudge": nudge})
        assert "mesh_nudge_substrate" not in text


def test_yaml_mesh_nudge_is_unconditional():
    # Unlike refine_n/refine_adaptive (which the runner rejects with
    # refine_xy: false), the nudge stands alone: it must be written whether
    # refinement is on or off -- with both on it just runs on the refined mesh.
    for refine in (False, True):
        text = _write({"feed": dict(_FEED), "refine_xy": refine})
        assert "mesh_nudge: true" in text


def test_yaml_adaptive_off_omits_reach():
    # Adaptive off by default: `adaptive: false` is written, and adaptive_n
    # must NOT appear (the runner rejects an orphan adaptive_n).
    text = _write({"feed": dict(_FEED)})
    assert "adaptive: false" in text
    assert "adaptive_n" not in text


def test_yaml_adaptive_on_writes_reach():
    # The "Fastest" speed stop turns adaptive on; the reach then rides along.
    text = _write({"feed": dict(_FEED), "adaptive": True})
    assert "adaptive: true" in text
    assert "adaptive_n: 0.25" in text  # DEFAULTS reach


def test_yaml_adaptive_reach_override():
    text = _write({"feed": dict(_FEED), "adaptive": True, "adaptive_n": 0.4})
    assert "adaptive_n: 0.4" in text


def test_yaml_adaptive_reach_ignored_when_off():
    # An adaptive_n typed while the slider is off the Fastest stop is silently
    # dropped, so it can't trip the runner's orphan-key error.
    text = _write({"feed": dict(_FEED), "adaptive_n": 0.4})
    assert "adaptive: false" in text
    assert "adaptive_n" not in text


def test_yaml_refine_off_omits_graded_knobs():
    # refine_xy off by default: refine_n/refine_adaptive must NOT appear (the
    # runner rejects either key with refine_xy: false).
    text = _write({"feed": dict(_FEED)})
    assert "refine_xy: false" in text
    assert "refine_n" not in text
    assert "refine_adaptive" not in text


def test_yaml_refine_on_writes_graded_knobs():
    text = _write({"feed": dict(_FEED), "refine_xy": True})
    assert "refine_xy: true" in text
    assert "refine_n: 3" in text  # DEFAULTS divisor
    assert "refine_adaptive: true" in text  # DEFAULTS grading


def test_yaml_refine_n_override():
    text = _write(
        {
            "feed": dict(_FEED),
            "refine_xy": True,
            "refine_n": 5,
            "refine_adaptive": False,
        }
    )
    assert "refine_n: 5" in text
    assert "refine_adaptive: false" in text


def test_yaml_refine_graded_knobs_ignored_when_off():
    # refine_n/refine_adaptive typed while refine_xy is off are silently
    # dropped, so they can't trip the runner's refine_xy: false error.
    text = _write({"feed": dict(_FEED), "refine_n": 5, "refine_adaptive": False})
    assert "refine_xy: false" in text
    assert "refine_n" not in text
    assert "refine_adaptive" not in text


def test_yaml_missing_feed_raises():
    try:
        _write({})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "feed marker" in str(exc)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
