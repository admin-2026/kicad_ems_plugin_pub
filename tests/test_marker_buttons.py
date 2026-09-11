"""What the two marker buttons show and say (no KiCad, real wx stubbed).

Both marker sections put a drawing of their own on the board and then leave
the user in the PCB editor with it, so three things have to be visible from the
plugin window:

* what the button is about to place -- the Feed marker box wears a picture of
  the marker beside its button (tools/icons/markers.py draws it), because the
  flow that follows hands the footprint to KiCad's paste tool and asks for a
  click on the board;
* that a marker is already there -- with one on the board the button stops
  offering to place a second (it never would) and offers to show the one that
  exists, so the user learns it before the press rather than after;
* where that marker is -- pressing it takes the PCB editor to the marker
  (gui.reveal) and the status line leads with its location, layer and size.
  A KiCad that can't be taken there says so in words instead.

The last two are one code path for both sections (marker._sync_button /
_show_already_placed over each section's ``_placed_text``), so they are checked
on both: the feed marker's line names its position, the area marker's the
rectangle it decoded.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_marker_buttons.py
"""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

area_section = load("gui.sections.area")
marker_section = load("emkit.gui.sections.marker")
area_marker = load("markers.area_marker")
feed_marker = load("emkit.markers.feed_marker")
registry = load("design.registry")
reveal = load("emkit.gui.reveal")

wx = wx_stub.wx
pcbnew = sys.modules["pcbnew"]
_SIZER = type(wx.BoxSizer())


class _FakeMarker:
    """A placed marker, as far as these tests' code paths ask: the graphics the
    layer lookup walks (none, so no layer switch is attempted). A footprint's
    accessor, not a group's -- the area marker's own group path is exercised
    against a fake board in test_area_drag.py."""

    def GraphicalItems(self):
        return []


# --------------------------------------------------------------------------- #
# Sections, off the board
# --------------------------------------------------------------------------- #
class _Page:
    """Just what a marker section reads off its page."""

    def __init__(self):
        self.scroll = None
        self.wrapped = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def _relayout_scroll(self):
        pass


class _WizardPage(_Page):
    """... plus what the area section reads off a designer page."""

    class _Host:
        def target_freq_ghz(self, default=None):
            return 2.45

        def marker_layer_n(self):
            return 2

    def __init__(self):
        super().__init__()
        self.design = registry.DESIGNS[0]
        self.host = self._Host()
        self.scan = None

    def refresh_area_checks(self):
        pass


def _feed_section():
    """A feed-marker section with the marker-layer picker the Advanced pane
    would add (the buttons ask it which layer they are placing on)."""
    section = marker_section.FeedMarkerSection(_Page(), wx.BoxSizer())
    section.build_layer_picker(None, wx.FlexGridSizer())
    return section


def _area_section():
    """An area section with the marker-layer picker the Advanced pane would
    add (its status line names the layer through it)."""
    section = area_section.AreaSection(_WizardPage(), wx.BoxSizer())
    section.build_layer_picker(None, wx.FlexGridSizer())
    return section


@contextlib.contextmanager
def _patch(module, **attrs):
    """Swap module functions out for the test's own and put the originals back
    -- the marker modules are shared with every other test in the process."""
    saved = {name: getattr(module, name) for name in attrs}
    for name, value in attrs.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


def _status(section):
    return section._status_label.GetLabel()


# --------------------------------------------------------------------------- #
# The picture beside the Generate button
# --------------------------------------------------------------------------- #
def _marker_box(section_class, page):
    """A marker section built into a body of its own, and the box it filled --
    so a test can read back the order its rows were added in."""
    body = wx.BoxSizer()
    section = section_class(page, body)
    return section, body.items[0]


def _button_row(box, button):
    """Where ``button`` sits among a marker box's rows: it is added either on
    its own (the area marker) or in a row beside the marker picture (the feed
    marker), so a row that contains it counts as its row. Only a sizer is looked
    inside -- a stub widget answers every attribute, ``items`` included."""
    for i, item in enumerate(box.items):
        row = item.items if isinstance(item, _SIZER) else ()
        if item is button or button in row:
            return i
    raise AssertionError("the marker button is not in the box")


def test_the_marker_button_comes_after_the_settings_it_places_with():
    """Both marker boxes read the same way down the page: the settings the
    marker is placed with (sliders, layer pickers), then the button that puts
    it on the board, then the status line saying what landed."""
    for section, box in (
        _marker_box(marker_section.FeedMarkerSection, _Page()),
        _marker_box(area_section.AreaSection, _WizardPage()),
    ):
        row = _button_row(box, section.marker_btn)
        # The settings come first -- both boxes build more than one row of
        # them (the feed-width slider, then the Feed layer picker).
        assert row >= 2, "the button is above the marker settings"
        # ... and the status line last, under the button (the area box adds its
        # bold edit-hint row under that, which says what to do with what landed).
        tail = [section._status_label]
        if getattr(section, "_hint_label", None) is not None:
            tail.append(section._hint_label)
        assert box.items[row + 1 :] == tail


