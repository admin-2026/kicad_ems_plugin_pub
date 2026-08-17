"""The About page's bundled documentation: the settings reference and the box
that opens it (no KiCad, no wx).

Two things are worth holding onto here. The first is that the reference stays
*complete*: it is the one page claiming to list every knob of the window, so a
knob added to the Advanced pane and not to the guide makes the guide wrong
rather than merely thin -- these tests read the field labels straight out of
gui.options and insist the page names each of them.

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
from bare_package import load, run_module_tests  # noqa: E402
from helppage import assert_page_loads  # noqa: E402

options = load("gui.options")
viewers = load("gui.viewers")
guides = load("gui.sections.guides")

wx = wx_stub.wx

SETTINGS_PAGE = "settings.html"


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
    """The two closed lists a user picks from: the metal models and the ground
    check's modes."""
    text = assert_page_loads(SETTINGS_PAGE)
    for name, _desc in options.MODELS:
        assert name in text, name
    for mode in options.GROUND_CHECKS:
        assert mode in text, mode


def test_it_quotes_the_speed_sliders_default_stop():
    """The one default the guide can't paraphrase: the slider's stops are
    captioned with their own settings, so the guide repeats that caption
    verbatim and this catches a moved SPEED_DEFAULT (or a retuned stop).
    Whitespace is normalised -- the guide wraps the caption over lines."""
    text = " ".join(assert_page_loads(SETTINGS_PAGE).split())
    assert options.SPEED_PRESETS[options.SPEED_DEFAULT].desc in text
    assert len(options.SPEED_PRESETS) == 7, "the guide says seven stops"


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


def test_the_settings_reference_is_one_of_them():
    """The guide this box exists for -- named by file, so a rename that skips
    the HTML is caught here rather than by an empty viewer."""
    assert SETTINGS_PAGE in [entry[1] for entry in guides.GUIDES]


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
