"""Unit tests for the pre-flight checks in antenna_plugin.sim.simulate.

preflight() itself needs a live pcbnew board, so these cover the pure layer:
stackup_problems (the predicates shared with collect_stackup), the Problem
dataclass defaults, and that every catalogued problem id ships its bundled
help page. Register a bare package (skipping antenna_plugin/__init__, which
imports pcbnew) so simulate's relative import of theme works:
python3 tests/test_preflight.py  (or pytest)
"""

import importlib
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
from helppage import assert_guide_loads  # noqa: E402

simulate = importlib.import_module("antenna_plugin.sim.simulate")


def _cu(thickness=0.035, name="Cu"):
    return {"kind": "copper", "name": name, "thickness_mm": thickness}


def _diel(subs=((1.51, 4.5, 0.02),), name="dielectric 1"):
    # Sublayers are (thickness_mm, eps, loss_tangent) triples, as read_stackup
    # now returns them.
    return {"kind": "dielectric", "name": name, "sublayers": list(subs)}


def _overlay(kind="paste", name="F.Paste"):
    # Silk/paste come out of read_stackup as name-only overlays: they are never
    # meshed, so they carry no thickness or material to validate.
    return {"kind": kind, "name": name}


def _ids(entries, names=("F_Cu", "B_Cu")):
    return [p.id for p in simulate.stackup_problems(entries, list(names))]


TWO_LAYER = [_cu(), _diel(), _cu()]


def test_complete_stackup_has_no_problems():
    assert _ids(TWO_LAYER) == []


def test_missing_stackup_block():
    probs = simulate.stackup_problems(None, ["F_Cu", "B_Cu"], "board.kicad_pcb")
    assert [p.id for p in probs] == ["no-stackup"]
    assert "board.kicad_pcb" in probs[0].message


def test_copper_count_mismatch_is_first():
    assert (
        _ids([_cu(), _diel(), _cu()], names=("F_Cu", "In1_Cu", "B_Cu"))[0]
        == "copper-count"
    )


def test_copper_thickness_named_by_board_suffix():
    probs = simulate.stackup_problems(
        [_cu(), _diel(), _cu(thickness=None)], ["F_Cu", "B_Cu"]
    )
    assert [p.id for p in probs] == ["copper-thickness"]
    assert "B_Cu" in probs[0].message


def test_dielectric_thickness_and_eps():
    assert _ids([_cu(), _diel(subs=((None, 4.5, 0.02),)), _cu()]) == [
        "dielectric-thickness"
    ]
    assert _ids([_cu(), _diel(subs=((1.51, None, 0.02),)), _cu()]) == ["dielectric-eps"]
    # A bad sublayer reports both, thickness first (matching the old raise
    # order in collect_stackup). A missing loss tangent is NOT flagged here --
    # it may come from a substrate material (checked in _apply_overrides).
    assert _ids([_cu(), _diel(subs=((0, 0, None),)), _cu()]) == [
        "dielectric-thickness",
        "dielectric-eps",
    ]


def test_overlays_never_block_and_do_not_break_the_gap_count():
    # Silk/paste overlays have nothing to validate, and they must not split a
    # dielectric gap or be mistaken for one (they sit outside the foils).
    assert (
        _ids(
            [
                _overlay(),
                _overlay("silk", "F.SilkS"),
                _cu(),
                _diel(),
                _cu(),
                _overlay("silk", "B.SilkS"),
                _overlay(name="B.Paste"),
            ]
        )
        == []
    )


def test_gap_count():
    # No gap between the two foils.
    assert _ids([_cu(), _cu()]) == ["dielectric-count"]
    # Consecutive plies merge into one gap: still fine.
    assert _ids([_cu(), _diel(), _diel(name="dielectric 2"), _cu()]) == []
    # A dielectric split by copper makes two gaps on a two-layer board.
    assert "dielectric-count" in _ids([_diel(), _cu(), _diel(), _cu()])
    # Single-layer board still needs its one substrate.
    assert _ids([_cu()], names=("F_Cu",)) == ["dielectric-count"]
    assert _ids([_cu(), _diel()], names=("F_Cu",)) == []


def test_problems_accumulate_in_file_order():
    probs = simulate.stackup_problems(
        [_cu(thickness=None), _diel(subs=((None, 4.5, 0.02),)), _cu()], ["F_Cu", "B_Cu"]
    )
    assert [p.id for p in probs] == ["copper-thickness", "dielectric-thickness"]


def test_problem_defaults():
    p = simulate.Problem("no-stackup", "block", "msg")
    assert p.help == "no-stackup.html"
    assert p.title == "Set up the physical stackup"
    assert p.severity == "block"


def test_every_catalogued_id_ships_a_help_page():
    for pid in simulate._PROBLEM_TITLES:
        # The shared rule for every bundled guide lives in tests/helppage.py.
        text = assert_guide_loads(simulate.Problem(pid, "block", "msg"))
        # A guide is prose, not a stub: it must at least carry its headline
        # and the standfirst the banner's one-liner expands into.
        assert "<h1>" in text and 'class="lead"' in text, f"{pid}: empty guide"


def test_help_page_missing_asset_returns_none():
    p = simulate.Problem("not-a-real-problem", "block", "msg")
    assert simulate.help_page(p) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