def test_the_feed_box_shows_a_picture_of_the_marker():
    section = _feed_section()
    picture = section.build_marker_icon(
        None, marker_section.ICON_FILE, marker_section.ICON_TIP
    )
    assert picture is not None, "the marker drawing is not bundled"
    # Loaded at the size the section shows it, off the bundled PNG.
    assert picture.bitmap.image.size == (marker_section.ICON_SIZE,) * 2
    assert picture.bitmap.image.path.endswith(marker_section.ICON_FILE)
    # The words for the drawing live in the tooltip, as the scan rows' do.
    assert "toward the antenna" in picture.tooltip


def test_a_missing_drawing_costs_no_button():
    """An installation short of a PNG still places markers: the loader answers
    None and the box is laid out without the picture."""
    assert _feed_section().build_marker_icon(None, "not_bundled.png", "") is None


# --------------------------------------------------------------------------- #
# A marker on the board: what the button says, and what pressing it does
# --------------------------------------------------------------------------- #
# The two markers' finders and the decodes their status lines are written from.
FEED_DESCRIBED = {"x_mm": 84.5, "y_mm": 61.25, "layer": "User.2", "width_mm": 1.0}
AREA_DECODED = {
    "area": (10.0, 20.0, 40.0, 32.0),
    "w_mm": 30.0,
    "h_mm": 12.0,
    "edge": "bottom",
    "frac": 0.3,
    "frac_local": 0.3,
    "tri_w_mm": 1.0,
    "layer": "User.2",
    "rot_deg": 0.0,
    "pivot": (0.0, 0.0),
    "angle_deg": 0.0,
}


@contextlib.contextmanager
def _placed(module, fp, shown=True, **finders):
    """``fp`` on the board: the board open, ``module``'s finders answering with
    it, and gui.reveal recording every item it is asked to take the editor to
    (``shown`` is what that attempt reports back -- False is a KiCad the plugin
    can't drive there). Yields the recording list."""
    seen = []

    def reveal_item(window, item):
        seen.append(item)
        return shown

    with _patch(module, placed_markers=lambda board: [fp], **finders):
        with _patch(reveal, reveal_item=reveal_item):
            pcbnew.GetBoard = lambda: object()
            try:
                yield seen
            finally:
                pcbnew.GetBoard = lambda: None


def test_the_button_offers_to_show_the_marker_already_there():
    """Both sections: with a marker on the board the button stops offering to
    place one -- the press would be refused -- and offers to show it, with the
    why in its tooltip. It goes back the moment the board has none."""
    for section, module, finders in (
        (_feed_section(), feed_marker, {"describe_marker": lambda _fp: FEED_DESCRIBED}),
        (_area_section(), area_marker, {"decode_marker": lambda _fp: AREA_DECODED}),
    ):
        with _placed(module, _FakeMarker(), **finders):
            section.refresh_status()
            assert section.marker_btn.GetLabel() == section._BTN_SHOW
            assert "already on the board" in section.marker_btn.tooltip

        section.refresh_status()  # ... and with the board empty again
        assert section.marker_btn.GetLabel() == section._BTN_PLACE
        assert not section.marker_btn.tooltip


def test_generate_takes_the_editor_to_the_feed_marker():
    section = _feed_section()
    fp = _FakeMarker()
    with _placed(
        feed_marker,
        fp,
        check_layer=lambda board, n: 0,
        describe_marker=lambda _fp: FEED_DESCRIBED,
    ) as seen:
        section.on_place_marker()

    assert seen == [fp]  # the editor was taken to that marker
    text = _status(section)
    assert "Shown in the PCB editor" in text
    assert "(84.5, 61.25) mm" in text  # where it is
    assert "User.2" in text  # and on which layer
    assert section.marker_btn.GetLabel() == section._BTN_SHOW


def test_place_takes_the_editor_to_the_area_marker():
    section = _area_section()
    fp = _FakeMarker()
    with _placed(area_marker, fp, decode_marker=lambda _fp: AREA_DECODED) as seen:
        section.on_place()

    assert seen == [fp]
    text = _status(section)
    assert "Shown in the PCB editor" in text
    assert "at (10, 20)" in text  # where it is
    assert "30 × 12 mm" in text  # how big
    assert "User.2" in text


def test_a_kicad_that_cannot_be_taken_there_says_it_in_words():
    """The jump is best effort (gui.reveal): where it doesn't happen the reply
    still names the marker's location, and doesn't claim the editor moved."""
    section = _feed_section()
    with _placed(
        feed_marker,
        _FakeMarker(),
        shown=False,
        check_layer=lambda board, n: 0,
        describe_marker=lambda _fp: FEED_DESCRIBED,
    ):
        section.on_place_marker()

    text = _status(section)
    assert "Shown in the PCB editor" not in text
    assert "Already on the board" in text
    assert "(84.5, 61.25) mm" in text


def test_a_marker_that_no_longer_decodes_says_so():
    """The area marker's location comes from its own drawing, so an edited one
    has none to report -- the reply carries the breakage instead of dropping
    the press silently."""
    section = _area_section()

    def broken(fp):
        raise ValueError("area marker segments do not form a rectangle")

    with _placed(area_marker, _FakeMarker(), decode_marker=broken):
        section.on_place()

    assert "✗" in _status(section)
    assert "do not form a rectangle" in _status(section)


if __name__ == "__main__":
    run_module_tests(globals())
