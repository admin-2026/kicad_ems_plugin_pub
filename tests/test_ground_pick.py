"""The Ground-layer pick: the Area box's second layer picker (no KiCad, no wx).

A design that radiates against a plane rather than against the pour beside it
(``AntennaDesign.needs_ground_plane`` -- the patch) grows one more control in
the Antenna area box, naming the copper layer the board's own pour has to cover
the area on. It draws nothing; it is the answer the advisory checks need before
they can tell "a plane is detuning this antenna" from "this antenna has no
plane" (markers/area_checks.py, check 5) -- and the layer the scan splices that
plane onto (design/wizard_scan.py).

So what is checked here is the seam: the picker exists for the designs that
want it and for no others, it defaults to the layer that is nearly always
right, it never offers the layer the antenna is fed on, it survives a save --
the section's, and the designer page's own trip to the settings file -- and the
pick reaches the page every other reader asks.

    python3 tests/test_ground_pick.py
"""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx / pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

area = load("gui.sections.area")
board_mod = load("emkit.gui.board")
marker = load("emkit.gui.sections.marker")
registry = load("design.registry")
wizard_page = load("gui.pages.wizard")
wx = wx_stub.wx


PATCH = registry.by_key("patch")


@contextlib.contextmanager
def _stackup(copper):
    """Pretend the open board has these copper layers -- off the board the
    plugin reads the two-layer fallback, and the pick this file is about only
    has room to move on a board with more than two."""
    original = board_mod.board_layer_names
    board_mod.board_layer_names = lambda: (list(copper), max(1, len(copper) - 1))
    try:
        yield
    finally:
        board_mod.board_layer_names = original


class _Page:
    """Just what the area section reads off its designer page."""

    class _Host:
        def target_freq_ghz(self, default=None):
            return 2.45

    def __init__(self, design):
        self.scroll = object()
        self.design = design
        self.host = self._Host()
        self.wrapped = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def _relayout_scroll(self):
        pass

    def refresh_area_checks(self):
        pass


def _section(design):
    """A real area section for ``design``, off the board (pcbnew is stubbed,
    so the layer list is the two-layer fallback: F_Cu, B_Cu)."""
    return area.AreaSection(_Page(design), wx.BoxSizer())


@contextlib.contextmanager
def _multilayer():
    """A patch section on a four-layer board, where the ground pick has
    somewhere to go. The stackup stays faked for the whole block: the picker
    re-reads the board every time the feed pick moves."""
    with _stackup(["F_Cu", "In1_Cu", "In2_Cu", "B_Cu"]):
        yield _section(PATCH)


def _needs_a_plane():
    return [d for d in registry.DESIGNS if d.needs_ground_plane]


# --------------------------------------------------------------------------- #
# Who gets one
# --------------------------------------------------------------------------- #
def test_only_a_design_that_radiates_against_a_plane_gets_the_picker():
    assert [d.key for d in _needs_a_plane()] == ["patch"]
    for design in registry.DESIGNS:
        section = _section(design)
        wanted = design.needs_ground_plane
        assert (section.ground_layer is not None) is wanted, design.key
        # A design with no plane answers "no plane" rather than a layer name
        # nobody picked: the checks read that as "ask the other questions".
        assert bool(section.ground_layer_name()) is wanted, design.key


def test_the_pick_defaults_to_the_bottom_copper():
    # The plane on the two-layer board a patch is nearly always drawn on. It is
    # a default for a pick, not for a missing input -- the picker shows it.
    section = _section(PATCH)
    assert section.ground_layer_name() == "B_Cu"


def test_the_pick_follows_the_user():
    with _multilayer() as section:
        section.ground_layer.SetStringSelection("In2_Cu")
        assert section.ground_layer_name() == "In2_Cu"


# --------------------------------------------------------------------------- #
# The feed layer is not on offer
# --------------------------------------------------------------------------- #
def test_the_feed_layer_is_left_out_of_the_list():
    # One layer can't be both the antenna and its reference: the layer the feed
    # is on is not a plane the user may pick.
    section = _section(PATCH)
    assert section.feed_layer_name() == "F_Cu"
    assert section.ground_layer.GetStrings() == ["B_Cu"]


def test_moving_the_feed_layer_rebuilds_the_list():
    section = _section(PATCH)
    section.feed_layer.SetStringSelection("B_Cu")
    section.feed_layer.fire("EVT_CHOICE")
    assert section.ground_layer.GetStrings() == ["F_Cu"]
    assert section.ground_layer_name() == "F_Cu"


