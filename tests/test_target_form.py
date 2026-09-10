"""The Design-target section: which fields a pick shows, and saving one.

Two rules live in this section and nowhere else: a named application answers
the target itself (so its fields are not shown -- only ``Custom…`` has anything
to type), and a typed target can be named into a picker entry of its own. Both
are widget state, so they are driven here through the wx stand-in rather than
through a window.

    python3 tests/test_target_form.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

pattern_freq = load("gui.sections.pattern_freq")
catalog_mod = load("applications.catalog")
userlib = load("emkit.userlib.store")
Applications = load("applications.db").Applications

BLE = "Bluetooth / BLE (2.4 GHz)"


class _Page:
    """Just what a Section reads off its page (no Advanced pane: the hint falls
    back to its thin-microstrip FR-4)."""

    def __init__(self):
        self.scroll = object()
        self.wrapped = []
        self.lines = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def _relayout_scroll(self):
        pass

    def log(self, text):
        self.lines.append(text)


def _catalog(directory):
    """The design-target catalog over a temporary saved-targets file."""
    Catalog = catalog_mod.Catalog
    return Catalog(userlib.UserStore(Catalog.FILENAME, directory))


def _section(directory, answers=("A name", True)):
    """A Design-target section over a temporary saved-targets file, with the
    two dialogs of the save/delete flow answered from ``answers``
    (name, confirm)."""
    page = _Page()
    section = pattern_freq.PatternFreqSection(page, wx_stub.wx.BoxSizer())
    section.catalog = _catalog(directory)
    section.saved.catalog = section.catalog
    section.saved.refresh_choices()
    section.sync_custom_fields()
    section.saved.ask_name = lambda default="": answers[0]
    section.saved.confirm = lambda message, title: answers[1]
    section.errors = []
    section.saved.error = section.errors.append
    return section


def _pick(section, name):
    """Choose ``name`` in the picker, as the user does (fires EVT_CHOICE)."""
    section.app.SetStringSelection(name)
    section.app.fire("EVT_CHOICE")


def _type_custom(
    section, freq="3.6", bandwidth="200", impedance="50", return_loss="10"
):
    section.freq.type(freq)  # typing the frequency snaps the pick to Custom…
    section.bandwidth.ChangeValue(bandwidth)
    section.impedance.ChangeValue(impedance)
    section.return_loss.ChangeValue(return_loss)


def _fields(section):
    """Every field a typed target is typed into -- what a named pick hides."""
    return (
        section.freq,
        section.bandwidth,
        section.impedance,
        section.return_loss,
    )


# --------------------------------------------------------------------------- #
# What a pick shows
# --------------------------------------------------------------------------- #
def test_a_named_application_hides_the_fields_it_answers_itself():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _pick(section, BLE)
        for widget in _fields(section):
            assert widget.shown is False
        assert section.saved.save_btn.shown is False  # nothing typed to save
        # ... and says what it picked instead of showing empty boxes.
        spec = section._spec.GetLabel()
        assert "2.45 GHz" in spec and "50 Ω" in spec and "≥10 dB" in spec


def test_custom_shows_every_field_and_no_spec_line():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _pick(section, Applications.CUSTOM)
        for widget in _fields(section):
            assert widget.shown is True
        assert section.saved.save_btn.shown is True
        assert section._spec.GetLabel() == ""


def test_a_pick_fills_the_fields_behind_it():
    # Hidden, but filled: dropping back to Custom… to bend a target starts
    # from the numbers of the one that was picked, and the run's frequency is
    # read out of that same field.
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _pick(section, BLE)
        assert section.freq.GetValue() == "2.45"
        assert section.bandwidth.GetValue() == "83.5"
        assert section.impedance.GetValue() == "50"
        assert section.return_loss.GetValue() == "10"
        params = {}
        section.contribute(params)
        assert params["fpattern_ghz"] == 2.45


def test_typing_a_frequency_snaps_back_to_custom():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _pick(section, BLE)
        section.freq.type("1.2")
        assert section.app.GetStringSelection() == Applications.CUSTOM
        assert section.freq.shown is True


# --------------------------------------------------------------------------- #
# Saving one
# --------------------------------------------------------------------------- #
def test_saving_turns_the_typed_target_into_a_picker_entry():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _type_custom(section, freq="3.6", bandwidth="200", impedance="50")
        section.saved.save_btn.fire("EVT_BUTTON")
        assert section.app.GetStringSelection() == "Drone link"
        assert "Drone link" in section.app.items
        assert section.app.items[-1] == Applications.CUSTOM  # sentinel stays last
        # It is now a named pick like any other: fields hidden, spec shown.
        assert section.freq.shown is False
        assert "3.6 GHz" in section._spec.GetLabel()
        app = section.current_application()
        assert app.name == "Drone link" and app.f0_ghz == 3.6
        assert section.errors == []


def test_a_saved_target_comes_back_on_the_next_window():
    with tempfile.TemporaryDirectory() as td:
        first = _section(td, answers=("Drone link", True))
        _type_custom(first)
        first.saved.save_btn.fire("EVT_BUTTON")
        # A second section over the same file (another page, another launch)
        # offers it, and a settings restore can pick it back.
        second = _section(td)
        assert "Drone link" in second.app.items
        second.restore({"app": "Drone link", "freq": "3.6"})
        assert second.app.GetStringSelection() == "Drone link"


def test_a_bad_name_is_refused_and_saves_nothing():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Wi-Fi 5 GHz", True))
        _type_custom(section)
        section.saved.save_btn.fire("EVT_BUTTON")
        assert len(section.errors) == 1 and "built-in" in section.errors[0]
        assert _catalog(td).saved_names() == []
        assert section.app.GetStringSelection() == Applications.CUSTOM


def test_replacing_a_saved_target_is_asked_about_first():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _type_custom(section, freq="3.6")
        section.saved.save_btn.fire("EVT_BUTTON")
        # Same name again, this time with the question answered no.
        section.saved.confirm = lambda message, title: False
        _type_custom(section, freq="5.8")
        assert section.saved.save_as("Drone link") is False
        assert _catalog(td).get_saved("Drone link").f0_ghz == 3.6
        # ... and yes replaces it.
        section.saved.confirm = lambda message, title: True
        assert section.saved.save_as("Drone link") is True
        assert _catalog(td).get_saved("Drone link").f0_ghz == 5.8


# --------------------------------------------------------------------------- #
# Updating one
# --------------------------------------------------------------------------- #
def _save_one(section, freq="3.6", bandwidth="200", impedance="50"):
    """Save 'Drone link' and leave it picked, as the save flow does."""
    _type_custom(section, freq=freq, bandwidth=bandwidth, impedance=impedance)
    section.saved.save_btn.fire("EVT_BUTTON")


def test_update_opens_the_saved_targets_fields_on_the_pick():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _save_one(section)
        section.saved.update_btn.fire("EVT_BUTTON")
        assert section.saved.is_editing()
        assert section.saved.update_btn.GetLabel() == "Save changes"
        for widget in _fields(section):
            assert widget.shown is True
        # Filled with what is saved, and the pick stays put while they are
        # edited -- this is the one place a typed frequency doesn't snap away.
        assert section.freq.GetValue() == "3.6"
        section.freq.type("5.8")
        assert section.app.GetStringSelection() == "Drone link"
        assert section.saved.is_editing()


def test_saving_changes_writes_them_back_under_the_same_name():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _save_one(section)
        section.saved.update_btn.fire("EVT_BUTTON")
        section.freq.type("5.8")
        section.bandwidth.ChangeValue("400")
        section.saved.update_btn.fire("EVT_BUTTON")  # now "Save changes"
        saved = _catalog(td).saved()
        assert [a.name for a in saved] == ["Drone link"]  # updated, not added
        assert saved[0].f0_ghz == 5.8 and saved[0].bandwidth_mhz == 400.0
        # The edit is over: the target is a named pick again.
        assert not section.saved.is_editing()
        assert section.saved.update_btn.GetLabel() == "Update"
        assert section.freq.shown is False
        assert "5.8 GHz" in section._spec.GetLabel()
        assert section.current_application().f0_ghz == 5.8
        # Replacing it needed no question: the user pointed at it twice.
        assert section.errors == []


def test_an_update_is_not_saved_until_it_is():
    # Picking something else abandons the edit, and the file keeps what it had.
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _save_one(section)
        section.saved.update_btn.fire("EVT_BUTTON")
        section.freq.type("5.8")
        _pick(section, BLE)
        assert not section.saved.is_editing()
        assert _catalog(td).get_saved("Drone link").f0_ghz == 3.6


def test_a_refused_value_leaves_the_edit_open():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _save_one(section)
        section.saved.update_btn.fire("EVT_BUTTON")
        section.freq.type("")  # no frequency: no target
        section.saved.update_btn.fire("EVT_BUTTON")
        assert len(section.errors) == 1 and "pattern frequency" in section.errors[0]
        assert section.saved.is_editing() and section.freq.shown is True
        assert _catalog(td).get_saved("Drone link").f0_ghz == 3.6


def test_update_only_offers_itself_for_the_users_own_targets():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _save_one(section)
        assert section.saved.update_btn.shown is True
        _pick(section, BLE)  # a built-in can be neither changed nor removed
        assert section.saved.update_btn.shown is False
        _pick(section, Applications.CUSTOM)
        assert section.saved.update_btn.shown is False


def test_delete_only_offers_itself_for_the_users_own_targets():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _type_custom(section)
        section.saved.save_btn.fire("EVT_BUTTON")
        assert section.saved.delete_btn.shown is True
        _pick(section, BLE)
        assert section.saved.delete_btn.shown is False


def test_deleting_leaves_custom_holding_the_numbers():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td, answers=("Drone link", True))
        _type_custom(section, freq="3.6", bandwidth="200")
        section.saved.save_btn.fire("EVT_BUTTON")
        section.saved.delete_btn.fire("EVT_BUTTON")
        assert section.app.GetStringSelection() == Applications.CUSTOM
        assert "Drone link" not in section.app.items
        assert section.freq.GetValue() == "3.6"  # savable straight back
        assert section.bandwidth.GetValue() == "200"


def test_a_pick_that_vanished_falls_back_to_custom():
    # The settings file names a target another session deleted: the form drops
    # to Custom… with its own numbers rather than designing for something else.
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        section.restore({"app": "Gone", "freq": "1.8", "bandwidth": "50"})
        assert section.app.GetStringSelection() == Applications.CUSTOM
        assert section.current_application().f0_ghz == 1.8


# --------------------------------------------------------------------------- #
# The return loss is a field, not a constant
#
# It is what the match is judged against *and* the depth the match bandwidth is
# measured at (design.measure.match_db), so a target that wants 15 dB has to be
# able to say so -- GPS L1 is the built-in that does.
# --------------------------------------------------------------------------- #
def test_a_pick_with_a_tighter_spec_fills_its_own_return_loss():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _pick(section, "GPS L1 (1.575 GHz)")
        assert section.return_loss.GetValue() == "15"
        assert section.current_application().return_loss_db == 15.0


def test_a_typed_return_loss_is_the_target_it_is_judged_against():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _type_custom(section, return_loss="20")
        assert section.current_application().return_loss_db == 20.0


def test_a_blank_return_loss_leaves_the_match_shown_but_not_judged():
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _type_custom(section, return_loss="")
        assert section.current_application().return_loss_db is None


def test_the_return_loss_survives_the_settings_file():
    # snapshot -> restore is how the window and the command line share one
    # form; a field that does not round-trip is one the CLI cannot set.
    with tempfile.TemporaryDirectory() as td:
        section = _section(td)
        _type_custom(section, return_loss="15")
        data = section.snapshot()
        assert data["return_loss"] == "15"
        other = _section(td)
        other.restore(data)
        assert other.return_loss.GetValue() == "15"
        assert other.current_application().return_loss_db == 15.0


if __name__ == "__main__":
    run_module_tests(globals())
