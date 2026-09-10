"""Area marker: the antenna area + feed position, drawn on the board and
dragged there.

The marker is a **group** the wizard drops on a User.1..User.9 layer, named
``AntennaAreaMarker`` (boardshapes.new_group), holding two things:

* the **rectangle** where the antenna may live — a board-level graphic, because
  that is the only kind of item KiCad's point editor gives drag handles to. The
  area is sized on the board (double-click the marker to enter the group, drag
  a corner), not by sliders in the plugin — there are none — and the wizard
  reads back whatever the user drew. It is a KiCad *rectangle* while the marker
  sits on the grid, which KiCad itself keeps square, and a four-point *polygon*
  once it is turned off one (a rectangle graphic is two opposite corners, so it
  is always upright); a polygon can be dragged out of square, and
  ``square_outline`` puts it back, reading the drag the way KiCad reads a
  rectangle's — anchored at the corner opposite the one that moved;
* the **feed arrow** on one of its edges — a triangle pointing into the
  rectangle with a short stem running back out through the edge and a dot on
  the joint between the two, the feed port entering the area there. It is a
  *footprint*, because that is the only kind of item KiCad will **not** let
  anyone take apart: inside a group every loose graphic is selectable on its
  own, so an arrow built from five segments could be dragged one segment at a
  time into something that is no longer an arrow. Drag it (as one thing) to the
  edge the feed should enter from and ``sync_marker`` lands its base back on the
  nearest edge at the point it was dropped, squared to that edge, the next time
  the wizard looks at the board.

KiCad draws the group's name over the group, so the marker says how it is used
in KiCad's own label rather than in a drawing of the plugin's: the name is
GROUP_NAME, the identity MARKER_NAME with HINT_TEXT after it, and markers are
found by that identity as a prefix (placed_markers).

The user positions the whole marker with KiCad's own tools — move it anywhere,
rotate it with R in KiCad's own rotation steps. An arbitrary angle is the one
thing the board cannot express here, since only a footprint carries an angle
anyone can type: ``rotate_marker`` is the wizard's answer to that, in the same
degrees KiCad means everywhere else (counter-clockwise on screen, 0 as placed).

At scan time the group's shapes are read back off the board and decoded
geometrically into the area rectangle, the feed edge and the feed position —
the inputs a design's solve() works from — so what the user sees on the board is
exactly what the scan simulates. Decoding accepts any position and any rotation:
the off-grid residual (beyond the nearest 90-degree multiple) is measured off
the rectangle, the segments are derotated, and the decoded area is reported in
that derotated frame together with ``rot_deg``/``pivot`` so the scan can solve
on-grid, rotate the candidate copper back onto the board, and hand the runner
the matching ``rotation_deg``. KiCad turns a rectangle rotated off a cardinal
angle into a polygon; both read back as the same four sides
(boardshapes.outline_segments_mm), so a rotated marker decodes like any other.
Edited shapes still raise with a regenerate hint.

A marker is a group and nothing else here: the version of the plugin that drew
the whole marker as one footprint is history, and a board still carrying one is
converted to this shape before anything below looks at it
(legacy/area_marker_v1.py, called from the wizard's board sync). That keeps the
one interface — drag it — as the only one this module has to describe.

Frames: KiCad mm, Y down — the "bottom" edge of the decoded rectangle is the
one at max Y; ``rot_deg`` is mathematically CCW in that Y-down frame. The pure
helpers (everything above the board-facing divider) have no pcbnew/wx
dependency; the board half reuses boardshapes and feed_marker, which import
pcbnew lazily.
"""

import math

from ..emkit.markers import boardshapes, feed_marker, markergeom

# The marker's identity on the board: the start of its group's name (see
# GROUP_NAME), and the LIB_ID item name of the single footprint the marker used
# to be, which is how legacy/area_marker_v1.py finds one left over to convert.
MARKER_NAME = "AntennaAreaMarker"
# The feed arrow inside that group: its own footprint, so that KiCad will not
# let anyone drag it apart a segment at a time (see _parts).
FEED_NAME = "AntennaAreaFeed"

# KiCad draws a group's name over the group, so the name is a caption as well
# as an identity -- and the identity alone says what the marker is but not that
# it is something to take hold of. Everything about this marker is done on the
# board, behind the double-click that enters the group, so the name says so.
# Nothing is drawn for it: the words are already on the canvas, in KiCad's own
# label, and a text item of the plugin's own would be one more thing on the
# user's board to select, move and delete.
HINT_TEXT = "double-click to edit the marker"
GROUP_NAME = f"{MARKER_NAME}: {HINT_TEXT}"

LINE_STROKE_MM = 0.15  # stroke width of the marker's rectangle and arrow
MIN_SIDE_MM = 2.0  # smallest rectangle side worth marking
_TOL_MM = markergeom.TOL_MM  # endpoint-matching / axis-alignment tolerance
_EDGE_TOL_MM = 0.02  # vertex-on-rectangle-edge tolerance
_TRI_MARGIN_MM = 0.1  # triangle kept off the corners (decode needs
# the rectangle and triangle unconnected)
_PLACEMENT_MARGIN_MM = 5.0  # gap left between the board outline and a
# freshly placed marker (see _drop_spot)
_PIN_TOL_MM = 0.002  # how near the drawn arrow has to be to the pinned one to
# be left alone (pin_is_current) -- under the decode's own 3-dp rounding, and
# far under the tolerance segments are joined up by
_SQUARE_TOL = 0.0002  # |cos| between two outline edges still called a right
# angle (square_outline) -- 0.01 degrees, which no drag lands inside by
# accident and every undragged corner is well within

# Unit inward normal of each rectangle edge (KiCad Y-down: "bottom" = max Y),
# used to check the decoded feed arrow points into the area -- and to aim a
# dragged one, which is why the order matters: a feed point equidistant from
# two edges (a corner) takes the first of them (pin_feed).
_INWARD = {
    "bottom": (0.0, -1.0),
    "top": (0.0, 1.0),
    "left": (1.0, 0.0),
    "right": (-1.0, 0.0),
}


