"""The contract every antenna design implements, and what it buys.

A *design* is one antenna topology the wizard can lay out, scan and place: the
L-shaped monopole (lmonopole.py), the meandered inverted-F (ifa.py), the
meandered monopole (meander.py), and whatever comes next. Everything around it
is written against this contract and nothing else -- the scan driver
(wizard_scan.py), the scan's view manifests (scan_views.py), the wizard page and
its Scan / Footprint sections -- so adding a topology is writing one module and
listing it in registry.py, with no edit to the driver, the GUI or the views.

A design supplies three things:

``params``      the geometry knobs the user sets and the scan sweeps, in table
                order. Every design has a *resonant length* (``LENGTH_KEY``,
                the one the frequency-aware ladder and the 1/L refinement act
                on) and a *track width* (``WIDTH_KEY``, which sizes the copper
                and the footprint pads); the rest are the design's own. Each
                carries a :class:`Seed` saying where its slider and its
                min/max start out, so the wizard never hard-codes a number for
                a topology it doesn't know.
``solve``       the antenna itself: values (a dict keyed by param) + the area
                marker's decoded rectangle -> a :class:`~.geometry.Geometry`
                (centerline paths + port + derived metrics). Raises ValueError
                with user-facing guidance when the values don't fit the area.
``capacity_mm`` the longest resonant length that area holds for the other
                values -- what bounds the scan ladder and drops the sweep
                values that cannot fit.

Everything downstream of ``solve`` is shared: copper rectangles, the gerber
splice and the port dict come from the Geometry (geometry.py), the candidate
lengths from sizing.py, the scoring from measure.py + scoring.py, and the
footprint from footprints.py.

Pure: a design module may not import wx or pcbnew, so every topology stays
unit-testable off KiCad (tests/test_designs.py checks the contract itself).
"""

import inspect
from typing import NamedTuple

from . import geometry, sizing


class Seed(NamedTuple):
    """Where a parameter's row starts out in the wizard: the min / max bounds
    and the slider's value inside them. ``relative`` (the default) reads the
    three as multiples of the free-space quarter wave at the target frequency,
    so a design describes its geometry in wavelengths and the wizard re-seeds
    it whenever the frequency changes; an absolute seed (the track width) is
    plain mm."""

    lo: float
    hi: float
    value: float
    relative: bool = True

    def at(self, quarter_wave_mm):
        """The seed as ``(lo, hi, value)`` in mm for this quarter wave."""
        if not self.relative:
            return (self.lo, self.hi, self.value)
        q = quarter_wave_mm
        return (self.lo * q, self.hi * q, self.value * q)


class Param(NamedTuple):
    """One geometry knob of a design: its ``key`` (how the scan spec, the
    result rows and the sweep refer to it), the ``label`` the wizard shows,
    the :class:`Seed` its row starts at, ``icon``, the picture of it, and
    ``reading``, the same thing in a sentence.

    ``icon`` names a PNG bundled under ``assets/icons/`` (drawn by
    tools/icons/designs/) showing which piece of *this* antenna the sweep
    moves: the words on a row can say "stem length", only the drawing can say
    which line that is. The Scan section puts it beside the row, and it is the
    *whole* of what the wizard says about a knob -- no hint, no paragraph
    under it.

    ``reading`` is for the reader who cannot see the drawing: it is what
    ``AntennaDesign.guide`` prints for the command line, and the wizard must
    never show it (tests/test_designs.py holds ``gui/`` to that). A picture
    beats a sentence at a dialog and is worth nothing down a pipe, so the two
    are not alternatives -- they are the same fact for two different readers.

    A shipped design illustrates and describes every knob (tests/test_designs.py
    holds it to both). Both fields still default to empty, which costs a row
    nothing but its picture, so a topology under development is not blocked on
    somebody drawing for it.
    """

    key: str
    label: str
    seed: Seed
    icon: str = ""
    reading: str = ""


