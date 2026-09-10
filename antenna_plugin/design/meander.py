"""The meandered monopole: a wire with turns, and nothing else.

A quarter-wave monopole fed from the edge of the marked area, whose wire is
folded into a serpentine so a quarter wave fits a board with nowhere near a
quarter wave of straight room. **One pin**, against the ground pour: no short
stub, no tap, no second connection. That is what makes it a monopole rather
than an inverted-F, and it is why it has no matching knob -- the port sees the
antenna's own radiation resistance, and the only thing that tunes it is the
length.

From the feed the trace runs straight **in** to the first turn, and from there
it zigzags: a leg **parallel to the feed edge**, a short jog further in, a leg
back the other way, another jog, and on until the length runs out. So
**total = the run in + the arm**, and every pair of legs carries the antenna one
jog further from the pour.

One wire, feed to open tip -- the drawing is its centerline, and the copper is
``width`` wide around it. There is one connection to the pour, at the triangle:

```
    ┌──────────          ← the last leg; the open tip ends wherever
    │                      the length runs out
    └───────────────┐
                    │
    ┌───────────────┘   ← full legs, spanning the area
    │
    └────┐              ← the first leg, short: the feed is not at a
         ▲                corner, so it reaches the near border only
  ───────┴────────────  the feed edge; the port is at the triangle,
                        against the ground pour. From there to the
                        corner above it is the run in, as long as
                        the "first turn" knob says
```

The first leg is the short one. The feed sits wherever the user put the
marker's triangle, which is not at a corner, so the leg that leaves the first
turn only reaches the **near** border; every leg after it spans the area. That
is ``geometry.meander_run``'s ``lead_mm``, and it is the one structural thing
this topology needed from the shared engine.

The three knobs -- ``length``, ``width`` and ``turn`` -- each carry their own
reading (``Param.reading``, printed by ``AntennaDesign.guide``), so what one
does is written once, beside its seed, rather than here as well. The one thing
``turn`` has that the reading leaves out is its floor: the legs run *parallel*
to the feed edge, so copper whose half-width reached over it would merge with
the pour and short the antenna out, and the pour clearance is refused rather
than drawn through.

**What is held while the length sweeps.** A scan reads a shape change as a
frequency change, so everything but the length has to stay put: every full leg
spans the area's width, the jogs spread over the whole depth behind the first
turn, and what absorbs a length those two do not divide is the **leg count**
and the **last leg** alone, which stops wherever the length runs out. A step
along a sweep therefore redraws the antenna a little rather than rebuilding it.

Only the layout is here; copper, the gerber splice, the port and the footprint
come from the shared engine through the :class:`~.base.AntennaDesign` contract.
Pure -- no wx, no pcbnew.
"""

from typing import NamedTuple

from . import base, geometry, sizing
from .base import AntennaDesign, Column, Param, Seed


class _Frame(NamedTuple):
    """The validated common ground of ``solve`` and ``capacity_mm``: the area's
    edge frame plus everything both need about the stack, already checked."""

    edge: geometry.EdgeFrame
    trace_w: float
    turn: float  # feed edge -> the first turn: the closest approach
    pitch: float  # smallest centerline spacing between two legs
    depth_left: float  # the room the stack spreads over, behind the turn
    span: float  # a full leg, across the area
    lead: float  # the short first leg, feed to the near border (0 = none)
    first: tuple  # the unit vector that first leg runs along


