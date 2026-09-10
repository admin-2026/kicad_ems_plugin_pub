"""``guide``: the one page a caller with no context reads first.

Three things are worth holding onto, and none of them is the prose.

**It has to run before anything is known.** No board, no ``pcbnew``, no
recorded interpreter -- it is the first command typed, and a guide that needed
what it exists to explain would fail exactly where it is needed.

**It has to be findable.** An agent's first move on an unknown command is
``--help``, so the guide leads the verb table and every failure names it.
That is one tuple index and one line, and both are the kind of thing a
refactor loses silently.

**It has to stay true.** The verb table is generated off ``VERBS``, so it
cannot drift; the folder beside the board is prose, so a test asserts every
filename it names is still spelled in the module that owns it. A guide naming
a file that has been renamed is *wrong*, which is worse than thin.

Nothing here asserts what the page says. A test that greps for a sentence pins
the wording and rots on the first edit -- whether a cold reader can actually
get to a verdict from this page is answered by handing it to one.

    python3 tests/test_agent_guide.py   (or pytest)
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import CORE, PRODUCT, load, run_module_tests  # noqa: E402
from clirun import run as _run  # noqa: E402  (one command, streams captured)

guide = load("emkit.agent.guide")
materials = load("emkit.materials.catalog")
store = load("emkit.userlib.store")
formparams = load("emkit.formparams")
jobs = load("emkit.sim.jobs")
runjob = load("runjob")
runlock = load("emkit.sim.runlock")
shim = load("emkit.agent.shim")
simulate = load("emkit.sim.simulate")
verbs = load("emkit.agent.verbs")


def _kinds():
    """Every kind of saved entry this install offers: the shared pane's, then
    whatever the product keeps a picker of its own for.

    Worked out here rather than read off ``guide.saved_kinds()`` -- a test that
    asked the page which kinds to look for could not tell a missing one from a
    page that had stopped looking.
    """
    kinds = (materials.MetalCatalog, materials.SubstrateCatalog, materials.MaskCatalog)
    return kinds + tuple(runjob.saved_catalogs())


# --------------------------------------------------------------------------- #
# It answers, and it answers without KiCad
# --------------------------------------------------------------------------- #
def test_the_guide_needs_no_board():
    code, out, err = _run(["guide"])
    assert code == 0, err
    assert len(out.splitlines()) > 40, "a briefing, not a sentence"


def test_assembling_the_page_never_reaches_for_pcbnew():
    """The regression a user only ever finds by being new: the first command
    anyone types, refusing to run on the Python they happen to have."""
    # Whether it was already there is another test's business (the board
    # suites stand a fake one in); what this says is that assembling the page
    # does not go looking for it.
    before = "pcbnew" in sys.modules
    guide.page()
    assert before == ("pcbnew" in sys.modules), "the guide imported pcbnew"


def test_no_placeholder_reaches_the_reader():
    """The preamble is a file with ``{{token}}``s substituted at print time
    (never at assemble time -- this command line *is* the render step). A
    leftover token is a page that reads like a template."""
    text = guide.page()
    assert "{{" not in text and "}}" not in text
    assert shim.STEM in text, "the page has to spell the command it is about"


# --------------------------------------------------------------------------- #
# Findable
# --------------------------------------------------------------------------- #
def test_the_guide_leads_the_verb_table():
    """One tuple index, and it is the whole discovery mechanism: ``--help``
    prints VERBS in order and the first line under the positional arguments is
    the one that gets read."""
    assert verbs.VERBS[0].NAME == "guide"


def test_help_names_the_guide_before_any_other_verb():
    code, out, _ = _run(["--help"])
    assert code in (0, None)
    positions = [out.index(verb.NAME) for verb in verbs.VERBS if verb.NAME in out]
    assert positions and positions[0] == min(positions)
    assert "guide" in out


def test_a_verbs_help_says_what_it_is_for_not_what_it_prints():
    """The one line that decides whether the verb is ever run."""
    help_line = verbs.VERBS[0].HELP
    assert "Start here" in help_line and len(help_line) > 30


def test_every_failure_points_at_the_guide():
    """A caller that fumbles its first invocation is reading this message and
    nothing else."""
    _code, _out, err = _run(["nosuchverb"])
    assert "guide" in err
    _code, out, _err = _run(["--json", "nosuchverb"])
    assert "guide" in json.loads(out)["guide"]


def test_the_parser_itself_points_at_the_guide():
    _code, out, _err = _run(["--help"])
    assert "New here?" in out


# --------------------------------------------------------------------------- #
# True
# --------------------------------------------------------------------------- #
def test_the_page_names_every_verb_the_parser_offers():
    """Generated off VERBS, so a verb added tomorrow is on the page the day it
    lands -- and this is what says so."""
    text = " ".join(guide.page().split())
    for verb in verbs.VERBS:
        for topic in getattr(verb, "TOPICS", ()) or ("",):
            spelling = f"{verb.NAME} {topic}".strip()
            assert spelling in text, f"the guide does not name {spelling!r}"


def test_every_file_the_page_names_is_still_called_that():
    """The folder beside a board is described in prose, because resolving it
    would need a board object and the guide must run without one. So the
    anti-drift is here: each name, and the module that owns it."""
    text = guide.page()
    owners = {
        "settings.yaml": CORE / "settings.py",
        "pcb.yaml": CORE / "sim" / "runner.py",
        runlock.DIRNAME: CORE / "sim" / "runlock.py",
        # The two files a run keeps beside its dumps, now that one folder is
        # the whole of a run and the id names it.
        jobs.FILE: CORE / "sim" / "jobs.py",
        jobs.LOG: CORE / "sim" / "jobs.py",
    }
    for name, owner in owners.items():
        assert name in text, f"the guide no longer names {name}"
        assert name in owner.read_text(encoding="utf-8"), (
            f"{name} is not spelled in {owner.name} any more -- the guide is "
            "now wrong rather than merely thin"
        )
    # The one name in that table that is *not* prose: it is the product's own
    # (pcb_data / scattering_data), so the page reads it rather than saying it.
    assert simulate.DUMPS[simulate.REPORT] in text


def test_every_key_that_holds_a_number_says_what_it_is_in():
    """The gap this closes: the key list printed `freq:`, `bandwidth:` and
    `time:` bare, and nothing on the page -- or anywhere else without a
    window -- said gigahertz, megahertz or nanoseconds. A reader learned the
    unit from an error message, or from the source.

    So every key a fresh form holds that is not a bool carries a note. Which
    ones those are is read off the form itself, so a key added tomorrow is
    held to this the day it lands."""
    form = dict(formparams.defaults())
    form.update(runjob.form_starter())
    notes = guide.key_notes()
    for key, value in sorted(form.items()):
        if value in ("true", "false"):
            continue  # a bool's name is the whole of what it is
        assert notes.get(key), f"{key} takes a value and nothing says what it is"


def test_a_keys_note_is_printed_on_the_line_the_key_is_on():
    """Derived notes are worth nothing in a table nobody can read them in:
    each one belongs beside its own key, behind a `#` -- which is a comment in
    the very file being described, so a line of the page can be pasted into
    one and stay legal."""
    page = guide.page()
    for key, note in guide.key_notes().items():
        line = next(
            (one for one in page.splitlines() if one.startswith(f"  {key}:")), ""
        )
        assert line, f"{key} has a note and is not on the page"
        assert line.endswith(f"# {note}"), line


def test_the_page_names_every_file_the_user_can_save_into():
    """The saved entries are the one input that is neither the board nor the
    folder beside it, and the section is generated off the catalogs -- so a
    kind left out of it (or a file renamed) is caught here.

    The kinds are the shared pane's plus whatever this product offers
    (``_kinds``), never what the page itself thinks they are."""
    text = guide.page()
    for kind in _kinds():
        assert str(store.UserStore(kind.FILENAME).path) in text, kind.FILENAME
        for field in kind.FIELDS:
            assert field in text, f"{kind.NOUN} saves {field}, unsaid on the page"


def test_every_name_a_picker_offers_is_on_the_page_with_what_it_stands_for():
    """The gap this section was written for: a settings file holds a *name*
    (`FR-4`), and a caller with no window had nothing that said what else it
    would have taken or what that one meant. So the built-in table is printed,
    numbers and all -- and a name printed without its numbers would be the old
    problem with more lines."""
    text = guide.page()
    for kind in _kinds():
        catalog = kind()
        for name in catalog.builtin_names():
            assert name in text, f"{catalog.NOUN}: {name!r} is offered, unprinted"
            entry = catalog.get(name)
            if entry is None:
                continue  # the sentinel: it stands for no record, and says so
            for value in catalog.fields_of(entry).values():
                assert guide._number_text(value) in text, (name, value)
        assert catalog.CUSTOM in text, catalog.NOUN


def test_the_rule_a_hand_edited_record_is_held_to_is_printed_with_the_file():
    """The page names the file and invites a reader to edit it, and a record
    that breaks its kind's rule is dropped in silence -- so the rule travels
    with the path. Taken off ``check`` itself, which is the same call that
    refuses a save, so the page cannot describe a rule the file is not held
    to."""
    text = guide.page()
    for kind in _kinds():
        assert guide._rule(kind()) in text, kind.FILENAME


def test_a_saved_entry_is_listed_beside_the_built_ins_and_marked_as_theirs():
    """What the user added is a legal value like any other, so it is on the
    page like any other -- and flagged, because it is the half of the list that
    lives in a file a reader may open."""
    with tempfile.TemporaryDirectory() as directory:
        home = store.config_home
        store.config_home = lambda: pathlib.Path(directory)
        try:
            materials.MetalCatalog().save("House foil", sigma=4.5e7)
            text = guide.page()
        finally:
            store.config_home = home
    assert "House foil" in text
    assert guide._number_text(4.5e7) in text
    assert guide.SAVED in text, "nothing said which row was the user's own"


def test_the_page_names_no_kind_this_product_has_not_got():
    """A kind is on the page because the *product* offers it, never because the
    core could import it. That was the bug: one page listed the catalogs it
    could reach, so a signal-integrity user was told where their design targets
    were kept, of which there are none.

    Asked by taking the product's kinds away and re-rendering, which is a
    question every product can answer -- including one whose answer is already
    ``()``, where it says the material kinds do not come through this seam."""
    mine = tuple(runjob.saved_catalogs())
    real = runjob.saved_catalogs
    runjob.saved_catalogs = lambda: ()
    try:
        without = guide.page()
    finally:
        runjob.saved_catalogs = real
    for kind in mine:
        assert str(store.UserStore(kind.FILENAME).path) not in without, (
            f"{kind.FILENAME} is on a page whose product no longer offers it"
        )
    for kind in (materials.MetalCatalog, materials.MaskCatalog):
        assert str(store.UserStore(kind.FILENAME).path) in without, kind.FILENAME


def test_every_path_the_map_prints_exists():
    """The map is resolved off this install rather than written down, so it is
    true on whatever machine it prints on -- provided nothing has moved. A
    file relocated by tools/assemble.py fails here."""
    for name, _what in guide.CODE_MAP:
        path = pathlib.Path(guide.ROOT).joinpath(*name.split("/"))
        assert path.exists(), path


def test_the_map_is_a_pointer_and_not_a_listing():
    """Pointed at a tree an agent will crawl it. Three entries is the budget:
    a verb's module, what the verbs call, and the human's page."""
    assert len(guide.CODE_MAP) <= 4


# --------------------------------------------------------------------------- #
# The product's half
# --------------------------------------------------------------------------- #
def test_the_product_answers_the_seam():
    """``()`` is a legal answer -- a product is not forced to invent prose --
    but what comes back has to be sections."""
    sections = guide.product_sections()
    assert isinstance(sections, tuple)
    for title, body in sections:
        assert title and body, title
        assert "\n" not in title, title


def test_the_page_is_this_products_own():
    assert PRODUCT.NAME in guide.page()


if __name__ == "__main__":
    run_module_tests(globals())
