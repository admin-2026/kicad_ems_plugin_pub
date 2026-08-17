"""The meandered inverted-F antenna (IFA).

An inverted-F is a quarter-wave monopole folded down over its own ground plane
and tapped for a match: a **short pin** ties the radiator to the ground pour, a
**feed pin** drives it a short distance along from there, and the radiating
**arm** runs on from the feed to an open tip. The resonant path is the run the
feed drives -- up from the feed pin to the arm, then along the arm to that tip
-- so it is a quarter wave, while the antenna occupies far less board than a
straight monopole. The tap is **not** part of it: the short pin and the spacing
to it are the match, not the resonator, so sliding that pin along the feed edge
leaves the resonant run exactly as it was. Where the arm is longer than the
area is wide, it **meanders**: square folds buy length without taking width
(geometry.meander_run). The arm keeps the area's **full width**, and its folds
the **full depth** behind it, however the antenna is dimensioned -- a narrower
or a shallower antenna is a different antenna, and a sweep that moved either
would read the difference as frequency. So what absorbs a length those two do
not divide evenly is one more half fold, and the *last* crossing alone: it
takes whatever is left over, anything from a whole fold down to a hair. That
half fold does not appear in the middle of the arm with every other fold
shoved sideways to make room for it -- it is peeled off the arm's far end and
turns out into place: it opens out of the tip as it deepens, reaching the
width the other folds have while it is still a whisker of one, and they close
up to pay for it as it does (geometry.meander_legs). So the arm is an even
comb in all but a couple of percent of a sweep's candidates, and a step along
one redraws the antenna a little rather than rebuilding it. Both pins rise the
whole way to the
arm, so the tap between them runs flush with the meander's first fold; every
full crossing reaches the area's far border on the way out and turns back
*toward* the feed edge, down to the height and no closer. That last crossing
is the exception, so the open tip stops wherever the length runs out, pointing
back at the edge or into the area.

So the arm itself rides the area's far border whatever the length, and the
height is only the level its folds turn back down to -- a minimum, not a level
(``_split``). An arm with nothing to fold gets to that border by being
**lifted** onto it rather than by crossing to it: it climbs the whole depth and
runs straight from there, paying for the climb out of its own length, because
drawn at the minimum instead it would hug the pour with the area empty above
it. The two ways of reaching the border meet on one drawing -- the longest
lifted arm just fills the room, which is what the shortest folded one does
before the first fold turns down off its tip -- so a length sweep crosses from
one to the other without a step. What a lifted arm cannot keep is the area's
full width: a length that cannot fill the room from the border cannot fill it
from anywhere, so that is the one place the width answers to the length, and it
does because the antenna is genuinely smaller.

```
    ┌────────┬────┐    ┌────┐    ┌────┐   ← the arm, resting on the area's
    │        │    │    │    │    │    │       far border: the height moves the
    │        │    └────┘    └────┘    ╵   ← folds' other end, not this one, and
    │        │                            ↑   the run spans the width either
    │ short  │ feed                    height  way. (Here the last crossing is
    ●        ▲                            ↓   a full one; a part one stops
   ─┴────────┴──────  feed edge               short of the height.)
    │← tap →│         (the port at the triangle, against the pour)
```

The four knobs, and what each does:

``length``  the resonant path (feed pin -> up to the arm -> open tip), the tap
            excluded. Sets the frequency; it is the parameter the automatic λ/4
            ladder and the 1/L refinement work on, exactly as for the monopole.
``width``   track width.
``height``  the *closest* the antenna may come back to the feed edge: the
            level a folded arm's folds turn down to, and the first leg of the
            resonant path. The loop the short pin, the tap and the ground plane
            form is what makes an IFA broadband: more height widens the match.
            It moves neither the antenna's width nor the far border its folds
            rest on: the folds keep spanning the area and reaching the back of
            it, so raising the height shortens them from the near end only, and
            the meander takes another half turn to make the length back. It is
            a floor, not a level -- an arm with no folds behind it is lifted off
            it, up to the far border (``_split``).
``tap``     the feed-to-short spacing. The impedance transformer: a tap close
            to the short presents a low resistance, further along a higher one,
            so this is the knob to sweep when the resonance is right but the
            match is not. It buys nothing else: the arm keeps its length, its
            folds and its height, and only the short pin moves.

Only the layout is here; copper, gerber splice, port and footprint come from
the shared engine through the :class:`~.base.AntennaDesign` contract. Pure --
no wx, no pcbnew.
"""

