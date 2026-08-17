"""Contract tests: every registered antenna design, held to design/base.py.

These run over ``registry.DESIGNS``, so a new topology is covered the moment it
is listed -- the point of the contract is that the scan driver, the GUI and the
views can rely on it without knowing which design they have. A design that
breaks one of these would break a wizard page it was never tested against.

    python3 tests/test_designs.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import ROOT, load, run_module_tests  # noqa: E402

base = load("design.base")
footprints = load("design.footprints")
geometry = load("design.geometry")
registry = load("design.registry")
sizing = load("design.sizing")

F0 = 2.45


def _area(design, f0=F0):
    """The starter area the design asks for, as a decoded marker rectangle at
    the origin (KiCad mm, Y down -- the feed edge is the bottom one)."""
    w, h = design.area_hint_mm(f0)
    return (0.0, 0.0, w, h)


def _default_geo(design, f0=F0):
    return design.solve(_area(design, f0), "bottom", 0.3, design.default_values(f0))


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
def test_registry_keys_are_unique_and_resolvable():
    keys = [d.key for d in registry.DESIGNS]
    assert len(keys) == len(set(keys)) and all(keys)
    for design in registry.DESIGNS:
        assert registry.by_key(design.key) is design
        assert registry.resolve(design.key) is design
        assert registry.resolve(design) is design


def test_unknown_key_names_what_is_available():
    try:
        registry.by_key("dipole")
        assert False, "expected KeyError"
    except KeyError as exc:
        assert "unknown antenna design" in str(exc)
        assert registry.DESIGNS[0].key in str(exc)


def test_every_design_is_fully_described():
    for design in registry.DESIGNS:
        for field in (
            "name",
            "short_name",
            "title",
            "summary",
            "wiring",
            "footprint_prefix",
        ):
            assert getattr(design, field), f"{design.key}.{field}"
        assert (ROOT / "antenna_plugin" / design.icon).is_file(), design.icon


def test_every_design_has_a_length_and_a_width_parameter():
    for design in registry.DESIGNS:
        keys = [p.key for p in design.params]
        assert len(keys) == len(set(keys))
        assert design.LENGTH_KEY in keys and design.WIDTH_KEY in keys
        # The resonant length leads the table: it is the row the automatic
        # ladder acts on and the one the wizard selects first.
        assert keys[0] == design.LENGTH_KEY
        for p in design.params:
            assert p.label, f"{design.key}.{p.key}"
            assert design.param(p.key) is p
            assert design.param_label(p.key) == p.label


def test_every_parameter_ships_the_illustration_it_names():
    # The Scan section shows Param.icon beside the row (gui/sections/scan.py),
    # and a name that doesn't resolve is a picture silently missing from a
    # dialog -- so the artwork is checked here, where a typo fails loudly. The
    # PNGs are drawn by tools/icons/scan.py.
    for design in registry.DESIGNS:
        for p in design.params:
            assert p.icon, f"{design.key}.{p.key} has no illustration"
            path = ROOT / "antenna_plugin" / "assets" / "icons" / p.icon
            assert path.is_file(), f"{design.key}.{p.key}: {p.icon}"


def test_unknown_parameter_names_the_design():
    design = registry.DESIGNS[0]
    try:
        design.param("nonesuch")
        assert False, "expected KeyError"
    except KeyError as exc:
        assert design.key in str(exc)


# --------------------------------------------------------------------------- #
# Seeds
# --------------------------------------------------------------------------- #
def test_seeds_are_ordered_and_bracket_their_value():
    for design in registry.DESIGNS:
        for key, (lo, hi, value) in design.seed_values(F0).items():
            assert 0 < lo < hi, f"{design.key}.{key}"
            assert lo <= value <= hi, f"{design.key}.{key}"


def test_relative_seeds_track_the_frequency():
    # Halving the frequency doubles the quarter wave, so every relative seed
    # doubles with it -- this is what re-seeds a wizard when the target moves.
    for design in registry.DESIGNS:
        low, high = design.seed_values(1.0), design.seed_values(2.0)
        for p in design.params:
            a, b = low[p.key][2], high[p.key][2]
            if p.seed.relative:
                assert math.isclose(a, 2 * b, rel_tol=1e-9)
            else:
                assert a == b


def test_the_default_geometry_solves_in_the_designs_own_area():
    """The starter area a design asks for must hold the geometry its own
    seeds describe -- otherwise a freshly opened wizard shows an error."""
    for design in registry.DESIGNS:
        geo = _default_geo(design)
        assert isinstance(geo, geometry.Geometry)
        assert geo.paths and all(len(p.points) >= 2 for p in geo.paths)
        assert math.isclose(
            geo.total_mm, design.default_values(F0)[design.LENGTH_KEY], abs_tol=1e-3
        )


def test_the_area_hint_holds_at_least_a_quarter_wave():
    """The starter area must have the capacity for the quarter wave the
    ladder is centred on -- above that the ladder clips to what fits, which is
    fine, but a starter area that cannot hold the estimate itself would make
    the first scan meaningless."""
    for design in registry.DESIGNS:
        cap = design.capacity_mm(
            _area(design), "bottom", 0.3, design.default_values(F0)
        )
        assert cap >= sizing.quarter_wave_mm(F0), design.key


# --------------------------------------------------------------------------- #
# Solve / capacity
# --------------------------------------------------------------------------- #
def test_capacity_is_solvable_and_is_a_real_ceiling():
    for design in registry.DESIGNS:
        area = _area(design)
        values = dict(design.default_values(F0))
        cap = design.capacity_mm(area, "bottom", 0.3, values)
        values[design.LENGTH_KEY] = cap
        design.solve(area, "bottom", 0.3, values)  # exactly fits
        values[design.LENGTH_KEY] = cap * 1.5
        try:
            design.solve(area, "bottom", 0.3, values)
            assert False, f"{design.key}: solved past its capacity"
        except ValueError:
            pass


def test_solving_from_every_edge_puts_the_feed_on_it():
    """The area marker can be rotated to feed from any side, so a design must
    lay out from all four -- with the port on the named edge and the geometry
    pointing into the area."""
    for design in registry.DESIGNS:
        # A square as big as the design's starter area in either direction, so
        # the same rectangle serves as all four feed edges.
        side = max(design.area_hint_mm(F0))
        (x0, y0, x1, y1) = area = (0.0, 0.0, side, side)
        values = design.default_values(F0)
        for edge, axis, want, inward in (
            ("bottom", 1, y1, (0, -1)),
            ("top", 1, y0, (0, 1)),
            ("left", 0, x0, (1, 0)),
            ("right", 0, x1, (-1, 0)),
        ):
            geo = design.solve(area, edge, 0.3, values)
            assert geo.inward == inward, (design.key, edge)
            assert math.isclose(geo.feed[axis], want), (design.key, edge)


def test_solved_copper_is_axis_aligned_and_covers_every_segment():
    for design in registry.DESIGNS:
        geo = _default_geo(design)
        rects = geo.copper_rects(1.0, 0.5)
        segments = sum(len(p.points) - 1 for p in geo.paths)
        assert len(rects) == segments, design.key
        for rx0, ry0, rx1, ry1 in rects:
            assert rx0 < rx1 and ry0 < ry1, design.key
        # Dropping the stubs never grows the copper.
        bare = geo.copper_rects(1.0, 0.5, include_stub=False)
        assert len(bare) == len(rects)


def test_describe_is_a_one_liner():
    for design in registry.DESIGNS:
        text = design.describe(_default_geo(design))
        assert isinstance(text, str) and text and "\n" not in text


# --------------------------------------------------------------------------- #
# Footprint
# --------------------------------------------------------------------------- #
def test_every_design_emits_a_loadable_footprint():
    for design in registry.DESIGNS:
        geo = _default_geo(design)
        name = footprints.item_name(design, F0, geo.total_mm)
        assert "." not in name and name.startswith(design.footprint_prefix)
        text = footprints.sexpr(design, geo, design.default_values(F0), F0)
        assert text.count("(") == text.count(")"), design.key
        assert text.startswith(f'(footprint "{name}"')
        assert '(layer "F.Cu")' in text
        pads = design.footprint_pads(geo)
        assert pads and pads[0][1] == geo.feed  # pad 1 is the feed
        assert text.count("(pad ") == len(pads)
        # The origin is the feed point, so pad 1 sits at (0, 0) -- and it is
        # the pad that carries the radiator, as one primitive per centerline
        # segment. No copper is left over as a netless graphic.
        assert '(pad "1" smd custom (at 0 0)' in text
        assert "fp_poly" not in text
        assert text.count("gr_poly") == sum(len(p.points) - 1 for p in geo.paths)
        assert "(options (clearance outline) (anchor rect))" in text
        # A design with a second pad short-circuits two nets on purpose.
        tie = f'  (net_tie_pad_groups "{", ".join(n for n, _pt in pads)}")'
        assert (tie in text) == (len(pads) > 1), design.key


def test_footprint_radiator_is_one_blob_touching_the_anchor():
    """A custom pad's primitives have to hang together and reach the pad's
    anchor -- KiCad's footprint checker rejects a shape whose copper is in two
    pieces, and a floating piece would carry no net, which is the whole reason
    the radiator is a pad and not a graphic. Every design's copper is one chain
    from the feed, so this is a property of the geometry, checked here rather
    than trusted."""
    for design in registry.DESIGNS:
        for trace_w in (0.4, 1.0, 1.6):
            values = dict(design.default_values(F0))
            values[design.WIDTH_KEY] = trace_w
            geo = design.solve(_area(design), "bottom", 0.3, values)
            fx, fy = geo.feed
            h = trace_w / 2.0
            anchor = (fx - h, fy - h, fx + h, fy + h)
            rects = [anchor] + geo.copper_rects(trace_w, 0.0, include_stub=False)
            reached, front = {0}, [0]
            while front:  # flood fill from the anchor through touching copper
                a = rects[front.pop()]
                for i, b in enumerate(rects):
                    if i not in reached and _touch(a, b):
                        reached.add(i)
                        front.append(i)
            assert len(reached) == len(rects), (design.key, trace_w)


def _touch(a, b, eps=1e-9):
    """Whether two (x0, y0, x1, y1) rectangles share any copper, edges
    included -- copper that touches is copper that conducts."""
    return (
        a[0] <= b[2] + eps
        and b[0] <= a[2] + eps
        and a[1] <= b[3] + eps
        and b[1] <= a[3] + eps
    )


def test_footprint_pads_are_exactly_the_track_width():
    """Every pad is the width of the antenna it terminates -- no floor, no
    padding. A wider pad is a step of copper at the port the scan never
    simulated; a narrower one necks the antenna's own current."""
    for design in registry.DESIGNS:
        for trace_w in (0.4, 1.0, 1.6):
            values = dict(design.default_values(F0))
            values[design.WIDTH_KEY] = trace_w
            geo = design.solve(_area(design), "bottom", 0.3, values)
            text = footprints.sexpr(design, geo, values, F0)
            # Pad lines only: the font sizes are "(size 1 1)" too.
            sizes = [
                line.split("(size ")[1].split(")")[0]
                for line in text.splitlines()
                if "(pad " in line
            ]
            assert len(sizes) == len(design.footprint_pads(geo)), design.key
            assert sizes == [f"{trace_w:g} {trace_w:g}"] * len(sizes), (
                design.key,
                trace_w,
            )


if __name__ == "__main__":
    run_module_tests(globals())