def _edge_at(px, py, x0, y0, x1, y1):
    """The rectangle edge the point ``(px, py)`` lies on (within
    ``_EDGE_TOL_MM`` and between that edge's corners), or None when it is on
    none or — at a corner — on two. Names follow the Y-down frame: "bottom" is
    the max-Y edge."""
    on = []
    if abs(py - y1) <= _EDGE_TOL_MM and x0 - _EDGE_TOL_MM <= px <= x1 + _EDGE_TOL_MM:
        on.append("bottom")
    if abs(py - y0) <= _EDGE_TOL_MM and x0 - _EDGE_TOL_MM <= px <= x1 + _EDGE_TOL_MM:
        on.append("top")
    if abs(px - x0) <= _EDGE_TOL_MM and y0 - _EDGE_TOL_MM <= py <= y1 + _EDGE_TOL_MM:
        on.append("left")
    if abs(px - x1) <= _EDGE_TOL_MM and y0 - _EDGE_TOL_MM <= py <= y1 + _EDGE_TOL_MM:
        on.append("right")
    return on[0] if len(on) == 1 else None


# --------------------------------------------------------------------------- #
# Pure geometry: the drawn shape, pinning the feed, decoding what is placed
# --------------------------------------------------------------------------- #
def _tri_size(edge_mm, depth_mm, tri_w_mm=None):
    """Feed-triangle base width and height. With no explicit width the base
    is scaled to the edge it sits on (the auto size); ``tri_w_mm`` sets it
    directly — the wizard's feed-width slider, a purely visual knob. Either way
    it is clamped so the triangle stays visible, fits between the edge's
    corners and sits inside a shallow area."""
    if tri_w_mm is None:
        tw = min(3.0, max(0.6, 0.18 * edge_mm))
    else:
        tw = min(max(float(tri_w_mm), 0.2), max(edge_mm - 2 * _TRI_MARGIN_MM, 0.2))
    return tw, min(0.75 * tw, 0.6 * depth_mm)


def _local_rect(w_mm, h_mm):
    """A rectangle ``w_mm`` × ``h_mm`` centered on the origin (KiCad Y-down):
    ``(x0, y0, x1, y1)``. What a freshly placed marker is drawn from, around
    its drop point. Raises ValueError on an area too small to mark."""
    w, h = float(w_mm), float(h_mm)
    if w < MIN_SIDE_MM or h < MIN_SIDE_MM:
        raise ValueError(
            f"the antenna area must be at least {MIN_SIDE_MM:g} x "
            f"{MIN_SIDE_MM:g} mm (got {w:g} x {h:g})"
        )
    return -w / 2, -h / 2, w / 2, h / 2


def _rect_segments(area):
    """The rectangle ``area`` (x0, y0, x1, y1) as its four sides, bottom edge
    first and drawn -x -> +x. The board draws the rectangle as one rectangle
    *shape* (that is what carries the drag handles); these segments are the
    same outline in the form everything decodes from, and what a marker's
    local geometry is built as."""
    x0, y0, x1, y1 = area
    return [
        ((x0, y1), (x1, y1)),  # bottom, -x -> +x
        ((x1, y1), (x1, y0)),
        ((x1, y0), (x0, y0)),
        ((x0, y0), (x0, y1)),
    ]


def rect_corners(area):
    """The rectangle ``area`` (x0, y0, x1, y1) as its four corners, clockwise
    from the min-x/min-y one — the order ``boardshapes.rect_corners_mm`` reads a
    placed rectangle back in, so corners written from here and corners read off
    the board are the same list in the same order (which is what lets
    ``_square_placed_outline`` compare them and write nothing)."""
    x0, y0, x1, y1 = area
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def edge_point(area, edge, frac):
    """The point on ``area``'s ``edge`` at ``frac`` (0..1 from the edge's
    smaller coordinate) — where a freshly placed marker's feed goes, and the
    inverse of the ``frac`` a decode reports. Not clamped off the corners:
    pin_feed does that, so the clamp has one home."""
    x0, y0, x1, y1 = area
    frac = min(max(float(frac), 0.0), 1.0)
    if edge in ("bottom", "top"):
        return (x0 + frac * (x1 - x0), y1 if edge == "bottom" else y0)
    return (x0 if edge == "left" else x1, y0 + frac * (y1 - y0))


def _nearest_edge(area, point):
    """The edge of ``area`` a dropped feed ``point`` belongs to: the one whose
    line it is nearest, measured perpendicular. A point equidistant from two
    (a corner, or the middle of a square) takes the first in _INWARD order —
    arbitrary, but the same arbitrary answer every time, so a marker doesn't
    change its feed edge on a redraw that changed nothing."""
    x0, y0, x1, y1 = area
    px, py = point
    distance = {
        "bottom": abs(py - y1),
        "top": abs(py - y0),
        "left": abs(px - x0),
        "right": abs(px - x1),
    }
    return min(_INWARD, key=lambda edge: distance[edge])


