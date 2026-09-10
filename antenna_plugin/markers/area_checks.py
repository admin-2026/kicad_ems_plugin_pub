"""Advisory validation of the wizard's area marker against the board copper.

The area marker (area_marker.py) marks *where the antenna may live* and *where
the feed enters*; the scan then splices candidate antenna copper into the feed
layer and simulates. Several preconditions of that splice are only assumed --
see dev_docs/area-checks.md. This module surfaces them as **warnings** (never
blockers). Checks 4 and 5 look at the decoded area rectangle, not the
enumerated antenna trace, because the rectangle is a conservative superset of
where the antenna can go -- a clear rectangle guarantees a clear antenna, an
overlap is exactly the "worth a look" signal. The overlap check (2+3) instead
tests *the antenna's own copper*, clipped to the rectangle: the area
legitimately abuts the ground pour (its rectangle may even hang over it), so
only metal the antenna itself would land on is worth a warning there.

    Checks 2+3 -- antenna over existing copper (``antenna_problems``, not one
        of the CHECKS: its copper comes from the caller, not the board). The
        scan splices each candidate into the feed layer, assumed empty where
        the copper lands; existing metal there (a track, a pour, a pad --
        including an antenna footprint placed by an earlier run) merges with
        the candidate and silently corrupts every result. Warn when that
        copper overlaps feed-layer metal *inside* the area rectangle. It is
        asked about copper somebody committed to -- the sweep of a started
        scan / grid pass, or the candidate being placed -- never about one
        that only sits in the wizard's scan rows, which splices nothing and so
        overlaps nothing yet. Outside the rectangle, overlap is expected --
        the feed / ground stubs must reach the surrounding pour -- so nothing
        outside is judged, and neither is the
        connection band just inside the feed edge (FEED_EDGE_SLACK_MM): the
        pins sit *on* that edge and the area is routinely drawn hanging over
        the pour so they reach it, so the pour a hair inside the feed edge is
        the layout working, not an overlap. The other three edges need no such
        band -- the design's own border keep-off already holds the copper off
        them.

    Check 4 -- feed-port axis. The port drives against the ground pour reached
        through the feed edge, while the monopole radiates off the opposite
        edge, so the two sides have opposite requirements. Warn when the strip
        just outside the feed edge has *no* ground copper (nothing to reference)
        or the strip outside the opposite edge *is* backed by copper (the
        radiator is shielded). Both read the feed-layer copper in-plane.

    Check 5 -- stacked copper. The antenna sits on the feed layer; copper on the
        *other* copper layers directly over/under the area (a ground plane
        behind the monopole body) detunes or kills it. Warn, naming the layers.

Frames: the decoded area rectangle is axis-aligned in the marker's *derotated*
frame (area_marker returns ``area`` there, with ``rot_deg``/``pivot`` mapping it
back onto the board). Rather than test against a rotated box, every board copper
point is mapped into that derotated frame (rotate by ``-rot_deg`` about
``pivot``), where all the overlap tests are plain axis-aligned-rectangle work.

Adding a check: write a ``def _..._problems(ctx)`` against
:class:`CheckContext` (the frame under test plus a cached board-copper reader)
and list it in ``CHECKS``; ``area_problems`` runs the list and the banner
renders whatever comes back, so nothing else changes.

Everything above the board-facing divider is pure planar geometry (KiCad mm,
Y-down) with no pcbnew/wx dependency, so it stays unit-testable off KiCad;
pcbnew is imported lazily below, like the rest of the markers package. The
Problem type and the enabled-copper-layer walk are reused from the pre-flight
layer (``sim.simulate``) so the wizard's banner renders these the same way as
the board-level blockers.
"""

from ..emkit.markers import feed_marker, markergeom, preview
from ..emkit.sim.simulate import Problem
from . import area_marker

# How far outside an edge the feed-axis check probes for copper (mm). Deep
# enough to clear the small keep-off a ground pour usually leaves against the
# antenna area, shallow enough that the radiating-side test doesn't reach
# unrelated copper further out on the board.
PROBE_MM = 2.0

# The edge facing the feed edge across the rectangle (Y-down names, "bottom" =
# max Y -- matching area_marker._edge_at).
_OPPOSITE = {"bottom": "top", "top": "bottom", "left": "right", "right": "left"}


