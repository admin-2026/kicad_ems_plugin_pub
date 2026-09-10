"""Pure planar geometry shared by every antenna design.

A design (design/base.py) is only asked to lay out **centerline paths** inside
the user's area marker; everything downstream of that -- turning the paths into
copper rectangles, rotating them back onto a board whose marker sits off-grid,
splicing them into a plotted gerber, describing the port to the runner -- is
the same work whatever the antenna looks like, and lives here.

The two shapes this module is built around:

``Path``      one centerline polyline of axis-aligned segments, plus the kind
              of copper *stub* that extends behind its first point. A stub is
              how a path ties into the board's ground pour: ``GROUND`` for a
              pin that simply merges with the pour (an inverted-F's short pin),
              ``FEED`` for the port pin, which is pushed out past the runner's
              one-cell feed gap as well, so the source side of the port still
              lands on the pour.
``Geometry``  every path of one candidate plus the port (feed point + inward
              direction) and the design's own derived numbers (``metrics``).

Frames: geometry is solved in KiCad mm (Y grows downward, so the "bottom" edge
of an area is the one at max Y) and in the area marker's *derotated* frame -- a
marker the user rotated off-grid solves on-grid, and ``rot_deg``/``pivot`` put
the result back on the board. Gerber output negates Y, matching how KiCad plots
the copper the candidates are spliced into.

Pure: no wx, no pcbnew (markergeom's own helpers here are pure too), so the
whole geometry stack stays unit-testable off KiCad (tests/test_geometry.py).
"""

import math
from typing import NamedTuple

from ..emkit.markers import markergeom

# Copper drawn past the feed gap on the ground side, so the port's source
# side lands on the board's ground pour even when the pour keeps a small
# clearance from the drawn area. The runner's ground check reports when this
# still doesn't reach ground (the area is too far from the pour).
GROUND_STUB_MM = 1.0

# Fixed keepout between a track centerline and the area border (added to the
# half-width). Small, just so the copper doesn't sit on the very edge of the
# drawn area.
BORDER_MM = 0.5

# Edge-relative clearance between two parallel runs of the same antenna (the
# gap a meander leaves between its folds, and the smallest feed-to-short
# spacing an inverted-F may use): added to the track width to get the minimum
# centerline-to-centerline pitch.
TRACK_GAP_MM = 0.25

# How far across the band a newborn crossing has to reach before the meander is
# drawn as an even comb again, as a fraction of the track pitch (see
# meander_legs). The room a new fold needs has to come off the folds already
# drawn, and that hand-over is packed into this first sliver of the new fold's
# reach -- 0.25 mm of it at a 1 mm track, a quarter of the track's own width,
# so the run is an even comb in ~98% of the candidates of a sweep and the
# hand-over happens while the new fold is nothing but a whisker in the corner.
#
# It is the one number trading the two things that cannot both be had (see
# meander_legs): 0 draws every candidate as a perfectly even comb, at the cost
# of handing the room over in one step -- which moves a full-length strand a
# whole leg width (14.5 mm at the first fold boundary of a 29 mm run) between
# two neighbouring candidates of a sweep. Larger spreads that hand-over over
# more of the sweep, at the cost of more candidates drawn with the newest fold
# narrower than the rest.
FOLD_TURNOUT_PITCHES = 0.2

EDGES = ("bottom", "top", "left", "right")

# Inward unit vector per edge, KiCad frame (Y down: bottom = max Y).
_INWARD = {"bottom": (0, -1), "top": (0, 1), "left": (1, 0), "right": (-1, 0)}

# The copper stub extending behind a path's first point (see the module
# docstring): none, a plain ground pin, or the port pin.
NO_STUB, GROUND_STUB, FEED_STUB = "none", "ground", "feed"


class Path(NamedTuple):
    """One centerline polyline of a candidate: ``points`` (>= 2 KiCad-mm
    points, consecutive ones axis-aligned) and the ``stub`` kind extending
    behind ``points[0]``, opposite the first segment."""

    points: tuple
    stub: str = NO_STUB