class Column(NamedTuple):
    """A derived-geometry column of the result table: which key of a
    Geometry's ``metrics`` to show, its heading, and the suffix to print
    after the value (``" mm"``, or ``""`` for a count)."""

    key: str
    label: str
    suffix: str = " mm"


class AntennaDesign:
    """One antenna topology. Subclasses set the class attributes below and
    implement ``solve`` / ``capacity_mm``; the rest is provided here."""

    # --- identity -------------------------------------------------------------
    key = ""  # registry key; also names the scan's work folder
    name = ""  # "L-shaped monopole" -- prose, used in sentences
    short_name = ""  # "L-monopole" -- the name under the sidebar tab's
    # drawing, which is as wide as the sidebar gets
    title = ""  # the wizard page's heading
    icon = ""  # the bundled PNG for its sidebar tab
    summary = ""  # one line under the heading: what it designs
    wiring = ""  # what to route where once the footprint is placed
    footprint_prefix = ""  # library item-name prefix (see footprints.py)

    # --- geometry knobs -------------------------------------------------------
    LENGTH_KEY = "length"  # the resonant parameter (auto ladder + refine)
    WIDTH_KEY = "width"  # the track width (sizes copper and pads)

    params = ()  # tuple[Param], in table order
    columns = ()  # tuple[Column]: derived metrics worth a column

    # --- solving --------------------------------------------------------------
    def solve(self, area, edge, frac, values):
        """The candidate geometry for ``values`` (a dict keyed by param key)
        inside the decoded area marker: ``area`` (x0, y0, x1, y1 KiCad mm, the
        marker's derotated frame), the ``edge`` the feed enters from and
        ``frac``, the feed's position along it. Returns a
        :class:`~.geometry.Geometry`; raises ValueError, with a message the
        user can act on, when the values don't fit."""
        raise NotImplementedError

    def capacity_mm(self, area, edge, frac, values):
        """The longest resonant length this area can hold for ``values``'
        other parameters -- the ceiling the scan ladder is clipped to and the
        test that drops infeasible sweep values. Raises ValueError when the
        area cannot hold the antenna at all (too narrow for the track)."""
        raise NotImplementedError

    def footprint_pads(self, geo):
        """The generated footprint's pads as ``(number, point)`` pairs in the
        solved frame. Pad 1 is the feed for every design; a topology with a
        second connection (an inverted-F's ground pin) adds it."""
        return (("1", geo.feed),)

    # --- provided -------------------------------------------------------------
    def param(self, key):
        """The :class:`Param` for ``key``."""
        for p in self.params:
            if p.key == key:
                return p
        raise KeyError(f"{self.key} design has no '{key}' parameter")

    def param_label(self, key):
        return self.param(key).label

    def seed_values(self, f0_ghz):
        """Every parameter's starting ``(lo, hi, value)`` in mm for a target
        frequency -- the wizard's row seeding, one call (see Seed)."""
        q = sizing.quarter_wave_mm(f0_ghz)
        return {p.key: p.seed.at(q) for p in self.params}

    def default_values(self, f0_ghz):
        """Every parameter's starting slider value in mm -- the geometry a
        preview shows before the user touches anything."""
        return {
            key: value for key, (_lo, _hi, value) in self.seed_values(f0_ghz).items()
        }

    def describe(self, geo):
        """A one-line summary of a solved geometry for the preview status
        line, e.g. "stem 4 + arm 8 mm". The default lists every derived
        column."""
        return ", ".join(
            f"{c.label.lower()} {mm(geo.metrics[c.key])}{c.suffix}"
            for c in self.columns
            if geo.metrics.get(c.key) is not None
        )

    def area_hint_mm(self, f0_ghz):
        """The starter area rectangle (width, height in mm) the wizard sizes a
        freshly placed area marker to: big enough that the design's default
        geometry fits with room to scan. Sized off the quarter wave, so it
        follows the target frequency."""
        raise NotImplementedError

    def guide(self, f0_ghz):
        """This topology explained to a reader with no screen: what it is, how
        it is wired, every knob and where that knob starts at ``f0_ghz``.

        Provided here and not overridden -- a design that needs different
        words has a different docstring, not a different method. Everything
        below is already declared; the only thing this adds is a reading
        order.

        The explanation comes from the design *module's* docstring, drawing
        included: that is where each topology is actually written down (the
        classes carry no docstring of their own), and taking the class's would
        silently print this one for every design, since ``getdoc`` inherits.
        It is the one docstring in this package that is load-bearing rather
        than merely helpful.

        ``f0_ghz`` is an argument because every relative seed is a multiple of
        the quarter wave: the millimetres are meaningless without a frequency,
        and inventing one here would be this repository's one forbidden move.
        The caller says which frequency it is working, and says so on the page.
        """
        q = sizing.quarter_wave_mm(f0_ghz)
        out = [
            f"{self.name} — design key `{self.key}`",
            "",
            self.summary,
            "",
            f"Wiring: {self.wiring}",
            f"Its generated footprints are named {self.footprint_prefix}_…",
            "",
            inspect.getdoc(inspect.getmodule(type(self))) or "",
            "",
            f"Knobs, as lo … start … hi in mm at {f0_ghz:g} GHz "
            "(a relative seed scales with 1/frequency):",
        ]
        for p in self.params:
            lo, hi, value = p.seed.at(q)
            out.append(
                f"  {p.key} — {p.label}: {mm(lo)} … {mm(value)} … {mm(hi)} mm"
                f"{self._role(p)}"
            )
            out.append(f"      {p.reading}")
        if self.columns:
            out.append("")
            out.append(
                "Derived geometry reported per candidate: "
                + ", ".join(f"{c.key} ({c.label.lower()})" for c in self.columns)
            )
        return "\n".join(out)

    def _role(self, param):
        """What the shared machinery does with this knob, for the two it
        singles out. Everything else is the design's own and the reading is
        the whole story."""
        if param.key == self.LENGTH_KEY:
            return "  [the resonant length: what a scan sweeps]"
        if param.key == self.WIDTH_KEY:
            return "  [the track width: sizes the copper and the pads]"
        return ""