from typing import NamedTuple

from . import base, geometry, sizing
from .base import AntennaDesign, Column, Param, Seed


class _Frame(NamedTuple):
    """The validated common ground of ``solve`` and ``capacity_mm``: the area's
    edge frame plus the values both need, already capped and checked."""

    edge: geometry.EdgeFrame
    trace_w: float
    height: float  # the minimum, capped to the area depth (``_split`` lifts it)
    tap: float
    pitch: float  # smallest centerline spacing between two runs
    depth_left: float  # inward room between the arm and the far border


class MeanderedIFADesign(AntennaDesign):
    key = "ifa"
    name = "Meandered inverted-F antenna"
    short_name = "Inverted-F"
    title = "Design a Meandered Inverted-F Antenna"
    icon = "ifa_icon.png"
    summary = (
        "A quarter-wave inverted-F: a short pin to the pour, a tapped "
        "feed, and an arm that meanders to fit the area."
    )
    wiring = (
        "Route your feed line to pad 1 and tie pad 2 (the short pin) "
        "to the ground pour — without that it is not an inverted-F."
    )
    footprint_prefix = "Meandered_IFA"

    params = (
        Param(
            "length",
            "Resonant length",
            # The quarter wave itself, over the band the automatic ladder
            # covers -- feed pin to open tip, folds included, tap excluded.
            Seed(0.72, 1.28, 1.0),
            "scan_ifa_length.png",
        ),
        Param(
            "width",
            "Track width",
            Seed(0.2, 2.0, 1.0, relative=False),
            "scan_ifa_width.png",
        ),
        Param(
            "height",
            "Minimum height over the feed edge",
            Seed(0.05, 0.25, 0.12),
            "scan_ifa_height.png",
        ),
        Param(
            "tap",
            "Feed-to-short spacing",
            Seed(0.03, 0.2, 0.08),
            "scan_ifa_tap.png",
        ),
    )

    columns = (
        Column("arm_mm", "Arm"),
        Column("folds", "Folds", suffix=""),
        Column("fold_depth_mm", "Fold depth"),
    )

    # --- geometry -------------------------------------------------------------
    def solve(self, area, edge, frac, values):
        total_mm = base.positive(values, self.LENGTH_KEY, "resonant length")
        fr, arm = self._split(self._frame(area, edge, frac, values), total_mm)
        e = fr.edge
        short = geometry.step(e.feed, geometry.opposite(e.tangent), fr.tap)
        feed_top = geometry.step(e.feed, e.inward, fr.height)
        run = geometry.meander_run(
            feed_top, e.tangent, e.inward, arm, e.room_mm, fr.depth_left, fr.pitch
        )
        arm_pts = run.points
        # Both pins rise all the way to the arm, so the tap crossbar between
        # them runs flush with the meander's first fold instead of sitting a
        # fold-depth below it: the run's opening inward leg simply moves ahead
        # of the crossbar. Same segments, and the feed pin grows by exactly
        # what the arm loses, so the resonant path is still exactly
        # height + arm. (A straight arm crosses nothing, and the two pins stop
        # at its own level -- the height it was lifted to, if it was.)
        if run.crossings:
            feed_top, arm_pts = arm_pts[0], arm_pts[1:]
        # Off the arm's own point, not off `height + depth`: `depth` is
        # reported rounded, and re-deriving the level from it would tilt the
        # crossbar by a hair -- enough for the copper builder to reject it as
        # not axis-aligned.
        short_top = geometry.step(feed_top, geometry.opposite(e.tangent), fr.tap)

        return geometry.Geometry(
            # The radiator: ground contact -> short pin -> tap -> arm. Its
            # first point is the ground pad (see footprint_pads); the feed pin
            # branches off the spine at the port.
            paths=(
                geometry.Path(
                    (short, short_top, feed_top) + tuple(arm_pts), geometry.GROUND_STUB
                ),
                geometry.Path((e.feed, feed_top), geometry.FEED_STUB),
            ),
            feed=e.feed,
            inward=e.inward,
            total_mm=round(total_mm, 4),
            metrics={
                "height_mm": round(fr.height, 4),
                "tap_mm": round(fr.tap, 4),
                "arm_mm": round(arm, 4),
                "folds": run.folds,
                "crossings": run.crossings,
                "fold_depth_mm": run.depth,
                # The last crossing, short of a full fold where the length
                # asked for half a one (geometry.Meander).
                "tail_mm": run.tail,
                "span_mm": run.span,
                "edge": edge,
            },
        )

    def _split(self, fr, total_mm):
        """How a resonant length is spent, as ``(frame, arm)``: the frame with
        the height the arm is actually drawn at, and what is left of the length
        for the arm itself.

        The resonant path is the feed pin's own run -- height + arm. The tap is
        deliberately NOT taken out of it: it is the match, not the resonator,
        so widening it slides the short pin along the edge and leaves the arm
        (and the frequency) alone.

        The height knob is a **minimum**, not a level: it is how close the arm
        may come back to the feed edge, which is all a folded arm needs it to
        be. A folded arm already rides the area's far border -- its first
        crossing climbs to it and the pins rise with it -- so the height only
        sets how far its folds turn back down. The **arm itself is on the far
        border whatever the length**, and this is the branch that keeps it
        there when there is nothing to fold: an arm short enough to run without
        crossing the band at full depth would otherwise be drawn down at the
        minimum, hugging the pour with the area empty above it, and every
        millimetre taken off a length scan would push it further into the
        pour's near field instead of away from it. So it is lifted to the
        border and run straight from there. The length pays for the rise -- the
        arm gives back exactly what the climb takes -- so the resonance is
        still the length that was asked for.

        What the lift cannot buy is the area's **full width**: a length that
        cannot fill the room from the border cannot fill it from anywhere
        (running lower only buys arm at the cost of depth), so this is the one
        place the width moves with the length, and it moves because the antenna
        is genuinely smaller. Everywhere the width *can* be had it still is.

        The two branches meet without a step, which is the point of judging
        the fit **after** the lift rather than before: the longest lifted arm
        is one that just fills the room from the border, and the shortest
        folded one is a full-width arm on the border with a hair of a fold
        turning down off its tip. They are the same drawing, so a length sweep
        crosses the boundary the way it crosses a fold boundary -- the tip
        moves and nothing else does.
        """
        arm = total_mm - fr.height
        if arm <= 0:
            raise ValueError(
                f"a {total_mm:.1f} mm inverted-F has nothing left for its "
                f"arm: the {fr.height:.1f} mm height over the feed edge "
                "already uses the resonant length up (lengthen the antenna, "
                "or lower the height)"
            )
        # The whole climb the area has room for -- but never so much of it that
        # the arm ends up shorter than the track is wide: that is not an arm
        # any more but the corner the riser turns through (the copper builder
        # squares corners by a half width), and a bare vertical pin is not the
        # antenna the user asked to draw.
        lift = min(fr.depth_left, arm - fr.trace_w)
        if lift > 0 and arm - lift <= fr.edge.room_mm + 1e-9:
            fr = fr._replace(height=fr.height + lift, depth_left=fr.depth_left - lift)
            arm -= lift
        return fr, arm

    def capacity_mm(self, area, edge, frac, values):
        """The longest resonant path this area holds: the minimum height, plus
        an arm that runs the full width and crosses the band as often as the
        track pitch allows, every crossing as deep as the area is behind the
        arm. The tap is not in the resonant length, so it is not in the
        capacity either -- it only has to fit behind the feed, which ``_frame``
        checks. The lift (``_split``) does not enter it: the longest arm is a
        folded one, and only an arm that already fits is ever lifted."""
        fr = self._frame(area, edge, frac, values)
        # c crossings lay c - 1 forward legs, each of which has to clear the
        # track pitch across the room they share. Halves count: the run may
        # end on one (geometry.meander_plan), so this is not rounded to whole
        # folds.
        crossings = (
            0
            if fr.depth_left < fr.pitch
            else int(fr.edge.room_mm // fr.pitch) + 1
        )
        return fr.height + fr.edge.room_mm + crossings * fr.depth_left

    def _frame(self, area, edge, frac, values):
        """Everything ``solve`` and ``capacity_mm`` must agree on, validated
        once: the edge frame, the minimum height capped to the area depth, and
        the tap -- which has to clear the feed pin (a tap under one track pitch
        would merge the two pins) and stay inside the area behind the feed."""
        trace_w = base.positive(values, self.WIDTH_KEY, "track width")
        height_mm = base.positive(values, "height", "height over the feed edge")
        tap_mm = base.positive(values, "tap", "feed-to-short spacing")
        e = geometry.edge_frame(area, edge, frac, trace_w / 2 + geometry.BORDER_MM)
        pitch = base.min_pitch_mm(trace_w)
        if tap_mm < pitch - 1e-9:
            raise ValueError(
                f"a {tap_mm:.2f} mm feed-to-short spacing would merge the two "
                f"pins at a {trace_w:g} mm track width -- it must be at least "
                f"{pitch:.2f} mm (widen the spacing or narrow the track)"
            )
        if tap_mm > e.back_mm + 1e-9:
            raise ValueError(
                f"the short pin needs {tap_mm:.1f} mm behind the feed but the "
                f"area only has {e.back_mm:.1f} mm there -- slide the feed "
                "along its edge (or widen the area)"
            )
        height = min(height_mm, e.depth_mm)
        gap = base.min_edge_gap_mm(trace_w)
        if height < gap - 1e-9:
            raise ValueError(
                f"a {height:.2f} mm height over the feed edge is less than a "
                f"{trace_w:g} mm track needs to clear the ground pour -- the "
                "arm turning back down to it would merge with the pour and "
                f"short the antenna out; it must be at least {gap:.2f} mm "
                "(raise the height or narrow the track)"
            )
        return _Frame(
            edge=e,
            trace_w=trace_w,
            height=height,
            tap=tap_mm,
            pitch=pitch,
            depth_left=e.depth_mm - height,
        )

    def footprint_pads(self, geo):
        """Pad 1 is the feed (the footprint origin); pad 2 is the short pin,
        the first point of the radiator path -- route it to the ground pour,
        or the antenna is not an inverted-F."""
        return (("1", geo.feed), ("2", geo.paths[0].points[0]))

    def describe(self, geo):
        m = geo.metrics
        if not m["crossings"]:
            folds = " (straight)"
        elif m["crossings"] == 1:
            # One crossing is no fold at all: the arm steps up by the little it
            # has over the width and runs straight at that level. The lift
            # takes this layout wherever it can (``_split``), so what is left
            # for it is the arm too short to be lifted -- one shorter than the
            # track is wide, in an area narrower still.
            folds = f" (straight, {base.mm(m['tail_mm'])} mm above the height)"
        else:
            folds = f", {m['folds']} fold(s) {base.mm(m['fold_depth_mm'])} mm deep"
            if m["tail_mm"] < m["fold_depth_mm"] - 1e-9:
                folds += f" + {base.mm(m['tail_mm'])} mm"
        # height + arm is the resonant path; the tap is quoted after it,
        # outside the sum, because it is the match and not the resonance.
        return (
            f"height {base.mm(m['height_mm'])} + arm {base.mm(m['arm_mm'])} mm"
            f", {base.mm(m['tap_mm'])} mm tap{folds}"
        )

    def area_hint_mm(self, f0_ghz):
        """Wide enough for a couple of folds, deep enough for the height plus
        the folds behind it -- an inverted-F is a fraction of the quarter wave
        it resonates at."""
        est = sizing.quarter_wave_mm(f0_ghz)
        return (est * 0.6, est * 0.36)
