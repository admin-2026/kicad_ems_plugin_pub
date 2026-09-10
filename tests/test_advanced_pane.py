"""The Advanced pane's layout, against the tables and the sections it serves.

The pane is sorted by function: one titled box per options.ADV_GROUPS entry,
built by its own method in gui.sections.advanced. Grouping is where a knob can
silently go missing -- a field left out of every group is typed by nobody and
reaches no config -- so these check that the boxes and the fields still add up,
and that both marker sections get the layer picker the pane builds for them
(the simulate view's feed marker, a designer's area marker) -- one pick behind
the two widgets, since both markers go on the same User layer.

Real wx is stubbed (see wx_stub.py); no KiCad, no board.

    python3 tests/test_advanced_pane.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx / pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

choices = load("emkit.choices")
options = load("emkit.options")
theme = load("emkit.gui.theme")
advanced = load("emkit.gui.sections.advanced")
marker = load("emkit.gui.sections.marker")
area = load("gui.sections.area")
registry = load("design.registry")
config = load("config")
wx = wx_stub.wx
_SIZER = type(wx.BoxSizer())


class _Form:
    """The Pattern-frequency section, as far as this pane reads it."""

    def update_hint(self, *args):
        pass


class _Speed:
    """The Speed/accuracy slider: the pane binds every optimization widget to
    its override handler, which is what snaps the slider to "Custom"."""

    def __init__(self):
        self.overrides = 0

    def on_override(self, *args):
        self.overrides += 1


class _MarkerSection:
    """A marker section, standing in for whichever one the page carries: it
    owns the layer picker the Advanced pane builds into its Markers box."""

    def __init__(self):
        self.grid = None

    def build_layer_picker(self, pane, grid):
        self.grid = grid
        self.marker_layer = wx.Choice(pane, choices=marker.MARKER_LAYERS)
        self.marker_layer.SetSelection(marker.MARKER_LAYER_DEFAULT)
        grid.Add(self.marker_layer)


class _Page:
    """Just what the Advanced section reads off its page."""

    def __init__(self, feed_section=None):
        self.scroll = object()
        self.form = _Form()
        self.speed = _Speed()
        self.feed_section = feed_section
        self.wrapped = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def _relayout_scroll(self):
        pass

    def _on_pane_changed(self, *args):
        pass


def _section(feed_section=None):
    page = _Page(feed_section)
    return advanced.AdvancedSection(page, wx.BoxSizer())


class _WizardPage(_Page):
    """What the area section reads off its designer page: the design it is
    sizing a starter rectangle for, and the target frequency."""

    class _Host:
        def target_freq_ghz(self, default=None):
            return 2.45

    def __init__(self):
        super().__init__()
        self.design = registry.DESIGNS[0]
        self.host = self._Host()

    def refresh_area_checks(self):
        pass


def _area_section():
    """A real area section, off the board (no marker placed: pcbnew is
    stubbed, so GetBoard() answers None)."""
    return area.AreaSection(_WizardPage(), wx.BoxSizer())


def _feed_section():
    """A real feed-marker section (the simulate view's), off the board."""
    return marker.FeedMarkerSection(_Page(), wx.BoxSizer())


def _labels(sizer):
    """Every label in a sizer tree, nested sizers walked. The config key a knob
    shows is a greyed label of its own beside it (gui.theme.with_key), so this
    is how a test sees what the pane says."""
    out = []
    for item in sizer.items:
        out += _labels(item) if isinstance(item, _SIZER) else [item.GetLabel()]
    return out


def _boxes(section):
    """The titles of the boxes the pane built, in order (the note label under
    them is not a box). A group is a plain sizer led by its heading label
    (gui.theme.group_box), so the title is the label of its first item."""
    pane_sizer = section.adv_pane.GetPane().sizer
    titles = []
    for item in pane_sizer.items:
        if isinstance(item, _SIZER) and item.items:
            titles.append(item.items[0].GetLabel())
    return [title for title in titles if title]


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #
def test_every_group_gets_its_box():
    # One titled box per group, in the order the pane builds them; nothing is
    # dropped on the way from the table to the layout.
    titles = _boxes(_section(_MarkerSection()))
    for group in options.ADV_GROUPS.values():
        assert group.title in titles, group.title


def test_every_field_lands_in_exactly_one_group():
    # ADV_FIELDS is the flattened groups, so a knob listed twice would be typed
    # into two controls and read back from one of them.
    keys = [key for key, _label, _hint in options.ADV_FIELDS]
    assert len(keys) == len(set(keys))


def test_every_field_gets_a_control():
    # What contribute() reads back: one control per config key, whichever box
    # it ended up in.
    section = _section(_MarkerSection())
    for key, _label, _hint in options.ADV_FIELDS:
        assert key in section.adv, key
    assert len(section.adv) == len(options.ADV_FIELDS)


# --------------------------------------------------------------------------- #
# The closed lists (emkit.choices)
# --------------------------------------------------------------------------- #
def test_every_closed_list_gets_a_picker():
    # The other half of the table -> layout check above, and the one that keeps
    # saving/restoring/contributing a loop: those read section.picks by key, so
    # a list no box drew would raise there rather than here.
    section = _section(_MarkerSection())
    for picker in choices.SHARED:
        assert picker.key in section.picks, picker.key
    assert len(section.picks) == len(choices.SHARED)


def test_a_picker_offers_its_values_captioned():
    section = _section(_MarkerSection())
    shown = section.picks[choices.COPPER_MODEL.key].GetStrings()
    assert shown == choices.COPPER_MODEL.labels()


def test_a_saved_form_holds_the_value_the_run_writes():
    # The whole point: the settings file and the run parameters say the same
    # word, and it is the one the config takes -- never the caption drawn
    # beside it.
    section = _section(_MarkerSection())
    # The speed slider seeds the optimization box on a real page; without it
    # the Cells-across-driven-copper field is empty and contribute refuses.
    section.apply_preset(options.SPEED_PRESETS[options.SPEED_DEFAULT])
    saved = section.snapshot()
    for picker in choices.SHARED:
        assert saved[picker.key] in picker.values(), saved[picker.key]
    params = {}
    section.contribute(params)
    for picker in choices.SHARED:
        assert params[picker.key] == saved[picker.key], picker.key


def test_a_pick_survives_a_save_and_a_restore():
    section = _section(_MarkerSection())
    section.restore({"copper_model": "slab", "ground_check": "off"})
    assert section.snapshot()["copper_model"] == "slab"
    assert section.snapshot()["ground_check"] == "off"


def test_an_older_settings_file_still_restores_its_metal_model():
    # Written before the pick was saved as a value: the caption the widget
    # drew, under the key the widget was called ("model").
    section = _section(_MarkerSection())
    section.restore({"model": "slab — volumetric foil"})
    assert section.snapshot()["copper_model"] == "slab"


def test_a_pick_that_no_longer_exists_restores_the_default():
    section = _section(_MarkerSection())
    section.restore({"copper_model": "cauldron"})
    assert section.snapshot()["copper_model"] == choices.COPPER_MODEL.default


# The pane's knobs that are not a typed field, each one config key: the pickers,
# the narrow copper-cells box, the toggles the speed slider drives (two of them
# under a label that reads the other way round -- "Skip in-plane feature
# refinement" is refine_xy off, "Mur boundary" is boundary: mur) and the toggles
# that stand alone. None of these has a placeholder to carry its key, so they
# say it in a label of their own.
_KEYED_WIDGETS = (
    "copper_model",
    "copper_cells",
    "coarse_air",
    "refine_xy",
    "boundary",
    "conformal",
    "adaptive",
    "mesh_fit_cell",
    "mesh_nudge",
    "output_json",
    "refine_adaptive",
    "feed_snap_to_center",
    "ground_check",
)


def test_every_field_s_box_says_its_default_and_its_config_key():
    # The placeholder is both halves of what an empty field means: what leaving
    # it blank resolves to, and the key it writes -- the name the solver's
    # messages use, and the only thing tying one of them to this box.
    section = _section(_MarkerSection())
    for key, label, hint in options.ADV_FIELDS:
        shown = section.adv[key].GetHint()
        if key in _LABELLED_FIELDS:  # its key is beside the field, not in it
            assert shown == hint, f"{label}: {shown}"
            continue
        assert shown == theme.hint_with_key(hint, key), f"{label}: {shown}"
        # The default first, then the key, bracketed -- never run together with
        # the hint's own arithmetic ("0 = 3·cell" is one of the defaults).
        assert shown.startswith(hint), f"{label}: {shown}"
        assert shown.endswith(f"[{key}]"), f"{label}: {shown}"


# The fields whose key is a label of their own rather than part of their
# placeholder: the Cell size pair, which is stacked under its labels (the two
# fields share one row, so there is a permanent label to hang the key on and
# saying it twice on one field would only crowd it).
_LABELLED_FIELDS = ("cell_mm", "cell_max_mm")


def test_the_cell_size_fields_say_their_keys_beside_them():
    # The exemption above is only sound while the keys really are on the box:
    # a field that says its key nowhere breaks the link between a solver
    # message and the widget that set it.
    shown = _labels(_section(_MarkerSection()).cell.sizer)
    for key in _LABELLED_FIELDS:
        assert theme.key_text(key) in shown, key


def test_a_filled_field_still_names_its_key_on_the_tooltip():
    # A placeholder is gone the moment a value is typed, which is exactly when
    # a run has happened and its messages are being read.
    section = _section(_MarkerSection())
    for key, _label, _hint in options.ADV_FIELDS:
        assert key in section.adv[key].tooltip, key


def test_every_other_knob_shows_the_config_key_it_writes():
    # No placeholder on a picker or a tick, so the key is a greyed label beside
    # it. A knob shown without its key -- or under a key the writer doesn't
    # emit -- breaks the same link silently.
    section = _section(_MarkerSection())
    shown = _labels(section.adv_pane.GetPane().sizer)
    for key in _KEYED_WIDGETS:
        assert theme.key_text(key) in shown, f"no widget shows {key}"
        assert key in config.AntennaConfig.DEFAULTS, f"{key} is not a config knob"


def test_the_mesh_toggles_default_to_the_writer_s_defaults():
    # The two Mesh checkboxes are the runner's own defaults spelled out, so an
    # untouched pane and a hand-written config describe the same run. Neither
    # is an optimization: a mesh inside its budget never reaches mesh_fit_cell,
    # and the nudge creates no node -- so neither is bound to the speed slider.
    section = _section(_MarkerSection())
    page = section.page
    for name in ("mesh_fit_cell", "mesh_nudge"):
        widget = getattr(section, name)
        assert widget.GetValue() is True, name
        assert config.AntennaConfig.DEFAULTS[name] is True, name
        before = page.speed.overrides
        widget.fire("EVT_CHECKBOX")
        assert page.speed.overrides == before, name


def test_the_bool_toggles_round_trip_through_the_shared_form():
    # Every toggle the section owns travels as a flat string through
    # snapshot/restore -- one left out of _TOGGLES would silently reset to its
    # default on every page switch and every settings load.
    section = _section(_MarkerSection())
    for name in advanced.AdvancedSection._TOGGLES:
        getattr(section, name).SetValue(False)
    saved = section.snapshot()
    for name in advanced.AdvancedSection._TOGGLES:
        getattr(section, name).SetValue(True)
    section.restore(saved)
    for name in advanced.AdvancedSection._TOGGLES:
        assert getattr(section, name).GetValue() is False, name


def _caption(section):
    """What the Cell size box currently says about its two fields."""
    return section.cell._caption.GetLabel()


def test_the_cell_size_box_re_captions_on_every_keystroke():
    # The pair's four combinations mean four different things, so the sentence
    # under them is the control's real output -- a field that didn't re-caption
    # would leave the box asserting the state before the edit.
    section = _section(_MarkerSection())
    # An untouched pair says nothing, and the empty label is out of the layout
    # rather than holding open the gap it would occupy.
    assert _caption(section) == "" and section.cell._caption.shown is False
    section.adv["cell_max_mm"].type("0.2")
    assert "refined to 0.2 mm" in _caption(section)
    assert section.cell._caption.shown is True
    section.adv["cell_mm"].type("0.1")
    assert "Mesh at 0.1 mm" in _caption(section)
    # An empty range says so where it is typed, not after a run is prepared.
    section.adv["cell_mm"].type("0.4")
    assert "empty range" in _caption(section)


def test_the_re_mesh_tick_re_captions_the_cell_size_box():
    # It decides what an over-budget lattice does, which is half of what the
    # pair means: with an explicit cell and this off, the ceiling bounds
    # nothing at all.
    section = _section(_MarkerSection())
    section.adv["cell_mm"].type("0.2")
    section.adv["cell_max_mm"].type("0.5")
    assert "may coarsen inside that range" in _caption(section)
    section.mesh_fit_cell.click(False)
    assert "binds nothing here" in _caption(section)


def test_a_restored_cell_size_re_captions_itself():
    # restore() writes the fields with ChangeValue, which fires no EVT_TEXT --
    # the caption would otherwise still describe the fields it replaced.
    section = _section(_MarkerSection())
    section.adv["cell_max_mm"].type("0.2")
    saved = section.snapshot()
    section.adv["cell_max_mm"].type("")
    assert _caption(section) == ""
    section.restore(saved)
    assert "refined to 0.2 mm" in _caption(section)


def test_the_optimization_widgets_snap_the_speed_slider():
    # Every widget the Speed/accuracy slider drives has to report a hand edit,
    # or the caption would go on claiming a preset the toggles no longer match.
    section = _section(_MarkerSection())
    page = section.page
    for widget in (
        section.coarse_air,
        section.no_refine_xy,
        section.mur,
        section.conformal,
        section.adaptive,
    ):
        before = page.speed.overrides
        widget.fire("EVT_CHECKBOX")
        assert page.speed.overrides == before + 1


# --------------------------------------------------------------------------- #
# The marker layer picker
# --------------------------------------------------------------------------- #
def test_the_page_s_marker_section_builds_the_layer_picker():
    # The pane builds the picker for whichever marker its page places -- the
    # simulate view's feed marker, a designer's area marker -- and the section
    # owns the widget.
    feed = _MarkerSection()
    section = _section(feed)
    assert feed.grid is not None
    assert options.ADV_GROUPS["markers"].title in _boxes(section)


def test_a_page_without_a_marker_section_has_no_markers_box():
    # Nothing else in the pane depends on the marker, so a page that places no
    # marker simply loses that one box.
    section = _section(None)
    assert options.ADV_GROUPS["markers"].title not in _boxes(section)
    for key, _label, _hint in options.ADV_FIELDS:
        assert key in section.adv, key


def test_the_two_markers_share_one_layer_pick():
    # The feed marker and the area marker go on the same User layer: one key
    # under one label, contributed by one snapshot -- so a pick made in either
    # page's Advanced pane is the pick the other page places with (the shared
    # form carries it between them, gui.model).
    assert area.AreaSection.snapshot is marker.FeedMarkerSection.snapshot
    assert area.AreaSection.restore is marker.FeedMarkerSection.restore
    assert not hasattr(area.AreaSection, "layer_key")  # no per-marker key left
    feed, section = _feed_section(), _area_section()
    for owner in (feed, section):
        owner.build_layer_picker(object(), wx.FlexGridSizer())
        owner.marker_layer.SetStringSelection("User.5")
    assert feed.snapshot()[marker.LAYER_KEY] == "User.5"
    assert section.snapshot()[marker.LAYER_KEY] == "User.5"


def test_the_area_section_takes_the_picker_the_pane_builds():
    # The real thing, on the designer's side: the area section builds its own
    # picker into the Advanced pane, defaulting to User.2, and answers with it.
    section = _area_section()
    section.build_layer_picker(object(), wx.FlexGridSizer())
    assert section.marker_layer_n() == marker.MARKER_LAYER_DEFAULT + 1
    assert section.snapshot()[marker.LAYER_KEY] == "User.2"


def test_a_fresh_area_marker_layer_pick_shows_on_the_status_line():
    # With no marker placed there is nothing to move, so the pick's only
    # visible effect is the line saying where Place will put one -- which is
    # what the area section's own refresh_status is for (the base's describes
    # the other marker).
    section = _area_section()
    section.build_layer_picker(object(), wx.FlexGridSizer())
    assert "User.2" in section._status_label.GetLabel()
    section.marker_layer.SetStringSelection("User.5")
    section._layer_changed()
    assert "User.5" in section._status_label.GetLabel()
    assert section.snapshot()[marker.LAYER_KEY] == "User.5"


def test_a_marker_layer_pick_round_trips_through_the_shared_form():
    # snapshot / restore are the one seam the pick travels on -- the model as
    # pages switch, and the settings file the simulate page writes from it.
    section = _area_section()
    section.build_layer_picker(object(), wx.FlexGridSizer())
    saved = section.snapshot()
    section.marker_layer.SetStringSelection("User.7")
    section.restore(saved)
    assert section.marker_layer.GetStringSelection() == "User.2"


def test_an_absent_picker_contributes_no_layer():
    # The picker is built by the Advanced pane, after the marker section: until
    # then there is no pick to save, and none to restore into.
    section = _area_section()
    assert marker.LAYER_KEY not in section.snapshot()
    section.restore({marker.LAYER_KEY: "User.5"})


if __name__ == "__main__":
    run_module_tests(globals())