class Geometry(NamedTuple):
    """One solved candidate: its centerline ``paths``, the port (``feed``
    point on the area edge and the ``inward`` unit vector pointing into the
    area), the resonant ``total_mm`` it was solved for, and ``metrics`` --
    the design's own derived numbers for the result table and the preview
    line (e.g. an L-monopole's stem/arm split, an inverted-F's fold count)."""

    paths: tuple
    feed: tuple
    inward: tuple
    total_mm: float
    metrics: dict

    # --- copper -------------------------------------------------------------
    def copper_rects(self, trace_w_mm, gap_mm, include_stub=True):
        """The candidate's copper as axis-aligned rectangles (KiCad mm,
        normalized (x0, y0, x1, y1)): one per centerline segment, buffered to
        the trace width. Each segment overshoots its far end by a half-width
        where another segment continues from it, so every corner is square;
        the first segment of a path is extended backwards by its stub
        (``include_stub=False`` drops that -- the footprint starts at the pins,
        where the user's own copper connects)."""
        h = trace_w_mm / 2
        stubs = {
            NO_STUB: 0.0,
            GROUND_STUB: GROUND_STUB_MM,
            FEED_STUB: gap_mm / 2 + GROUND_STUB_MM,
        }
        rects = []
        for path in self.paths:
            back = stubs[path.stub] if include_stub else 0.0
            rects.extend(path_rects(path.points, h, back))
        return rects

    def centerline_segments(self, rot_deg=0.0, pivot=(0.0, 0.0)):
        """Every path's centerline as board-frame segment pairs (KiCad mm):
        consecutive points rotated by ``rot_deg`` about ``pivot`` -- the step
        that puts a geometry solved in a rotated area marker's derotated frame
        back onto the board (identity at 0). The wizard draws these onto a
        copper layer as its live antenna preview (markers.preview), stroked at
        the trace width so they read as the copper the footprint would
        place."""
        segments = []
        for path in self.paths:
            pts = [markergeom.rotate_pt(p, rot_deg, pivot) for p in path.points]
            segments.extend(zip(pts, pts[1:]))
        return segments

    def feed_dict(self, rot_deg=0.0, pivot=(0.0, 0.0)):
        """The feed for ``config.write_yaml`` (``params['feed']``): the port
        point on the area edge and the direction vector toward the antenna,
        handed to the shared markergeom.explicit_feed builder.
        ``rot_deg``/``pivot`` place a candidate solved in a rotated area
        marker's derotated frame back onto the board (identity when the marker
        sits on-grid). KiCad -> gerber: negate Y on the point and the
        direction."""
        (fx, fy) = markergeom.rotate_pt(self.feed, rot_deg, pivot)
        (ix, iy) = markergeom.rotate_pt(self.inward, rot_deg)
        return markergeom.explicit_feed(fx, -fy, ix, -iy)


# --------------------------------------------------------------------------- #
# The area marker's feed edge
# --------------------------------------------------------------------------- #
class EdgeFrame(NamedTuple):
    """Where a candidate starts and how much room it has: the feed point on
    the area's feed edge, the unit vector pointing into the area, the unit
    edge tangent toward the *roomier* side, how deep the centerline may run in
    (``depth_mm``) and how far it may run along the edge toward the roomier
    side (``room_mm``) and back the other way (``back_mm``). All distances
    already subtract the centerline's keepout from the border."""

    feed: tuple
    inward: tuple
    tangent: tuple
    depth_mm: float
    room_mm: float
    back_mm: float


def edge_frame(area, edge, frac, half):
    """The feed frame on one edge of ``area`` (x0, y0, x1, y1, normalized).
    ``frac`` in [0, 1] places the feed along the edge (from the smaller
    coordinate); ``half`` is the centerline's required distance from the area
    border (trace half-width + BORDER_MM). Raises ValueError when the area is
    too small to hold a centerline at all."""
    x0, y0, x1, y1 = area
    if edge not in EDGES:
        raise ValueError(f"unknown edge '{edge}'")
    u = _INWARD[edge]
    if edge in ("bottom", "top"):
        lo, hi, depth = x0, x1, y1 - y0
        base = y1 if edge == "bottom" else y0
    else:
        lo, hi, depth = y0, y1, x1 - x0
        base = x0 if edge == "left" else x1
    if hi - lo <= 2 * half:
        raise ValueError(
            f"the area is only {hi - lo:.2f} mm wide along its {edge} edge "
            f"-- too narrow for the track width + border ({2 * half:.2f} "
            "mm)"
        )
    depth_mm = depth - half
    if depth_mm <= 0:
        raise ValueError(
            f"the area is only {depth:.2f} mm deep from its {edge} edge -- "
            f"too shallow for the track width + border ({half:.2f} mm)"
        )
    fpos = min(max(lo + frac * (hi - lo), lo + half), hi - half)
    feed = (fpos, base) if edge in ("bottom", "top") else (base, fpos)
    plus, minus = (hi - half) - fpos, fpos - (lo + half)
    d = 1 if plus >= minus else -1
    return EdgeFrame(
        feed=feed,
        inward=u,
        tangent=(d * abs(u[1]), d * abs(u[0])),
        depth_mm=depth_mm,
        room_mm=max(plus, minus),
        back_mm=min(plus, minus),
    )