def mm(value):
    """A millimetre number for a status line or a table cell: two decimals at
    most, trailing zeros dropped. Geometry is kept at full precision
    internally and only rounded where a human reads it."""
    return f"{round(value, 2):g}"


def min_pitch_mm(trace_w_mm):
    """The smallest centerline spacing two parallel runs of the same antenna
    may have: the track width plus a fixed clearance. Shared by the designs
    that fold copper back on itself, or run two pins side by side (see
    geometry.TRACK_GAP_MM)."""
    return trace_w_mm + geometry.TRACK_GAP_MM


def min_edge_gap_mm(trace_w_mm):
    """The closest a run travelling *parallel to the feed edge* may put its
    centerline to it: half the track, plus the same clearance two of the
    antenna's own runs keep (see geometry.TRACK_GAP_MM).

    The feed edge is the one border a candidate is allowed to cross -- the
    pins do, that is what makes them pins -- so it carries no keepout of its
    own (geometry.edge_frame). Copper that merely *runs along* it is a
    different matter: the board's ground pour is on the other side, and a run
    whose half-width reaches over the edge merges with it. That shorts out
    exactly the gap the knob setting it exists to open (an inverted-F's
    height, an L-monopole's stem), so it is refused rather than drawn."""
    return trace_w_mm / 2 + geometry.TRACK_GAP_MM


def positive(values, key, label):
    """Read ``values[key]`` as a positive mm number, or raise with its
    user-facing ``label`` -- the guard every design's ``solve`` opens with, so
    a blank or nonsensical knob fails the same way whatever the topology."""
    v = values.get(key)
    if v is None or v <= 0:
        raise ValueError(f"{label} must be positive")
    return float(v)