def pin_feed(area, point, tri_w_mm=None):
    """Put the feed arrow on the rectangle: the arrow for a feed dropped at
    ``point``, landed on the edge of ``area`` it is nearest and squared to it.
    Returns ``{"edge", "frac", "feed", "tri_w_mm", "segments", "dots"}`` in
    the frame ``area`` is given in — the segments and dot ready to be written
    onto the board, the rest describing what they mean.

    This is the whole feed UI: the user drags the arrow roughly where the feed
    belongs and this puts it exactly on the edge, apex pointing into the area,
    base centred on the feed point, clear of the corners. It is also how a
    fresh marker's arrow is built (through ``edge_point``) and how the arrow
    follows an edge the user has just dragged — one rule for placing a feed on
    a rectangle, wherever the ask came from.

    ``tri_w_mm`` is the triangle's (visual-only) base width; None scales it to
    the edge."""
    x0, y0, x1, y1 = area
    edge = _nearest_edge(area, point)
    horizontal = edge in ("bottom", "top")
    span_lo, span_hi = (x0, x1) if horizontal else (y0, y1)
    depth = (y1 - y0) if horizontal else (x1 - x0)
    tw, th = _tri_size(span_hi - span_lo, depth, tri_w_mm)

    # The base centre slides along the edge, clear of both corners: the decode
    # needs the triangle and the rectangle unconnected. An edge with no room
    # for that at all takes the middle and lets the decode complain.
    lo = span_lo + tw / 2 + _TRI_MARGIN_MM
    hi = span_hi - tw / 2 - _TRI_MARGIN_MM
    along = point[0] if horizontal else point[1]
    along = min(max(along, lo), hi) if lo <= hi else (span_lo + span_hi) / 2
    frac = (along - span_lo) / (span_hi - span_lo) if span_hi > span_lo else 0.0
    bx, by = edge_point(area, edge, frac)
    return {
        "edge": edge,
        "frac": frac,
        "feed": (bx, by),
        "tri_w_mm": tw,
        "segments": markergeom.arrow_segments(bx, by, tw / 2, th, _INWARD[edge]),
        "dots": [markergeom.arrow_dot(bx, by, tw / 2)],
    }


def marker_geometry(area, point, tri_w_mm=None):
    """A whole marker as ``(segments, dots)`` in the frame ``area`` is given
    in: the rectangle's four sides plus the feed arrow pinned to the edge
    nearest ``point`` (pin_feed). The one place the marker's drawing is
    defined — a fresh one is built from it and a repin rewrites the arrow half
    of it."""
    pinned = pin_feed(area, point, tri_w_mm)
    return _rect_segments(area) + pinned["segments"], pinned["dots"]


def _local_segments(w_mm, h_mm, frac, tri_w_mm=None):
    """A marker's segments in local mm (KiCad Y-down), rectangle centered on
    the origin with the feed on its bottom edge at ``frac``: the four sides,
    bottom first, then the five-segment feed arrow. What a fresh marker is
    drawn from (place_marker translates it onto the board) and the shape the
    decode below is written against."""
    area = _local_rect(w_mm, h_mm)
    return marker_geometry(area, edge_point(area, "bottom", frac), tri_w_mm)[0]


def _local_dots(w_mm, h_mm, frac, tri_w_mm=None):
    """A marker's filled dots in local mm as ``((x, y), radius)`` pairs: the
    one dot on the feed point, the joint between the arrow's stem and triangle
    on the rectangle's edge (markergeom.arrow_dot). Drawn only — the decode
    reads the segments (_decode_segments)."""
    area = _local_rect(w_mm, h_mm)
    return marker_geometry(area, edge_point(area, "bottom", frac), tri_w_mm)[1]


def square_outline(corners):
    """The rectangle a dragged outline means, from its four ``corners`` (mm, in
    board order) — the repair that keeps a *rotated* marker as unbreakable as
    an upright one.

    An upright marker's rectangle is a KiCad rectangle graphic, and KiCad will
    not let anyone drag it out of square: a rectangle is two opposite corners,
    so moving one handle moves the two beside it. A turned marker cannot be one
    (a rectangle graphic is always axis-aligned), so it is drawn as a four-point
    polygon — and a polygon *can* be dragged out of square, one vertex at a
    time. This puts it back, reading the drag the way KiCad reads a rectangle's:
    the corner opposite the one that moved is the anchor, and the two edges that
    did not move are the frame.

    Which corner moved is recoverable because the other three did not: exactly
    one corner has both of its non-adjacent edges still perpendicular to each
    other. (An edge dragged sideways — two corners moving together — leaves the
    same signature, and is squared the same way.) A drawing where no corner
    qualifies (two independent drags, or a corner KiCad's polygon editor
    *added*) has no such reading, and falls back to the bounding box in the
    frame of its longest edge: the area is then whatever was drawn, squared up,
    rather than an error the user can't act on.

    Returns four corners in the same order they came in, so the outline keeps
    its winding — and returns them unchanged, to the float, for a rectangle
    that was never dragged out of square."""
    if len(corners) == 4:
        if _is_rectangle(corners):
            return list(corners)  # untouched, to the float
        for i in range(4):
            squared = _square_about(corners, i)
            if squared is not None:
                return squared
    return _square_by_bbox(corners)


def _is_rectangle(corners):
    """Whether four corners already are one — every angle a right angle. The
    common case by far: it is what the wizard finds every time it looks at a
    marker nobody dragged, and answering it here is what lets those be handed
    straight back rather than rebuilt through float arithmetic that would move
    them a nanometre and call it a change."""
    for i in range(4):
        u = _unit(corners[i - 1], corners[i])
        v = _unit(corners[(i + 1) % 4], corners[i])
        if u is None or v is None or abs(u[0] * v[0] + u[1] * v[1]) > _SQUARE_TOL:
            return False
    return True


def _square_about(corners, i):
    """``corners`` rebuilt as a rectangle on the assumption that corner ``i``
    is the one that moved: the anchor is the corner opposite it and the frame
    is the two edges that don't touch it. None when those two edges are not
    perpendicular — which is what says corner ``i`` is not the one that
    moved."""
    p, anchor = corners[i], corners[(i + 2) % 4]
    u = _unit(corners[(i + 1) % 4], anchor)  # anchor -> the neighbour of p
    v = _unit(corners[(i + 3) % 4], anchor)  # anchor -> its other neighbour
    if u is None or v is None or abs(u[0] * v[0] + u[1] * v[1]) > _SQUARE_TOL:
        return None
    a = (p[0] - anchor[0]) * u[0] + (p[1] - anchor[1]) * u[1]
    b = (p[0] - anchor[0]) * v[0] + (p[1] - anchor[1]) * v[1]
    along = (anchor[0] + a * u[0], anchor[1] + a * u[1])
    across = (anchor[0] + b * v[0], anchor[1] + b * v[1])
    squared = [None] * 4
    squared[i] = (along[0] + b * v[0], along[1] + b * v[1])
    squared[(i + 1) % 4] = along
    squared[(i + 2) % 4] = anchor
    squared[(i + 3) % 4] = across
    return squared


