"""The L-shaped monopole: a bent quarter-wave monopole in the marked area.

One candidate is one centerline: from the feed point on the area's feed edge
the trace runs straight into the area (the *stem*) and, when the target length
is longer than the stem, bends 90 degrees toward whichever side has more room
(the *arm*), so **total = stem + arm**. A total no longer than the stem is a
plain straight monopole with no arm.

Neither part is trimmed to the rectangle: a stem deeper than the area, like an
arm longer than the room along the edge, is a candidate that does **not fit**
and says so. The wizard then draws it on the area marker's own layer instead of
on copper, spilling out of the rectangle by exactly what is missing, and the
scan skips it (design/fit.py). Quietly shortening the stem to the depth would
be worse than either: a stem sweep would stop moving partway up its range and
preview an antenna nobody asked for, as copper, as though it fitted.

```
        │←──────── arm ────────→│
        ┌────────────────────────   ↑
        │                           stem
        ▲                           ↓
   ─────┴─────  feed edge (the port, against the ground pour)
```

Only the layout is here: the copper, the gerber splice, the port dict, the
candidate ladder and the footprint are the shared engine's (geometry.py,
sizing.py, footprints.py), reached through the :class:`~.base.AntennaDesign`
contract. Pure -- no wx, no pcbnew.
"""

from . import base, geometry, sizing
from .base import AntennaDesign, Column, Param, Seed


class LMonopoleDesign(AntennaDesign):
    key = "lmonopole"
    name = "L-shaped monopole"
    short_name = "L-monopole"
    title = "Design an L-Shaped Monopole Antenna"
    icon = "lmonopole_icon.png"
    summary = (
        "A bent quarter-wave monopole: a stem straight in from the "
        "feed, then an arm along the roomier side."
    )
    wiring = "Route your feed line to pad 1."
    footprint_prefix = "L_Monopole"

    params = (
        Param(
            "length",
            "Total track length",
            Seed(0.72, 1.28, 1.0),
            "scan_lmonopole_length.png",
            reading=(
                "The whole centerline, feed to open tip: stem + arm. The "
                "quarter wave itself, seeded over the band the automatic "
                "ladder covers, and the parameter that sets the frequency."
            ),
        ),
        Param(
            "width",
            "Track width",
            Seed(0.2, 2.0, 1.0, relative=False),
            "scan_lmonopole_width.png",
            reading=(
                "How wide the copper is drawn, in plain mm rather than "
                "wavelengths. It sizes the footprint's pads with it."
            ),
        ),
        Param(
            "stem",
            "Stem length",
            Seed(0.15, 0.5, 0.4),
            "scan_lmonopole_stem.png",
            reading=(
                "How far the trace runs straight in from the feed before it "
                "bends; whatever the length has left becomes the arm along "
                "the edge. It is also the antenna's clearance from the ground "
                "pour, so too short a stem is refused rather than shorted."
            ),
        ),
    )

    columns = (Column("stem_mm", "Stem"), Column("arm_mm", "Arm"))

    # --- geometry -------------------------------------------------------------
    def solve(self, area, edge, frac, values):
        total_mm = base.positive(values, self.LENGTH_KEY, "antenna length")
        fr, stem_mm, trace_w = self._frame(area, edge, frac, values)

        a = min(total_mm, stem_mm)  # the stem, feed to bend
        b = total_mm - a  # the arm, along the edge
        # Against the stem actually drawn, not the row's value: an antenna
        # shorter than its stem never reaches the bend, so it cannot run out of
        # the far border however deep that row is set.
        if a > fr.depth_mm + 1e-9:
            raise ValueError(
                f"a {a:.1f} mm stem does not fit: the area is only "
                f"{fr.depth_mm:.1f} mm deep from its {edge} edge (grow the "
                "area, or shorten the stem)"
            )
        if b > fr.room_mm + 1e-9:
            raise ValueError(
                f"a {total_mm:.1f} mm antenna with a {a:.1f} mm stem does "
                f"not fit: its {b:.1f} mm arm exceeds the {fr.room_mm:.1f} mm "
                "of room (grow the area, shorten the antenna, or lengthen "
                "the stem)"
            )
        # Only once there is an arm: it is the arm that runs *along* the feed
        # edge, and a stem too shallow to hold its copper clear of the pour
        # would bend the antenna straight into it. A stem with no arm to bend
        # into (a plain straight monopole) crosses nothing and is left alone.
        gap = base.min_edge_gap_mm(trace_w)
        if b > 1e-9 and a < gap - 1e-9:
            raise ValueError(
                f"a {a:.2f} mm stem is less than a {trace_w:g} mm track needs "
                "to clear the ground pour -- the arm it bends into would "
                f"merge with the pour and short the antenna out; it must be "
                f"at least {gap:.2f} mm (lengthen the stem or narrow the "
                "track)"
            )

        corner = geometry.step(fr.feed, fr.inward, a)
        points = [fr.feed, corner]
        if b > 1e-9:
            points.append(geometry.step(corner, fr.tangent, b))
        return geometry.Geometry(
            paths=(geometry.Path(tuple(points), geometry.FEED_STUB),),
            feed=fr.feed,
            inward=fr.inward,
            total_mm=round(total_mm, 4),
            metrics={"stem_mm": round(a, 4), "arm_mm": round(b, 4), "edge": edge},
        )

    def capacity_mm(self, area, edge, frac, values):
        """The longest centerline that fits for this stem: the stem runs in as
        far as it is asked to, and the arm takes the horizontal room.

        A stem deeper than the area is the exception -- then the ceiling is the
        depth itself. Nothing longer reaches the bend before the far border, so
        there is no arm to add the room to, and the fix is a shorter stem
        rather than a shorter antenna (which is what ``solve`` says)."""
        fr, stem_mm, _trace_w = self._frame(area, edge, frac, values)
        if stem_mm > fr.depth_mm:
            return fr.depth_mm
        return stem_mm + fr.room_mm

    def _frame(self, area, edge, frac, values):
        """The edge frame, the stem and the track width, read once for
        ``solve`` and ``capacity_mm`` so the two can never disagree about
        where the antenna starts or how far in it may run:
        ``(EdgeFrame, stem length mm, track width mm)``."""
        trace_w = base.positive(values, self.WIDTH_KEY, "track width")
        stem_mm = base.positive(values, "stem", "stem length")
        return (
            geometry.edge_frame(area, edge, frac, trace_w / 2 + geometry.BORDER_MM),
            stem_mm,
            trace_w,
        )

    def describe(self, geo):
        return (
            f"stem {base.mm(geo.metrics['stem_mm'])} + arm "
            f"{base.mm(geo.metrics['arm_mm'])} mm"
        )

    def area_hint_mm(self, f0_ghz):
        """A quarter wave with bend room: wide enough for the longest ladder
        candidate to lie down, deep enough for a stem."""
        est = sizing.quarter_wave_mm(f0_ghz)
        return (est * 1.1, est * 0.45)
