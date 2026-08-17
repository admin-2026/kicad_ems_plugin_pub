"""Area-marker footprint: the wizard's antenna area + feed position, on-board.

The marker is a footprint the wizard drops on a User.1..User.9 layer, like
the feed marker: a rectangle outline marking where the antenna may live, with
a small feed arrow on the rectangle's bottom edge — a triangle pointing into
the rectangle with a short stem running back out through the edge, a dot on
the joint between the two — the feed port, entering the area from that edge at
the dot. The wizard's sliders reshape the
placed marker in place (width, height, and the feed's position along its
edge); the user positions it with KiCad's own tools — move it anywhere and
rotate it (R) to feed the antenna from another side or at an angle. A reshape
that would drag the feed point across the board can hold it still instead
(``update_marker(..., hold_feed=True)``): the rectangle is drawn about the
marker's own origin, so the area grows away from the feed edge rather than
over whatever the user lined the feed up with.

At scan time the placed footprint's segments are read back off the board and
decoded geometrically into the area rectangle, the feed edge and the feed
position — the inputs a design's solve() works from — so what the user sees on the
board is exactly what the scan simulates. Decoding accepts any position and
any rotation: the off-grid residual (beyond the nearest 90-degree multiple)
is measured off the rectangle, the segments are derotated, and the decoded
area is reported in that derotated frame together with ``rot_deg``/``pivot``
so the scan can solve on-grid, rotate the candidate copper back onto the
board, and hand the runner the matching ``rotation_deg``. Edited segments
still raise with a regenerate hint.

Frames: KiCad mm, Y down — the "bottom" edge of the decoded rectangle is the
one at max Y; ``rot_deg`` is mathematically CCW in that Y-down frame. The
pure helpers (everything above the board-facing divider) have no pcbnew/wx
dependency; the module reuses feed_marker's footprint mechanics, which
import pcbnew lazily.
"""

import math

from . import feed_marker, markergeom

# Footprint id (LIB_ID item name) the wizard generates and looks for.
MARKER_NAME = "AntennaAreaMarker"

LINE_STROKE_MM = 0.15  # stroke width of the marker's segments
MIN_SIDE_MM = 2.0  # smallest rectangle side worth marking
_TOL_MM = markergeom.TOL_MM  # endpoint-matching / axis-alignment tolerance
_EDGE_TOL_MM = 0.02  # vertex-on-rectangle-edge tolerance
_TRI_MARGIN_MM = 0.1  # triangle kept off the corners (decode needs
# the rectangle and triangle unconnected)
_PLACEMENT_MARGIN_MM = 5.0  # gap left between the board outline and a
# freshly placed marker (see _drop_beside_board)

# Unit inward normal of each rectangle edge (KiCad Y-down: "bottom" = max Y),
# used to check the decoded feed arrow points into the area.
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
# Pure geometry: local shape + decoding placed segments
# --------------------------------------------------------------------------- #
def _tri_size(w_mm, h_mm, tri_w_mm=None):
    """Feed-triangle base width and height. With no explicit width the base
    is scaled to the rectangle (the auto size); ``tri_w_mm`` sets it directly
    — the wizard's feed-width slider, a purely visual knob. Either way it is
    clamped so the triangle stays visible, fits between the edge's corners
    and sits inside a shallow area."""
    if tri_w_mm is None:
        tw = min(3.0, max(0.6, 0.18 * w_mm))
    else:
        tw = min(max(float(tri_w_mm), 0.2), max(w_mm - 2 * _TRI_MARGIN_MM, 0.2))
    return tw, min(0.75 * tw, 0.6 * h_mm)


def _local_rect(w_mm, h_mm):
    """The marked rectangle in footprint-local mm (KiCad Y-down), centered on
    the origin: ``(x0, y0, x1, y1)``. Raises ValueError on an area too small
    to mark."""
    w, h = float(w_mm), float(h_mm)
    if w < MIN_SIDE_MM or h < MIN_SIDE_MM:
        raise ValueError(
            f"the antenna area must be at least {MIN_SIDE_MM:g} x "
            f"{MIN_SIDE_MM:g} mm (got {w:g} x {h:g})"
        )
    return -w / 2, -h / 2, w / 2, h / 2


