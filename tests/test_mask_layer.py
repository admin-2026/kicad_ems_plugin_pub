"""The solder mask: a coating the board may be solved with, or without.

Every schema before this one solved a bare board -- the mask was read by
nothing and plotted by nothing. It is a layer now, and a layer that is
*optional* is the shape a silent default hides in, so what these follow is the
one decision from end to end:

    the tick        one checkbox in Advanced > Materials, off until it is asked
                    for -- the coating is meshed at its own thickness, so it is
                    the dearest thing on that pane and no speed stop buys it
    the board       KiCad's stackup states the mask's thickness, and sometimes
                    its permittivity
    the material    the Materials row states the rest, or the board's own stand
    the banner      a run that includes the mask and cannot say what it is made
                    of is refused *before* it starts, naming what is missing
    the config      the entries are emitted only for a run that asked, with the
                    thickness and eps it will be meshed with

The wx side runs on the stand-in (wx_stub); the board side reads a real
``.kicad_pcb`` with the file parser, which needs no KiCad.

    python3 tests/test_mask_layer.py   (or pytest)
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx / pcbnew)
from bare_package import load, run_module_tests  # noqa: E402
from helppage import assert_guide_loads  # noqa: E402
from kicad_board import board_path  # noqa: E402

choices = load("emkit.choices")
options = load("emkit.options")
advanced = load("emkit.gui.sections.advanced")
marker = load("emkit.gui.sections.marker")
stackup = load("emkit.kicad.stackup")
simulate = load("emkit.sim.simulate")
core_config = load("emkit.config")
formparams = load("emkit.formparams")
Materials = load("emkit.materials.db").Materials
wx = wx_stub.wx

MASK = "include_mask"


# --------------------------------------------------------------------------- #
# The tick, and what a form holds for it
# --------------------------------------------------------------------------- #
def test_no_speed_stop_buys_the_coating():
    """The slider drives the mesh; the mask is not one of the knobs it turns,
    so the most accurate stop solves a bare board like every other one."""
    assert not any(hasattr(preset, "include_mask") for preset in options.SPEED_PRESETS)
    assert formparams.defaults()[MASK] == "false"


def test_it_is_not_a_closed_list_but_a_bool_the_config_knows():
    assert MASK not in [pick.key for pick in choices.SHARED]
    assert core_config.ConfigWriter.DEFAULTS[MASK] is False


# --------------------------------------------------------------------------- #
# What the board states
# --------------------------------------------------------------------------- #
def _stackup_file(mask_props):
    """A minimal saved board whose two mask layers carry ``mask_props``."""
    text = f"""(kicad_pcb (setup (stackup
    (layer "F.Mask" (type "Top Solder Mask") {mask_props})
    (layer "F.Cu" (type "copper") (thickness 0.035))
    (layer "dielectric 1" (type "core") (thickness 1.51) (epsilon_r 4.5)
      (loss_tangent 0.02))
    (layer "B.Cu" (type "copper") (thickness 0.035))
    (layer "B.Mask" (type "Bottom Solder Mask") {mask_props})
  )))"""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
    )
    handle.write(text)
    handle.close()
    return handle.name


def test_a_mask_layer_comes_back_with_what_the_board_states():
    entries = stackup.read_stackup(_stackup_file("(thickness 0.02) (epsilon_r 3.3)"))
    masks = [e for e in entries if e["kind"] == "mask"]
    assert [e["name"] for e in masks] == ["F.Mask", "B.Mask"]
    assert masks[0]["thickness_mm"] == 0.02 and masks[0]["eps"] == 3.3


def test_a_mask_the_board_says_nothing_about_carries_nothing():
    """Missing is missing: KiCad's own default stackup gives the mask a
    thickness and no permittivity, and the entry must not invent one -- who
    supplies it is the whole question below."""
    entries = stackup.read_stackup(_stackup_file("(thickness 0.01)"))
    mask = next(e for e in entries if e["kind"] == "mask")
    assert mask["thickness_mm"] == 0.01
    assert "eps" not in mask


def test_a_real_board_reads_the_same_way():
    entries = stackup.read_stackup(str(board_path("patch_antenna")))
    masks = [e for e in entries if e["kind"] == "mask"]
    assert len(masks) == 2
    assert all(e["thickness_mm"] > 0 for e in masks)
    # The fixture is a stock KiCad stackup, which states no permittivity for
    # the coating -- exactly the board the banner has to say something about.
    assert all("eps" not in e for e in masks)


# --------------------------------------------------------------------------- #
# The banner: what a run that includes the mask must be able to say
# --------------------------------------------------------------------------- #
def _entries(thickness=0.02, eps=3.3):
    mask = {"kind": "mask", "name": "F.Mask"}
    if thickness is not None:
        mask["thickness_mm"] = thickness
    if eps is not None:
        mask["eps"] = eps
    return [
        mask,
        {"kind": "copper", "name": "F.Cu", "thickness_mm": 0.035},
        {"kind": "dielectric", "name": "D1", "sublayers": [(1.51, 4.5, 0.02)]},
        {"kind": "copper", "name": "B.Cu", "thickness_mm": 0.035},
    ]


def _problems(entries, **params):
    return simulate.mask_problems(entries, params, "board.kicad_pcb")


def test_a_run_without_the_mask_asks_nothing_of_it():
    """Not part of the board being solved: there is nothing about it to be
    missing, however little the stackup says."""
    assert _problems(_entries(thickness=None, eps=None)) == []
    assert _problems(_entries(thickness=None, eps=None), include_mask=False) == []


def test_a_complete_mask_blocks_nothing():
    assert _problems(_entries(), include_mask=True) == []


def test_including_a_mask_the_board_does_not_have_blocks():
    bare = [e for e in _entries() if e["kind"] != "mask"]
    problems = _problems(bare, include_mask=True)
    assert [p.severity for p in problems] == ["block"]
    assert "board.kicad_pcb" in problems[0].message
    assert "untick" in problems[0].message  # and how to get on without it


def test_a_mask_with_no_epsilon_blocks_unless_a_material_supplies_it():
    entries = _entries(eps=None)
    problems = _problems(entries, include_mask=True)
    assert [p.severity for p in problems] == ["block"]
    assert "F.Mask" in problems[0].message and "epsilon r" in problems[0].message
    # The other source: a picked mask material answers for every layer.
    material = {"eps": 3.5, "loss_tangent": 0.025}
    assert _problems(entries, include_mask=True, mask_material=material) == []


def test_a_mask_with_no_thickness_blocks_whatever_is_picked():
    """The one constant no material can supply: how thick the coating is comes
    from the board and nowhere else."""
    problems = _problems(
        _entries(thickness=None),
        include_mask=True,
        mask_material={"eps": 3.5, "loss_tangent": 0.025},
    )
    assert [p.severity for p in problems] == ["block"]
    assert "F.Mask" in problems[0].message and "thickness" in problems[0].message


def test_a_material_that_is_not_typed_yet_blocks_naming_the_reason():
    """A Custom pick with empty fields: the pane hands the reason over instead
    of raising into the banner, so the row says what to type."""
    problems = _problems(
        _entries(eps=None),
        include_mask=True,
        mask_material_error="Solder mask: enter εr (≥ 1) and a loss tangent (≥ 0)",
    )
    assert [p.severity for p in problems] == ["block"]
    assert "enter εr" in problems[0].message


def test_every_mask_blocker_ships_its_help_page():
    for problem in _problems(_entries(thickness=None, eps=None), include_mask=True):
        assert problem.id in simulate._PROBLEM_TITLES
        text = assert_guide_loads(problem)
        assert "Solder mask" in text


# --------------------------------------------------------------------------- #
# The config: the coating is emitted only for a run that asked
# --------------------------------------------------------------------------- #
class _Writer(core_config.ConfigWriter):
    """The core writer with the one block a flow has to supply."""

    CONFIG_VERSION = "0.0.0"

    def ports(self):
        return ["feed_ports: []"]


_STACK = [
    {"type": "mask", "name": "F_Mask", "thickness_mm": 0.02, "eps": 3.3},
    {"type": "copper", "name": "F_Cu", "thickness_mm": 0.035},
    {
        "type": "core",
        "name": "D1",
        "thickness_mm": 1.51,
        "eps": 4.5,
        "loss_tangent": 0.02,
    },
    {"type": "copper", "name": "B_Cu", "thickness_mm": 0.035},
    {"type": "mask", "name": "B_Mask", "thickness_mm": 0.02, "eps": 3.3},
]

_MATERIALS = {
    "metal_layers": [{"sigma": 5.8e7}, {"sigma": 5.8e7}],
    "substrate_layers": [None],
}


def _write(mask_gerbers=True, **params):
    merged = dict(_MATERIALS)
    merged.update(params)
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        gerbers = {
            "edge": str(td / "edge.gbr"),
            "copper": [("F_Cu", str(td / "F_Cu.gbr")), ("B_Cu", str(td / "B_Cu.gbr"))],
        }
        if mask_gerbers:
            gerbers["mask_top"] = str(td / "mask_top.gbr")
            gerbers["mask_bottom"] = str(td / "mask_bottom.gbr")
        _Writer(gerbers, {"stackup": _STACK}, merged).write(str(td / "pcb.yaml"))
        return (td / "pcb.yaml").read_text(encoding="utf-8")


def _blocks(text):
    body = text[text.index("stackup:") : text.index("# --- copper model")]
    return ["- type:" + e for e in body.split("- type:")[1:]]


def test_the_coating_is_left_off_a_run_that_did_not_ask():
    types = [b.split("\n")[0] for b in _blocks(_write())]
    assert types == ["- type: copper", "- type: core", "- type: copper"]


def test_an_included_mask_rides_on_its_own_gerber():
    blocks = _blocks(_write(include_mask=True))
    masks = [b for b in blocks if b.startswith("- type: mask")]
    assert len(masks) == 2
    assert "name: F_Mask" in masks[0] and "mask_top.gbr" in masks[0]
    assert "name: B_Mask" in masks[1] and "mask_bottom.gbr" in masks[1]
    # A coating is a dielectric where it is meshed and a layer where it is
    # drawn: it carries both constants, and it is in the grid view (unlike the
    # paste, whose apertures only overdraw the copper they mark).
    assert "thickness_mm: 0.02" in masks[0] and "eps: 3.3" in masks[0]
    assert "show_in_grid: true" in masks[0]
    # Top mask before the first foil, bottom after the last: that position is
    # what tells the runner which side each is on.
    assert blocks[0] is masks[0] and blocks[-1] is masks[1]


def test_a_picked_material_overrides_the_boards_epsilon():
    text = _write(include_mask=True, mask_material={"eps": 3.5, "loss_tangent": 0.025})
    mask = _blocks(text)[0]
    assert "eps: 3.5" in mask and "loss_tangent: 0.025" in mask


def test_an_included_mask_with_no_material_at_all_raises():
    """The last-line guard, for a run started from anywhere the banner is not
    (the command line, a saved form). Never a quietly dropped layer."""
    bare = [dict(e) for e in _STACK]
    bare[0].pop("eps")
    try:
        core_config._apply_overrides(bare, {"include_mask": True, **_MATERIALS})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "F_Mask" in str(exc) and "epsilon r" in str(exc)


def test_a_mask_the_board_never_plotted_raises():
    """An entry with no gerber is skipped when the stackup is written, so a run
    that asked for the coating would otherwise solve a bare board and say
    nothing about it."""
    try:
        _write(mask_gerbers=False, include_mask=True)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "F.Mask" in str(exc) and "untick" in str(exc)


def test_the_mask_layers_are_always_plotted():
    """Why the guard above is the only one needed: the roles exist for every
    board, so no caller of plot_gerbers has a flag to forget."""
    roles = [role for _suffix, _id, role in simulate._AUX_LAYERS]
    assert "mask_top" in roles and "mask_bottom" in roles


# --------------------------------------------------------------------------- #
# The pane: what the tick is, and what the run gets
# --------------------------------------------------------------------------- #
class _Form:
    def __init__(self):
        self.hints = 0

    def update_hint(self, *args):
        self.hints += 1


class _Speed:
    def on_override(self, *args):
        pass


class _Banner:
    def __init__(self):
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


class _MarkerSection:
    def build_layer_picker(self, pane, grid):
        self.marker_layer = wx.Choice(pane, choices=marker.MARKER_LAYERS)
        self.marker_layer.SetSelection(marker.MARKER_LAYER_DEFAULT)
        grid.Add(self.marker_layer)


class _Page:
    def __init__(self):
        self.scroll = object()
        self.form = _Form()
        self.speed = _Speed()
        self.banner = _Banner()
        self.feed_section = _MarkerSection()

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def _on_pane_changed(self, *args):
        pass


def _section(stop=None):
    """The Advanced pane, seeded from a speed stop the way a page seeds it."""
    page = _Page()
    section = advanced.AdvancedSection(page, wx.BoxSizer())
    stop = options.SPEED_DEFAULT if stop is None else stop
    section.apply_preset(options.SPEED_PRESETS[stop])
    return section


def _set(section, on):
    section.include_mask.SetValue(on)


def test_the_tick_starts_off_on_every_stop():
    """Off is off wherever the slider is: the coating is asked for by hand or
    not at all."""
    for stop in range(len(options.SPEED_PRESETS)):
        section = _section(stop=stop)
        assert section.include_mask.GetValue() is False, stop
        assert section.snapshot()[MASK] == "false", stop


def test_the_tick_is_what_the_run_gets():
    section = _section()
    _set(section, True)
    params = {}
    section.contribute(params)
    assert params[MASK] is True
    _set(section, False)
    params = {}
    section.contribute(params)
    assert params[MASK] is False


def test_the_speed_slider_does_not_move_it_and_it_does_not_move_the_slider():
    """Not one of the toggles: applying a stop leaves the tick where it was,
    and ticking it does not make the slider read Custom."""
    section = _section()
    _set(section, True)
    section.apply_preset(options.SPEED_PRESETS[len(options.SPEED_PRESETS) - 1])
    assert section.include_mask.GetValue() is True
    assert section.preset_index() == len(options.SPEED_PRESETS) - 1


def test_the_tick_survives_a_save_and_a_restore():
    section = _section()
    _set(section, True)
    saved = section.snapshot()
    assert saved[MASK] == "true"
    other = _section()
    other.restore(saved)
    assert other.snapshot()[MASK] == "true"
    assert other.mask_params()[MASK] is True


def test_moving_the_tick_re_runs_the_pre_flight():
    """Whether the mask has to state a material is not a fact about the board,
    so the banner cannot notice this one on its own."""
    section = _section()
    before = section.page.banner.refreshes
    section.include_mask.fire("EVT_CHECKBOX")
    assert section.page.banner.refreshes == before + 1


def test_the_pane_hands_the_pre_flight_what_it_cannot_read_off_the_board():
    section = _section()
    _set(section, True)
    params = section.mask_params()
    assert params[MASK] is True
    assert params["mask_material"] is None  # from board stackup, by default
    assert _problems(_entries(eps=None), **params)  # ...so the board must say


def test_an_untyped_custom_material_travels_as_the_reason_not_as_a_raise():
    section = _section()
    _set(section, True)
    row = section.materials.mask_row
    row.choice.SetStringSelection(Materials.CUSTOM)
    row.choice.fire("EVT_CHOICE")
    for field in row.fields.values():
        field.ChangeValue("")
    params = section.mask_params()
    assert "εr" in params["mask_material_error"]
    assert [p.id for p in _problems(_entries(), **params)] == ["mask-material"]


if __name__ == "__main__":
    run_module_tests(globals())
