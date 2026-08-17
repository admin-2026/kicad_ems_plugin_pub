"""The knobs of the pass: what the two solver sections spend (no KiCad, real wx
stubbed).

They live beside the button that pays for them — the Run section's and every
designer's Scan section's — and reach the solver through one contract:
``contribute`` writes ``time_ns`` (0 meaning "solve until the port rings down")
and ``auto_ground`` into the run params. So what is pinned here is that
contract: the Auto tick and the typed ns field can't both speak, a run length
that isn't a positive number of ns is refused rather than guessed at, the
ground/source tick is carried as it stands, and the rows survive the round trip
through the shared model (snapshot -> restore -> what a restore can't fire
re-derived).

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_passknobs.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

passknobs = load("gui.sections.passknobs")
run = load("gui.sections.run")


def _row():
    """A row like a section builds, with the list its relayout appends to (the
    ns field coming and going changes the section's width)."""
    layouts = []
    row = passknobs.SimTimeRow(object(), lambda: layouts.append(True))
    return row, layouts


# --------------------------------------------------------------------------- #
# Simulation time
# --------------------------------------------------------------------------- #
def test_auto_is_the_ring_down_and_greys_the_field():
    row, _ = _row()
    params = {}
    row.contribute(params)
    assert params["time_ns"] == 0.0  # 0 = run until the port rings down
    assert row.value.enabled is False


def test_unchecking_auto_reveals_the_field_and_its_unit():
    row, layouts = _row()
    row.auto.click(False)
    assert row.value.enabled is True
    assert row.unit.shown is True
    assert layouts  # the row grew; the form was relaid out


def test_a_typed_length_is_what_the_solver_gets():
    row, _ = _row()
    row.auto.click(False)
    row.value.ChangeValue("12.5")
    params = {}
    row.contribute(params)
    assert params["time_ns"] == 12.5


def test_a_blank_or_unusable_length_is_refused_by_name():
    # No silent default: a field the user opened and left empty (or typed
    # nonsense into) stops the run, saying which field and what to do.
    for text in ("", "soon", "0", "-3"):
        row, _ = _row()
        row.auto.click(False)
        row.value.ChangeValue(text)
        try:
            row.contribute({})
            assert False, f"expected RuntimeError for {text!r}"
        except RuntimeError as exc:
            assert passknobs.SimTimeRow.LABEL in str(exc)
            assert "Auto (ring-down)" in str(exc)


# --------------------------------------------------------------------------- #
# Auto ground/source
# --------------------------------------------------------------------------- #
def test_the_solver_looks_for_its_own_reference_by_default():
    knobs = passknobs.PassKnobs(object())
    params = {}
    knobs.contribute(params)
    assert params["auto_ground"] is True


def test_unticking_it_drives_the_board_as_drawn():
    knobs = passknobs.PassKnobs(object())
    knobs.auto_ground.check.SetValue(False)
    params = {}
    knobs.contribute(params)
    assert params["auto_ground"] is False


def test_the_label_names_both_readings_of_the_reference():
    # Bipolar antennas feed a source arm through the same search, so the knob
    # can't be called "ground" alone. The name is the column label; the tick
    # beside it says what automatic means, exactly as the time row's does, so
    # the two read as one pair.
    assert "ground/source" in passknobs.AutoGroundRow.LABEL.lower()
    for row in (passknobs.SimTimeRow, passknobs.AutoGroundRow):
        assert row.CHECK_LABEL.startswith("Auto (")


# --------------------------------------------------------------------------- #
# The shared model / settings round trip
# --------------------------------------------------------------------------- #
def test_every_knob_round_trips_through_the_model():
    # Two views onto one form: what the Run section's knobs hold is what a
    # designer's Scan knobs show after the shell syncs the pages -- and the
    # composite carries every row, so a page syncs them in one call.
    source = passknobs.PassKnobs(object())
    source.time.auto.click(False)
    source.time.value.ChangeValue("15")
    source.auto_ground.check.SetValue(False)
    target = passknobs.PassKnobs(object())
    target.restore(source.snapshot())
    target.sync()  # restore fires no event, so the caller re-derives the greying
    assert target.snapshot() == source.snapshot()
    assert target.time.value.enabled is True
    params = {}
    target.contribute(params)
    assert params == {"time_ns": 15.0, "auto_ground": False}


def test_the_row_round_trips_through_the_model():
    # Two views onto one value: what the Run section's row holds is what a
    # designer's Scan row shows after the shell syncs the pages.
    source, _ = _row()
    source.auto.click(False)
    source.value.ChangeValue("8")
    target, _ = _row()
    target.restore(source.snapshot())
    target.sync()  # restore fires no event, so the caller re-derives the greying
    assert target.snapshot() == source.snapshot()
    assert target.value.enabled is True
    params = {}
    target.contribute(params)
    assert params["time_ns"] == 8.0


def test_a_file_without_the_keys_leaves_the_row_alone():
    row, _ = _row()
    row.restore({"freq": "2.45"})  # a settings file written before this row
    assert row.snapshot()["time_auto"] == "true"


# --------------------------------------------------------------------------- #
# The run params
# --------------------------------------------------------------------------- #
def test_the_page_contributes_its_own_knobs():
    # collect_run_params asks the page for its knobs, so the same builder
    # serves the simulate view's Run section and a designer's Scan section.
    knobs = passknobs.PassKnobs(object())
    knobs.time.auto.click(False)
    knobs.time.value.ChangeValue("20")
    knobs.auto_ground.check.SetValue(False)

    class _Page:
        form = type("_Form", (), {"contribute": lambda self, p: None})()
        advanced = type("_Adv", (), {"contribute": lambda self, p: None})()
        pass_knobs = knobs

        def feed_layer_name(self):
            return "F_Cu"

    params = run.collect_run_params(_Page(), "/tmp/run")
    assert params["time_ns"] == 20.0 and params["auto_ground"] is False
    assert params["outdir"] == "/tmp/run" and params["feed_layer"] == "F_Cu"


if __name__ == "__main__":
    run_module_tests(globals())