# --------------------------------------------------------------------------- #
# Walking a centerline
# --------------------------------------------------------------------------- #
class Meander(NamedTuple):
    """One solved serpentine run (see ``meander_run``): the ``points`` after
    the run's start, how many times it crosses the band (``crossings``), how
    far a full crossing reaches across it (``cross`` -- the whole band it was
    given, bar the one layout that has no full crossing), how far the last one
    reaches (``tail`` -- equal to ``cross`` when the run ends on a full
    crossing, and as little as a hair when the length has only just asked for
    another) and how far it travels along the tangent overall (``advance`` --
    the whole run it was given), plus how far the *first* one reaches when it
    is a short one (``lead`` -- 0 when the run starts at the edge of its band,
    and 0 again when the run is over before that first crossing finishes, in
    which case ``tail`` is the one that covers it). A straight run has no
    crossings, and no ``cross`` or ``tail`` with it.

    The two axes are named for what the run *does* along them rather than for
    where the area's borders are, because a design chooses which of its own
    directions ``tangent`` and ``inward`` point at, and the two that meander
    choose oppositely: an inverted-F crosses the depth behind its arm and
    advances along the feed edge, a meandered monopole crosses the width and
    advances away from that edge. A design's own words for the two ("fold
    depth", "leg spacing") are its metrics' business, not this module's."""

    points: list
    crossings: int
    cross: float
    tail: float
    advance: float
    lead: float = 0.0

    @property
    def folds(self):
        """Complete out-and-back teeth. An odd crossing count ends on a half
        fold -- the tail -- which is how the run meets a length that whole
        teeth cannot. A single crossing is no fold at all: the run steps off
        the near side and travels at that level."""
        return self.crossings // 2

    def metrics(self, cross_key, advance_key):
        """The run's numbers for a design's ``metrics`` dict, with the two
        axes under **that design's own words** for them: the counts and the
        tail as they are, and ``cross`` / ``advance`` keyed by ``cross_key``
        and ``advance_key`` -- an inverted-F's fold depth and arm span, a
        meandered monopole's leg length and stack depth. The engine has one
        serpentine and no opinion about which of those a caller drew, so this
        hands the numbers over rather than naming them (see the class
        docstring); a design adds its own keys to what comes back."""
        return {
            "folds": self.folds,
            "crossings": self.crossings,
            cross_key: self.cross,
            "tail_mm": self.tail,
            advance_key: self.advance,
            "lead_mm": self.lead,
        }


def step(point, direction, distance):
    """``point`` moved ``distance`` along the unit vector ``direction``."""
    return (point[0] + direction[0] * distance, point[1] + direction[1] * distance)


def opposite(direction):
    return (-direction[0], -direction[1])


