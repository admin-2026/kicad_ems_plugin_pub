"""Does the candidate fit the area marker -- and what is drawn when it doesn't.

The wizard draws the candidate at the current sliders straight into the placed
area marker (sections/scan.py). Shrink the area, widen the track or stretch the
length past what the rectangle holds and the design's ``solve`` raises: there
is no geometry inside the area to draw.

There is, however, a geometry -- just not one that fits. This module is the one
place that says which of the two the wizard has. It answers the question once
(:func:`check`) and hands back a :class:`Fit` carrying everything the GUI wants
from it:

``geo``            the geometry solved inside the area, or None -- the fit test
                   itself
``overflow``       the same candidate laid out in the smallest rectangle that
                   does hold it (:func:`_overflow`), so a candidate that
                   doesn't fit still has a shape: the wizard draws it on the
                   marker's own User layer instead of on copper, spilling out
                   of the rectangle by exactly what is missing. None only when
                   growing the area is not the answer at all (values the
                   geometry rejects on their own terms)
``preview``        whichever of the two there is -- what the wizard draws
``detail``         why it doesn't fit, in one line: the design's own message
                   plus, when that is what went wrong, the longest resonant
                   length the area *does* hold (``design.capacity_mm``)

Self-contained and pure: it imports the design contract and nothing else -- no
wx, no pcbnew -- so the whole fit story is unit-testable off KiCad against every
registered design (tests/test_fit.py) and nothing else has to change when its
wording does.
"""

import math
from typing import NamedTuple

from . import base

# The search for the smallest rectangle that holds an overflowing candidate
# (_overflow): where it starts doubling from, how far past the largest knob it
# gives up, and how closely it pins the answer down. A tenth of a millimetre is
# well under what a preview shows; the solves it costs are pure arithmetic.
_GROW_START_MM = 0.5
_GROW_CEILING = 4.0
_GROW_TOL_MM = 0.1


class Fit(NamedTuple):
    """The answer to "does this candidate fit?" -- see the module docstring.
    ``geo`` is None exactly when it doesn't, and then ``reason`` carries the
    design's own explanation, ``capacity_mm`` the length the area holds (None
    when the length is not what went wrong) and ``overflow`` the shape to draw
    outside the rectangle instead."""

    design: object
    values: dict
    geo: object
    reason: str
    capacity_mm: float
    overflow: object

    @property
    def ok(self):
        return self.geo is not None

    @property
    def preview(self):
        """The geometry the wizard draws for this candidate: the one solved
        inside the area when it fits, the overflowing one when it doesn't
        (which is why the drawing layer follows ``ok``, not this). None when
        the values yield no shape at all."""
        return self.geo if self.ok else self.overflow

    @property
    def detail(self):
        """Why it doesn't fit, in one line the user can act on: the design's
        own message, and -- when the resonant length is what overflowed -- the
        longest one this area holds at the other values. Empty when it fits."""
        if self.ok:
            return ""
        if self.capacity_mm is None:
            return self.reason
        label = self.design.param_label(self.design.LENGTH_KEY).lower()
        return (
            f"{self.reason} -- at these values the area holds at most "
            f"{base.mm(_floor_mm(self.capacity_mm))} mm of {label}"
        )


def check(design, area, edge, frac, values):
    """Solve ``design`` at ``values`` in the decoded area marker and report
    the outcome as a :class:`Fit`. Never raises for a geometry that doesn't
    fit -- that is the answer, not an error (a caller that wants the raise
    keeps using ``design.solve``)."""
    try:
        geo = design.solve(area, edge, frac, values)
    except ValueError as exc:
        return Fit(
            design,
            dict(values),
            None,
            str(exc),
            _capacity(design, area, edge, frac, values),
            _overflow(design, area, edge, frac, values),
        )
    return Fit(design, dict(values), geo, "", None, None)


def _floor_mm(value):
    """A capacity for a human to type back in, at 0.01 mm -- rounded *down*.
    An area holding 81.385 mm must not be quoted as "at most 81.39 mm", a
    length that then fails to solve by a hundredth of a millimetre (the trap
    ``sizing.snap`` avoids for the candidate lengths themselves)."""
    return math.floor(value * 100) / 100