# --------------------------------------------------------------------------- #
# Pure geometry: axis-aligned rectangle overlap tests
# --------------------------------------------------------------------------- #
def _inflate(rect, r):
    """``rect`` (x0, y0, x1, y1) grown by ``r`` on every side -- used to fold a
    track's half-width or a via's radius into a point/segment test."""
    x0, y0, x1, y1 = rect
    return (x0 - r, y0 - r, x1 + r, y1 + r)


def _point_in_rect(p, rect):
    x0, y0, x1, y1 = rect
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def _orient(a, b, c):
    """Signed area of triangle a-b-c (>0 CCW, <0 CW, 0 collinear)."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_span(a, b, c):
    """``c``, known collinear with a-b, lies within the a-b bounding span."""
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[
        1
    ] <= max(a[1], b[1])


def _segments_cross(p1, p2, p3, p4):
    """True when segment p1-p2 meets segment p3-p4 (proper crossing or a
    collinear/endpoint touch)."""
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return (
        (d1 == 0 and _on_span(p3, p4, p1))
        or (d2 == 0 and _on_span(p3, p4, p2))
        or (d3 == 0 and _on_span(p1, p2, p3))
        or (d4 == 0 and _on_span(p1, p2, p4))
    )


def _rect_edges(rect):
    x0, y0, x1, y1 = rect
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


def _seg_hits_rect(a, b, rect):
    """Segment a-b intersects (or lies inside) the axis-aligned ``rect``."""
    if _point_in_rect(a, rect) or _point_in_rect(b, rect):
        return True
    return any(_segments_cross(a, b, e0, e1) for e0, e1 in _rect_edges(rect))


def _point_in_poly(p, poly):
    """Ray-cast point-in-polygon for a closed ``poly`` (list of vertices)."""
    inside = False
    n = len(poly)
    for i in range(n):
        (xi, yi), (xj, yj) = poly[i], poly[(i + 1) % n]
        if (yi > p[1]) != (yj > p[1]):
            x_cross = xi + (p[1] - yi) * (xj - xi) / (yj - yi)
            if p[0] < x_cross:
                inside = not inside
    return inside


def _poly_hits_rect(poly, rect):
    """Closed ``poly`` overlaps the axis-aligned ``rect``: an edge crosses the
    rectangle (covers a poly vertex inside it too), or the rectangle sits
    wholly inside the polygon (a rect corner inside it)."""
    if len(poly) < 3:
        return False
    if any(
        _seg_hits_rect(poly[i], poly[(i + 1) % len(poly)], rect)
        for i in range(len(poly))
    ):
        return True
    x0, y0, x1, y1 = rect
    return any(
        _point_in_poly(c, poly) for c in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    )


def _shape_hits_rect(shape, rect):
    """Whether a copper ``shape`` overlaps ``rect``. A shape is one of
    ``("point", (p, r))`` (via / pad centre + radius), ``("seg", (a, b, hw))``
    (track centreline + half-width) or ``("poly", pts)`` (zone fill / pad
    outline)."""
    kind, data = shape
    if kind == "point":
        p, r = data
        return _point_in_rect(p, _inflate(rect, r))
    if kind == "seg":
        a, b, hw = data
        return _seg_hits_rect(a, b, _inflate(rect, hw))
    return _poly_hits_rect(data, rect)


def _to_local(shape, rot_deg, pivot):
    """``shape`` (board-frame mm) with its points mapped into the marker's
    derotated frame (rotate by ``-rot_deg`` about ``pivot``); the radius /
    half-width is rotation-invariant and passes through. A 0-degree marker maps
    identically."""

    def xf(p):
        return markergeom.rotate_pt(p, -rot_deg, pivot)

    kind, data = shape
    if kind == "point":
        p, r = data
        return ("point", (xf(p), r))
    if kind == "seg":
        a, b, hw = data
        return ("seg", (xf(a), xf(b), hw))
    return ("poly", [xf(p) for p in data])


def _outward_band(rect, edge, depth):
    """The strip of width ``depth`` just outside ``edge`` of ``rect`` (Y-down:
    "bottom" = max Y), spanning that edge's length -- where check 4 looks for
    ground / shielding copper."""
    x0, y0, x1, y1 = rect
    if edge == "bottom":
        return (x0, y1, x1, y1 + depth)
    if edge == "top":
        return (x0, y0 - depth, x1, y0)
    if edge == "left":
        return (x0 - depth, y0, x0, y1)
    return (x1, y0, x1 + depth, y1)  # right


def _aabb_overlap(a, b):
    """Two axis-aligned mm bboxes (x0, y0, x1, y1) overlap (touching counts)."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# Copper must reach deeper than this into the area to count as *inside* it:
