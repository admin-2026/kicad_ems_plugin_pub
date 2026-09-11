"""The inset-fed microstrip patch: a rectangle of copper over a ground plane.

A patch is the odd one out of this set, and in two ways. It is not a wire: the
radiator is a **rectangle** roughly half a wavelength long (in the substrate,
so shorter than in air) and about as wide, and the current flows across a sheet
of copper rather than along a track. And it does not radiate against a coplanar
pour reached through the feed edge -- it radiates against a **ground plane on
the other side of the board**, which is what turns the two open ends of the
rectangle into the slots that do the work. So a patch wizard is only half done
when the copper is drawn: the layer carrying that plane is picked in the Area
box (``needs_ground_plane``), and the plane travels with every candidate --
spliced onto that layer for the scan (wizard_scan.ground_polys) and sketched
there by the preview, so a patch is simulated as the two conductors it is.

The feed is a microstrip line running in from the area's feed edge, and it is
**inset**: it does not stop at the patch's edge but runs into a notch cut into
it, clear of the copper either side. That is the whole matching network. The
edge of a patch is a high resistance (a couple of hundred ohms, far off 50) and
its centre is a short, so the resistance the line sees falls the deeper it is
let in -- and the inset depth is the knob that sets it, without touching the
resonance, exactly as an inverted-F's tap does.

```
        │←────────── patch width (W) ─────────→│
        ┌──────────────────────────────────────┐   ↑
        │                                      │   │
        │                                      │  patch
        │                                      │  length
        │                                      │  (L)
        │           ┌─────┐                    │   │
        │           │     │                    │   ↓
        └───────────┘     └────────────────────┘   ← inset depth (y0): the
                    │ │ │       ↑                     notch cut into the patch
                    │ │▲│   feed line length
        ────────────┴─┴─┴───────↓──  feed edge (the port at the triangle)
                    →│ │←  feed line width (wf)
                  →│   │← inset gap: the clearance either side of it
```

**What each knob does, and what it leaves alone.** The six are ``length``
(the resonant one: L sets the frequency), ``patch_w`` (W, which sets the
bandwidth and the edge resistance and barely moves the frequency), ``width``
(wf, the microstrip's own width -- a 50 ohm line, which this plugin does not
compute for you), ``inset_gap`` (the clearance either side of that line inside
the notch, which is the second half of the match and the coupling into the
patch), ``feed_len`` (how far the line runs before the patch begins, which
walks the whole patch away from the feed edge without changing its length) and
``inset`` (y0, the match). Each carries its own reading (``Param.reading``,
printed by ``AntennaDesign.guide``), so what one does is written once, beside
its seed.

The gap and the line width are two knobs rather than one because they do two
different things: the line width is set by the impedance your stackup asks for
(and is usually not free), while the gap tunes the coupling into the patch and
is. The classic drawing makes them equal, which is where they both start.

**Where it sits in the area.** The patch is centred on the feed: an inset feed
belongs on the patch's centre line, or the notch drives modes the design is not
for. So the area needs half the patch width either side of the marker's feed
arrow, and an arrow dragged into a corner is refused rather than drawn
off-centre -- move it toward the middle of the edge, or widen the area. Away
from that edge it sits wherever ``feed_len`` puts it: the drawn microstrip is
that run plus the inset, the user's own line meets it at the marker, and the
depth it spends is depth the patch does not get (so it is in the capacity a
scan clips its ladder to).

**The seeds are free-space quarter waves**, like every other design here, and
for a patch that is a coincidence worth naming rather than a physical claim: a
half wave in the substrate is a quarter wave in air when the effective
permittivity is about 4, which is where an FR-4 board with a patch this wide
lands. On a thin low-loss laminate the true length is longer and on a thick one
shorter; the ladder covers +-28% of the seed and the scan's own 1/L refinement
walks the rest of the way, which is what a scan is for.

Only the layout is here; copper, the gerber splice, the port and the footprint
come from the shared engine through the :class:`~.base.AntennaDesign` contract
-- the patch body and its shoulders are ordinary paths that state their own
width (``geometry.Path.width``), since a rectangle 30 mm across and a 1.5 mm
microstrip cannot be one number. Pure -- no wx, no pcbnew.
"""