def test_a_pick_the_feed_layer_takes_moves_off_it():
    # The user picks an inner plane, then feeds the antenna on it: the pick
    # cannot stand, so it falls back to the bottom copper rather than name a
    # layer the list no longer offers.
    with _multilayer() as section:
        section.ground_layer.SetStringSelection("In1_Cu")
        section.feed_layer.SetStringSelection("In1_Cu")
        section.feed_layer.fire("EVT_CHOICE")
        assert section.ground_layer.GetStrings() == ["F_Cu", "In2_Cu", "B_Cu"]
        assert section.ground_layer_name() == "B_Cu"


def test_a_surviving_pick_is_kept_when_the_list_is_rebuilt():
    with _multilayer() as section:
        section.ground_layer.SetStringSelection("In2_Cu")
        section.feed_layer.SetStringSelection("In1_Cu")
        section.feed_layer.fire("EVT_CHOICE")
        assert section.ground_layer_name() == "In2_Cu"


# --------------------------------------------------------------------------- #
# Saving it
# --------------------------------------------------------------------------- #
def test_the_pick_is_saved_and_restored_beside_the_feed_picks():
    section = _section(PATCH)
    section.feed_layer.SetStringSelection("B_Cu")  # frees the top copper
    section.feed_layer.fire("EVT_CHOICE")
    data = section.snapshot()
    assert data["ground_layer"] == "F_Cu"
    # The shared picks are still the base's own, untouched by the addition.
    shared = marker.FeedMarkerSection.snapshot(section)
    assert {key: data[key] for key in shared} == shared

    restored = _section(PATCH)
    restored.restore(data)
    assert restored.ground_layer_name() == "F_Cu"


def test_a_design_without_the_picker_ignores_a_saved_pick():
    # One shared form serves every designer page, so the patch's key reaches
    # the monopole's section too -- and must go nowhere near it.
    section = _section(registry.by_key("lmonopole"))
    section.restore({"ground_layer": "F_Cu"})
    assert "ground_layer" not in section.snapshot()
    assert section.ground_layer_name() == ""


class _Scan:
    """The other section the page's settings hooks touch: its rows are their
    own tests' business (test_scan_section.py), so this one just records --
    but its key namespace is the real one, since that is what the page saves
    the Ground pick under."""

    def __init__(self, design):
        self.design = design
        self.restored = None

    def settings_key(self, *parts):
        return ".".join(("scan", self.design.key) + parts)

    def snapshot(self):
        return {self.settings_key("count"): "5"}

    def restore(self, data):
        self.restored = data


def _settings(section):
    """A stand-in for the designer page, carrying the two sections its settings
    hooks read. The hooks themselves are the real ones, called unbound: the
    page is a panel tree of no use here, and what is under test is which
    sections it hands the settings file."""
    page = type("_SettingsPage", (), {})()
    page.area, page.scan = section, _Scan(section.page.design)
    return page


def test_the_designer_page_writes_the_pick_to_the_settings_file():
    # The bug this pins down: the pick rides the shared form, but the page that
    # persists the shared form is the simulate view, which has no such picker
    # -- so unless this page claims the key it never reaches the file, and the
    # pick comes back as the default on the next launch. It is claimed in this
    # designer's own namespace, beside its rows.
    with _multilayer() as section:
        section.ground_layer.SetStringSelection("In2_Cu")
        page = _settings(section)
        data = wizard_page.DesignWizardPage.settings_snapshot(page)
        assert data["scan.patch.ground_layer"] == "In2_Cu"
        assert data["scan.patch.count"] == "5"  # and the rows still go too

    # A designer with no plane claims no such key.
    plain = _settings(_section(registry.by_key("lmonopole")))
    written = wizard_page.DesignWizardPage.settings_snapshot(plain)
    assert not [key for key in written if key.endswith("ground_layer")]


def test_the_designer_page_reads_the_pick_back_from_the_file():
    with _multilayer() as section:
        page = _settings(section)
        saved = {"scan.patch.ground_layer": "In2_Cu", "scan.patch.count": "5"}
        wizard_page.DesignWizardPage.settings_restore(page, saved)
        assert section.ground_layer_name() == "In2_Cu"
        assert page.scan.restored == saved


def test_one_designer_s_pick_is_not_another_s():
    # The namespace is the point: a key under scan.patch says nothing to a
    # design that keeps its plane somewhere else.
    with _stackup(["F_Cu", "In1_Cu", "In2_Cu", "B_Cu"]):
        page = _settings(_section(PATCH))
        wizard_page.DesignWizardPage.settings_restore(
            page, {"scan.other.ground_layer": "In2_Cu"}
        )
        assert page.area.ground_layer_name() == "B_Cu"  # its own default


def test_a_layer_the_board_has_not_got_leaves_the_pick_alone():
    # A settings file written against another board (or hand-edited): the pick
    # keeps the layer this board actually has rather than one nobody can see.
    section = _section(PATCH)
    section.restore({"ground_layer": "In3_Cu"})
    assert section.ground_layer_name() == "B_Cu"


if __name__ == "__main__":
    run_module_tests(globals())
