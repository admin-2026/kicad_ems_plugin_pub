"""The closed lists: the table, and the verb that prints it.

A picker is the one kind of knob whose *value* used to be private to the
window -- the settings file held the caption the widget drew, under a key of
the widget's own, and nothing outside the wx section could say what else it
would have accepted. So what these check is the property that replaced that:
one vocabulary, readable from outside.

  * a value is a word the runner's config takes, and every shared list's key
    is a real config knob;
  * ``index`` reads a value *or* the caption an older window saved, so a
    settings file written before this survives being opened;
  * the guide prints every list -- the product's own included -- so a caller
    editing a settings file can see what a pick may be without a window.

No wx and no board: the table is stdlib data and the page renders in-process.

    python3 tests/test_choices.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402
from clirun import run as _run  # noqa: E402

choices = load("emkit.choices")
config = load("emkit.config")
guide = load("emkit.agent.guide")

# One list to exercise the shapes on, named rather than indexed: the metal
# model is the list this whole slice started from.
MODEL = choices.COPPER_MODEL


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #
def test_every_list_is_a_key_a_label_a_line_and_some_values():
    """Walked off ``pickers()`` -- the product's own included -- so a list
    added tomorrow is held to this the day it lands."""
    for pick in choices.pickers():
        assert pick.key and " " not in pick.key, pick
        assert pick.key.islower(), f"{pick.key}: a config key, not a caption"
        assert pick.label and pick.what, pick.key
        assert pick.what.endswith("."), f"{pick.key}: one line, ending in a stop"
        assert pick.options, pick.key
        for value, note in pick.options:
            assert value and isinstance(note, str), pick.key


def test_no_list_offers_one_value_twice():
    for pick in choices.pickers():
        values = pick.values()
        assert len(set(values)) == len(values), pick.key


def test_every_list_starts_on_one_of_its_own_values():
    """A default outside the list would put a fresh form on a pick it cannot
    save -- and ``index`` falls back to it, so it would take every unknown
    value down with it."""
    for pick in choices.pickers():
        assert pick.default in pick.values(), pick.key


def test_two_lists_never_share_a_key():
    keys = [pick.key for pick in choices.pickers()]
    assert len(set(keys)) == len(keys), keys


def test_the_shared_lists_are_config_knobs():
    """The point of the key: what the window saves is what the runner reads.
    A shared list naming something ``config.py`` does not emit would be a
    vocabulary for nobody."""
    for pick in choices.SHARED:
        assert pick.key in config.ConfigWriter.DEFAULTS, pick.key


# --------------------------------------------------------------------------- #
# Labels, values, and reading an old file
# --------------------------------------------------------------------------- #
def test_a_label_leads_with_the_value():
    """What the picker shows: the config's word first, its gloss after -- the
    value is the name, the note is the explanation."""
    assert MODEL.labels()[MODEL.index("sibc")].startswith("sibc — ")


def test_a_value_with_no_note_is_its_own_label():
    bare = choices.Choices("k", "K", "What.", (("only", ""),), "only")
    assert bare.labels() == ["only"]


def test_a_pick_round_trips_through_its_index():
    """What a picker does between one save and the next restore."""
    for pick in choices.pickers():
        for value in pick.values():
            assert pick.value(pick.index(value)) == value, (pick.key, value)


def test_a_caption_an_older_window_saved_still_selects_its_value():
    """The migration this table exists for: settings files hold
    ``sibc — skin-effect loss`` where they now hold ``sibc``."""
    for pick in choices.pickers():
        for label, value in zip(pick.labels(), pick.values()):
            assert pick.value(pick.index(label)) == value, (pick.key, label)


def test_an_unknown_pick_restores_the_default_and_not_its_neighbour():
    """A value dropped from a list must not silently become whatever took its
    place -- that is a run simulating something nobody asked for."""
    for pick in choices.pickers():
        for gone in ("", "no-such-value", "sheet — a caption from another list"):
            assert pick.value(pick.index(gone)) == pick.default, (pick.key, gone)


def test_no_selection_at_all_is_the_default():
    """wx answers -1 for an empty pick; so does an index past the end."""
    assert MODEL.value(-1) == MODEL.default
    assert MODEL.value(len(MODEL.options)) == MODEL.default


# --------------------------------------------------------------------------- #
# ...and where a caller reads them: the guide's own section
# --------------------------------------------------------------------------- #
def test_the_guide_prints_every_list_and_every_value():
    """The vocabulary has to be readable by something that has never seen the
    window -- that is the whole point of a value being a word and not a
    caption. It is a section of the one page that needs no board."""
    text = guide.form_options()
    for pick in choices.pickers():
        assert pick.key in text and pick.label in text, pick.key
        for value, note in pick.options:
            assert value in text, value
            assert note in text, note


def test_the_guide_says_which_value_a_form_starts_on():
    assert guide.form_options().count("(default)") == len(choices.pickers())


def test_the_lists_reach_the_page_itself():
    """Not just the section in isolation: a section nobody calls is a table
    nobody reads."""
    code, out, err = _run(["guide"])
    assert code == 0, err
    for pick in choices.pickers():
        assert pick.key in out, pick.key


if __name__ == "__main__":
    run_module_tests(globals())