def _local_arrow(w_mm, h_mm, frac, tri_w_mm=None):
    """The feed arrow's placement in footprint-local mm, as
    markergeom.arrow_segments takes it: ``(cx, cy, half_w, tri_h)`` with the
    base centre on the rectangle's bottom edge at ``frac`` (0..1, clamped
    clear of the corners). ``tri_w_mm`` sets the base width (the visual
    feed-width slider); None keeps the auto size. The segments and the
    feed-point dot both hang off this, so the dot lands on the joint
    exactly."""
    x0, _, x1, y1 = _local_rect(w_mm, h_mm)
    tw, th = _tri_size(float(w_mm), float(h_mm), tri_w_mm)
    lo = x0 + tw / 2 + _TRI_MARGIN_MM
    hi = x1 - tw / 2 - _TRI_MARGIN_MM
    bx = x0 + min(max(frac, 0.0), 1.0) * (x1 - x0)
    bx = min(max(bx, lo), hi) if lo <= hi else 0.0
    return bx, y1, tw / 2, th


def _local_segments(w_mm, h_mm, frac, tri_w_mm=None):
    """The marker's segments in footprint-local mm (KiCad Y-down), rectangle
    centered on the origin: four rectangle edges — the bottom one first,
    drawn -x -> +x (decoding recovers the slider's local feed fraction from
    it) — then the feed arrow (_local_arrow), its triangle base on the bottom
    edge, its apex pointing inward and a short stem running back out through
    the edge, half the base width long. The feed is
    markergeom.arrow_segments — the same triangle-plus-stem arrow the feed
    marker uses, here with its base centred on the bottom edge, apex pointing
    inward (−Y) and stem running back out through the edge (+Y)."""
    x0, y0, x1, y1 = _local_rect(w_mm, h_mm)
    rect = [
        ((x0, y1), (x1, y1)),  # bottom (the feed edge), -x -> +x
        ((x1, y1), (x1, y0)),
        ((x1, y0), (x0, y0)),
        ((x0, y0), (x0, y1)),
    ]
    return rect + markergeom.arrow_segments(*_local_arrow(w_mm, h_mm, frac, tri_w_mm))