def path_length(points):
    """The centerline length of a polyline (KiCad mm)."""
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def meander_run(
    start, tangent, inward, length_mm, advance_mm, cross_mm, pitch_mm, lead_mm=None
):
    """A serpentine run of exactly ``length_mm`` of centerline, starting at
    ``start`` and travelling along ``tangent``, folded ``inward`` when it is
    longer than the ``advance_mm`` of straight travel available.

    Returns a :class:`Meander`. The length is met exactly, never approximated.

    The run is a square wave across the band: ``crossings`` legs of ``cross``,
    alternating inward and outward, with a forward leg between consecutive
    ones. It crosses off ``start`` before travelling at all, so it rides the
    far side of the band from the first leg on and comes back to ``start``'s
    level at every full crossing.

    A scan needs everything but the length itself held, and two things would
    otherwise move with it. One is the **advance**: a run that travels less far
    than its ``advance_mm`` is a smaller antenna along that axis. The other is
    the crossings' **reach**: folds that stop short of the far side of the band
    are a smaller one across it. A sweep that let either move would compare
    candidates of different shapes and read the difference as frequency. So
    neither gives here. The run keeps the whole advance, every full crossing
    reaches the whole ``cross_mm`` band, and what absorbs a length those two do
    not divide is the crossing **count** -- half a fold at a time -- and the
    **last crossing** alone, which takes the remainder (``tail``). The open tip
    therefore travels across the band as the length grows, and the count ticks
    over when it arrives; every other candidate in the sweep is the same
    antenna with its tip somewhere else.

    The run is drawn **evenly** -- every leg ``advance / (crossings - 1)``, so
    the folds are one regular comb -- but it cannot be drawn evenly at the
    instant a crossing is added, or the shape would jerk: every fold would
    shuffle sideways at once as the divisor changed, and a full-depth strand of
    copper would land a whole leg width away between two neighbouring
    candidates. So a new crossing is **peeled off the far corner** and turned
    out into place (``meander_legs``): it opens from nothing at the run's tip,
    widening as it reaches further, while the folds behind it close up to pay
    for it. It is a fold like the others while still a whisker across, and the
    run is even again for the rest of the cycle -- all but a sliver of the
    sweep. Every point moves with the length and only with the length, so
    consecutive candidates really are the same antenna slightly redrawn.

    That whisker is the one place a fold is not like its neighbours, and it is
    also where the tail is free to be shorter than the track is wide: a
    crossing that short is a dimple inside the corner it grows out of, and buys
    less length than it measures. It is the cheapest of the three to give --
    never longer than a track width, gone again as the length grows through the
    window, and it leaves the rest of the antenna exactly where its neighbours
    have it.

    The one run whose far side is not the band's is the one that cannot reach
    it: a length less than a band over the advance has a single crossing, and
    simply steps across by what it has spare and travels at that level. There
    is no layout that reaches the far side with less -- crossing the band costs
    the whole band -- so this is as far across as such a run gets.

    ``pitch_mm`` is the smallest centerline spacing two parallel runs may have
    (the track width plus a clearance): the legs between the crossings each
    need one, and so does the band itself -- a band narrower than that would
    fold the run back inside its own width and buy no length.

    ``lead_mm`` is the first crossing's span, for a run that **enters its band
    part way across** rather than at one edge of it -- a serpentine whose
    crossings run parallel to the feed edge starts where the feed is, which is
    wherever the user put the marker's triangle, so its first crossing reaches
    the nearer border only and every one after it spans the whole band. None
    (the default) starts with a full crossing, which is what a run entering at
    the band's own edge does. A lead of nothing is the same thing -- but note
    it also means the caller's ``inward`` is pointing the wrong way for that
    layout, so the direction is the caller's to fix, not this function's.

    Raises ValueError with guidance when the length cannot be folded into the
    room available.
    """
    crossings, cross, tail, advance, lead = meander_plan(
        length_mm, advance_mm, cross_mm, pitch_mm, lead_mm
    )
    if not crossings:
        # Rounded like the folded branch below: the advance is a reported
        # number (a design's metrics, the result table), and a straight run's is
        # the length itself, float dust and all, unless it is cleaned here too.
        return Meander(
            [step(start, tangent, length_mm)], 0, 0.0, 0.0, round(length_mm, 4)
        )
    legs = meander_legs(crossings, tail, advance, pitch_mm)
    out = opposite(inward)
    points, p = [], start
    for i in range(crossings):
        # The last crossing takes the remainder; the first takes the lead when
        # there is one and it isn't also the last (then the tail already is it).
        reach = tail if i == crossings - 1 else (lead if i == 0 and lead else cross)
        p = step(p, inward if i % 2 == 0 else out, reach)
        points.append(p)
        if i < len(legs):  # ... the last crossing of a folded run ends it
            p = step(p, tangent, legs[i])
            points.append(p)
    return Meander(
        points,
        crossings,
        round(cross, 4),
        round(tail, 4),
        round(advance, 4),
        round(lead, 4),
    )