def _capacity(design, area, edge, frac, values):
    """The longest resonant length this area holds at ``values``' other
    parameters -- but only when the length is what overflowed. None otherwise:
    a candidate rejected for something else (an inverted-F's tap too close to
    its feed pin, an area too narrow for the track at all) would be *more*
    confusing for being told a length it already respects."""
    try:
        cap = design.capacity_mm(area, edge, frac, values)
    except ValueError:
        return None  # the area holds nothing at all
    length = values.get(design.LENGTH_KEY)
    if cap is None or length is None or length <= cap + 1e-9:
        return None
    return cap


def _overflow(design, area, edge, frac, values):
    """The candidate laid out as if the area were just big enough: the same
    solve in the **smallest** rectangle grown around the fixed feed point
    (:func:`_grown`) that holds it. The wizard draws this on the marker's own
    User layer -- an antenna spilling out of the rectangle it doesn't fit into
    is the thing to look at, and the thing to drag an area slider against; an
    empty marker is not.

    Smallest, rather than simply big enough, because the spill is the message:
    it should be as small as the miss is, and the shape should be the one the
    area nearly held -- an inverted-F given acres of room would draw a straight
    arm where the user was watching a meander, and a candidate a hair too long
    would jump to a different antenna instead of poking out by a hair. The
    search doubles a margin until the solve lands (the biggest knob bounds how
    far, since every design's parameters are mm lengths) and then bisects to
    ``_GROW_TOL_MM``; every geometry returned is one that really solved, so a
    design whose feasibility isn't monotonic in area costs accuracy, never
    correctness.

    None when growing is not the answer at all: values a design rejects on
    their own terms -- an inverted-F's tap narrower than its own track pitch, a
    length that isn't a length -- fail the same way in any rectangle, and there
    is no shape to draw."""

    def solved(margin):
        grown, grown_frac = _grown(area, edge, frac, margin)
        try:
            return design.solve(grown, edge, grown_frac, values)
        except ValueError:
            return None

    knobs = [
        v
        for v in values.values()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    ceiling = _GROW_CEILING * max([v for v in knobs if v > 0] or [0.0])
    lo, hi, geo = 0.0, None, None
    margin = _GROW_START_MM
    while hi is None and margin <= max(ceiling, _GROW_START_MM):
        geo = solved(margin)
        if geo is None:
            lo, margin = margin, margin * 2
        else:
            hi = margin
    if hi is None:
        return None
    while hi - lo > _GROW_TOL_MM:
        mid = (lo + hi) / 2
        found = solved(mid)
        if found is None:
            lo = mid
        else:
            hi, geo = mid, found
    return geo


def _grown(area, edge, frac, margin_mm):
    """``(area, frac)`` for a rectangle grown to hold an overflowing
    candidate: the feed edge extended by ``margin_mm`` at both ends and the
    area deepened by it away from that edge, with the feed point left exactly
    where it is -- ``frac`` is re-expressed in the bigger rectangle, so the
    antenna still starts on the marker's feed arrow and only its far end
    escapes.

    Both ends of the feed edge grow by the same amount on purpose: that keeps
    the roomier side roomier, so the drawn candidate bends the way it will once
    the area really holds it (``geometry.edge_frame`` picks its tangent from
    that comparison)."""
    x0, y0, x1, y1 = area
    m = float(margin_mm)
    lo, hi = (x0, x1) if edge in ("bottom", "top") else (y0, y1)
    pos = lo + frac * (hi - lo)  # the feed, in absolute mm
    lo, hi = lo - m, hi + m
    grown_frac = (pos - lo) / (hi - lo)
    # Deepen away from the feed edge only (Y-down: "bottom" is the max-Y edge).
    box = {
        "bottom": (x0 - m, y0 - m, x1 + m, y1),
        "top": (x0 - m, y0, x1 + m, y1 + m),
        "left": (x0, y0 - m, x1 + m, y1 + m),
        "right": (x0 - m, y0 - m, x1, y1 + m),
    }.get(edge)
    if box is None:
        raise ValueError(f"unknown edge '{edge}'")
    return box, grown_frac
