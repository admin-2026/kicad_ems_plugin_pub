"""The one translation between a saved form and a run's parameters.

Both frontends go through it -- the window's sections hand it their own
snapshot, ``run start`` hands it a settings file -- so what is pinned here is
that a *file* is enough to describe a run, and that it describes the same one
either way:

  * a starter form is a whole form: every knob a run takes comes out of it,
    with nothing invented and nothing left over;
  * the two vocabularies stay apart -- ``adv.cell_mm`` is the form's,
    ``cell_mm`` is the config's, and the config's spelling in a form file is
    refused by name rather than quietly ignored;
  * a key a form does not hold means what a fresh form holds, not a number
    nobody chose;
  * a blank field stays out of the params, so the runner's own auto answers.

No wx, no board, no solver: this is stdlib data in and a dict out.

    python3 tests/test_formparams.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

choices = load("emkit.choices")
config = load("emkit.config")
formparams = load("emkit.formparams")
options = load("emkit.options")
settings = load("emkit.settings")


def _form(**overrides):
    """A starter form for a two-layer board, with anything a product leaves
    blank filled in -- the frequency and the impedance are the two every flow
    here needs (the port has to be driven through something, and S11 measured
    against it)."""
    form = formparams.starter(("F_Cu", "B_Cu"), 1)
    form["freq"] = "2.44"
    form.setdefault("impedance", "")
    form["impedance"] = form["impedance"] or "50"
    form.update(overrides)
    return form


# --------------------------------------------------------------------------- #
# A form is enough to describe a run
# --------------------------------------------------------------------------- #
def test_a_starter_form_makes_a_whole_set_of_run_parameters():
    """What ``settings init`` writes, plus the one field it leaves for the
    caller, is a run. That is the property the CLI stands on."""
    params = formparams.params(_form())
    for key in ("copper_model", "boundary", "copper_cells", "time_ns", "auto_ground"):
        assert key in params, key
    assert params["metal_layers"] == [{"sigma": 58e6}, {"sigma": 58e6}]
    assert params["substrate_layers"] == [None]  # "from board stackup"
    assert params["feed_layer"] == "F_Cu"


def test_every_parameter_it_produces_is_a_knob_the_writer_knows():
    """A key the config never reads would be a form field typed into a void."""
    known = set(config.ConfigWriter.DEFAULTS)
    known.update(("feed_layer", "metal_layers", "substrate_layers", "mask_material"))
    for key in formparams.params(_form()):
        assert key in known, f"{key} is not a config knob"


def test_a_blank_field_leaves_the_runner_its_auto():
    """Nothing substitutes a number for an empty field: the key stays out and
    the config's own 0 = auto is what the run gets. (Only the Advanced fields
    no flow's own form also writes -- a sweep types its band twice over.)"""
    params = formparams.params(_form())
    assert "cell_mm" not in params
    assert formparams.params(_form(**{"adv.cell_mm": "0.5"}))["cell_mm"] == 0.5


def test_an_advanced_field_wins_over_a_flow_that_writes_the_same_knob():
    """The order the window builds its params in: the flow's own form, then
    the Advanced pane over it, then the pass. Where both spell one config key,
    the pane is the last word -- as it is on screen.

    ``port_resistance`` is the exception and has its own tests below: what the
    solver normalizes S11 to cannot quietly differ from what the verdicts are
    labelled with, so there a disagreement is refused instead."""
    form = _form()
    filled = {
        key: "1.5"
        for key, _label, _hint in options.ADV_FIELDS
        if key in formparams.params(form) and key != "port_resistance"
    }
    for key, value in filled.items():
        form["adv." + key] = value
    params = formparams.params(form)
    for key in filled:
        # port_resistance rides through as a string (the runner also takes
        # "inf"), so what is asserted is the value and not its type.
        assert float(params[key]) == 1.5, key


def test_a_field_that_is_not_a_number_is_refused_naming_it():
    """Named by the label the pane draws beside it, not by the config key: a
    caller reading the message is looking at a form."""
    label = dict((key, label) for key, label, _hint in options.ADV_FIELDS)["cell_mm"]
    for text in ("wide", "-1"):
        try:
            formparams.params(_form(**{"adv.cell_mm": text}))
            assert False, f"expected RuntimeError for {text!r}"
        except RuntimeError as exc:
            assert label in str(exc), exc


# --------------------------------------------------------------------------- #
# The two vocabularies
# --------------------------------------------------------------------------- #
def test_a_config_key_in_a_form_is_refused_and_the_form_spelling_named():
    """The mistake a reader of ``pcb.yaml`` makes first. Silently ignoring it
    would report a run at the automatic cell as the run that was asked for."""
    try:
        formparams.params(_form(cell_mm="0.5"))
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "cell_mm" in str(exc) and "adv.cell_mm" in str(exc)


def test_the_two_inverted_toggles_survive_the_translation():
    """The form says what a checkbox *skips*; the config says what it does."""
    assert formparams.params(_form(no_refine_xy="true"))["refine_xy"] is False
    assert formparams.params(_form(no_refine_xy="false"))["refine_xy"] is True
    assert formparams.params(_form(mur="true"))["boundary"] == "mur"
    assert formparams.params(_form(mur="false"))["boundary"] == "pml"


