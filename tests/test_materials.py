"""Unit tests for antenna_plugin.materials.db (pure, no KiCad).

The plugin package's __init__ imports pcbnew, so load the module by path to
keep these runnable off-KiCad:  python3 tests/test_materials.py
"""

import importlib.util
import pathlib

_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "antenna_plugin"
    / "materials"
    / "db.py"
)
_spec = importlib.util.spec_from_file_location("materials", _SRC)
materials = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(materials)
Materials = materials.Materials


def test_copper_default_matches_config():
    # Copper is the default metal pick; its bulk conductivity is the textbook
    # 5.8e7 S/m (config injects no copper constant of its own anymore).
    assert Materials.metal(Materials.DEFAULT_METAL).sigma == 5.8e7


def test_fr4_has_textbook_eps_and_loss():
    # FR-4 carries the familiar eps 4.4 / loss tangent 0.02, both of which now
    # ride straight through to the solver (no derived conductivity).
    fr4 = Materials.substrate("FR-4")
    assert fr4.eps == 4.4 and fr4.tan_d == 0.02


def test_board_sentinel_means_no_override():
    assert Materials.substrate(Materials.BOARD_SUBSTRATE) is None


def test_substrate_list_leads_with_board_default():
    names = Materials.substrate_names()
    assert names[0] == Materials.BOARD_SUBSTRATE
    assert "FR-4" in names and "PTFE (Teflon)" in names


def test_metal_conductivity_scales_with_material():
    # Aluminium is less conductive than copper; silver more.
    assert Materials.metal("Aluminium").sigma < Materials.metal("Copper").sigma
    assert Materials.metal("Silver").sigma > Materials.metal("Copper").sigma


def test_unknown_metal_falls_back_to_copper():
    assert Materials.metal("Unobtainium").name == "Copper"


def test_substrate_loss_tangents_differ_by_material():
    # A low-loss laminate carries a smaller loss tangent than FR-4; the value
    # is what the picker hands the config as loss_tangent.
    assert (
        Materials.substrate("Rogers RO4003C").tan_d < Materials.substrate("FR-4").tan_d
    )


def test_custom_metal_uses_typed_conductivity():
    assert Materials.custom_metal("3.1e7").sigma == 3.1e7


def test_custom_substrate_uses_typed_eps_and_loss():
    m = Materials.custom_substrate("2.5", "0.001")
    assert m.eps == 2.5 and m.tan_d == 0.001


def test_choices_expose_custom_sentinel():
    assert Materials.metal_choices()[-1] == Materials.CUSTOM
    subs = Materials.substrate_choices()
    assert subs[0] == Materials.BOARD_SUBSTRATE and subs[-1] == Materials.CUSTOM


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} passed")
