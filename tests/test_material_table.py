"""The Advanced pane's material table: typing a material, and keeping one.

Every row of the table wears the same trio as the Design-target section, over a
catalog of its own kind, so what is checked here is what the *rows* add: which
fields a pick brings to life, that a material saved on one layer is offered on
all of them, and that the picks still reach the run config the way
``config._apply_overrides`` expects. Driven through the wx stand-in.

    python3 tests/test_material_table.py
"""

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

ui = load("emkit.materials.ui")
Materials = load("emkit.materials.db").Materials

LAYERS = (["F.Cu", "B.Cu"], 1)  # a two-copper board: 2 metal rows, 1 substrate


class _Home:
    """A temporary config home, so the rows' catalogs write to a scratch file
    instead of the user's own (materials.ui builds its own catalogs -- that it
    doesn't take them from a caller is the point of the class)."""

    def __init__(self):
        self._dir = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "APPDATA")}
        for key in self._saved:
            os.environ[key] = self._dir.name

    def close(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._dir.cleanup()


def _table(answers=("A name", True)):
    """A material table over a temporary saved-materials file, with every row's
    dialogs answered from ``answers`` (name, confirm)."""
    home = _Home()
    table = ui.MaterialSelector(object(), LAYERS, on_change=None)
    table.errors = []
    for row in table._rows():  # every row of the table, the mask's included
        row.saved.ask_name = lambda default="", a=answers: a[0]
        row.saved.confirm = lambda message, title, a=answers: a[1]
        row.saved.error = table.errors.append
    return table, home


def _pick(row, name):
    """Choose ``name`` in a row's picker, as the user does."""
    row.choice.SetStringSelection(name)
    row.choice.fire("EVT_CHOICE")


def _type(row, **values):
    for key, text in values.items():
        row.fields[key].SetValue(text)


# --------------------------------------------------------------------------- #
# What a pick shows
# --------------------------------------------------------------------------- #
def test_a_builtin_pick_answers_for_itself():
    table, home = _table()
    try:
        row = table.metal_rows[0]
        assert row.choice.GetStringSelection() == Materials.DEFAULT_METAL
        assert row.fields["sigma"].enabled is False
        assert row.saved.save_btn.shown is False
        assert row.saved.update_btn.shown is False
        assert row.material().sigma == 5.8e7
    finally:
        home.close()


def test_custom_brings_the_fields_to_life_prefilled():
    table, home = _table()
    try:
        row = table.metal_rows[0]
        _pick(row, "Silver")  # a pick fills the (dead) field with its own value
        assert row.fields["sigma"].GetValue() == "6.3e+07"
        _pick(row, Materials.CUSTOM)
        assert row.fields["sigma"].enabled is True
        assert row.saved.save_btn.shown is True
        # ... so typing a material starts from the one that was picked.
        assert row.material().sigma == 6.3e7
    finally:
        home.close()


def test_a_custom_row_with_unusable_fields_judges_nothing():
    table, home = _table()
    try:
        row = table.substrate_rows[0]
        _pick(row, Materials.CUSTOM)
        _type(row, eps="", tand="")
        # No material rather than an invented FR-4: the hint shows its own
        # default, and the run refuses, naming the layer.
        assert row.material() is None
        assert table.substrate_material() is None
        try:
            table.apply({})
            assert False, "expected the run config to refuse it"
        except ValueError as exc:
            assert "Substrate" in str(exc) and "εr" in str(exc)
    finally:
        home.close()


# --------------------------------------------------------------------------- #
# Keeping one
# --------------------------------------------------------------------------- #
def test_a_saved_metal_is_offered_on_every_layer():
    table, home = _table(answers=("Thick copper", True))
    try:
        first, second = table.metal_rows
        _pick(first, Materials.CUSTOM)
        _type(first, sigma="5.9e7")
        first.saved.save_btn.fire("EVT_BUTTON")
        assert first.choice.GetStringSelection() == "Thick copper"
        assert first.fields["sigma"].enabled is False  # a named pick now
        # The other layer's picker was rebuilt from the file, without the
        # window being reopened -- a saved material is the user's, not a row's.
        assert "Thick copper" in second.choice.items
        _pick(second, "Thick copper")
        assert second.material().sigma == 5.9e7
        assert table.errors == []
    finally:
        home.close()


def test_a_saved_substrate_reaches_the_run_config():
    table, home = _table(answers=("House laminate", True))
    try:
        row = table.substrate_rows[0]
        _pick(row, Materials.CUSTOM)
        _type(row, eps="3.9", tand="0.017")
        row.saved.save_btn.fire("EVT_BUTTON")
        params = {}
        table.apply(params)
        assert params["substrate_layers"] == [{"eps": 3.9, "loss_tangent": 0.017}]
        assert params["metal_layers"] == [{"sigma": 5.8e7}, {"sigma": 5.8e7}]
    finally:
        home.close()


def test_the_mask_row_starts_on_the_boards_own_numbers():
    # The coating's row is a substrate row over a list of its own: the same
    # sentinel first pick, which means the same thing (keep what the board's
    # Physical Stackup says) and emits no material at all.
    table, home = _table()
    try:
        row = table.mask_row
        assert row.choice.GetStringSelection() == Materials.BOARD_SUBSTRATE
        assert row.material() is None
        params = {}
        table.apply_mask(params)
        assert params["mask_material"] is None
    finally:
        home.close()


def test_a_picked_mask_reaches_the_run_config():
    table, home = _table()
    try:
        _pick(table.mask_row, "LPI solder mask")
        params = {}
        table.apply(params)  # the whole table: the mask rides with the rest
        assert params["mask_material"] == {"eps": 3.5, "loss_tangent": 0.025}
    finally:
        home.close()


def test_a_saved_mask_is_kept_apart_from_the_substrates():
    # A coating and a laminate are not interchangeable, so they are saved in
    # files of their own: a mask saved here is offered on the mask row and
    # nowhere else.
    table, home = _table(answers=("House green", True))
    try:
        row = table.mask_row
        _pick(row, Materials.CUSTOM)
        _type(row, eps="3.6", tand="0.022")
        row.saved.save_btn.fire("EVT_BUTTON")
        assert row.choice.GetStringSelection() == "House green"
        assert "House green" not in table.substrate_rows[0].choice.items
        params = {}
        table.apply_mask(params)
        assert params["mask_material"] == {"eps": 3.6, "loss_tangent": 0.022}
        assert table.errors == []
    finally:
        home.close()


def test_a_custom_mask_with_nothing_typed_refuses_the_run():
    # The "properties not set" case, at the row: no material, and a run that
    # asks for one is told which row and what is missing (the banner turns the
    # same message into a blocker -- see test_mask_layer.py).
    table, home = _table()
    try:
        _pick(table.mask_row, Materials.CUSTOM)
        _type(table.mask_row, eps="", tand="")
        assert table.mask_row.material() is None
        try:
            table.apply_mask({})
            assert False, "expected the run config to refuse it"
        except ValueError as exc:
            assert "Solder mask" in str(exc) and "εr" in str(exc)
    finally:
        home.close()


def test_update_edits_a_saved_material_in_place():
    table, home = _table(answers=("Thick copper", True))
    try:
        row = table.metal_rows[0]
        _pick(row, Materials.CUSTOM)
        _type(row, sigma="5.9e7")
        row.saved.save_btn.fire("EVT_BUTTON")
        row.saved.update_btn.fire("EVT_BUTTON")  # opens the edit
        assert row.fields["sigma"].enabled is True
        assert row.saved.update_btn.GetLabel() == "Save changes"
        _type(row, sigma="6.05e7")
        assert row.material().sigma == 5.9e7  # not saved until it is
        row.saved.update_btn.fire("EVT_BUTTON")
        assert row.material().sigma == 6.05e7
        assert row.choice.items.count("Thick copper") == 1  # updated, not added
        assert row.fields["sigma"].enabled is False
    finally:
        home.close()


def test_delete_leaves_custom_holding_the_numbers():
    table, home = _table(answers=("Thick copper", True))
    try:
        first, second = table.metal_rows
        _pick(first, Materials.CUSTOM)
        _type(first, sigma="5.9e7")
        first.saved.save_btn.fire("EVT_BUTTON")
        first.saved.delete_btn.fire("EVT_BUTTON")
        assert first.choice.GetStringSelection() == Materials.CUSTOM
        assert first.fields["sigma"].GetValue() == "5.9e7"  # savable straight back
        assert "Thick copper" not in second.choice.items  # gone from every row
    finally:
        home.close()


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def test_the_settings_keys_carry_the_pick_and_its_fields():
    table, home = _table(answers=("Thick copper", True))
    try:
        row = table.metal_rows[0]
        _pick(row, Materials.CUSTOM)
        _type(row, sigma="5.9e7")
        row.saved.save_btn.fire("EVT_BUTTON")
        state = table.state()
        assert state["metal0.choice"] == "Thick copper"
        assert state["metal0.sigma"] == "5.9e7"
        assert state["sub0.choice"] == Materials.BOARD_SUBSTRATE
        # A second table (another page) restores the pick from the same file.
        other = ui.MaterialSelector(object(), LAYERS, on_change=None)
        other.restore(state)
        assert other.metal_rows[0].choice.GetStringSelection() == "Thick copper"
        assert other.metal_rows[0].material().sigma == 5.9e7
    finally:
        home.close()


def test_a_pick_deleted_from_under_the_window_is_not_quietly_copper():
    # Another KiCad session deleted the saved metal this row is picked on: the
    # name stands for nothing now, and a run must say so rather than solve
    # copper (the catalog's strict lookup is what makes that visible).
    table, home = _table(answers=("Thick copper", True))
    try:
        row = table.metal_rows[0]
        _pick(row, Materials.CUSTOM)
        _type(row, sigma="5.9e7")
        row.saved.save_btn.fire("EVT_BUTTON")
        row.catalog.delete("Thick copper")  # behind this window's back
        assert row.material() is None
        try:
            table.apply({})
            assert False, "expected the run config to refuse it"
        except ValueError as exc:
            assert "Thick copper" in str(exc) and "F.Cu" in str(exc)
    finally:
        home.close()


def test_a_pick_that_vanished_restores_as_custom():
    # The settings name a material another session deleted: the row drops to
    # Custom… holding the numbers saved beside it, rather than solving with
    # whichever entry the picker happened to be on.
    table, home = _table()
    try:
        row = table.metal_rows[0]
        row.restore("metal0", {"metal0.choice": "Gone", "metal0.sigma": "4.2e7"})
        assert row.choice.GetStringSelection() == Materials.CUSTOM
        assert row.material().sigma == 4.2e7
    finally:
        home.close()


if __name__ == "__main__":
    run_module_tests(globals())