def test_a_pick_is_read_as_a_value_and_an_unknown_one_is_the_default():
    assert formparams.params(_form(copper_model="sheet"))["copper_model"] == "sheet"
    unknown = formparams.params(_form(copper_model="brass-ish"))
    assert unknown["copper_model"] == choices.COPPER_MODEL.default


def test_a_caption_an_older_window_saved_still_reads_as_its_value():
    """Settings files hold ``sibc — skin-effect loss`` where they now hold
    ``sibc``, and one held it under ``model``."""
    caption = choices.COPPER_MODEL.labels()[1]
    form = _form()
    del form["copper_model"]
    form["model"] = caption
    assert formparams.params(form)["copper_model"] == "sibc"


# --------------------------------------------------------------------------- #
# What a form leaves out
# --------------------------------------------------------------------------- #
def test_a_key_a_form_never_held_means_what_a_fresh_form_holds():
    """A settings file written before a knob existed opens in the window on
    that knob's default; it has to run the same way."""
    form = _form()
    del form["mesh_nudge"]
    del form["copper_cells"]
    params = formparams.params(form)
    assert params["mesh_nudge"] is config.ConfigWriter.DEFAULTS["mesh_nudge"]
    fresh = options.SPEED_PRESETS[options.SPEED_DEFAULT]
    assert params["copper_cells"] == fresh.copper_cells


def test_the_time_row_is_two_keys_and_auto_is_the_ring_down():
    assert formparams.params(_form())["time_ns"] == 0.0
    typed = formparams.params(_form(time_auto="false", time="12.5"))
    assert typed["time_ns"] == 12.5
    try:
        formparams.params(_form(time_auto="false", time=""))
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "ring-down" in str(exc)


# --------------------------------------------------------------------------- #
# Materials
# --------------------------------------------------------------------------- #
def test_a_picked_material_is_read_out_of_the_catalog_by_name():
    params = formparams.params(_form(**{"materials.sub0.choice": "FR-4"}))
    assert params["substrate_layers"] == [{"eps": 4.4, "loss_tangent": 0.02}]


def test_a_custom_pick_takes_the_fields_typed_beside_it():
    params = formparams.params(
        _form(
            **{
                "materials.sub0.choice": "Custom…",
                "materials.sub0.eps": "3.0",
                "materials.sub0.tand": "0.001",
            }
        )
    )
    assert params["substrate_layers"] == [{"eps": 3.0, "loss_tangent": 0.001}]


def test_a_custom_pick_with_no_numbers_is_refused_naming_the_row():
    """Never copper by default, and never the board's own numbers instead:
    a pick that stands for nothing stops the run."""
    try:
        formparams.params(_form(**{"materials.metal0.choice": "Custom…"}))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "metal0" in str(exc)


def test_a_row_the_form_does_not_have_is_a_layer_the_config_refuses():
    """The lists come up short rather than being padded with a default, and
    the config writer names the layer that has no material."""
    form = _form()
    for key in list(form):
        if key.startswith("materials.metal1."):
            del form[key]
    assert formparams.params(form)["metal_layers"] == [{"sigma": 58e6}]


def test_the_bare_json_dump_is_asked_for_on_the_form_like_everything_else():
    """The one output knob, and the only way a caller with no browser reads a
    run back: the ``.js`` the report page loads is an assignment, not JSON. It
    is a form key so that both frontends ask for it the same way -- a tick on
    the pane and a line in a settings file -- rather than it being reachable
    only by hand-writing a pcb.yaml."""
    assert formparams.params(_form())["output_json"] is False  # off unless asked
    assert formparams.params(_form(output_json="true"))["output_json"] is True
    assert "output_json" in formparams.defaults()


# --------------------------------------------------------------------------- #
# The mask, which is one tick and no speed stop's business
# --------------------------------------------------------------------------- #
def test_the_coating_is_off_until_a_form_asks_for_it():
    """The dearest tick on the pane, so nothing but the tick turns it on -- not
    the most accurate speed stop, and not a form that never mentions it."""
    assert formparams.params(_form())["include_mask"] is False
    assert formparams.params(_form(include_mask="true"))["include_mask"] is True
    assert formparams.params(_form(include_mask="false"))["include_mask"] is False
    top = options.SPEED_PRESETS[-1]
    at_top = _form(
        coarse_air=formparams.bool_str(top.coarse_air),
        no_refine_xy=formparams.bool_str(not top.refine_xy),
        mur=formparams.bool_str(top.boundary == "mur"),
        conformal=formparams.bool_str(top.conformal),
        adaptive=formparams.bool_str(top.adaptive),
        copper_cells=str(top.copper_cells),
    )
    assert formparams.params(at_top)["include_mask"] is False


# --------------------------------------------------------------------------- #
# Through the file
# --------------------------------------------------------------------------- #
def test_a_form_survives_being_written_and_read_back(tmp_path=None):
    """The file is the seam, so the round trip is the thing: what
    ``settings init`` writes must read back as the same run."""
    import tempfile

    directory = tempfile.mkdtemp(prefix="formparams_")
    form = _form()
    path = settings.write(settings.path(directory), form)
    assert formparams.params(settings.read(path)) == formparams.params(form)


def test_an_empty_file_is_not_a_form():
    import tempfile

    directory = tempfile.mkdtemp(prefix="formparams_")
    path = settings.write(settings.path(directory), {})
    try:
        settings.read(path)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "no settings" in str(exc)


if __name__ == "__main__":
    run_module_tests(globals())
