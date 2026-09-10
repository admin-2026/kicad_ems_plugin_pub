"""The Advanced pane's numeric fields, against the writer they feed.

Every ADV_FIELDS row is a runner knob typed by hand, so the two things that can
silently rot are the key (a field the writer never emits does nothing) and the
parse (a value the writer or the runner would reject). Both are pure -- no
board, no dialog, and the parse is not even the pane's (formparams reads the
same field out of a settings file) -- so they are checked here rather than
through a live pane.

    python3 tests/test_adv_fields.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

options = load("emkit.options")
formparams = load("emkit.formparams")
config = load("config")


def test_every_advanced_field_is_a_writer_knob():
    # A field whose key the writer doesn't know would be typed into a void:
    # collect_run_params passes it through and write_yaml never reads it.
    for key, label, _hint in options.ADV_FIELDS:
        knobs = config.AntennaConfig.DEFAULTS
        assert key in knobs, f"{label} ({key}) is not a config knob"


def test_every_speed_preset_knob_is_a_writer_knob():
    # The slider's stops are the other half of the Advanced pane: each
    # SpeedPreset field but its caption is a config key the writer emits, so a
    # knob the schema renames can't stay half-renamed here and silently stop
    # reaching the runner.
    for name in options.SpeedPreset._fields:
        if name == "desc":
            continue
        knobs = config.AntennaConfig.DEFAULTS
        assert name in knobs, f"{name} is not a config knob"


def test_negatives_are_refused_naming_the_field():
    # No numeric field means anything below zero, and the runner's reaction to
    # one is uneven (min_raster_mm: -1 is a config error, mesh_budget_gb: -1
    # silently reverts to the auto budget), so the pane refuses it up front.
    for key in ("min_raster_mm", "mesh_budget_gb", "auto_ground_radius_mm", "cell_mm"):
        try:
            formparams.adv_value(key, "Field", "-1")
            assert False, f"expected RuntimeError for {key}"
        except RuntimeError as exc:
            assert "Field" in str(exc) and "negative" in str(exc)


def test_zero_is_the_auto_for_every_field():
    # 0 stays 0 through the pane: what each auto resolves to is the runner's
    # business (min_raster_mm's 0, for one, derives the connectivity cell from
    # the narrowest fed trace), so nothing here substitutes a number for it.
    assert formparams.adv_value("min_raster_mm", "Field", "0") == 0.0
    assert formparams.adv_value("mesh_budget_gb", "Field", "0") == 0.0
    assert formparams.adv_value("pml_cells", "Field", "0") == 0


if __name__ == "__main__":
    run_module_tests(globals())
