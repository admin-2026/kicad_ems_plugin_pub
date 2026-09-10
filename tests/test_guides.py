"""The About page's bundled documentation: the two guides and the box that
opens them (no KiCad, no wx).

Two things are worth holding onto here. The first is that a guide stays
*complete*: the settings reference is the one page claiming to list every knob
of the window, and the command-line guide the one page claiming to list every
verb, so a knob added to the Advanced pane or a verb added to agent/verbs and
not to its guide makes that guide wrong rather than merely thin -- these tests
read the labels and the verb table straight out of the code and insist the page
names each of them.

The second is the wiring: the box offers a button per guide, it opens through
the shared help path (gui.viewers.show_guide, the same one a pre-flight
banner's Help button takes), and a guide missing from the install is said on
the section's status line -- the About page has no run log for the message to
land in.

The section is built on the wx stand-in (tests/wx_stub), so what is checked is
what it put in the box, not how wx would lay it out.

    python3 tests/test_guides.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs the stand-in wx)
from bare_package import PKG, load, run_module_tests  # noqa: E402
from helppage import assert_page_loads  # noqa: E402

choices = load("emkit.choices")
options = load("emkit.options")
viewers = load("emkit.gui.viewers")
guides = load("emkit.gui.sections.guides")
clibox = load("emkit.gui.sections.cli")
cli = load("emkit.agent.cli")
shim = load("emkit.agent.shim")
verbs = load("emkit.agent.verbs")
image = load("emkit.sim.container.image")

wx = wx_stub.wx

SETTINGS_PAGE = "settings.html"
CLI_PAGE = "cli.html"
DOCKER_PAGE = "docker.html"


class _Viewers:
    """A stand-in ViewerHub: records what was presented, in which slot."""

    def __init__(self, ok=True):
        self.ok = ok
        self.shown = []

    def present(self, slot, url, title):
        self.shown.append((slot, url, title))
        return self.ok


class _Page:
    """Just what a Section reads off its page -- plus the viewer hub the About
    page borrows from the simulate view."""

    def __init__(self, ok=True):
        self.scroll = object()
        self.viewers = _Viewers(ok)
        self.wrapped = []
        self.logged = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def log(self, text):
        self.logged.append(text)

    def _relayout_scroll(self):
        pass


# --------------------------------------------------------------------------- #
# the guide itself
# --------------------------------------------------------------------------- #
def test_the_settings_guide_is_plain_offline_html():
    """The shared rule for every bundled guide lives in tests/helppage.py."""
    text = assert_page_loads(SETTINGS_PAGE)
    assert "Settings" in text


def test_the_settings_guide_was_given_this_products_half():
    """The shared page describes the shared boxes and carries a token where the
    product's own go; ``tools/assemble.py`` (stage_help) splices in the
    fragment beside that plugin's code. A leftover token is that step not
    having run -- and it would leave a reference with this window's own boxes
    missing from it, which is the drift the split was made to end."""
    text = assert_page_loads(SETTINGS_PAGE)
    assert "{{" not in text, "an unsubstituted token reached the install"


def test_no_fragment_ships_as_a_page():
    """A ``.part.html`` is half a document -- no <html>, no stylesheet -- and
    is spliced, then dropped from the staged tree. One left behind is a file a
    reader can open and find broken, the same reason another product's viewer
    pages are deleted rather than shipped unused."""
    stray = sorted(p.name for p in PKG.rglob("*.part.html"))
    assert stray == [], f"fragments shipped as pages: {stray}"


def test_it_names_every_advanced_field():
    """The Advanced pane's numeric knobs, by the label the pane itself shows --
    add a field to options.ADV_GROUPS and this is what says the guide has not
    caught up."""
    text = assert_page_loads(SETTINGS_PAGE)
    for _key, label, _hint in options.ADV_FIELDS:
        assert label in text, f"the settings guide does not name {label!r}"


def test_it_names_every_advanced_group():
    text = assert_page_loads(SETTINGS_PAGE)
    for group in options.ADV_GROUPS.values():
        assert group.title in text, f"no section for the {group.title} box"


def test_it_names_the_pickers_choices():
    """Every closed list the pane draws, value by value (emkit.choices) -- the
    metal models and the ground check's modes. The page has to name each one,
    because a value it leaves out is one a user cannot look up anywhere except
    by opening the picker."""
    text = assert_page_loads(SETTINGS_PAGE)
    for picker in choices.SHARED:
        assert picker.label in text, picker.label
        for value in picker.values():
            assert value in text, value


def test_it_quotes_the_speed_sliders_default_stop():
    """The one default the guide can't paraphrase: the slider's stops are
    captioned with their own settings, so the guide repeats that caption
    verbatim and this catches a moved SPEED_DEFAULT (or a retuned stop).
    Whitespace is normalised -- the guide wraps the caption over lines."""
    text = " ".join(assert_page_loads(SETTINGS_PAGE).split())
    assert options.SPEED_PRESETS[options.SPEED_DEFAULT].desc in text
    assert len(options.SPEED_PRESETS) == 7, "the guide says seven stops"


# --------------------------------------------------------------------------- #
# the command-line guide
# --------------------------------------------------------------------------- #
def test_the_command_line_guide_is_plain_offline_html():
    text = assert_page_loads(CLI_PAGE)
    assert "versions" in text, "the guide has to give the one command"


def test_its_examples_are_spelled_with_this_products_shortcut():
    """The guide's examples are copied, so they name the shortcut this install
    actually writes -- ``tools/assemble.py`` (stage_help) substitutes it into
    the core's page on the way into the checkout, because the core may not
    spell a product's name. A leftover token is that step not having run."""
    text = assert_page_loads(CLI_PAGE)
    assert f"{shim.STEM} versions" in text, "the guide names another shortcut"
    assert "{{" not in text, "an unsubstituted token reached the install"