from typing import NamedTuple

from . import base, geometry, sizing
from .base import AntennaDesign, Column, Param, Seed


class _Frame(NamedTuple):
    """The validated common ground of ``solve`` and ``capacity_mm``: the area's
    edge frame plus the values both need, already checked."""

    edge: geometry.EdgeFrame
    feed_w: float
    patch_w: float
    inset: float
    feed_len: float  # feed edge to the patch's near edge
    gap: float  # the clearance either side of the inset feed line
    shoulder: float  # the patch either side of the notch
    depth_mm: float  # the longest patch this area holds from its near edge


class PatchDesign(AntennaDesign):
    key = "patch"
    name = "Inset-fed microstrip patch"
    short_name = "Patch"
    title = "Design an Inset-Fed Patch Antenna"
    icon = "patch_icon.png"
    needs_ground_plane = True  # it radiates against the plane, not a pour
    feed_frac = 0.5  # centred on its feed, so a fresh marker's arrow is too
    summary = (
        "A half-wave patch over the board's ground plane, fed by a "
        "microstrip line let into it for the match."
    )
    wiring = (
        "Route your 50 ohm microstrip to pad 1 and keep an unbroken ground "
        "pour on the layer picked in the Area box — the patch radiates "
        "against that plane."
    )
    footprint_prefix = "Patch"

    params = (
        Param(
            "length",
            "Patch length",
            Seed(0.72, 1.28, 1.0),
            "scan_patch_length.png",
            reading=(
                "The patch from its feed edge to its far edge — the resonant "
                "dimension, and the only one that really moves the frequency. "
                "It is a half wave in the substrate, which is why the seed "
                "reads as a quarter wave in air."
            ),
        ),
        Param(
            "width",
            "Feed line width",
            Seed(0.2, 4.0, 1.5, relative=False),
            "scan_patch_width.png",
            reading=(
                "How wide the microstrip feeding the patch is drawn, in plain "
                "mm rather than wavelengths — make it the 50 ohm width for "
                "your stackup (about 3 mm on 1.6 mm FR-4, about half that on "
                "0.8 mm); nothing here computes it for you. It sizes the "
                "footprint's pad, and the notch opens with it — the gap either "
                "side is its own knob."
            ),
        ),
        Param(
            "inset_gap",
            "Inset gap",
            Seed(geometry.TRACK_GAP_MM, 4.0, 1.5, relative=False),
            "scan_patch_inset_gap.png",
            reading=(
                "The clearance between the inset feed line and the patch "
                "either side of it, in plain mm. It is how tightly the line "
                "couples into the patch — narrower is tighter — and it is the "
                "half of the notch you are free to tune, since the line's own "
                "width is set by the impedance your stackup asks for. The "
                "classic drawing makes it the line width, which is where it "
                "starts; it cannot go below the clearance the rest of this "
                "antenna keeps."
            ),
        ),
        Param(
            "patch_w",
            "Patch width",
            Seed(0.8, 1.6, 1.2),
            "scan_patch_patch_w.png",
            reading=(
                "The patch across the feed, at right angles to the resonant "
                "length. It sets the bandwidth and the edge resistance — wider "
                "is broader and lower — and moves the frequency only a little, "
                "so sweep it once the length has the resonance."
            ),
        ),
        Param(
            "feed_len",
            "Feed line length",
            Seed(0.02, 0.3, 0.08),
            "scan_patch_feed_len.png",
            reading=(
                "How far the patch stands off the area's feed edge — the run "
                "of microstrip the wizard draws before the patch begins, where "
                "your own feed line takes over. It moves the whole patch "
                "further in (the resonant length does not change with it), so "
                "it is how the antenna is walked away from a pour or a board "
                "edge crowding it, and how much line the scan simulates for "
                "you rather than leaving to your routing."
            ),
        ),
        Param(
            "inset",
            "Inset depth",
            Seed(0.05, 0.5, 0.3),
            "scan_patch_inset.png",
            reading=(
                "How far the feed line is let into the patch: the match, and "
                "nothing else. The patch edge is a couple of hundred ohms and "
                "its centre is a short, so deeper is lower — sweep this when "
                "the resonance is right and the match is not, since the "
                "resonant length does not move with it."
            ),
        ),
    )

    columns = (
        Column("patch_w_mm", "Patch width"),
        Column("inset_mm", "Inset"),
        # Derived, unlike the two above: what is left of the patch either side
        # of the notch. It is the number that goes to nothing as the feed line
        # or its gaps widen, so it is worth a column of its own -- a shoulder
        # narrower than the fab's minimum is a patch that comes back in two
        # pieces.
        Column("shoulder_mm", "Shoulder"),
    )

    # --- geometry -------------------------------------------------------------
    def solve(self, area, edge, frac, values):
        total_mm = base.positive(values, self.LENGTH_KEY, "patch length")
        fr = self._frame(area, edge, frac, values)
        e = fr.edge
        if total_mm > fr.depth_mm + 1e-9:
            raise ValueError(
                f"a {total_mm:.1f} mm patch does not fit: the area is only "
                f"{fr.depth_mm:.1f} mm deep from its {edge} edge (grow the "
                "area or shorten the patch)"
            )
        if total_mm - fr.inset < fr.feed_w - 1e-9:
            raise ValueError(
                f"a {fr.inset:.1f} mm inset into a {total_mm:.1f} mm patch "
                "leaves next to no copper beyond the notch — the feed line "
                "would run out of the far edge; shorten the inset or lengthen "
                "the patch"
            )

        # The patch's near edge, on the feed's own centre line: the feed line's
        # own length inside the feed edge, so the microstrip the wizard draws
        # is that plus the inset, and the user's own line meets it at the
        # marker.
        near = geometry.step(e.feed, e.inward, fr.feed_len)
        junction = geometry.step(near, e.inward, fr.inset)
        far = geometry.step(near, e.inward, total_mm)
        # The two shoulders: the patch either side of the notch, each one
        # centred so its outer edge is the patch's own and its inner edge
        # stands one gap off the feed line.
        offset = (fr.patch_w - fr.shoulder) / 2
        shoulders = tuple(
            geometry.Path(
                (
                    geometry.step(near, direction, offset),
                    geometry.step(junction, direction, offset),
                ),
                geometry.NO_STUB,
                fr.shoulder,
            )
            for direction in (e.tangent, geometry.opposite(e.tangent))
        )

        return geometry.Geometry(
            # The feed line first: its stub is the port, and the pad the
            # footprint hangs the whole radiator off sits on its first point.
            paths=(
                geometry.Path((e.feed, junction), geometry.FEED_STUB, fr.feed_w),
                # The patch beyond the notch: one rectangle the full width.
                geometry.Path((junction, far), geometry.NO_STUB, fr.patch_w),
            )
            + shoulders,
            feed=e.feed,
            inward=e.inward,
            total_mm=round(total_mm, 4),
            metrics={
                "patch_w_mm": round(fr.patch_w, 4),
                "inset_mm": round(fr.inset, 4),
                "feed_len_mm": round(fr.feed_len, 4),
                "shoulder_mm": round(fr.shoulder, 4),
                "inset_gap_mm": round(fr.gap, 4),
                "edge": edge,
            },
        )

    def capacity_mm(self, area, edge, frac, values):
        """The longest patch this area holds: the depth from the feed edge,
        less the feed line standing the patch off that edge and the keep-off at
        the far border. The feed line is in it because it is depth the patch
        does not get (an L-monopole's stem is in its capacity the same way);
        the patch *width* is not -- a patch too wide for the area is not a
        patch that can be shortened into fitting, so ``_frame`` refuses it
        outright rather than quoting a length."""
        return self._frame(area, edge, frac, values).depth_mm

    def _frame(self, area, edge, frac, values):
        """Everything ``solve`` and ``capacity_mm`` must agree on, validated
        once: the edge frame, the notch's own arithmetic, and the two ways an
        area can be wrong for a patch whatever its length -- too narrow across
        the feed edge, or too shallow to hold any patch at all."""
        feed_w = base.positive(values, self.WIDTH_KEY, "feed line width")
        patch_w = base.positive(values, "patch_w", "patch width")
        inset = base.positive(values, "inset", "inset depth")
        feed_len = base.positive(values, "feed_len", "feed line length")
        gap = base.positive(values, "inset_gap", "inset gap")
        e = geometry.edge_frame(area, edge, frac, feed_w / 2 + geometry.BORDER_MM)
        if feed_len < geometry.BORDER_MM - 1e-9:
            raise ValueError(
                f"a {feed_len:.2f} mm feed line puts the patch on the area's "
                f"own border -- it must stand at least {geometry.BORDER_MM:g} "
                "mm off the feed edge, as every design's copper does (lengthen "
                "the feed line)"
            )
        # The gap either side of the inset feed line is the user's own knob
        # (it starts at the line width, which is the classic drawing of this
        # antenna), floored at the clearance two runs of the same antenna keep
        # anywhere else here -- below that the notch closes up on the fab, and
        # a value that cannot be made is refused rather than quietly widened.
        if gap < geometry.TRACK_GAP_MM - 1e-9:
            raise ValueError(
                f"a {gap:g} mm gap between the feed line and the patch is "
                f"below the {geometry.TRACK_GAP_MM:g} mm clearance the rest of "
                "this antenna keeps — widen the inset gap"
            )
        shoulder = (patch_w - feed_w - 2 * gap) / 2
        if shoulder <= 0:
            raise ValueError(
                f"a {patch_w:.1f} mm patch is too narrow for the notch a "
                f"{feed_w:g} mm feed line and its {gap:g} mm gaps cut into it "
                f"({feed_w + 2 * gap:.1f} mm across) -- widen the patch, "
                "narrow the feed line or close the gap"
            )
        # The patch is centred on the feed, so it needs half its width on the
        # *narrower* side of the marker's arrow.
        room = min(e.room_mm, e.back_mm)
        if patch_w / 2 > room + 1e-9:
            raise ValueError(
                f"a {patch_w:.1f} mm patch centred on the feed needs "
                f"{patch_w / 2:.1f} mm either side of it, and the area only "
                f"has {room:.1f} mm on one side -- drag the feed arrow toward "
                "the middle of its edge, widen the area, or narrow the patch"
            )
        depth_mm = e.depth_mm - feed_len
        if depth_mm <= 0:
            raise ValueError(
                f"the area is {e.depth_mm:.1f} mm deep from its {edge} edge "
                f"and the feed line spends {feed_len:.1f} mm of that -- there "
                "is nothing left for the patch (shorten the feed line or grow "
                "the area)"
            )
        return _Frame(
            edge=e,
            feed_w=feed_w,
            patch_w=patch_w,
            inset=inset,
            feed_len=feed_len,
            gap=gap,
            shoulder=shoulder,
            depth_mm=depth_mm,
        )

    def describe(self, geo):
        m = geo.metrics
        return (
            f"patch {base.mm(m['patch_w_mm'])} x {base.mm(geo.total_mm)} mm, "
            f"{base.mm(m['inset_mm'])} mm inset on "
            f"{base.mm(m['feed_len_mm'])} mm of line"
        )

    def area_hint_mm(self, f0_ghz):
        """Half as wide again as the patch, and deep enough for the longest
        ladder candidate *plus* the feed line standing it off the edge, with
        the keep-off at the far border on top. The width is what it is because
        the patch is centred on the feed and a fresh marker drops its arrow in
        the middle (``feed_frac``): the room either side of it is half the
        rectangle, so a rectangle much narrower than this would refuse the
        widest candidates of a patch-width sweep."""
        est = sizing.quarter_wave_mm(f0_ghz)
        return (est * 1.5, est * 1.45)
