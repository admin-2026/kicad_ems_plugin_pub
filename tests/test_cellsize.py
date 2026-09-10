"""The cell-size range: the pair's rules and the sentence it reads back as.

``cell_mm`` and ``cell_max_mm`` are one control with two sides, and what the
window promises about them is text: four combinations mean four different
things, and two of them mean nothing the solver will accept. Both halves are
pure (no wx, no board), so they are checked here rather than through a live
pane -- the pane's own coverage is tests/test_advanced_pane.py, which sees
these two fields like any other Advanced field.

    python3 tests/test_cellsize.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

knobs = load("emkit.cellsize.knobs")
caption = load("emkit.cellsize.caption")


def test_blank_zero_and_junk_all_mean_leave_it_to_the_solver():
    # 0 is how every mesh knob spells "auto", so a typed 0 and an empty field
    # are the same knob; a half-typed one is not an error while the caption is
    # being redrawn on it (the strict parse belongs to the run).
    for text in ("", "   ", "0", "0.0", "-1", "abc", "0.", None):
        assert knobs.value(text) is None, text
    assert knobs.value("0.2") == 0.2
    assert knobs.value(" 0.5 ") == 0.5


def test_a_start_above_the_ceiling_is_an_empty_range():
    # CFG-042: no cell satisfies both keys, so neither is the one that wins.
    problem = knobs.problem("0.4", "0.2")
    assert "cell_mm 0.4 mm" in problem and "cell_max_mm 0.2 mm" in problem
    assert "empty range" in problem
    # Equal is a range of exactly one cell; finer than the ceiling is the
    # ordinary case; and with no ceiling there is nothing to contradict.
    assert knobs.problem("0.2", "0.2") is None
    assert knobs.problem("0.1", "0.2") is None
    assert knobs.problem("0.4", "") is None


def test_a_floor_above_the_ceiling_can_never_bind():
    # CFG-043: the ceiling bounds every base cell the config permits, so a
    # coarser floor is a knob that would silently do nothing.
    problem = knobs.problem("", "0.2", floors=(("feature_min_cell_mm", "0.3"),))
    assert "feature_min_cell_mm 0.3 mm" in problem and "cell_max_mm 0.2 mm" in problem
    # An automatic floor (0) is derived from the cell and follows the ceiling.
    assert knobs.problem("", "0.2", floors=(("feature_min_cell_mm", "0"),)) is None
    # No ceiling: a floor has nothing to be above.
    assert knobs.problem("", "0", floors=(("via_min_cell_mm", "9"),)) is None


def test_an_untouched_pair_is_captioned_with_nothing():
    # The placeholders already say both fields are the solver's; a sentence
    # restating that would be the one caption here that never changes.
    assert caption.caption("", "") == ""
    assert caption.caption("0", "0") == ""


def test_a_ceiling_alone_captions_a_refinement():
    # The knob's main use, and the reading that has to come first: the rule
    # still applies, the ceiling only makes its answer finer.
    text = caption.caption("", "0.2")
    assert text.startswith("Auto, refined to 0.2 mm")
    assert "coarser cell" in text
    # Where the ceiling set the cell, the budget re-mesh has nowhere to land.
    assert "still under 0.2 mm" in text
    assert "re-meshing is off" in caption.caption("", "0.2", fit_cell=False)


def test_a_pinned_cell_says_the_rule_is_off():
    # The way to coarsen a mesh, and what it costs: both safety terms stop
    # applying, on this board and on every later one.
    text = caption.caption("0.3", "")
    assert text.startswith("Mesh at 0.3 mm")
    assert "automatic rule" in text and "is off" in text
    assert "re-meshes as coarse as it needs to" in text
    assert "the run stops" in caption.caption("0.3", "", fit_cell=False)


def test_the_pair_captions_the_range_it_brackets():
    text = caption.caption("0.2", "0.5")
    assert "Mesh at 0.2 mm" in text and "no cell coarser than 0.5 mm" in text
    assert "may coarsen inside that range" in text


def test_the_pair_says_when_the_ceiling_binds_nothing():
    # An explicit cell with the re-mesh tick off leaves the ceiling with
    # nothing to bound -- an inert knob, said out loud rather than left to look
    # like it is working.
    text = caption.caption("0.2", "0.5", fit_cell=False)
    assert "binds nothing here" in text


def test_an_empty_range_captions_the_refusal_the_run_would_raise():
    # The same sentence the writer raises with, so the window says it while the
    # number is being typed instead of after a run is prepared.
    assert caption.caption("0.4", "0.2") == knobs.problem("0.4", "0.2")


def test_the_advice_names_both_directions():
    # Which side does what is the one thing a user cannot guess: a ceiling set
    # coarser than the automatic cell is silently inert.
    assert "refine" in caption.ADVICE and "coarsen" in caption.ADVICE


if __name__ == "__main__":
    run_module_tests(globals())
