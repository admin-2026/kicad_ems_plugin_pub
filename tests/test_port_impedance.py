"""One impedance, not two.

The design target's impedance is what the feed port is driven through, and the
solver normalizes the ``S11``/``VSWR`` columns it writes to exactly that
resistance. The verdict table then reads those columns back and prints the
target's impedance over them -- so the two being one number is what makes the
table mean what it says. They used to be two: ``impedance`` scored, and
``adv.port_resistance`` drove, and nothing compared them.

    python3 tests/test_port_impedance.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

formparams = load("emkit.formparams")
runjob = load("runjob")


def _form(**overrides):
    """A whole form for a two-layer board, on the Custom… target."""
    form = formparams.starter(("F_Cu", "B_Cu"), 1)
    form["freq"] = "2.44"
    form["impedance"] = "50"
    form.update(overrides)
    return form


def _refused(form):
    """The message a run of ``form`` is refused with."""
    try:
        formparams.params(form)
    except RuntimeError as exc:
        return str(exc)
    raise AssertionError("expected a refusal")


# --------------------------------------------------------------------------- #
# the target drives the port
# --------------------------------------------------------------------------- #
def test_a_typed_impedance_is_what_the_port_is_driven_through():
    assert formparams.params(_form(impedance="75"))["port_resistance"] == "75"


def test_a_named_application_carries_its_own():
    # The pick is the target in full, so its impedance drives the port the same
    # way its frequency sets the pattern -- with the fields beside it unread.
    form = _form(app="Wi-Fi 2.4 GHz", freq="", impedance="")
    params = formparams.params(form)
    assert params["port_resistance"] == "50"
    assert params["fpattern_ghz"] == 2.45


def test_the_target_and_the_port_are_the_same_number():
    # The property the whole seam exists for: whatever the verdicts are
    # labelled with is what the solver was told to normalize S11 to.
    for ohms in ("50", "75", "300"):
        form = _form(impedance=ohms)
        assert float(formparams.params(form)["port_resistance"]) == (
            runjob.form_target(form).impedance_ohm
        )


# --------------------------------------------------------------------------- #
# ...and the Advanced field may not quietly disagree with it
# --------------------------------------------------------------------------- #
def test_an_advanced_override_that_disagrees_is_refused_naming_both():
    message = _refused(_form(impedance="50", **{"adv.port_resistance": "75"}))
    assert "75" in message and "50" in message
    assert "Port resistance" in message  # the pane's label, not the config key


def test_an_advanced_override_that_agrees_is_no_disagreement():
    form = _form(impedance="50", **{"adv.port_resistance": "50"})
    assert formparams.params(form)["port_resistance"] == "50"


def test_an_ideal_current_source_still_wins():
    # "inf"/"none" is a different port model, not a different number -- it is
    # the reason the Advanced field is still writable, so it is not a clash.
    form = _form(impedance="50", **{"adv.port_resistance": "inf"})
    assert formparams.params(form)["port_resistance"] == "inf"


# --------------------------------------------------------------------------- #
# and nothing is invented when neither says
# --------------------------------------------------------------------------- #
def test_a_target_with_no_impedance_and_no_override_is_refused():
    message = _refused(_form(impedance=""))
    assert "Impedance" in message
    assert "Port resistance" in message  # ...and where the other answer lives


def test_a_free_target_may_be_answered_by_the_advanced_field_alone():
    # A target is allowed to leave its impedance free (it then judges the match
    # on nothing), but the port still has to be driven through something.
    form = _form(impedance="", **{"adv.port_resistance": "75"})
    assert formparams.params(form)["port_resistance"] == "75"


if __name__ == "__main__":
    run_module_tests(globals())
