"""Unit tests for the pre-flight checks in antenna_plugin.sim.simulate.

preflight() itself needs a live pcbnew board, so these cover the pure layer:
stackup_problems (the predicates shared with collect_stackup), the Problem
dataclass defaults, and that every catalogued problem id ships its bundled
help page. Register a bare package (skipping antenna_plugin/__init__, which
imports pcbnew) so simulate's relative import of theme works:
python3 tests/test_preflight.py  (or pytest)
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))
from bare_package import load  # noqa: E402
from helppage import assert_guide_loads  # noqa: E402

simulate = load("emkit.sim.simulate")


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


# --------------------------------------------------------------------------- #
# the container, which is not a board problem but is a run-stopper
# --------------------------------------------------------------------------- #
def _container_problems(ready=True, use_docker=True, raises=None):
    """container_problems() with the preference and the engine stood in for."""
    hostprefs = load("emkit.hostprefs")
    container = load("emkit.sim.container")
    kept = (hostprefs.use_docker, container.status)
    try:
        hostprefs.use_docker = lambda *a, **k: use_docker

        def probe(**kwargs):
            if raises:
                raise RuntimeError(raises)
            return container.Status(
                container.READY if ready else container.NO_DAEMON,
                "the daemon is not answering",
                "Start Docker Desktop.",
            )

        container.status = probe
        return simulate.container_problems()
    finally:
        hostprefs.use_docker, container.status = kept


def test_a_machine_that_solves_natively_is_not_asked_about_docker():
    # It costs a process to ask, and most machines have no container to ask
    # about. Nothing is spent on the question until the answer could matter.
    assert _container_problems(use_docker=False) == []


def test_a_container_that_is_not_ready_blocks_with_its_own_remedy():
    # Found here it is a row in the banner with the fix on it. Found at launch
    # it is a failed spawn in the middle of a log, minutes of gerber plotting
    # after the user pressed Run.
    (problem,) = _container_problems(ready=False)
    assert problem.severity == "block"
    assert "Start Docker Desktop." in problem.message
    assert problem.help == "docker.html"
    # ...and the probe's own state travels with it. One id covers every way a
    # container can be unready, because they are one story and one guide; the
    # window offers a Build button for the two states it can fix from there,
    # and picking that out of the sentence would be the wrong way to know.
    assert problem.state == "no_daemon"


def test_a_ready_container_stops_nothing():
    assert _container_problems(ready=True) == []


def test_a_probe_that_raises_is_reported_and_not_propagated():
    # Pre-flight runs while the banner is being drawn; an exception there would
    # take the window's refresh with it.
    (problem,) = _container_problems(raises="something odd")
    assert "something odd" in problem.message


def test_help_page_missing_asset_returns_none():
    p = simulate.Problem("not-a-real-problem", "block", "msg")
    assert simulate.help_page(p) is None


def test_a_clean_answer_says_where_the_solver_answers_the_rest():
    """A clean pre-flight is where a caller stops reading, so
    the other half of the question -- the ground check, the lattice, the copper
    around the port, all of them the solver's and none of them visible here --
    has to name the verb that reads them back out of the run's log."""
    check = load("emkit.agent.verbs.check")
    clean = {
        "ok": True,
        "problems": [],
        "covers": list(check.COVERS),
        "defers_to_solver": list(check.DEFERS),
        "solver_says": check.SOLVER_SAYS,
    }
    rendered = "\n".join(check.lines(clean))
    assert "No problems with the board itself" in rendered
    assert "run log --severity warning" in rendered


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