def _square_by_bbox(corners):
    """The fallback repair: the bounding box of ``corners`` in the frame of
    their longest edge, as four corners in that frame's order. For an outline
    no single drag explains — the user moved two corners, or KiCad's polygon
    editor added one."""
    edges = [(corners[i], corners[(i + 1) % len(corners)]) for i in range(len(corners))]
    (a, b) = max(edges, key=lambda e: math.dist(e[0], e[1]))
    u = _unit(b, a) or (1.0, 0.0)
    v = (-u[1], u[0])
    us = [(p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1] for p in corners]
    vs = [(p[0] - a[0]) * v[0] + (p[1] - a[1]) * v[1] for p in corners]
    lo_u, hi_u, lo_v, hi_v = min(us), max(us), min(vs), max(vs)

    def at(su, sv):
        return (a[0] + su * u[0] + sv * v[0], a[1] + su * u[1] + sv * v[1])

    return [at(lo_u, lo_v), at(hi_u, lo_v), at(hi_u, hi_v), at(lo_u, hi_v)]


def _unit(point, origin):
    """The unit vector from ``origin`` to ``point``, or None when they
    coincide."""
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    length = math.hypot(dx, dy)
    return None if length <= _TOL_MM else (dx / length, dy / length)


def feed_angle_deg(decoded):
    """A decoded marker's rotation on the board, in the degrees KiCad means by
    an orientation: counter-clockwise on screen, 0 for a marker as it is placed
    (feed edge along the bottom, arrow pointing up the screen).

    Measured off the *feed direction* rather than off a side of the rectangle,
    because that is the one thing about the marker that is not four-fold
    symmetric: a rectangle turned by 90° is the same rectangle, but a feed on
    the left edge is not a feed on the bottom. So this is the whole rotation,
    0..360, and not the (-45, 45] residual the runner needs (``rot_deg``)."""
    inx, iny = _INWARD[decoded["edge"]]
    dx, dy = markergeom.rotate_pt((inx, iny), decoded["rot_deg"])
    return round(math.degrees(math.atan2(-dy, dx)) - 90.0, 4) % 360.0


def _split_shapes(segments):
    """A marker's segments split into ``(rectangle indices, arrow indices)``
    by connectivity: the four sides form one closed outline, the arrow's
    triangle-plus-stem another five-segment one. Raises ValueError when the
    segments are not those two shapes — an edited marker."""
    comps = markergeom.components(segments)
    rects = [c for c in comps if len(c) == 4]
    feeds = [c for c in comps if len(c) != 4]
    if len(rects) != 1 or len(feeds) != 1 or len(feeds[0]) != 5:
        raise ValueError(
            "area marker segments do not form a rectangle + a feed arrow; "
            "drag the arrow clear of the rectangle's corners, or regenerate "
            "the marker"
        )
    return rects[0], feeds[0]


def _decode_segments(segments):
    """Recover the marked area from a placed marker's segments (mm pairs in
    board coordinates, any position and rotation): ``{"area": (x0, y0, x1,
    y1), "edge", "frac", "w_mm", "h_mm", "feed", "rot_deg", "pivot"}``.
    ``rot_deg`` is the marker's off-grid rotation residual (beyond the
    nearest 90-degree multiple, mathematically CCW in the Y-down board
    frame, in (-45, 45]) about ``pivot`` (the rectangle centre); the area,
    feed point and edge name are reported in the DEROTATED frame — rotate
    them by ``rot_deg`` about ``pivot`` to land back on the board. The edge
    is named in that frame (Y down: "bottom" = max Y), ``frac`` is the feed
    position from the edge's smaller coordinate, ``w_mm`` the feed edge's
    length and ``h_mm`` the depth. Raises ValueError when the segments don't
    form the rectangle + inward feed arrow (an edited marker, or one whose
    arrow has been dragged off its edge and not yet repinned).

    The feed arrow (see pin_feed) is a triangle plus an outward stem — five
    connected segments — sharing the base centre; decoding takes the apex as
    the lone vertex inside the area, the two base corners as the triangle base
    and ignores the outward tail."""
    rect, feed = _split_shapes(segments)
    segments, rot_deg, pivot = _derotate(segments, rect)
    d = _decode_area(segments, rect, feed)
    d["rot_deg"] = rot_deg
    d["pivot"] = pivot
    return d


def _derotate(segments, rect):
    """The placed marker's off-grid rotation, undone: measures the residual
    angle of the ``rect`` component's first segment to its nearest axis and
    rotates every segment back by it about the rectangle's centre. Returns
    ``(derotated_segments, rot_deg, pivot)`` with ``rot_deg`` the rotation
    that maps the derotated frame back onto the board (0.0 for a marker on
    the grid — the segments pass through untouched, keeping exact
    coordinates)."""
    (a, b) = segments[rect[0]]
    rot_deg = -markergeom.align_rotation_deg(b[0] - a[0], b[1] - a[1])
    corners = markergeom.unique_vertices([segments[i] for i in rect])
    pivot = (
        round(sum(p[0] for p in corners) / len(corners), 4),
        round(sum(p[1] for p in corners) / len(corners), 4),
    )
    if not rot_deg:
        return segments, 0.0, pivot
    return (markergeom.rotate_segments(segments, -rot_deg, pivot), rot_deg, pivot)