# the area is routinely drawn flush against the ground pour, and a pour edge
# exactly on the area edge (or a hair over it, from grid snapping) is that
# layout working as intended, not an overlap worth warning about.
EDGE_SLACK_MM = 0.02

# ... and deeper than this at the *feed* edge, where the antenna's own pins
# land: they sit exactly on that edge (geometry.edge_frame puts the feed point
# there, with no border keep-off, unlike the other three edges) and are meant
# to meet the ground pour, so the area is routinely placed hanging a little
# over it. Copper this close to the feed edge is therefore the connection, not
# an obstruction. Matched to the reach of the runner's own ground stub
# (design.geometry.GROUND_STUB_MM) -- a pour intruding further than the stub
# is worth a look after all.
FEED_EDGE_SLACK_MM = 1.0


def _judged_area(area, edge, slack=EDGE_SLACK_MM, feed_slack=FEED_EDGE_SLACK_MM):
    """The part of ``area`` the overlap check may judge: the rectangle inset by
    ``slack`` on every side and by ``feed_slack`` at the feed ``edge`` (see the
    two constants). Degenerate on an area shallower than the two insets, which
    ``_inside_area`` then clips everything away against."""
    x0, y0, x1, y1 = _inflate(area, -slack)
    deeper = max(feed_slack - slack, 0.0)
    if edge == "bottom":
        y1 -= deeper
    elif edge == "top":
        y0 += deeper
    elif edge == "left":
        x0 += deeper
    else:  # right
        x1 -= deeper
    return (x0, y0, x1, y1)


def _inside_area(rects, area, edge, slack=EDGE_SLACK_MM, feed_slack=FEED_EDGE_SLACK_MM):
    """The parts of the candidate's copper ``rects`` that lie inside ``area``
    (all axis-aligned marker-frame mm): each rect clipped to the judged part of
    the area (``_judged_area``), degenerate leftovers dropped. The stubs, any
    copper hanging out of the area -- where overlapping the ground pour is what
    they are *for* -- and the pins' connection band along the feed edge vanish
    here, so what remains is exactly what the overlap check may judge."""
    x0, y0, x1, y1 = _judged_area(area, edge, slack, feed_slack)
    clipped = []
    for a0, b0, a1, b1 in rects:
        c = (max(a0, x0), max(b0, y0), min(a1, x1), min(b1, y1))
        if c[2] > c[0] and c[3] > c[1]:
            clipped.append(c)
    return clipped


def _any_hit(shapes, rects):
    """Any copper shape overlapping any of the axis-aligned ``rects``."""
    return _first_hit(shapes, rects) is not None


def _first_hit(shapes, rects):
    """The first of ``rects`` any copper shape overlaps, or None -- the rect
    lets the overlap check say *where* it found metal.

    The rectangles are prepared for as a *set*, not tested one at a time: they
    all sit inside the area, so the copper is first reduced to what can reach
    their common span (``_near_span``). Asked rect by rect instead, every one of
    the antenna's rectangles walked every vertex of every pour on the layer, and
    the wizard paid that product on every keystroke -- a ground pour is
    thousands of vertices, and the *clear* board is the slow case, since there
    is no early hit to stop at. Reduced, the pour costs one pass to find the
    handful of its edges that come near (or one answer to "does it cover them
    all"), and each rect then meets only those."""
    if not rects or not shapes:
        return None
    probes = _near_span(shapes, _union_bbox(rects))
    for r in rects:
        if any(_probe_hits_rect(p, r) for p in probes):
            return r
    return None