def test_it_names_every_verb_the_cli_offers():
    """The guide is the only thing a reader with a shell has, and agent/verbs
    is where a verb is really added -- so a verb (or a topic) that reached the
    parser and not the guide is caught here rather than by somebody typing
    --help and finding something nobody documented."""
    text = " ".join(assert_page_loads(CLI_PAGE).split())
    for verb in verbs.VERBS:
        for topic in getattr(verb, "TOPICS", ()) or ("",):
            spelling = f"{verb.NAME} {topic}".strip()
            assert spelling in text, f"the CLI guide does not name {spelling!r}"


def test_every_option_its_examples_type_is_one_that_exists():
    """The example commands are the part a reader copies, so a flag the page
    invented -- or one that has since been renamed -- is worse there than
    anywhere else on it. The options come from the verbs themselves, the way
    the parser builds them."""
    import argparse
    import re

    real = {cli.JSON_FLAG, "--help"}

    def collect(parser):
        for action in parser._actions:
            real.update(action.option_strings)
            # A verb whose topics are parsers of their own (verbs/run.py) keeps
            # its flags one level down, and those are the flags the page types.
            if isinstance(action, argparse._SubParsersAction):
                for topic in action.choices.values():
                    collect(topic)

    for verb in verbs.VERBS:
        parser = argparse.ArgumentParser()
        verb.add_arguments(parser)
        collect(parser)

    text = assert_page_loads(CLI_PAGE)
    for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text)):
        assert flag in real, f"the CLI guide types {flag}, which no verb takes"


# --------------------------------------------------------------------------- #
# the container guide
# --------------------------------------------------------------------------- #
def test_the_container_guides_examples_name_this_products_own_image():
    """Its examples are `docker run <image> ...` lines meant to be copied, so
    the image has to be the one this install builds -- which the core may not
    spell, and tools/assemble.py substitutes on the way into the checkout (the
    same staging that writes the command-line shortcut). This is also what
    holds assemble's spelling of the tag against sim.container.image's."""
    text = assert_page_loads(DOCKER_PAGE)
    assert f"{image.latest()}" in text, "the guide names another image"
    assert f"{shim.STEM} preflight" in text, "the guide names another shortcut"
    assert "{{" not in text, "an unsubstituted token reached the install"


def test_the_container_guide_says_where_the_recipe_is():
    # The one file in this feature a user may want to edit, and the one that
    # is genuinely hard to find: it lives inside an install whose folder KiCad
    # chose.
    text = assert_page_loads(DOCKER_PAGE)
    assert "emkit/sim/container/Dockerfile" in text


# --------------------------------------------------------------------------- #
# the box on the About page
# --------------------------------------------------------------------------- #
def test_the_box_offers_a_button_per_guide():
    body = wx.BoxSizer()
    guides.GuidesSection(_Page(), body)
    labels = [w.GetLabel() for w in _flatten(body)]
    for label, _file, _title, tip in guides.GUIDES:
        assert label in labels, label
        assert tip, f"{label}: a button says what it opens"


def test_each_guide_is_offered_where_it_belongs():
    """Named by file, so a rename that skips the HTML is caught here rather
    than by an empty viewer. The command-line guide is not in this box: it
    moved to the box that installs the command line's shortcut, where a reader
    is already looking at the thing it explains."""
    offered = [entry[1] for entry in guides.GUIDES]
    assert SETTINGS_PAGE in offered
    assert CLI_PAGE not in offered, "the CLI guide belongs to the command-line box"
    assert clibox.GUIDE[1] == CLI_PAGE


def test_pressing_a_button_opens_the_guide_in_the_help_window():
    page = _Page()
    body = wx.BoxSizer()
    section = guides.GuidesSection(page, body)
    _button(body, "Settings reference").fire("EVT_BUTTON")

    ((slot, url, title),) = page.viewers.shown
    assert slot == viewers.HELP, "a guide never replaces a report"
    assert url.startswith("file://") and url.endswith("/" + SETTINGS_PAGE)
    assert title == "Settings reference"
    # The status line stays on what the buttons do; nothing went wrong.
    assert section._status_label.GetLabel() == guides.GuidesSection._NOTE


def test_a_missing_guide_is_said_on_the_status_line():
    """A partial install: the About page has no run log, so the section's own
    line has to carry it -- and it names the guide that isn't there."""
    page = _Page()
    body = wx.BoxSizer()
    section = guides.GuidesSection(page, body)
    original = guides.show_guide
    guides.show_guide = lambda *args, **kwargs: False
    try:
        _button(body, "Settings reference").fire("EVT_BUTTON")
    finally:
        guides.show_guide = original
    assert "Settings reference" in section._status_label.GetLabel()
    assert "missing" in section._status_label.GetLabel()


def test_the_shared_help_path_reports_a_page_that_is_not_installed():
    """viewers.show_guide is what both the banner and this box call: an asset
    that isn't there is a logged line and a False, never a blank viewer."""
    page = _Page()
    assert viewers.show_guide(page, "no-such-guide.html", "Nope") is False
    assert not page.viewers.shown
    assert any("no-such-guide.html" in line for line in page.logged)


def _flatten(sizer):
    """Every widget under ``sizer``, its nested sizers walked through."""
    out = []
    for item in sizer.items:
        if isinstance(item, wx.BoxSizer):  # every stand-in sizer is this class
            out.extend(_flatten(item))
        else:
            out.append(item)
    return out


def _button(sizer, label):
    return next(w for w in _flatten(sizer) if w.GetLabel() == label)


if __name__ == "__main__":
    run_module_tests(globals())