def _rect_bbox(segments, rect):
    """The bounding box ``(x0, y0, x1, y1)`` of the derotated rectangle
    component, raising ValueError when its sides are no longer axis-aligned
    (so it is no longer a rectangle) or it has collapsed."""
    for i in rect:
        (a, b) = segments[i]
        if abs(a[0] - b[0]) > _TOL_MM and abs(a[1] - b[1]) > _TOL_MM:
            raise ValueError(
                "the area marker's rectangle was edited out of shape; "
                "regenerate the marker"
            )
    xs = [p[0] for i in rect for p in segments[i]]
    ys = [p[1] for i in rect for p in segments[i]]
    area = (min(xs), min(ys), max(xs), max(ys))
    if area[2] - area[0] < 1.0 or area[3] - area[1] < 1.0:
        raise ValueError("area marker rectangle is degenerate; regenerate the marker")
    return area


def _decode_area(segments, rect, feed):
    """Decode the area ``rect`` (four segment indices) and its ``feed`` arrow
    (five segment indices) into the area dict, or raise ValueError when they
    don't form an area marker. Off-grid rotation was already derotated away
    (_derotate)."""
    x0, y0, x1, y1 = _rect_bbox(segments, rect)

    # The feed arrow decodes (shared with the feed marker) to its base centre
    # (the feed point), width and inward direction. The base centre sits on the
    # feed edge; the direction must point into the area.
    fx, fy, tri_w, dvx, dvy = markergeom.decode_arrow([segments[i] for i in feed])
    edge = _edge_at(fx, fy, x0, y0, x1, y1)
    if edge is None:
        raise ValueError(
            "the feed arrow is not attached to the rectangle's edge; "
            "drag it back onto an edge (the wizard repins it), or "
            "regenerate the marker"
        )
    inx, iny = _INWARD[edge]  # unit inward normal (Y-down)
    if dvx * inx + dvy * iny <= 0:
        raise ValueError(
            "the feed arrow does not point into the area; regenerate the marker"
        )

    if edge in ("bottom", "top"):
        frac, w, h = (fx - x0) / (x1 - x0), x1 - x0, y1 - y0
    else:
        frac, w, h = (fy - y0) / (y1 - y0), y1 - y0, x1 - x0
    return {
        "area": (round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)),
        "edge": edge,
        "frac": round(frac, 4),
        "w_mm": round(w, 3),
        "h_mm": round(h, 3),
        "tri_w_mm": round(tri_w, 3),
        "feed": (round(fx, 3), round(fy, 3)),
    }


def repin_geometry(segments, tri_w_mm=None):
    """What a repin has to write: ``(arrow segments, dots, pinned)`` for the
    placed ``segments`` (board-frame mm pairs), with the arrow landed back on
    the rectangle edge it is nearest (pin_feed) and the fresh geometry given in
    that same board frame.

    This is the drag half of the marker, in pure form: the rectangle is taken
    as the user left it — dragged to any size, moved, rotated — and only the
    arrow is rewritten, so a repin never resists an edit. The pinning happens in
    the derotated frame (the rectangle's own), and the result is rotated back
    onto the board.

    ``tri_w_mm`` sets the triangle's visual width; None keeps the width the
    arrow is drawn with, so a repin the user didn't ask for doesn't resize
    their feed. Raises ValueError when the segments aren't a rectangle plus an
    arrow, or the rectangle is no longer one."""
    rect, feed = _split_shapes(segments)
    flat, rot_deg, pivot = _derotate(segments, rect)
    area = _rect_bbox(flat, rect)
    # The arrow, wherever the drag left it, in the rectangle's own frame.
    fx, fy, drawn_w, _dx, _dy = markergeom.decode_arrow([flat[i] for i in feed])
    pinned = pin_feed(area, (fx, fy), drawn_w if tri_w_mm is None else tri_w_mm)
    arrow, dots = pinned["segments"], pinned["dots"]
    if rot_deg:
        arrow = markergeom.rotate_segments(arrow, rot_deg, pivot)
        dots = [(markergeom.rotate_pt(pt, rot_deg, pivot), r) for pt, r in dots]
    return arrow, dots, pinned


def pin_is_current(segments, pinned, tol_mm=_PIN_TOL_MM):
    """Whether the arrow drawn in ``segments`` is already the one ``pinned``
    (a pin_feed result for those same segments) describes.

    This is what lets a repin write *nothing* in the ordinary case: the wizard
    repins every time its window regains the focus, and all but one of those
    finds a marker nobody touched. Rewriting six shapes to the values they
    already hold would be churn on the user's board for no drawing anyone can
    see. False for a marker that doesn't decode at all — that is exactly the
    marker a repin is for."""
    try:
        d = _decode_segments(segments)
    except ValueError:
        return False
    if d["edge"] != pinned["edge"]:
        return False
    if abs(d["tri_w_mm"] - pinned["tri_w_mm"]) > tol_mm:
        return False
    return all(abs(a - b) <= tol_mm for a, b in zip(d["feed"], pinned["feed"]))


def feed_point_mm(segments):
    """The feed point -- the arrow's base centre -- in the frame ``segments``
    (mm pairs) are given in: hand it a placed marker's board-frame segments and
    it answers where on the board the feed sits. That is _decode_segments'
    ``feed`` without its derotation and its 3-dp rounding. Raises ValueError
    when the segments don't carry exactly one feed arrow."""
    arrows = [c for c in markergeom.components(segments) if len(c) == 5]
    if len(arrows) != 1:
        raise ValueError(
            "area marker segments do not carry a single feed arrow; "
            "regenerate the marker"
        )
    fx, fy, _w, _dx, _dy = markergeom.decode_arrow([segments[i] for i in arrows[0]])
    return fx, fy


