"""The parameter record a generated footprint carries on F.Fab.

Everything about design/annotation.py is checked here and nowhere else, which
is the same claim the module makes about itself: the record is an annotation,
not an input, so deleting the module, its one line in ``footprints.sexpr`` and
this file leaves a plugin that places exactly the same copper and a suite that
still passes.

The tests run over ``registry.DESIGNS``, so a new topology's knobs are covered
the moment it is listed.

    python3 tests/test_annotation.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

annotation = load("design.annotation")
footprints = load("design.footprints")
registry = load("design.registry")
versions = load("versions")

F0 = 2.45


def _area(design, f0=F0):
    w, h = design.area_hint_mm(f0)
    return (0.0, 0.0, w, h)


def _default_geo(design, f0=F0):
    return design.solve(_area(design, f0), "bottom", 0.3, design.default_values(f0))


def _fab_lines(text):
    """The record's text items of a .kicad_mod, as whole lines."""
    return [line for line in text.splitlines() if "(fp_text user " in line]


# --------------------------------------------------------------------------- #
# What is recorded
# --------------------------------------------------------------------------- #
def test_the_record_holds_every_knob_of_the_design():
    """What generated the copper travels with it: the design, the plugin that
    laid it out, the target frequency and *every* parameter of the design -- a
    new knob is in the record the moment it is in the table, or a footprint's
    parameters would be a partial answer nobody could tell from a whole one."""
    for design in registry.DESIGNS:
        values = design.default_values(F0)
        lines = annotation.record(design, values, F0)
        keys = [line.split("=")[0] for line in lines]
        assert keys == ["design", "plugin_version", "f0_ghz"] + [
            f"{p.key}_mm" for p in design.params
        ], design.key
        assert lines[0] == f"design={design.key}"


def test_the_derived_geometry_is_not_recorded():
    """Only what was asked for: an L-monopole's arm and a meander's fold count
    are what solve makes of these values, and a copy beside the copper could
    only go stale. A column that merely restates a knob (the L-monopole's
    stem, which is both) is that knob, and is recorded as one."""
    for design in registry.DESIGNS:
        recorded = " ".join(annotation.record(design, design.default_values(F0), F0))
        knobs = {f"{p.key}_mm" for p in design.params}
        derived = [c.key for c in design.columns if c.key not in knobs]
        assert derived, design.key  # or the case isn't being tested at all
        for key in derived:
            assert key not in recorded, (design.key, key)


def test_the_record_names_the_plugin_that_laid_the_copper_out():
    """A topology's layout can move between releases, so the same values
    re-solve into a subtly different antenna. The record says which plugin's
    idea of them the copper beside it is -- and, on a host where that cannot
    be established, says *that* rather than inventing one."""
    design = registry.DESIGNS[0]
    values = design.default_values(F0)
    pkg = sys.modules["antenna_plugin"]  # the bare package: no __version__
    assert annotation.record(design, values, F0)[1] == (
        f"plugin_version={versions.UNKNOWN}"
    )
    pkg.__version__ = "9.9.9"
    try:
        lines = annotation.record(design, values, F0)
    finally:
        del pkg.__version__
    assert lines[1] == "plugin_version=9.9.9"


def test_a_knob_without_a_value_is_refused_not_recorded():
    for design in registry.DESIGNS:
        values = dict(design.default_values(F0))
        dropped = design.params[-1].key
        del values[dropped]
        try:
            annotation.record(design, values, F0)
            assert False, f"expected ValueError for {design.key}"
        except ValueError as exc:
            assert dropped in str(exc), design.key


# --------------------------------------------------------------------------- #
# On the footprint
# --------------------------------------------------------------------------- #
def test_the_generated_footprint_carries_the_record():
    for design in registry.DESIGNS:
        values = design.default_values(F0)
        text = footprints.sexpr(design, _default_geo(design), values, F0)
        fab = _fab_lines(text)
        assert len(fab) == len(annotation.record(design, values, F0)), design.key
        assert all(f'(layer "{annotation.LAYER}")' in line for line in fab), design.key
        # Visible: a record the board editor doesn't draw is one nobody knows
        # to look for (hidden text takes an Appearance toggle to see at all).
        assert not any(" hide" in line for line in fab), design.key
        # Nothing but the record itself -- no prefix to read past on the
        # drawing.
        assert fab[0].split('"')[1] == f"design={design.key}", design.key


def test_the_lines_stack_below_the_footprints_own_text():
    """One line pitch apart, under the value field the caller passes -- so the
    block reads as a block and nothing lands on the copper above it."""
    design = registry.DESIGNS[0]
    items = annotation.fab_text(design, design.default_values(F0), F0, below_mm=3.2)
    ys = [float(item.split("(at 0 ")[1].split(")")[0]) for item in items]
    assert math.isclose(ys[0], 3.2 + annotation.LINE_MM)
    steps = {round(b - a, 6) for a, b in zip(ys, ys[1:])}
    assert steps == {annotation.LINE_MM}


# --------------------------------------------------------------------------- #
# Reading it back
# --------------------------------------------------------------------------- #
def test_the_record_reads_back_as_the_values_it_was_written_from():
    for design in registry.DESIGNS:
        values = design.default_values(F0)
        text = footprints.sexpr(design, _default_geo(design), values, F0)
        read = annotation.read(text)
        assert read.design == design.key and registry.by_key(read.design) is design
        assert read.plugin_version == versions.plugin_version(), design.key
        assert math.isclose(read.f0_ghz, F0)
        assert read.values.keys() == values.keys(), design.key
        for key, value in values.items():
            assert math.isclose(read.values[key], value, abs_tol=1e-6), (
                design.key,
                key,
            )
        # ... and the values read back re-solve the copper they were written
        # beside (to the nanometre they are written at -- see modtext.num).
        again = design.solve(_area(design), "bottom", 0.3, read.values)
        was = _default_geo(design)
        assert [p.stub for p in again.paths] == [p.stub for p in was.paths]
        for path, before in zip(again.paths, was.paths):
            assert len(path.points) == len(before.points), design.key
            for got, want in zip(path.points, before.points):
                assert math.isclose(got[0], want[0], abs_tol=1e-6), design.key
                assert math.isclose(got[1], want[1], abs_tol=1e-6), design.key


def test_a_footprint_that_is_not_ours_has_no_record():
    assert annotation.read('(footprint "R_0603" (layer "F.Cu"))\n') is None
    # ... including one whose F.Fab carries a fab note of somebody's own.
    note = '  (fp_text user "DO NOT POPULATE" (at 0 2) (layer "F.Fab")\n'
    assert annotation.read(note) is None


def test_a_damaged_record_is_a_complaint_not_a_guess():
    design = registry.DESIGNS[0]
    text = footprints.sexpr(
        design, _default_geo(design), design.default_values(F0), F0
    ).replace("f0_ghz=2.45", "f0_ghz=about 2.45")
    try:
        annotation.read(text)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "damaged" in str(exc)


if __name__ == "__main__":
    run_module_tests(globals())