class MeanderedMonopoleDesign(AntennaDesign):
    key = "meander"
    name = "Meandered monopole"
    short_name = "Meander"
    title = "Design a Meandered Monopole Antenna"
    icon = "meander_icon.png"
    summary = (
        "A quarter-wave monopole folded into a serpentine: one pin, and "
        "a wire that turns back and forth to fit the area."
    )
    wiring = "Route your feed line to pad 1."
    footprint_prefix = "Meandered_Monopole"

    LENGTH_KEY = "length"
    WIDTH_KEY = "width"

    params = (
        Param(
            "length",
            "Antenna length",
            Seed(0.72, 1.28, 1.0),
            "scan_meander_length.png",
            reading=(
                "The whole centerline, feed to open tip: the run in, every "
                "leg and every jog. The quarter wave itself, seeded over the "
                "band the automatic ladder covers."
            ),
        ),
        Param(
            "width",
            "Arm thickness",
            Seed(0.2, 2.0, 1.0, relative=False),
            "scan_meander_width.png",
            reading=(
                "How wide the copper is drawn, in plain mm rather than "
                "wavelengths. It sizes the footprint's pads with it."
            ),
        ),
        Param(
            "turn",
            "Feed edge to first turn",
            Seed(0.05, 0.3, 0.12),
            "scan_meander_turn.png",
            reading=(
                "How far the wire runs in before it turns, which is where the "
                "stack starts and so the antenna's closest approach to the "
                "feed edge: every full leg comes back to exactly this level. "
                "A position, not a floor — the stack already spreads over the "
                "whole depth behind it, so there is no lift to be had."
            ),
        ),
    )

    columns = (
        Column("arm_mm", "Arm"),
        Column("crossings", "Legs", suffix=""),
        Column("leg_mm", "Leg length"),
    )

    # --- geometry -------------------------------------------------------------
    def solve(self, area, edge, frac, values):
        total_mm = base.positive(values, self.LENGTH_KEY, "antenna length")
        fr = self._frame(area, edge, frac, values)
        e = fr.edge
        arm = total_mm - fr.turn
        if arm <= 0:
            raise ValueError(
                f"a {total_mm:.1f} mm antenna has nothing left to fold: the "
                f"{fr.turn:.1f} mm run in to the first turn already uses its "
                "whole length (lengthen the antenna, or turn sooner)"
            )
        turn_pt = geometry.step(e.feed, e.inward, fr.turn)
        # The stack advances *into* the area and its legs alternate *along* the
        # feed edge, which is the opposite way round from the inverted-F's arm
        # -- the engine takes either (geometry.meander_run), the caller says
        # which vector does what. It spreads over the whole depth behind the
        # turn whatever the length, so the run reaches as far from the pour as
        # the area allows and a length sweep moves the leg count, not the shape.
        run = geometry.meander_run(
            turn_pt,
            e.inward,
            fr.first,
            arm,
            fr.depth_left,
            fr.span,
            fr.pitch,
            lead_mm=fr.lead or None,
        )
        # One path, one pad, no ground stub anywhere: a monopole that touched
        # the pour twice would not be a monopole. An antenna short enough to
        # run straight in never reaches its turn, and simply passes through it.
        return geometry.Geometry(
            paths=(
                geometry.Path(
                    (e.feed, turn_pt) + tuple(run.points), geometry.FEED_STUB
                ),
            ),
            feed=e.feed,
            inward=e.inward,
            total_mm=round(total_mm, 4),
            metrics={
                "turn_mm": round(fr.turn, 4),
                "arm_mm": round(arm, 4),
                # This design's own words for the run's two axes: its crossings
                # are the legs across the area and its advance is the depth the
                # stack spreads over (geometry.Meander.metrics). `lead_mm` comes
                # with them -- the short first leg, back to the near border.
                **run.metrics("leg_mm", "stack_mm"),
                "edge": edge,
            },
        )

    def capacity_mm(self, area, edge, frac, values):
        """The longest wire this area holds for this first turn: the run in,
        the whole depth behind it, and as many legs as the track pitch leaves
        room for -- every one of them spanning the area.

        The count is what the pitch bounds. ``n`` legs are joined by ``n - 1``
        jogs, each needing a pitch of the depth they share, so the depth buys
        one more leg than it has jogs; the first of them is the short lead-in
        where there is one."""
        fr = self._frame(area, edge, frac, values)
        jogs = int(fr.depth_left // fr.pitch)
        return fr.turn + fr.depth_left + (fr.lead or fr.span) + jogs * fr.span

    def _frame(self, area, edge, frac, values):
        """Everything ``solve`` and ``capacity_mm`` must agree on, validated
        once: the edge frame, the run in to the first turn, the depth the stack
        has behind it, and how wide a leg is -- including whether there is a
        short first one at all."""
        trace_w = base.positive(values, self.WIDTH_KEY, "arm thickness")
        turn_mm = base.positive(values, "turn", "distance to the first turn")
        e = geometry.edge_frame(area, edge, frac, trace_w / 2 + geometry.BORDER_MM)
        pitch = base.min_pitch_mm(trace_w)
        # The legs run parallel to the feed edge, and the first of them is the
        # closest the antenna ever comes back to it, so this is where the pour
        # clearance is spent (base.min_edge_gap_mm).
        gap = base.min_edge_gap_mm(trace_w)
        if turn_mm < gap - 1e-9:
            raise ValueError(
                f"a first turn {turn_mm:.2f} mm from the feed edge is closer "
                f"than a {trace_w:g} mm track can clear the ground pour -- the "
                "leg turning off it would merge with the pour and short the "
                f"antenna out; it must be at least {gap:.2f} mm (turn later or "
                "narrow the arm)"
            )
        depth_left = e.depth_mm - turn_mm
        if depth_left <= 0:
            raise ValueError(
                f"a first turn {turn_mm:.1f} mm in leaves nothing to fold "
                f"into: the area is only {e.depth_mm:.1f} mm deep from its "
                f"{edge} edge (grow the area, or turn sooner)"
            )
        if e.back_mm >= pitch - 1e-9:
            # The usual case: the feed is somewhere along its edge, so the leg
            # leaving the first turn reaches the near border only and every one
            # after it spans the area.
            lead, first, span = (
                e.back_mm,
                geometry.opposite(e.tangent),
                e.room_mm + e.back_mm,
            )
        else:
            # The feed is within a track pitch of the near border. There is no
            # first leg worth drawing behind it -- a stub that short is copper
            # inside the corner it grows out of -- so the stack simply starts at
            # the feed and every leg runs to the roomier side.
            lead, first, span = 0.0, e.tangent, e.room_mm
        if span < pitch - 1e-9:
            raise ValueError(
                f"the area is only {span:.1f} mm wide for a leg at a "
                f"{pitch:.2f} mm track pitch -- folding into it would lay the "
                "wire back inside its own width and buy no length (widen the "
                "area or narrow the arm)"
            )
        return _Frame(
            edge=e,
            trace_w=trace_w,
            turn=turn_mm,
            pitch=pitch,
            depth_left=depth_left,
            span=span,
            lead=lead,
            first=first,
        )

    def describe(self, geo):
        m = geo.metrics
        if not m["crossings"]:
            # Short enough to run straight in: it never reaches its turn.
            legs = " (straight)"
        else:
            legs = f", {m['crossings']} leg(s) {base.mm(m['leg_mm'])} mm long"
            if m["tail_mm"] < m["leg_mm"] - 1e-9:
                legs += f" + {base.mm(m['tail_mm'])} mm"
        return f"{base.mm(m['turn_mm'])} mm in + {base.mm(m['arm_mm'])} mm arm{legs}"

    def area_hint_mm(self, f0_ghz):
        """Small in both directions -- the point of the topology. Wide enough
        for a leg worth folding, deep enough for a few jogs behind the turn."""
        est = sizing.quarter_wave_mm(f0_ghz)
        return (est * 0.55, est * 0.5)