def meander_plan(length_mm, advance_mm, cross_mm, pitch_mm, lead_mm=None):
    """The layout ``meander_run`` will walk: ``(crossings, cross, tail,
    advance, lead)``, at full precision. The advance is the whole run available
    and the cross the whole band; only the count and the tail answer to the
    length (see its docstring). Zero crossings means the run is straight and the
    advance is the whole length.

    Split out so the decision reads on its own -- and so the tests can check
    the arithmetic against an independent enumeration of the layouts an area
    admits, without walking any points. Raises the same ValueErrors
    ``meander_run`` does."""
    if length_mm <= 0:
        raise ValueError("the meandered run must be longer than 0 mm")
    if length_mm <= advance_mm + 1e-9:
        return 0, 0.0, 0.0, length_mm, 0.0

    across = length_mm - advance_mm  # what the crossings have to supply
    if cross_mm < pitch_mm:
        raise ValueError(
            f"a {length_mm:.1f} mm run does not fit the {advance_mm:.1f} mm of "
            f"room and the area is only {max(cross_mm, 0.0):.1f} mm deeper "
            "than the antenna -- too shallow to meander (grow the area or "
            "shorten the antenna)"
        )
    lead = 0.0 if lead_mm is None else float(lead_mm)
    if lead > cross_mm + 1e-9:
        raise ValueError(
            f"the run enters its band {lead:.1f} mm from the near side, which "
            f"is more than the {cross_mm:.1f} mm band itself -- it would start "
            "outside the area"
        )
    # A run entering at (or within float dust of) the band's edge has no lead
    # at all: its first crossing is a full one like every other.
    if lead <= 1e-9:
        lead = 0.0
    if lead and across <= lead + 1e-9:
        # Over before the lead-in crossing finishes: that crossing is the run's
        # only one, so it is the tail, and there is no separate lead to report.
        return 1, round(across, 10), across, advance_mm, 0.0
    # The lead is fixed by where the run entered; the crossings after it are the
    # free variable. The fewest of them that can supply what is left, with none
    # running past the far side of the band -- which are also the longest ones.
    rest = across - lead
    more = max(1, math.ceil(rest / cross_mm - 1e-9))
    crossings = more + (1 if lead else 0)
    # Every crossing but the last reaches the whole band -- a single one is no
    # fold at all, just the step a run this short can afford. The last takes
    # what is left over, which is anything from the whole band down to a hair.
    cross = min(cross_mm, rest)
    tail = rest - (more - 1) * cross
    # One forward leg per gap between crossings -- one fewer than the crossings
    # (the same count, not the same thing) -- and each needs the track pitch.
    if advance_mm < (crossings - 1) * pitch_mm - 1e-9:
        raise ValueError(
            f"a {length_mm:.1f} mm run needs {crossings} crossing(s) of the "
            f"band, which do not fit the {advance_mm:.1f} mm of room at a "
            f"{pitch_mm:.2f} mm track pitch (widen the area, narrow the "
            "track, or shorten the antenna)"
        )
    return crossings, cross, tail, advance_mm, lead


def meander_legs(crossings, tail, advance, pitch):
    """How a planned run shares its ``advance`` out between its crossings: the
    forward legs in walk order, one after every crossing but the last (and one
    after the single crossing of a run that only steps across, which would
    otherwise not travel at all). They always sum to the whole ``advance``.

    **Evenly, bar a whisker at the start of each fold.** The run wants to be
    one regular comb of ``advance / (c - 1)`` legs, and is drawn that way for
    all but a sliver of every cycle -- but it cannot be drawn that way *through*
    a fold boundary, and this is where that is paid for.

    The forward legs are the one part of the run that buys no length: they sum
    to ``advance`` however they are shared out (the run keeps the whole of it,
    ``meander_run``), so all the length lives in the crossings' reach, and that
    reach is the only clock a sweep has. That is what makes "widen the new
    fold's leg first, then extend it" impossible to draw: widening the leg
    takes room off the other folds and adds nothing to the length, so it is not
    a stage a sweep can pass through -- it would have to happen at a single
    length, and every fold already drawn would jump sideways as it did
    (``advance / (c - 2)`` to ``advance / (c - 1)``, a whole leg width, with a
    full-length strand of copper on the end of it).

    So the hand-over is hung off the only clock there is, and packed into as
    little of it as the drawing can stand. A new crossing starts from
    **nothing at the far corner** and **turns out as it reaches further**,
    reaching the others' width once it is ``FOLD_TURNOUT_PITCHES`` of a
    ``pitch`` across -- while it is still a whisker in the corner, and long
    before it is copper worth the name. From there to the end of the cycle
    every leg is exactly ``advance / (c - 1)``.

    Writing ``g = min(1, tail / turnout)`` for how far the newborn one has
    turned out, the settled legs run at ``advance / (full + g)`` and the newborn
    one takes what is left. The two ends of the turnout are what carry the run
    continuously across a fold boundary:

    * ``g -> 0``: the settled legs share the whole advance evenly, as they did
      before the crossing appeared, and the newborn leg is nothing -- which is
      exactly the layout one fewer crossing ends on.
    * ``g = 1``: every leg, newborn included, is ``advance / (c - 1)`` -- the
      even run, which is also the layout the *next* crossing is born out of.

    Between them every leg moves with the length and only with the length, so
    no point of the run ever jumps."""
    if crossings <= 2:
        # Nothing to share: one crossing travels the whole advance at its
        # level, two hold it between them however far the second has reached.
        return [advance]
    full = crossings - 2  # the legs at the even width; + 1 turning out
    turnout = FOLD_TURNOUT_PITCHES * pitch
    g = 1.0 if tail >= turnout else tail / turnout
    settled = advance / (full + g)
    return [settled] * full + [advance - full * settled]


