"""design/fit.py: does the candidate still fit the area, and what is drawn when
it doesn't.

Run over every registered design, because the whole point of the module is that
the wizard's "it doesn't fit" story is told the same way whatever the topology
-- the design supplies the reason, the capacity and the layout, fit.py decides
which of the two shapes the wizard draws.

    python3 tests/test_fit.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

fit = load("design.fit")
registry = load("design.registry")

F0 = 2.45
EDGE = "bottom"


def _area(design, scale=1.0):
    """The design's starter area as a decoded marker rectangle (KiCad mm, Y
    down -- the bottom edge is the feed edge), optionally scaled."""
    w, h = design.area_hint_mm(F0)
    return (0.0, 0.0, w * scale, h * scale)


def _check(design, values, scale=1.0):
    """The design at ``values`` in its own starter area, fed where a fresh
    marker's arrow lands (``feed_frac``: off to one side for the wire designs,
    the middle for the patch, which is centred on its feed)."""
    return fit.check(design, _area(design, scale), EDGE, design.feed_frac, values)


def _too_long(design):
    """The design's defaults with a resonant length no area of that size can
    hold -- what a user gets by dragging the length slider up in a small area,
    or by shrinking the area under a length that fitted."""
    values = design.default_values(F0)
    values[design.LENGTH_KEY] = values[design.LENGTH_KEY] * 20
    return values


# --------------------------------------------------------------------------- #
# It fits
# --------------------------------------------------------------------------- #
def test_the_default_candidate_fits_its_own_starter_area():
    for design in registry.DESIGNS:
        state = _check(design, design.default_values(F0))
        assert state.ok, design.key
        assert state.geo is not None and state.reason == ""
        assert state.detail == "", design.key  # nothing to report
        # What gets drawn is the geometry inside the area -- on copper.
        assert state.preview is state.geo, design.key
        assert state.overflow is None, design.key


# --------------------------------------------------------------------------- #
# It doesn't
# --------------------------------------------------------------------------- #
def test_a_candidate_that_does_not_fit_is_an_answer_not_an_exception():
    """The whole point: fit.check reports, never raises -- the GUI asks this
    question on every slider move."""
    for design in registry.DESIGNS:
        state = _check(design, _too_long(design))
        assert not state.ok, design.key
        assert state.geo is None
        assert state.reason, design.key  # the design's own words


def test_the_detail_quotes_the_length_the_area_does_hold():
    """The number nothing showed before: the design's capacity, named with the
    design's own label for its resonant parameter."""
    for design in registry.DESIGNS:
        values = _too_long(design)
        area = _area(design)
        cap = design.capacity_mm(area, EDGE, design.feed_frac, values)
        state = fit.check(design, area, EDGE, design.feed_frac, values)
        assert state.capacity_mm == cap, design.key
        detail = state.detail
        assert state.reason in detail, design.key
        assert "at most" in detail, design.key
        assert design.param_label(design.LENGTH_KEY).lower() in detail


def test_the_quoted_length_is_one_that_actually_fits():
    """It is printed at 0.01 mm, so it has to be rounded *down*: a capacity of
    81.385 mm quoted as 81.39 would be a number the user types back in and
    watches fail."""
    for design in registry.DESIGNS:
        values = _too_long(design)
        area = _area(design)
        state = fit.check(design, area, EDGE, design.feed_frac, values)
        quoted = float(state.detail.split("at most ")[1].split(" mm")[0])
        assert quoted <= state.capacity_mm, design.key
        assert state.capacity_mm - quoted < 0.01, design.key
        # ... and typing it back in draws an antenna again.
        assert fit.check(
            design,
            area,
            EDGE,
            design.feed_frac,
            dict(values, **{design.LENGTH_KEY: quoted}),
        ).ok


def test_a_failure_that_is_not_about_length_quotes_no_capacity():
    """A candidate rejected for something else -- here an area too narrow for
    the track at all -- must not be told a length it already respects."""
    for design in registry.DESIGNS:
        values = design.default_values(F0)
        values[design.WIDTH_KEY] = 500.0  # wider than any area here
        state = _check(design, values)
        assert not state.ok, design.key
        assert state.capacity_mm is None, design.key
        assert state.detail == state.reason
        assert "at most" not in state.detail


# --------------------------------------------------------------------------- #
# ... and is drawn anyway, outside the rectangle
# --------------------------------------------------------------------------- #
def test_a_candidate_that_does_not_fit_still_has_a_shape_to_draw():
    """The wizard draws this one on the marker layer instead of on copper, so
    the antenna never silently vanishes off the board."""
    for design in registry.DESIGNS:
        state = _check(design, _too_long(design))
        assert state.overflow is not None, design.key
        assert state.preview is state.overflow, design.key
        # It is the candidate the user asked for, at full length -- an
        # overflowing preview that quietly shortened itself would be a lie.
        assert (
            abs(state.overflow.total_mm - _too_long(design)[design.LENGTH_KEY]) < 1e-3
        ), design.key


def test_the_overflowing_candidate_starts_at_the_same_feed_point():
    """It is grown around the feed, so it still leaves the marker's feed arrow
    and runs the same way in -- only its far end escapes the rectangle."""
    for design in registry.DESIGNS:
        area = _area(design)
        fitting = fit.check(
            design, area, EDGE, design.feed_frac, design.default_values(F0)
        )
        spilling = fit.check(design, area, EDGE, design.feed_frac, _too_long(design))
        # Same point, to within re-expressing the fraction in a bigger
        # rectangle (a float hair, far under a KiCad nanometre).
        assert all(
            abs(a - b) < 1e-6 for a, b in zip(fitting.geo.feed, spilling.overflow.feed)
        ), design.key
        assert fitting.geo.inward == spilling.overflow.inward, design.key
        # ... and it really is bigger than the area: something lands outside.
        x0, y0, x1, y1 = area
        assert any(
            not (x0 <= x <= x1 and y0 <= y <= y1)
            for (a, b) in spilling.overflow.centerline_segments()
            for (x, y) in (a, b)
        ), design.key


def test_values_no_area_could_hold_have_no_shape_at_all():
    """Growing the rectangle is not the answer to every rejection: values a
    design refuses on their own terms fail the same way at any size, and then
    there is nothing to draw (the wizard says so instead)."""
    for design in registry.DESIGNS:
        values = design.default_values(F0)
        values[design.LENGTH_KEY] = -1.0  # not a length at all
        state = _check(design, values)
        assert not state.ok and state.preview is None, design.key


# --------------------------------------------------------------------------- #
# Growing the area back
# --------------------------------------------------------------------------- #
def test_the_same_values_fit_again_once_the_area_is_grown():
    """What the wizard relies on to bring the preview back by itself: the fit
    is a pure function of (values, area), so nothing has to be reset."""
    for design in registry.DESIGNS:
        values = design.default_values(F0)
        assert not _check(design, values, scale=0.3).ok, design.key
        assert _check(design, values, scale=1.0).ok, design.key


if __name__ == "__main__":
    run_module_tests(globals())