def _union_bbox(rects):
    """The one bbox covering every rect (they are all in the area together)."""
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def _seg_bbox(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _shape_bbox(shape):
    """A copper shape's bbox with its radius / half-width folded in -- the
    cheap stand-in tested before the shape itself is."""
    kind, data = shape
    if kind == "point":
        (x, y), r = data
        return (x - r, y - r, x + r, y + r)
    if kind == "seg":
        a, b, hw = data
        return _inflate(_seg_bbox(a, b), hw)
    return (
        min(p[0] for p in data),
        min(p[1] for p in data),
        max(p[0] for p in data),
        max(p[1] for p in data),
    )


def _near_span(shapes, span):
    """``shapes`` reduced to what can overlap a rectangle inside ``span``, as
    probes for ``_probe_hits_rect``: shapes nowhere near it are dropped, and a
    polygon keeps only the edges that reach it.

    A polygon with no edge near ``span`` can't cross any rect in there, so it
    either contains every one of them or none -- one point test settles it for
    the whole set, and a polygon that settles it with "none" is dropped too.
    That is the whole-board ground pour: thousands of edges, none of them
    within reach of the antenna, either wrapped around the area or nowhere near
    it."""
    probes = []
    for shape in shapes:
        kind, data = shape
        if kind != "poly":
            if _aabb_overlap(_shape_bbox(shape), span):
                probes.append(shape)
            continue
        if len(data) < 3:  # not a polygon: overlaps nothing (_poly_hits_rect)
            continue
        if not _aabb_overlap(_shape_bbox(shape), span):
            continue
        # The near edges keep their own bbox: an area drawn across the pour's
        # edge has hundreds of them in the span, and each rect only meets the
        # few that reach it.
        near = [
            (bb, a, b)
            for a, b, bb in (
                (a, b, _seg_bbox(a, b)) for a, b in zip(data, data[1:] + data[:1])
            )
            if _aabb_overlap(bb, span)
        ]
        # No edge near: the span (and so every rect in it) is wholly inside the
        # polygon or wholly outside it, and one probe point says which.
        covers = None if near else _point_in_poly((span[0], span[1]), data)
        if covers is False:
            continue
        probes.append(("poly", (near, data, covers)))
    return probes


def _probe_hits_rect(probe, rect):
    """Whether a ``_near_span`` probe overlaps ``rect`` -- the same question
    ``_shape_hits_rect`` answers, on a shape already reduced to the rect's
    neighbourhood. Points and segments are unreduced and go straight there."""
    kind, data = probe
    if kind != "poly":
        return _shape_hits_rect(probe, rect)
    near, poly, covers = data
    if covers is not None:
        return covers
    if any(_aabb_overlap(bb, rect) and _seg_hits_rect(a, b, rect) for bb, a, b in near):
        return True
    # No edge of the polygon crosses this rect (the ones not kept can't reach
    # it -- the rect is inside the span they were rejected against), so the
    # rect is wholly inside the polygon or wholly outside: one corner decides
    # what _poly_hits_rect asks of all four.
    return _point_in_poly((rect[0], rect[1]), poly)


def _area_board_bbox(marker, pad):
    """The area rectangle's bounding box in the *board* frame (rot_deg applied),
    grown by ``pad`` -- a cheap clip so the board walk skips copper nowhere near
    the area (see the cost note in dev_docs/area-checks.md)."""
    x0, y0, x1, y1 = marker["area"]
    rot, pivot = marker["rot_deg"], marker["pivot"]
    pts = [
        markergeom.rotate_pt(c, rot, pivot)
        for c in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


# --------------------------------------------------------------------------- #
# Board-facing: the check registry (pcbnew imported lazily)
# --------------------------------------------------------------------------- #
class CheckContext:
    """What one refresh hands every check.

    ``frame`` is where the checks look: a dict carrying the axis-aligned
    ``area`` rectangle in the marker's derotated frame, the
    ``rot_deg``/``pivot`` mapping that frame onto the board, and ``edge`` for
    the checks that care where the feed enters -- the decoded marker itself
    for the CHECKS, the scan spec the copper was solved in for the overlap
    check (``antenna_problems``). ``antenna_rects`` is that copper, in the
    same frame (geometry.Geometry.copper_rects, stubs off), or None -- the
    overlap check then stays quiet. ``local_shapes`` reads one layer's board
    copper mapped into the frame, walked once per layer and cached, so however
    many checks probe a layer the board is walked once."""

    def __init__(self, board, frame, feed_layer, feed_id, antenna_rects=None):
        self.board = board
        self.frame = frame
        self.feed_layer = feed_layer  # copper suffix, e.g. "F_Cu"
        self.feed_id = feed_id  # its pcbnew layer id
        self.antenna_rects = antenna_rects
        self._shapes = {}  # layer_id -> shapes, derotated frame

    @property
    def area(self):
        return self.frame["area"]

    def copper_layers(self):
        """The board's enabled copper layers as (suffix, layer_id) pairs."""
        from ..emkit.sim import simulate

        return simulate.copper_layers(self.board)

    def local_shapes(self, layer_id):
        """The board's copper on ``layer_id`` near the area, as geometry
        shapes in the derotated frame (see _shape_hits_rect). One clip serves
        every check -- the area bbox grown past the deepest outward probe; it
        only bounds the walk, the checks' own rect tests decide.

        The walk visits every track, zone, drawing and footprint on the board
        through SWIG and reads a zone's fill vertex by vertex (~17 ms on a
        2-layer board), so it is worth the cache -- which is per *context*,
        though: one refresh that builds two contexts walks the same layer
        twice."""
        if layer_id not in self._shapes:
            clip = _area_board_bbox(self.frame, PROBE_MM + 1.0)
            rot, pivot = self.frame["rot_deg"], self.frame["pivot"]
            self._shapes[layer_id] = [
                _to_local(s, rot, pivot)
                for s in _copper_shapes(self.board, layer_id, clip)
            ]
        return self._shapes[layer_id]


def area_problems(board, feed_layer_name):
    """Every advisory area-marker warning that reads the board alone, for
    ``board`` with the antenna on ``feed_layer_name`` (a copper-layer suffix,
    e.g. ``F_Cu``): the CHECKS run against the single decoded area marker.
    The antenna-overlap check is not among them -- it needs copper somebody
    committed to (``antenna_problems``). Returns a list of
    ``sim.simulate.Problem`` (all ``severity="warn"``), empty when there isn't
    exactly one decodable area marker (that case is reported elsewhere) or the
    feed layer isn't a copper layer on this board. Read-only."""
    marker = _one_marker(board)
    if marker is None:
        return []
    resolved = _resolve_layer(board, feed_layer_name)
    if resolved is None:
        return []
    ctx = CheckContext(board, marker, *resolved)
    return [p for check in CHECKS for p in check(ctx)]


def antenna_problems(board, feed_layer_name, frame, antenna_rects):
    """The antenna-overlap warnings alone, for copper the user has committed
    to: the sweep a started scan / grid pass splices (the wizard's banner,
    through ScanSection.spliced_copper) and the chosen candidate the footprint
    section is about to place. ``frame`` is the scan spec that copper was
    solved in (its ``area`` / ``rot_deg`` / ``pivot`` / ``edge``), not the
    marker on the board: both land in that frame even when the marker has been
    moved (or deleted) since the scan."""
    resolved = _resolve_layer(board, feed_layer_name)
    if resolved is None:
        return []
    ctx = CheckContext(board, frame, *resolved, antenna_rects=antenna_rects)
    return _antenna_overlap_problems(ctx)


def _one_marker(board):
    """The single placed area marker decoded (area_marker.decode_marker), or
    None when there is not exactly one, or it no longer decodes -- both are
    surfaced by the area section itself, so the checks stay quiet."""
    markers = area_marker.placed_markers(board)
    if len(markers) != 1:
        return None
    try:
        return area_marker.decode_marker(markers[0])
    except ValueError:
        return None


def _resolve_layer(board, name):
    """The copper layer for suffix ``name`` (defaulting to the top copper
    when blank) as a ``(suffix, layer_id)`` pair, or None when it isn't an
    enabled copper layer on this board."""
    from ..emkit.sim import simulate

    want = name or "F_Cu"
    for suffix, layer_id in simulate.copper_layers(board):
        if suffix == want:
            return (suffix, layer_id)
    return None


# --------------------------------------------------------------------------- #
# The checks (one function each; listed in CHECKS below)
# --------------------------------------------------------------------------- #
def _antenna_overlap_problems(ctx):
    """Checks 2+3: the candidate's copper against existing feed-layer metal
    inside the area (see the module docstring; outside the area -- and in the
    connection band just inside the feed edge -- overlapping the ground pour
    is what the pins and stubs are *for*, so nothing there is judged)."""
    if ctx.antenna_rects is None:
        return []
    rects = _inside_area(ctx.antenna_rects, ctx.area, ctx.frame["edge"])
    hit = _first_hit(ctx.local_shapes(ctx.feed_id), rects)
    if hit is None:
        return []
    return [
        Problem(
            "area-antenna-overlap",
            "warn",
            f"the antenna's copper lands on existing {ctx.feed_layer} metal "
            f"inside the area, {_where(ctx.frame, hit)} -- the scan splices "
            "candidates into that layer, so the shapes would merge and quietly "
            "corrupt every result; clear the copper under the antenna or move "
            "the area",
            title="Antenna overlaps copper in the area",
        )
    ]


def _where(frame, rect):
    """Where a marker-frame ``rect`` is, as ``around (x, y) mm``: its centre
    mapped back onto the board, so the warning names a spot the user can go and
    look at in the editor (KiCad's coordinate readout is in the same board
    mm)."""
    p = ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)
    x, y = markergeom.rotate_pt(p, frame["rot_deg"], frame["pivot"])
    return f"around ({x:.2f}, {y:.2f}) mm"


def _feed_axis_problems(ctx):
    """Check 4: the feed edge should back onto ground, the opposite (radiating)
    edge should be open. Both read the feed-layer copper just outside the two
    edges, in the marker's derotated frame."""
    edge = ctx.frame["edge"]
    source = _outward_band(ctx.area, edge, PROBE_MM)
    radiating = _outward_band(ctx.area, _OPPOSITE[edge], PROBE_MM)
    shapes = ctx.local_shapes(ctx.feed_id)

    problems = []
    if not _any_hit(shapes, [source]):
        problems.append(
            Problem(
                "area-feed-open",
                "warn",
                "no ground copper just outside the area's feed edge -- the feed "
                "port has no pour to reference; move the area against the ground "
                "plane or rotate it so the feed enters from the grounded side",
                title="Feed edge has no ground",
            )
        )
    if _any_hit(shapes, [radiating]):
        problems.append(
            Problem(
                "area-radiating-shielded",
                "warn",
                "copper backs the radiating edge (opposite the feed) -- the "
                "monopole may be shielded and won't radiate; keep that side open "
                "to free space or the board edge",
                title="Radiating edge is shielded",
            )
        )
    return problems


def _stacked_copper_problems(ctx):
    """Check 5: copper on the other copper layers over/under the area (a ground
    plane behind the monopole body) detunes it. One warning naming the layers."""
    hit = [
        suffix
        for suffix, layer_id in ctx.copper_layers()
        if layer_id != ctx.feed_id and _any_hit(ctx.local_shapes(layer_id), [ctx.area])
    ]
    if not hit:
        return []
    layers = ", ".join(hit)
    return [
        Problem(
            "area-stacked-copper",
            "warn",
            f"copper on {layers} lies over/under the antenna area -- a plane "
            f"behind the monopole body detunes or kills it; keep the area clear "
            f"on the other copper layers",
            title="Copper stacked over the area",
        )
    ]


# The advisory checks that read the board alone, in banner order. The overlap
# check is deliberately not one of them: it judges copper the user committed to
# by starting a pass (or by placing a footprint), which only its own caller
# has, so it runs through antenna_problems -- the banner puts it first, where
# CHECKS would have. Adding a board-only check is writing a
# ``def _..._problems(ctx)`` above and listing it here.
CHECKS = (_feed_axis_problems, _stacked_copper_problems)


def _copper_shapes(board, layer_id, clip):
    """Every copper feature on ``layer_id`` whose board bbox overlaps ``clip``
    (mm bbox), as geometry shapes in board-frame KiCad mm (see
    _shape_hits_rect for the shape kinds). Covers tracks/vias, zone fills, pads,
    board graphic shapes drawn on the copper layer (PCB_SHAPE -- copper poured
    as a filled polygon/rectangle or a drawn line, which carries no net and so
    isn't a zone or track) and the same graphics inside footprints. The
    plugin's *own* placed antenna arrives through the pad walk: footprints.sexpr
    carries the whole radiator as the feed pad's custom shape (so that it has a
    net and can be routed to), which is why pads are read as their real outline
    where the build offers one and only fall back to a bounding box otherwise --
    the box around a meandered arm is mostly empty space, and this walk decides
    whether copper is in the way. A zone/pad/graphic whose polygon binding
    differs across KiCad builds is skipped rather than raising (the checks are
    advisory)."""
    import pcbnew

    tom = pcbnew.ToMM

    def mm(pt):
        return (tom(int(pt.x)), tom(int(pt.y)))

    def in_clip(item):
        return _aabb_overlap(_item_bbox_mm(item, tom), clip)

    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            if t.IsOnLayer(layer_id) and in_clip(t):
                yield ("point", (mm(t.GetPosition()), tom(int(t.GetWidth())) / 2.0))
        elif t.GetLayer() == layer_id and in_clip(t):
            yield (
                "seg",
                (mm(t.GetStart()), mm(t.GetEnd()), tom(int(t.GetWidth())) / 2.0),
            )

    for z in board.Zones():
        if z.IsOnLayer(layer_id) and in_clip(z):
            for poly in _zone_polys(z, layer_id, mm):
                yield ("poly", poly)

    # Copper drawn as board graphics (a filled polygon/rectangle pour or a
    # line) has no net, so it's a PCB_SHAPE in GetDrawings(), not a zone/track.
    kinds = _shape_kind_ids()
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == layer_id and in_clip(d):
            for shape in _pcb_shape_geoms(d, kinds, mm, tom):
                yield shape

    for fp in board.GetFootprints():
        # The plugin's own drawings are skipped whole: the preview footprint is
        # filled polys on the feed layer, and a sketch of the candidate being
        # judged is not copper it collides with. (The antenna footprint a
        # placement writes is not one of these -- that one is real copper, and
        # is meant to be seen by the next candidate's check.)
        if _is_marker(fp):
            continue
        for pad in fp.Pads():
            if pad.IsOnLayer(layer_id) and in_clip(pad):
                for poly in _pad_polys(pad, layer_id, mm, tom):
                    yield ("poly", poly)
        for item in fp.GraphicalItems():
            if _is_graphic(item) and item.GetLayer() == layer_id and in_clip(item):
                for shape in _pcb_shape_geoms(item, kinds, mm, tom):
                    yield shape


def _is_marker(fp):
    """Whether ``fp`` is one of the plugin's own drawings -- the feed marker,
    the wizard's antenna preview, the area marker's feed arrow, or a whole area
    marker from the versions when it was one footprint and the wizard has not
    converted it yet (legacy/area_marker_v1.py) -- matched by LIB_ID item name
    the way the marker finders do (feed_marker.footprints_named). The area
    marker's rectangle is a board graphic and never reaches this walk; it is on
    a User layer either way, and this walk only ever asks about copper."""
    return str(fp.GetFPID().GetLibItemName()) in (
        area_marker.MARKER_NAME,
        area_marker.FEED_NAME,
        feed_marker.MARKER_NAME,
        preview.PREVIEW_NAME,
    )


def _is_graphic(item):
    """Whether a footprint item is a drawn shape rather than text or a zone --
    duck-typed on ``GetShape``, the way feed_marker picks a marker's segments
    out, because the class is ``FP_SHAPE`` on KiCad 6/7 and ``PCB_SHAPE`` from
    8 on and a missed shape here is a missed warning."""
    return getattr(item, "GetShape", None) is not None


def _item_bbox_mm(item, tom):
    """A board item's bounding box as an (x0, y0, x1, y1) mm bbox."""
    bb = item.GetBoundingBox()
    x, y = tom(int(bb.GetX())), tom(int(bb.GetY()))
    return (x, y, x + tom(int(bb.GetWidth())), y + tom(int(bb.GetHeight())))


def _bbox_poly(bb, tom):
    """A board item's bounding box as a 4-corner polygon in mm (a conservative
    stand-in for a pad's real outline -- enough for an advisory overlap)."""
    x, y = tom(int(bb.GetX())), tom(int(bb.GetY()))
    w, h = tom(int(bb.GetWidth())), tom(int(bb.GetHeight()))
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _pad_polys(pad, layer_id, mm, tom):
    """A pad's copper as vertex polygons (mm): its effective outline where the
    build exposes one, its bounding box where it does not.

    The outline matters for one pad in particular -- the generated antenna's,
    which is a custom pad shaped like the whole radiator, and whose bounding box
    would claim every millimetre of board the meander merely reaches around.
    ``GetEffectivePolygon`` takes nothing before KiCad 9 and a layer from 9 on
    (padstacks), so both are tried in that order; a build that offers neither
    falls back to the box, which leaves the walk coarse rather than blind."""
    getter = getattr(pad, "GetEffectivePolygon", None)
    for args in ((), (layer_id,)) if getter else ():
        try:
            polys = _polyset_polys(getter(*args), mm)
        except Exception:
            continue
        if polys:
            return polys
    return [_bbox_poly(pad.GetBoundingBox(), tom)]


def _zone_polys(zone, layer_id, mm):
    """A zone's filled copper on ``layer_id`` as a list of vertex polygons
    (mm). Empty when the zone has no fill on that layer or the SHAPE_POLY_SET
    binding differs (older KiCad wants no layer arg); either way the check just
    misses that zone rather than failing the whole banner."""
    try:
        try:
            sps = zone.GetFilledPolysList(layer_id)
        except TypeError:
            sps = zone.GetFilledPolysList()
        return _polyset_polys(sps, mm)
    except Exception:
        return []


def _polyset_polys(sps, mm):
    """The outer outlines of a SHAPE_POLY_SET as vertex polygons (mm). Holes
    are ignored -- treating a cut-out as filled only over-reports, which is safe
    for an advisory overlap."""
    polys = []
    for i in range(sps.OutlineCount()):
        chain = sps.Outline(i)
        pts = [mm(chain.CPoint(j)) for j in range(chain.PointCount())]
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def _shape_kind_ids():
    """The PCB_SHAPE shape-type enum values on this KiCad build (SHAPE_T_* on
    6+, the older S_* names as a fallback), keyed by a stable short name."""
    import pcbnew

    def one(new, old):
        v = getattr(pcbnew, new, None)
        return v if v is not None else getattr(pcbnew, old, None)

    return {
        "seg": one("SHAPE_T_SEGMENT", "S_SEGMENT"),
        "rect": one("SHAPE_T_RECT", "S_RECT"),
        "circle": one("SHAPE_T_CIRCLE", "S_CIRCLE"),
        "arc": one("SHAPE_T_ARC", "S_ARC"),
        "poly": one("SHAPE_T_POLYGON", "S_POLYGON"),
    }


def _pcb_shape_geoms(shape, kinds, mm, tom):
    """Copper shapes for one PCB_SHAPE graphic (a segment/arc line, a circle, a
    rectangle or a filled polygon). Its line width folds into the half-width /
    radius; an unrecognised shape falls back to its bounding box so it is never
    silently dropped."""
    st = shape.GetShape()
    hw = tom(int(shape.GetWidth())) / 2.0
    if st in (kinds["seg"], kinds["arc"]):  # arc approximated by its chord
        yield ("seg", (mm(shape.GetStart()), mm(shape.GetEnd()), hw))
    elif st == kinds["circle"]:
        yield ("point", (mm(shape.GetCenter()), tom(int(shape.GetRadius())) + hw))
    elif st == kinds["rect"]:
        a, b = mm(shape.GetStart()), mm(shape.GetEnd())
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        yield ("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    elif st == kinds["poly"]:
        try:
            for poly in _polyset_polys(shape.GetPolyShape(), mm):
                yield ("poly", poly)
        except Exception:
            yield ("poly", _bbox_poly(shape.GetBoundingBox(), tom))
    else:
        yield ("poly", _bbox_poly(shape.GetBoundingBox(), tom))