# --------------------------------------------------------------------------- #
# Board-facing: place, sync, rotate, decode (pcbnew imported lazily downstream)
# --------------------------------------------------------------------------- #
def placed_markers(board):
    """Every area marker on the board, in board order — the groups whose name
    starts with MARKER_NAME (the rest of it is the caption KiCad draws with it,
    GROUP_NAME). A whole-marker footprint from the versions before the marker
    was draggable is not one of these and is not looked for: the wizard's board
    sync converts it first (legacy/area_marker_v1.py)."""
    return boardshapes.groups_labelled(board, MARKER_NAME)


def _is_footprint(item):
    """Whether a group member is a footprint (the feed arrow) rather than a
    graphic (the rectangle). Duck-typed on a footprint's own accessor, so no
    pcbnew class has to be imported to ask."""
    return hasattr(item, "GraphicalItems")


def marker_shapes(marker):
    """Every graphic a placed marker is drawn with, in a stable order — the
    rectangle, and the arrow footprint's own shapes flattened in beside it (so
    a layer move or a layer reading covers the whole marker, not the half of it
    that isn't inside a footprint)."""
    shapes = []
    for item in boardshapes.group_items(marker):
        if _is_footprint(item):
            shapes.extend(_graphics_of(item))
        elif boardshapes.kind_of(item) is not None:
            shapes.append(item)
    return shapes


def _graphics_of(fp):
    """A footprint's drawn shapes (text and anything else dropped)."""
    return [item for item in fp.GraphicalItems() if getattr(item, "GetShape", None)]


def _parts(marker):
    """A marker group's two members: ``(outline shape, arrow footprint)`` — the
    rectangle (a polygon once it has been turned off a cardinal angle) and the
    feed arrow.

    The arrow is a footprint and not five loose segments precisely so that it
    *can't* be taken apart: inside a group every board shape is selectable on
    its own, so a five-segment arrow could be dragged one segment at a time
    into something that is no longer an arrow. A footprint's graphics can't be
    selected on the board at all, so the arrow moves and rotates as one thing
    or not at all — which is exactly what it means.

    Raises ValueError when the group no longer holds exactly those two: someone
    deleted one, or added something, and the wizard is not going to guess."""
    outline, arrows = [], []
    for item in boardshapes.group_items(marker):
        if _is_footprint(item):
            if str(item.GetFPID().GetLibItemName()) == FEED_NAME:
                arrows.append(item)
        elif boardshapes.kind_of(item) in ("rect", "poly"):
            outline.append(item)
    if len(outline) != 1 or len(arrows) != 1:
        raise ValueError(
            "the area marker's group no longer holds one rectangle and one "
            "feed arrow; regenerate the marker"
        )
    return outline[0], arrows[0]


def outline_corners_mm(shape):
    """A marker outline's four corners in board mm, whichever way it is drawn:
    a rectangle graphic while the marker sits on the grid, a four-point polygon
    once it has been turned off one."""
    kind = boardshapes.kind_of(shape)
    if kind == "rect":
        return boardshapes.rect_corners_mm(shape)
    return boardshapes.poly_points_mm(shape)


def segments_mm(marker):
    """A placed marker's drawing as ``((x0, y0), (x1, y1))`` mm pairs in board
    coordinates, ready for _decode_segments: the rectangle's four sides
    (whether it is drawn as a rectangle or, turned, as a polygon) plus the
    arrow's five segments."""
    ids = boardshapes.kind_ids()
    segments = []
    for shape in marker_shapes(marker):
        segments.extend(boardshapes.outline_segments_mm(shape, ids))
    return segments


def marker_layer_id(marker):
    """The pcbnew layer id a placed marker is drawn on, or None when it holds
    no shapes. The marker's layer is also where the wizard draws a candidate
    that doesn't fit (preview.draw)."""
    shapes = marker_shapes(marker)
    return shapes[0].GetLayer() if shapes else None


def marker_layer_name(marker):
    """The ``User.N`` name of the layer a placed marker sits on, or None when
    it has no shapes or they're off the User layers."""
    layer_id = marker_layer_id(marker)
    if layer_id is None:
        return None
    return next(
        (f"User.{n}" for n in range(1, 10) if feed_marker.user_layer_id(n) == layer_id),
        None,
    )


def marker_layer(marker):
    """The placed marker's own layer as ``(name, layer_id)`` -- where the
    wizard draws a candidate that does not fit the area, instead of on copper
    (preview.draw). Raises ValueError when the marker isn't on a User layer,
    which is the one case there is nowhere to put it."""
    name, layer_id = marker_layer_name(marker), marker_layer_id(marker)
    if name is None or layer_id is None:
        raise ValueError(
            "the area marker is not drawn on a User layer; regenerate the marker"
        )
    return name, layer_id


def decode_marker(marker):
    """The placed marker decoded off the board (see _decode_segments), plus
    ``layer`` (its ``User.N`` name, None when off the User layers),
    and ``angle_deg`` (its whole rotation on the board, KiCad's own convention —
    feed_angle_deg). Raises ValueError on a broken marker."""
    d = _decode_segments(segments_mm(marker))
    d["layer"] = marker_layer_name(marker)
    d["angle_deg"] = feed_angle_deg(d)
    return d