# --------------------------------------------------------------------------- #
# Centerline -> copper rectangles
# --------------------------------------------------------------------------- #
def path_rects(points, half, back_ext=0.0):
    """One polyline's copper as normalized axis-aligned rects, each segment
    buffered by ``half`` across its axis. A segment that another one continues
    from overshoots that joint by ``half`` so the corner is square (the joint
    is covered once, by the incoming segment); the open end of the polyline
    stays flat, and its start is pushed back by ``back_ext`` (the path's
    stub)."""
    segs = list(zip(points, points[1:]))
    rects = []
    for i, (p, q) in enumerate(segs):
        start = step(p, _unit(q, p), back_ext) if i == 0 and back_ext else p
        end = step(q, _unit(p, q), half) if i < len(segs) - 1 else q
        rects.append(seg_rect(start, end, half))
    return rects


def _unit(frm, to):
    """The unit vector from ``frm`` toward ``to``."""
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("a centerline segment has zero length")
    return (dx / length, dy / length)


def seg_rect(p, q, h):
    """An axis-aligned segment buffered by ``h`` across its axis only (flat
    ends), as a normalized rect."""
    if abs(p[0] - q[0]) < 1e-9:  # vertical
        return (p[0] - h, min(p[1], q[1]), p[0] + h, max(p[1], q[1]))
    if abs(p[1] - q[1]) > 1e-9:
        raise ValueError("centerline segments must be axis-aligned")
    return (min(p[0], q[0]), p[1] - h, max(p[0], q[0]), p[1] + h)


# --------------------------------------------------------------------------- #
# Copper -> gerber
# --------------------------------------------------------------------------- #
def candidate_polys(rects_kicad, rot_deg=0.0, pivot=(0.0, 0.0)):
    """The candidate's copper rectangles as board-frame corner polygons
    (KiCad mm): each rect's corners rotated by ``rot_deg`` about ``pivot``
    -- the step that puts geometry solved in a rotated area marker's
    derotated frame back onto the board (identity at 0)."""
    return [
        [
            markergeom.rotate_pt(p, rot_deg, pivot)
            for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        ]
        for (x0, y0, x1, y1) in rects_kicad
    ]


def splice_copper(gerber_text, polys_kicad, label="antenna"):
    """Splice the candidate copper into a plotted copper gerber: the KiCad-mm
    corner polygons (see candidate_polys) become dark G36 regions (Y negated
    into the gerber frame) inserted before the closing M02. The 4.6/mm
    coordinate format is asserted -- it is what KiCad plots and what the
    region coordinates are written in."""
    if "%FSLAX46Y46*%" not in gerber_text or "%MOMM*%" not in gerber_text:
        raise RuntimeError(
            "unexpected copper gerber coordinate format (want 4.6 mm, as "
            "KiCad plots); cannot splice the antenna candidate"
        )
    idx = gerber_text.rfind("M02*")
    if idx < 0:
        raise RuntimeError("copper gerber has no M02* end-of-file marker")
    lines = [f"G04 antenna_plugin: {label} candidate copper*", "%LPD*%"]
    for poly in polys_kicad:
        lines.extend(_region_lines([(x, -y) for (x, y) in poly]))
    return gerber_text[:idx] + "\n".join(lines) + "\n" + gerber_text[idx:]


def _region_lines(poly_gerber):
    """One closed G36/G37 polygon region (coordinates in gerber 4.6 mm
    ints)."""
    pts = [(int(round(x * 1e6)), int(round(y * 1e6))) for x, y in poly_gerber]
    lines = ["G36*", f"X{pts[0][0]}Y{pts[0][1]}D02*", "G01*"]
    lines += [f"X{x}Y{y}D01*" for x, y in pts[1:] + pts[:1]]
    lines.append("G37*")
    return lines