def _local_dots(w_mm, h_mm, frac, tri_w_mm=None):
    """The marker's filled dots in footprint-local mm as ``((x, y), radius)``
    pairs: the one dot on the feed point, the joint between the arrow's stem
    and triangle on the rectangle's edge (markergeom.arrow_dot). Drawn only —
    the decode reads the segments (_decode_segments)."""
    cx, cy, half_w, _ = _local_arrow(w_mm, h_mm, frac, tri_w_mm)
    return [markergeom.arrow_dot(cx, cy, half_w)]


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
    form the rectangle + inward feed arrow (an edited marker).

    The feed arrow (see _local_segments) is a triangle plus an outward stem —
    five connected segments — sharing the base centre; decoding takes the apex
    as the lone vertex inside the area, the two base corners as the triangle
    base and ignores the outward tail."""
    comps = markergeom.components(segments)
    rects = [c for c in comps if len(c) == 4]
    feeds = [c for c in comps if len(c) != 4]
    # The feed shape is the arrow: a triangle plus its stem, five connected
    # segments; anything else is a broken/edited marker.
    if len(rects) != 1 or len(feeds) != 1 or len(feeds[0]) != 5:
        raise ValueError(
            "area marker segments do not form a rectangle + a feed "
            "arrow; regenerate the marker"
        )
    segments, rot_deg, pivot = _derotate(segments, rects[0])
    d = _decode_area(segments, rects[0], feeds[0])
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


def _decode_area(segments, rect, feed):
    """Decode the area ``rect`` (four segment indices) and its ``feed`` arrow
    (five segment indices) into the area dict, or raise ValueError when they
    don't form an area marker."""
    # Off-grid rotation was already derotated away (_derotate), so a
    # non-axis-aligned side here means the outline is no longer rectangular.
    for i in rect:
        (a, b) = segments[i]
        if abs(a[0] - b[0]) > _TOL_MM and abs(a[1] - b[1]) > _TOL_MM:
            raise ValueError(
                "the area marker's rectangle was edited out of shape; "
                "regenerate the marker"
            )
    xs = [p[0] for i in rect for p in segments[i]]
    ys = [p[1] for i in rect for p in segments[i]]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
        raise ValueError("area marker rectangle is degenerate; regenerate the marker")

    # The feed arrow decodes (shared with the feed marker) to its base centre
    # (the feed point), width and inward direction. The base centre sits on the
    # feed edge; the direction must point into the area.
    fx, fy, tri_w, dvx, dvy = markergeom.decode_arrow([segments[i] for i in feed])
    edge = _edge_at(fx, fy, x0, y0, x1, y1)
    if edge is None:
        raise ValueError(
            "the feed arrow is not attached to the rectangle's edge; "
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


def feed_point_mm(segments):
    """The feed point -- the arrow's base centre -- in the frame ``segments``
    (mm pairs) are given in: hand it a placed marker's board-frame segments and
    it answers where on the board the feed sits. That is _decode_segments'
    ``feed`` without its derotation and its 3-dp rounding, which is what a
    board-frame move has to be measured in: rounding here would leave a micron
    of the feed's place behind on every nudge of a slider. Raises ValueError
    when the segments don't carry exactly one feed arrow."""
    arrows = [c for c in markergeom.components(segments) if len(c) == 5]
    if len(arrows) != 1:
        raise ValueError(
            "area marker segments do not carry a single feed arrow; "
            "regenerate the marker"
        )
    fx, fy, _w, _dx, _dy = markergeom.decode_arrow([segments[i] for i in arrows[0]])
    return fx, fy


def hold_shift_mm(before, after):
    """How far a reshaped marker has to move for its feed point to land back
    where it was: ``(dx, dy)`` in the segments' own frame, from the marker's
    segments ``before`` and ``after`` the reshape (feed_point_mm on each).

    The rectangle is drawn about the marker's own origin, so a change of height
    moves the feed edge -- and with it the feed point the user lined up with
    something on the board -- half the change outward. Sliding the whole marker
    back by this leaves the feed where it is drawn and grows (or shrinks) the
    area away from it, the depth's answer to what the width slider does by
    re-aiming the feed fraction. Raises ValueError when either bag of segments
    has no feed arrow."""
    (bx, by), (ax, ay) = feed_point_mm(before), feed_point_mm(after)
    return bx - ax, by - ay


def _local_frac(segments, decoded):
    """The feed position as the wizard's slider means it — the fraction
    along the marker's own bottom edge, in its local left-to-right direction
    — recovered by projecting the feed point onto the first segment (the
    bottom edge, drawn -x -> +x at creation; the projection is invariant
    under the moves and 90-degree rotations the editor applies). None when
    the segments were reordered/edited and the hint can't be trusted."""
    (s, e) = segments[0]
    ex, ey = e[0] - s[0], e[1] - s[1]
    length = math.hypot(ex, ey)
    if length <= _TOL_MM or abs(length - decoded["w_mm"]) > 0.05:
        return None
    fx, fy = decoded["feed"]
    if abs((fx - s[0]) * ey - (fy - s[1]) * ex) / length > 0.05:
        return None  # feed is not on that segment's line
    t = ((fx - s[0]) * ex + (fy - s[1]) * ey) / (length * length)
    if not -0.01 <= t <= 1.01:
        return None
    return round(min(max(t, 0.0), 1.0), 4)


# --------------------------------------------------------------------------- #
# Board-facing: generate, update, decode (pcbnew imported lazily downstream)
# --------------------------------------------------------------------------- #
def marker_footprints(board):
    """Every placed area-marker footprint, in board order."""
    return feed_marker.footprints_named(board, MARKER_NAME)


def _drop_beside_board(board, fp, w_mm):
    """Add ``fp`` to the board just clear of the board outline's right edge,
    vertically centered on it, so a freshly placed marker stands out on a
    dense board instead of landing buried among existing copper -- the user
    repositions it with KiCad's own tools anyway. Falls back to
    feed_marker._drop_at_center (the combined bounding box of everything on
    the board) when there is no Edge.Cuts outline yet to sit beside
    (GetBoardEdgesBoundingBox answers an empty box). Returns the (x, y)
    position in KiCad mm."""
    import pcbnew

    from ..kicad.compat import vec2

    edges = board.GetBoardEdgesBoundingBox()
    if edges.GetWidth() <= 0 or edges.GetHeight() <= 0:
        return feed_marker._drop_at_center(board, fp)

    margin = pcbnew.FromMM(_PLACEMENT_MARGIN_MM)
    half_w = pcbnew.FromMM(float(w_mm)) // 2
    pos = vec2(
        edges.GetX() + edges.GetWidth() + margin + half_w,
        edges.GetY() + edges.GetHeight() // 2,
    )
    board.Add(fp)
    fp.SetPosition(pos)
    pcbnew.Refresh()
    return (round(pcbnew.ToMM(int(pos.x)), 3), round(pcbnew.ToMM(int(pos.y)), 3))


def place_marker(board, user_n, w_mm, h_mm, frac, tri_w_mm=None):
    """Create the area marker just outside the board outline's right edge
    (see _drop_beside_board), straight through the pcbnew API — not the feed
    marker's clipboard/paste-to-cursor flow, which degrades into pasting the
    footprint as a slow text string when KiCad's clipboard parser rejects the
    text. Placing it clear of the board keeps it easy to spot on a dense
    board; the user repositions it with KiCad's own tools anyway. ``tri_w_mm``
    is the feed triangle's visual base width (None = auto; the stem is always
    half that). Returns the (x, y) position in KiCad mm."""
    layer_id = feed_marker.check_layer(board, user_n)
    fp = feed_marker._build_footprint(
        board,
        MARKER_NAME,
        "AREA",
        layer_id,
        _local_segments(w_mm, h_mm, frac, tri_w_mm),
        LINE_STROKE_MM,
        _local_dots(w_mm, h_mm, frac, tri_w_mm),
    )
    return _drop_beside_board(board, fp, w_mm)


def update_marker(fp, w_mm, h_mm, frac, tri_w_mm=None, layer_id=None, hold_feed=False):
    """Reshape a placed area marker in place, feed-point dot and all
    (rotation is kept — see feed_marker._rewrite_marker for why never remove +
    re-add). ``tri_w_mm`` sets the feed triangle's visual base width (None =
    auto; the stem is always half that); ``layer_id`` moves the marker to
    another User layer, None leaves it on the one it is drawn on. The feed
    arrow's segment count is fixed, so _rewrite_marker (a same-count reshape)
    always applies; a marker drawn before the dot existed gains one.

    With ``hold_feed`` the marker is then slid so its feed point lands back
    where this reshape found it (_shift_to_held_feed / hold_shift_mm) — what a
    change of height wants, since the rectangle grows about the marker's own
    origin and would otherwise push the feed edge across the board. Without it
    the marker's position is kept and the feed goes where the new shape puts
    it. Returns the marker's (x, y) in KiCad mm either way.

    A drawn antenna preview is NOT moved with it (it is a filled polygon, not a
    marker segment, and belongs on the copper whenever the candidate fits):
    the wizard redraws that, picking its layer again — sections.scan. It does
    travel with a ``hold_feed`` slide, though, which moves the footprint
    itself; the redraw that follows puts it right regardless."""
    before = feed_marker._segment_points_mm(fp) if hold_feed else None
    pos = feed_marker._rewrite_marker(
        fp,
        _local_segments(w_mm, h_mm, frac, tri_w_mm),
        _local_dots(w_mm, h_mm, frac, tri_w_mm),
        layer_id,
    )
    return pos if before is None else _shift_to_held_feed(fp, before)


def _shift_to_held_feed(fp, before_segments):
    """Slide the just-reshaped ``fp`` so its feed point returns to where
    ``before_segments`` (its board-mm segments as the reshape found them) had
    it, and answer its new (x, y) in KiCad mm.

    The footprint is moved, not its graphics: FOOTPRINT::SetPosition carries
    every shape — the marker's segments, its feed dot, any drawn antenna
    preview — along with it, so nothing is unlinked or rewritten (the rule
    feed_marker._detach_item spells out). A marker whose segments no longer
    decode is left where the reshape put it: there is no feed to hold, and the
    caller's own decode is what reports the breakage."""
    import pcbnew

    from ..kicad.compat import vec2

    pos = fp.GetPosition()
    try:
        dx, dy = hold_shift_mm(before_segments, feed_marker._segment_points_mm(fp))
    except ValueError:
        dx = dy = 0.0
    if dx or dy:
        pos = vec2(pos.x + pcbnew.FromMM(dx), pos.y + pcbnew.FromMM(dy))
        fp.SetPosition(pos)
    return (round(pcbnew.ToMM(int(pos.x)), 3), round(pcbnew.ToMM(int(pos.y)), 3))


def antenna_items(fp):
    """The wizard's drawn antenna-preview shapes: every filled polygon the
    marker carries (feed_marker._filled_poly_items). Found by shape, not by
    layer, because the preview is drawn on copper when the candidate fits and
    on the marker's own layer when it doesn't; decoding and the slider reshape
    only ever read User-layer *segments* (feed_marker._marker_segments), so the
    marker and its preview never collide either way."""
    return feed_marker._filled_poly_items(fp)


def marker_layer(fp):
    """The placed marker's own layer as ``(name, layer_id)`` -- where the
    wizard draws a candidate that does not fit the area, instead of on copper
    (draw_antenna). Raises ValueError when the marker isn't on a User layer,
    which is the one case there is nowhere to put it."""
    name = feed_marker.marker_layer_name(fp)
    layer_id = feed_marker.marker_layer_id(fp)
    if name is None or layer_id is None:
        raise ValueError(
            "the area marker is not drawn on a User layer; regenerate the marker"
        )
    return name, layer_id


def _rect_corners(seg_mm, width_mm):
    """The four corners (KiCad mm) of the solid rectangle that renders a
    centerline segment ``seg_mm`` at ``width_mm``: the segment swept out to
    half-width on each side, with the ends pushed out by half-width too so
    consecutive rectangles meet flush at bends (matching the square-capped
    extent of a stroked track). Degenerate zero-length segments yield None."""
    (x0, y0), (x1, y1) = seg_mm
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    ux, uy = dx / length, dy / length  # along the segment
    px, py = -uy, ux  # perpendicular (unit)
    h = width_mm / 2.0
    ax, ay = x0 - ux * h, y0 - uy * h  # end-capped endpoints
    bx, by = x1 + ux * h, y1 + uy * h
    return [
        (ax + px * h, ay + py * h),
        (bx + px * h, by + py * h),
        (bx - px * h, by - py * h),
        (ax - px * h, ay - py * h),
    ]


def draw_antenna(fp, segments_mm, layer_id, trace_w_mm):
    """Draw (or redraw) the wizard's antenna preview into a placed area
    marker: the candidate's centerline ``segments_mm`` (board-frame KiCad mm,
    design.geometry.Geometry.centerline_segments) on ``layer_id`` as solid
    filled rectangles ``trace_w_mm`` wide, so the preview reads as the track
    the footprint would place.

    ``layer_id`` is the feed copper layer for a candidate that fits the area
    and the marker's own User layer (marker_layer) for one that doesn't: the
    same drawing either way, but only real metal is ever drawn as metal -- an
    antenna hanging out of the rectangle is a sketch on the marker, not copper
    anyone would fabricate.

    A redraw **reuses the shapes already on the marker**, rewriting each in
    place (feed_marker._rewrite_filled_poly) as the marker's own segments are:
    a preview that was saved with the board and loaded back is KiCad's, and
    unlinking one of those from a plugin is a use-after-free
    (feed_marker._detach_item spells it out). Only the surplus a shorter
    candidate leaves over is detached -- and the count only changes when the
    candidate's shape does (straight vs folded), so the common redraw touches
    the footprint's item list not at all."""
    rects = [
        corners
        for corners in (_rect_corners(seg, trace_w_mm) for seg in segments_mm)
        if corners is not None
    ]
    drawn = antenna_items(fp)
    for poly, corners in zip(drawn, rects):
        feed_marker._rewrite_filled_poly(poly, layer_id, corners)
    for corners in rects[len(drawn) :]:
        feed_marker._add_filled_poly(fp, layer_id, corners)
    for poly in drawn[len(rects) :]:
        feed_marker._detach_item(fp, poly)


def clear_antenna(fp):
    """Take the drawn antenna preview (see draw_antenna) off a placed marker;
    returns how many shapes went (0 = there was none). The scan calls this
    before plotting gerbers -- a preview on the feed layer is real copper and
    would otherwise be spliced under every candidate -- and the footprint step
    once the real copper is placed.

    Every shape goes through feed_marker._detach_item: a preview loaded off
    the board cannot simply be removed. Nothing else clears a preview, so a
    caller that is about to draw another one should call draw_antenna
    directly, which reuses these shapes rather than orphaning them."""
    items = antenna_items(fp)
    for item in items:
        feed_marker._detach_item(fp, item)
    return len(items)


def decode_marker(fp):
    """The placed marker decoded off the board (see _decode_segments), plus
    ``frac_local`` (the slider's fraction, None when unrecoverable) and
    ``layer`` (its ``User.N`` name, None when off the User layers). Raises
    ValueError on a broken marker."""
    segs = feed_marker._segment_points_mm(fp)
    d = _decode_segments(segs)
    if d["rot_deg"]:
        # _local_frac projects the decoded (derotated-frame) feed point onto
        # the placed segments, so bring those into the same frame.
        segs = markergeom.rotate_segments(segs, -d["rot_deg"], d["pivot"])
    d["frac_local"] = _local_frac(segs, d)
    d["layer"] = feed_marker.marker_layer_name(fp)
    return d