def _drop_spot(board, w_mm):
    """Where a fresh marker goes: just clear of the board outline's right
    edge, vertically centered on it, so it stands out on a dense board instead
    of landing buried among existing copper — the user drags it where it
    belongs anyway. Falls back to the middle of everything on the board when
    there is no Edge.Cuts outline yet to sit beside
    (GetBoardEdgesBoundingBox answers an empty box). Returns (x, y) in KiCad
    mm."""
    import pcbnew

    edges = board.GetBoardEdgesBoundingBox()
    if edges.GetWidth() <= 0 or edges.GetHeight() <= 0:
        box = board.GetBoundingBox()
        return (
            pcbnew.ToMM(int(box.GetX() + box.GetWidth() // 2)),
            pcbnew.ToMM(int(box.GetY() + box.GetHeight() // 2)),
        )
    x = edges.GetX() + edges.GetWidth() + pcbnew.FromMM(_PLACEMENT_MARGIN_MM)
    return (
        pcbnew.ToMM(int(x)) + float(w_mm) / 2,
        pcbnew.ToMM(int(edges.GetY() + edges.GetHeight() // 2)),
    )


def place_marker(board, user_n, w_mm, h_mm, frac, tri_w_mm=None):
    """Draw a new area marker on ``board``, just outside the board outline's
    right edge (see _drop_spot): a rectangle ``w_mm`` × ``h_mm`` with the feed
    arrow on its bottom edge at ``frac``, gathered into a group (build_marker,
    which is where what a marker is made of is written down).

    ``tri_w_mm`` is the feed triangle's visual base width (None = auto; the stem
    is always half that). Returns the (x, y) drop point in KiCad mm."""
    import pcbnew

    layer_id = feed_marker.check_layer(board, user_n)
    cx, cy = _drop_spot(board, w_mm)
    x0, y0, x1, y1 = _local_rect(w_mm, h_mm)  # also the too-small check
    area = (cx + x0, cy + y0, cx + x1, cy + y1)
    pinned = pin_feed(area, edge_point(area, "bottom", frac), tri_w_mm)
    build_marker(
        board, layer_id, rect_corners(area), pinned["segments"], pinned["dots"]
    )
    pcbnew.Refresh()
    return (round(cx, 3), round(cy, 3))


def build_marker(board, layer_id, corners, arrow, dots):
    """Draw a marker on ``board`` from finished board-frame geometry — the
    outline's four ``corners`` and the feed ``arrow`` segments and ``dots``
    (a pin_feed result, in the same frame) — and return the group holding them.

    The one place a marker is made, so there is one answer to what a marker *is*
    (a group of a draggable outline and a rigid arrow footprint, named so that
    KiCad's own label says what to do with it): Place builds a fresh one through
    here, and so does the conversion of a marker an older plugin drew as a
    single footprint (legacy/area_marker_v1.py)."""
    group = boardshapes.new_group(board, GROUP_NAME)
    outline = boardshapes.add_shape(board, "rect")
    _write_outline(outline, corners, layer_id)  # a rect, or a poly if turned
    boardshapes.add_to_group(group, outline)
    boardshapes.add_to_group(group, _new_arrow(board, layer_id, arrow, dots))
    return group


def _new_arrow(board, layer_id, arrow, dots):
    """The feed arrow of a marker being built: a board_only footprint of its
    own, added to the board with its origin on the feed point and its shapes
    drawn around that (``_arrow_local``). Its orientation is left at zero and
    stays there — the arrow is aimed by the geometry written into it, not by a
    footprint angle whose sign convention differs between KiCad versions."""
    import pcbnew

    from ..emkit.kicad.compat import vec2

    segments, local_dots = _arrow_local(arrow, dots)
    fp = feed_marker._build_footprint(
        board, FEED_NAME, "AREAFEED", layer_id, segments, LINE_STROKE_MM, local_dots
    )
    board.Add(fp)
    # The footprint's origin is the feed point, which is where the dot sits
    # (_arrow_local drew everything as offsets from it).
    (fx, fy) = dots[0][0]
    fp.SetPosition(vec2(pcbnew.FromMM(fx), pcbnew.FromMM(fy)))
    return fp


def _arrow_local(segments, dots):
    """An arrow's board-frame ``segments`` and ``dots`` moved into the frame of
    the footprint that carries them: origin on the feed point, which is where
    the dot sits (markergeom.arrow_dot) and where the footprint is placed."""
    (fx, fy) = dots[0][0]
    local = [((a[0] - fx, a[1] - fy), (b[0] - fx, b[1] - fy)) for (a, b) in segments]
    return local, [((x - fx, y - fy), r) for ((x, y), r) in dots]


def set_layer(marker, layer_id):
    """Move every shape of a placed marker to ``layer_id`` — the Advanced
    pane's Marker-layer pick, applied to the marker already on the board.
    Nothing is removed or re-added: a shape KiCad loaded with the board is
    KiCad's, and unlinking one from a plugin is a use-after-free
    (feed_marker._detach_item spells the rule out). An item already on the
    layer is left alone: this runs on every look at the board, and the common
    case is a pick nothing has changed."""
    if layer_id is None:
        return marker
    for shape in marker_shapes(marker):
        if shape.GetLayer() != layer_id:
            shape.SetLayer(layer_id)
    return marker


def sync_marker(marker, tri_w_mm=None, layer_id=None):
    """Bring a placed marker back into line with itself, in place, and answer
    it decoded (decode_marker). Three things, in this order:

    1. the layer, when ``layer_id`` says so (set_layer);
    2. the **outline**, squared back into a rectangle if a drag left it out of
       square (square_outline). Only a *turned* marker can be — an upright one
       is a KiCad rectangle, which KiCad keeps square itself;
    3. the **feed arrow**, landed back on whichever edge it now sits nearest,
       squared to it (repin_geometry).

    That is the whole board→plugin direction: whatever the user dragged is
    taken as what they meant, and the marker is left saying it cleanly. The
    rectangle's *size* is never argued with — only its squareness.

    ``tri_w_mm`` sets the triangle's visual width (None keeps the drawn one).

    Nothing is written that doesn't have to be (pin_is_current, and the outline
    only when it moved): this runs on every look at the board, and the ordinary
    case is a marker nobody touched."""
    import pcbnew

    set_layer(marker, layer_id)
    outline, arrow_fp = _parts(marker)
    wrote = _square_placed_outline(outline, layer_id)
    segments = segments_mm(marker)
    arrow, dots, pinned = repin_geometry(segments, tri_w_mm)
    if not pin_is_current(segments, pinned):
        _write_arrow(arrow_fp, arrow, dots, layer_id)
        wrote = True
    if wrote:
        pcbnew.Refresh()
    return decode_marker(marker)


def _square_placed_outline(outline, layer_id=None):
    """Square a placed outline shape back into a rectangle if a drag pulled it
    out of one (square_outline), and say whether anything was written.

    A rectangle that comes back axis-aligned is written as a KiCad *rectangle*
    and a turned one as a polygon (boardshapes.become switches the shape in
    place, so it stays the same item): on the grid the marker gets KiCad's own
    rectangle handles, which cannot be dragged out of square in the first
    place."""
    corners = outline_corners_mm(outline)
    if len(corners) < 3:
        raise ValueError(
            "the area marker's rectangle has no corners to read; regenerate the marker"
        )
    squared = square_outline(corners)
    if all(markergeom.near(a, b, _PIN_TOL_MM) for a, b in zip(corners, squared)):
        return False
    _write_outline(outline, squared, layer_id)
    return True


def _write_outline(outline, corners, layer_id=None):
    """Write four ``corners`` into a placed outline shape: as a rectangle when
    they are axis-aligned (KiCad's own rectangle, with the handles that keep it
    square), as a four-point polygon when they are not — a rectangle graphic is
    two opposite corners and can only ever be upright."""
    xs = sorted(p[0] for p in corners)
    ys = sorted(p[1] for p in corners)
    upright = (
        abs(xs[0] - xs[1]) <= _TOL_MM
        and abs(xs[2] - xs[3]) <= _TOL_MM
        and abs(ys[0] - ys[1]) <= _TOL_MM
        and abs(ys[2] - ys[3]) <= _TOL_MM
    )
    if upright:
        boardshapes.become(outline, "rect")
        boardshapes.set_rect(
            outline, layer_id, (xs[0], ys[0], xs[3], ys[3]), LINE_STROKE_MM
        )
    else:
        boardshapes.become(outline, "poly")
        boardshapes.set_outline_poly(outline, layer_id, corners, LINE_STROKE_MM)
    return outline


def _write_arrow(arrow_fp, segments, dots, layer_id=None):
    """Move the feed-arrow footprint onto ``segments``/``dots`` (board-frame
    mm): its origin goes on the feed point and its shapes are rewritten around
    it, squared to zero orientation.

    The footprint is moved and its graphics rewritten in place — never removed
    and re-added, and never rotated by a footprint angle (see _new_arrow).
    Squaring the orientation first is what lets the fresh geometry go in as
    plain offsets from the feed point: a user who rotated the arrow themselves
    (R) has it taken back to the edge it belongs on, which is where the arrow
    means anything at all."""
    import pcbnew

    from ..emkit.kicad.compat import vec2

    local_segments, local_dots = _arrow_local(segments, dots)
    (fx, fy) = dots[0][0]
    arrow_fp.SetOrientationDegrees(0)
    arrow_fp.SetPosition(vec2(pcbnew.FromMM(fx), pcbnew.FromMM(fy)))
    feed_marker._rewrite_marker(arrow_fp, local_segments, local_dots, layer_id)
    return arrow_fp


def rotate_marker(marker, angle_deg, tri_w_mm=None):
    """Turn a placed marker to ``angle_deg`` about its own centre — the one
    thing about the marker that cannot be done on the board.

    KiCad rotates a selection by its rotation *step* (Preferences → PCB Editor
    → Editing Options), and only a footprint carries an angle anyone can type;
    a group of graphics has none. So the wizard keeps this one control, in the
    same degrees KiCad means everywhere else: counter-clockwise on screen, 0
    for a marker as it is placed (feed edge along the bottom, arrow pointing up
    the screen). The rectangle's size and the feed's place along its edge are
    untouched — this is a turn, not a reshape.

    The outline becomes a polygon off the cardinal angles and a rectangle back
    on them (_write_outline), and the arrow rides round with it and is repinned
    (sync_marker). Answers the marker decoded."""
    import pcbnew

    outline, arrow_fp = _parts(marker)
    corners = outline_corners_mm(outline)
    pivot = (
        sum(p[0] for p in corners) / len(corners),
        sum(p[1] for p in corners) / len(corners),
    )
    # Screen-counter-clockwise (KiCad's convention, and the field's) is
    # mathematically clockwise in the Y-down board frame markergeom works in,
    # so the turn goes in negated.
    turn = -(float(angle_deg) - decode_marker(marker)["angle_deg"])
    _write_outline(
        outline, [markergeom.rotate_pt(p, turn, pivot) for p in corners], None
    )
    _turn_arrow(arrow_fp, turn, pivot)
    pcbnew.Refresh()
    return sync_marker(marker, tri_w_mm)


def _turn_arrow(arrow_fp, turn_deg, pivot):
    """Carry the feed-arrow footprint round with a rotating outline: its whole
    drawing rotated about ``pivot`` in the board frame (rotate_marker's own
    sense of the angle). Written as geometry rather than as a footprint
    orientation for the reason _new_arrow gives; sync_marker's repin squares it
    onto the turned edge straight after, so this only has to put it on the
    right side of the rectangle."""
    segments = markergeom.rotate_segments(
        feed_marker._segment_points_mm(arrow_fp), turn_deg, pivot
    )
    dots = [
        (markergeom.rotate_pt(center, turn_deg, pivot), radius)
        for center, radius in _arrow_dots_mm(arrow_fp)
    ]
    if dots:
        _write_arrow(arrow_fp, segments, dots)
    return arrow_fp


def _arrow_dots_mm(arrow_fp):
    """The feed-arrow footprint's dots as ``((x, y), radius)`` in board mm --
    what it is drawn with now, so a turn can carry them round."""
    import pcbnew

    dots = []
    for circle in feed_marker._circle_items(arrow_fp):
        center, edge = circle.GetStart(), circle.GetEnd()
        cx, cy = pcbnew.ToMM(int(center.x)), pcbnew.ToMM(int(center.y))
        dots.append(((cx, cy), abs(pcbnew.ToMM(int(edge.x)) - cx)))
    return dots
