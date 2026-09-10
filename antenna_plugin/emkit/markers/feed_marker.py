"""Feed-marker footprint: generate, find on the board, and hand to the runner.

The marker is a small footprint the GUI drops on a User.1..User.9 layer: an
arrow — a triangle head ``width_mm`` wide whose apex points along the feed
direction (toward the antenna), with a short stem running back from the base
centre, half the width long. The base centre is the feed point and its width
is the feed width, so what the user sees on the board is exactly the port the
solver builds; a filled dot sits on that base centre so the port point itself
is unmistakable.

The runner takes the feed as a point + direction (the ``feed_ports`` entry: it
infers the axis/width off the copper and severs a one-cell gap on the
simulation grid), so the footprint is never plotted and the drawn width is
visual. At run time the plugin reads the placed footprint's segments back off
the board and recovers the feed point (the base centre) and the arrow's
direction, which config.py writes into the ``feed_ports`` entry; a marker
rotated off-grid additionally yields the ``rotation_deg`` that re-aligns it
(markergeom.align_rotation_deg). Coordinates follow KiCad's gerber plots (mm,
Y negated), so the point lands on the plotted copper exactly.

The arrow's shape and decode live in markergeom (arrow_segments / arrow_dot /
decode_arrow), shared with the area marker and pure so they stay
unit-testable off-KiCad; pcbnew is imported lazily like simulate.py does.
"""

from ... import product
from ..kicad import modtext
from . import boardshapes, markergeom

# Footprint id (LIB_ID item name) the plugin generates and looks for.
MARKER_NAME = "AntennaFeedMarker"

LINE_STROKE_MM = 0.1  # stroke width of the marker's segments


# --------------------------------------------------------------------------- #
# Pure geometry: local shape + decoding placed segments
# --------------------------------------------------------------------------- #
def _local_segments(width_mm):
    """The marker's segments in footprint-local mm (KiCad Y-down): the feed
    arrow (markergeom.arrow_segments) centred on the origin — the feed point —
    a triangle ``width_mm`` wide whose apex points away (−Y, the feed
    direction) with a stem running back the other way, half the width long.
    The triangle height is scaled to the width."""
    w = float(width_mm)
    return markergeom.arrow_segments(0.0, 0.0, w / 2, 0.75 * w)


def _local_dots(width_mm):
    """The marker's filled dots in footprint-local mm as ``((x, y), radius)``
    pairs: the one dot on the feed point at the origin, where the stem meets
    the triangle (markergeom.arrow_dot). Drawn only — the decode reads the
    segments."""
    return [markergeom.arrow_dot(0.0, 0.0, float(width_mm) / 2)]


# The feed decode is exactly the shared arrow decode (base centre + direction
# + width); the marker carries nothing else the runner needs (the dot is
# drawn on the point this recovers).
_decode_segments = markergeom.decode_arrow


def _marker_sexpr(name, reference, layer, segments, stroke_mm, dots=()):
    """A board_only marker footprint drawn as line ``segments`` plus filled
    ``dots`` (``((x, y), radius)`` pairs, the feed point) on ``layer``, as
    .kicad_mod text -- the scaffolding shared by the plugin's markers (the
    feed marker here, the wizard's area marker in area_marker.py). Emitted in
    KiCad 6 syntax with its version token, the oldest format every supported
    KiCad (6..9) still parses (its numbers and text items come from
    kicad/modtext.py, shared with the generated antenna footprint)."""
    lines = [
        f'(footprint "{name}" (version 20211014) (generator {product.PACKAGE})',
        '  (layer "F.Cu")',
        "  (attr board_only exclude_from_pos_files exclude_from_bom)",
        modtext.fp_text("reference", reference, layer="F.SilkS", hide=True),
        modtext.fp_text("value", name, hide=True),
    ]
    for (x0, y0), (x1, y1) in segments:
        lines.append(
            f"  (fp_line (start {modtext.num(x0)} {modtext.num(y0)}) "
            f"(end {modtext.num(x1)} {modtext.num(y1)}) "
            f'(layer "{layer}") (width {modtext.num(stroke_mm)}))'
        )
    for (x, y), radius in dots:
        # A circle is centre + a point on it; solid fill with no stroke, so
        # the dot is exactly the radius asked for (as _add_filled_circle).
        lines.append(
            f"  (fp_circle (center {modtext.num(x)} {modtext.num(y)}) "
            f"(end {modtext.num(x + radius)} {modtext.num(y)}) "
            f'(layer "{layer}") (width 0) (fill solid))'
        )
    lines.append(")")
    return "\n".join(lines) + "\n"


def footprint_sexpr(user_n, width_mm):
    """The marker footprint as .kicad_mod text, for cursor placement: the
    text goes on the clipboard and a simulated paste hands it to KiCad's
    native paste tool, which puts it on the cursor (the Python API exposes no
    interactive move)."""
    return _marker_sexpr(
        MARKER_NAME,
        "FEED",
        f"User.{user_n}",
        _local_segments(width_mm),
        LINE_STROKE_MM,
        _local_dots(width_mm),
    )


# --------------------------------------------------------------------------- #
# Board-facing: generate, find, export
# --------------------------------------------------------------------------- #
def user_layer_id(n):
    """pcbnew layer id for User.``n`` (1..9), or None when this KiCad build
    doesn't define it."""
    import pcbnew

    return getattr(pcbnew, f"User_{n}", None)


def _build_footprint(board, name, reference, layer_id, segments, stroke_mm, dots=()):
    """Build a board_only marker footprint (not yet added to the board): the
    line ``segments`` and the filled ``dots`` (``((x, y), radius)`` pairs, the
    feed point) on ``layer_id``, hidden reference/value, excluded from BOM and
    position files. Shared by the feed marker and the wizard's area marker
    (area_marker.py)."""
    import pcbnew

    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID("", name))
    fp.SetReference(reference)
    fp.SetValue(name)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    attrs = 0
    for attr in ("FP_EXCLUDE_FROM_BOM", "FP_EXCLUDE_FROM_POS_FILES", "FP_BOARD_ONLY"):
        attrs |= getattr(pcbnew, attr, 0)
    fp.SetAttributes(attrs)

    for seg_mm in segments:
        _add_segment(fp, layer_id, seg_mm, stroke_mm)
    for center_mm, radius_mm in dots:
        _add_filled_circle(fp, layer_id, center_mm, radius_mm)
    return fp


def _new_shape(fp, shape_t):
    """A fresh footprint graphic of type ``shape_t``, parented to ``fp`` but
    not yet added to it (boardshapes.new_shape, which the area marker's
    board-level shapes come from as well)."""
    return boardshapes.new_shape(fp, shape_t)


def _shape_items(fp, shape_t):
    """A footprint's graphics of one shape type, in draw order -- duck-typed
    on ``GetShape`` so text and other non-shape items drop out. Empty for a
    ``shape_t`` of None (a build with neither enum name)."""
    if shape_t is None:
        return []
    items = []
    for item in fp.GraphicalItems():
        shape = getattr(item, "GetShape", None)
        if shape is not None and shape() == shape_t:
            items.append(item)
    return items


def _add_segment(fp, layer_id, seg_mm, stroke_mm):
    """Add one line-segment graphic to ``fp`` on ``layer_id``. ``seg_mm`` is
    an ((x0, y0), (x1, y1)) pair in KiCad mm, in the frame the footprint
    currently sits in -- board coordinates for a placed footprint,
    footprint-local for one still being built at origin (_build_footprint).
    Shared by both, the KiCad-6 FP_SHAPE local-coordinate sync included (the
    geometry itself goes in through boardshapes.set_segment, the writer the
    area marker's board-level shapes use too)."""
    seg = _new_shape(fp, boardshapes.shape_type_id("SHAPE_T_SEGMENT", "S_SEGMENT"))
    boardshapes.set_segment(seg, layer_id, seg_mm, stroke_mm)
    fp.Add(seg)
    return seg


def _add_filled_circle(fp, layer_id, center_mm, radius_mm):
    """Add one solid-filled circle graphic to ``fp`` on ``layer_id`` -- a
    marker's feed-point dot (markergeom.arrow_dot). ``center_mm`` is an
    (x, y) in KiCad mm, in the frame the footprint currently sits in (see
    _add_segment). The outline stroke is zero-width so the drawn dot is
    exactly ``radius_mm``."""
    circle = _new_shape(fp, boardshapes.shape_type_id("SHAPE_T_CIRCLE", "S_CIRCLE"))
    _rewrite_filled_circle(circle, layer_id, center_mm, radius_mm)
    fp.Add(circle)
    return circle


def _rewrite_filled_circle(circle, layer_id, center_mm, radius_mm):
    """Rewrite an existing filled-circle graphic (_add_filled_circle) to a
    fresh centre/radius on ``layer_id``, in place -- a marker reshaped by the
    sliders moves its feed-point dot with the arrow. In place for the same
    reason every other marker shape is (see _rewrite_filled_poly).

    The geometry goes in through boardshapes.set_filled_circle, which spells
    out how a circle is stored and is the same writer the area marker's own
    feed-point dot is written with."""
    return boardshapes.set_filled_circle(circle, layer_id, center_mm, radius_mm)


def _add_filled_poly(fp, layer_id, points_mm):
    """Add one solid-filled polygon graphic to ``fp`` on ``layer_id``.
    ``points_mm`` is a list of (x, y) corners in KiCad mm, in the frame the
    footprint currently sits in (board coordinates for a placed footprint --
    the wizard's antenna preview, preview.draw). The outline stroke is
    zero-width so only the fill shows."""
    poly = _new_shape(fp, boardshapes.shape_type_id("SHAPE_T_POLYGON", "S_POLYGON"))
    _rewrite_filled_poly(poly, layer_id, points_mm)
    fp.Add(poly)
    return poly


def _rewrite_filled_poly(poly, layer_id, points_mm):
    """Rewrite an existing filled-polygon graphic (_add_filled_poly) to fresh
    corners on ``layer_id``, in place — the wizard's antenna preview redrawn
    for another candidate (preview.draw).

    In place for the same reason a marker's own segments are rewritten rather
    than replaced (_rewrite_marker): once the board has been saved and
    reloaded, these shapes are KiCad's, and unlinking one is a use-after-free
    (see _detach_item). Reusing a shape keeps every pointer to it valid. The
    corners go in through boardshapes.set_filled_poly."""
    return boardshapes.set_filled_poly(poly, layer_id, points_mm)


def make_footprint(board, layer_id, width_mm):
    """Build the feed-marker footprint (not yet added to the board)."""
    return _build_footprint(
        board,
        MARKER_NAME,
        "FEED",
        layer_id,
        _local_segments(width_mm),
        LINE_STROKE_MM,
        _local_dots(width_mm),
    )


def check_layer(board, user_n):
    """The pcbnew layer id for User.``n``, raising when this board doesn't
    have that layer enabled."""
    layer_id = user_layer_id(user_n)
    if layer_id is None or not board.IsLayerEnabled(layer_id):
        raise RuntimeError(
            f"layer User.{user_n} is not enabled on this board -- enable it "
            "in Board Setup > Board Editor Layers, or pick another layer"
        )
    return layer_id


def footprints_named(board, name):
    """Every placed footprint whose LIB_ID item name is ``name``, in board
    order — the finder shared by the plugin's markers (the feed marker here,
    the wizard's area marker in area_marker.py)."""
    return [
        fp for fp in board.GetFootprints() if str(fp.GetFPID().GetLibItemName()) == name
    ]


def marker_footprints(board):
    """Every placed feed-marker footprint, in board order."""
    return footprints_named(board, MARKER_NAME)


# The name the GUI's two marker sections look their markers up by
# (sections.marker.FeedMarkerSection._markers): this marker is footprints, the
# area marker is groups of board shapes, and the seam is one function name.
placed_markers = marker_footprints


def pasted_as_text(board):
    """The plain-text item a degraded paste left on the board, or None.

    When an asynchronous clipboard manager hands KiCad stale or truncated
    content, the paste's s-expression parse fails and KiCad 9 falls back to
    dropping the raw clipboard text as a PCB_TEXT — the marker appears on
    the board as its own source text. Finding it tells the GUI to stop
    fighting the clipboard and place through the API instead (the text item
    itself is the user's to delete: it came from KiCad's paste tool, so the
    selection/undo stack may point at it — same rule as for footprints)."""
    import pcbnew

    for item in board.GetDrawings():
        if isinstance(item, pcbnew.PCB_TEXT) and item.GetText().lstrip().startswith(
            f'(footprint "{MARKER_NAME}"'
        ):
            return item
    return None


def _rewrite_marker(fp, segments, dots=(), layer_id=None):
    """Rewrite a placed marker's segments and feed-point dots to fresh local
    geometry, in place.
    The footprint is never removed and re-added: it was placed by KiCad's own
    paste tool, so the editor's selection and undo stack may still hold
    pointers to it, and ``board.Remove`` from a plugin turns those into a
    use-after-free crash. Mutating the geometry keeps every pointer valid.
    ``layer_id`` moves the shapes to another layer (None keeps each where
    it is). Returns the marker's (x, y) in KiCad mm.

    The footprint is squared to 0° while the fresh local coordinates are
    written, then KiCad's own SetOrientationDegrees rotates them back into
    place — no home-grown angle math (whose sign convention differs between
    KiCad versions)."""
    import pcbnew

    from ..kicad.compat import vec2

    segs = _marker_segments(fp)
    if len(segs) != len(segments):
        raise RuntimeError(
            "the placed marker was edited and can't be regenerated in "
            "place; delete it and generate a new one"
        )
    orient = fp.GetOrientationDegrees()
    fp.SetOrientationDegrees(0)
    pos = fp.GetPosition()
    for seg, ((x0, y0), (x1, y1)) in zip(segs, segments):
        if layer_id is not None:
            seg.SetLayer(layer_id)
        seg.SetStart(vec2(pos.x + pcbnew.FromMM(x0), pos.y + pcbnew.FromMM(y0)))
        seg.SetEnd(vec2(pos.x + pcbnew.FromMM(x1), pos.y + pcbnew.FromMM(y1)))
        if hasattr(seg, "SetLocalCoord"):  # KiCad 6 FP_SHAPE keeps local pts
            seg.SetLocalCoord()
    _rewrite_dots(
        fp, dots, (pcbnew.ToMM(int(pos.x)), pcbnew.ToMM(int(pos.y))), layer_id
    )
    fp.SetOrientationDegrees(orient)
    return (round(pcbnew.ToMM(int(pos.x)), 3), round(pcbnew.ToMM(int(pos.y)), 3))


def _rewrite_dots(fp, dots, origin_mm, layer_id=None):
    """Rewrite a placed marker's feed-point dots to fresh local geometry, the
    footprint squared to 0 degrees and its position at ``origin_mm`` (KiCad
    mm) -- the dot half of _rewrite_marker, which owns that orientation dance.

    Dots already on the marker are reused and only the surplus is detached,
    the rule every marker shape follows (see _detach_item); a marker drawn
    before the dot existed simply has one added."""
    ox, oy = origin_mm
    dots, drawn = list(dots), _circle_items(fp)
    for circle, ((x, y), radius) in zip(drawn, dots):
        _rewrite_filled_circle(
            circle,
            circle.GetLayer() if layer_id is None else layer_id,
            (ox + x, oy + y),
            radius,
        )
    if len(dots) > len(drawn):  # a marker drawn before the dot existed
        layer = marker_layer_id(fp) if layer_id is None else layer_id
        for (x, y), radius in dots[len(drawn) :]:
            _add_filled_circle(fp, layer, (ox + x, oy + y), radius)
    for circle in drawn[len(dots) :]:
        _detach_item(fp, circle)


def _detach_item(fp, item):
    """Take one graphic off a placed footprint, leaking the C++ object rather
    than letting it be freed — the only safe way for a plugin to drop a graphic
    while the PCB editor is live.

    ``FOOTPRINT::Remove`` merely unlinks the item; the SWIG proxy then owns the
    C++ object and frees it as soon as Python drops the last reference. For a
    graphic KiCad itself loaded with the board — the wizard's antenna preview,
    saved with it — the editor's view, the connectivity graph,
    the selection and the undo stack all still hold raw pointers to it, so that
    free is exactly the use-after-free ``_rewrite_marker`` exists to avoid
    (a preview redrawn from the sliders in one session is the plugin's own and
    survived it; one reloaded off the board did not). Clearing ``thisown``
    orphans the object instead: those pointers stay valid, and the next
    ``pcbnew.Refresh()`` rebuilds the view without it.

    The cost is a leaked shape (a few hundred bytes) until KiCad closes, so
    callers reuse what they can instead — ``preview.draw`` rewrites every
    preview shape it can (_rewrite_filled_poly) and only comes here for the
    surplus a shorter candidate leaves behind."""
    fp.Remove(item)
    try:
        item.thisown = False
    except AttributeError:  # a binding that never handed ownership over
        pass
    return item


def _detach_footprint(board, fp):
    """Take one whole footprint off the board the way _detach_item takes a
    graphic off a footprint: unlinked, but never freed.

    This is for the plugin's own throwaway drawing — the wizard's antenna
    preview (preview.clear), which the plugin writes and nothing else does. A
    footprint the *user* put on the board is never removed by the plugin: the
    marker footprints are reshaped in place instead (_rewrite_marker), and
    deleting one is the user's own Del.

    The one exception is the conversion of an area marker an older plugin drew
    as a single footprint (legacy/area_marker_v1.py), which comes here for the
    old marker: it has just been replaced, drawing for drawing, by the group
    that took its place, so nothing the user drew is lost — and two markers
    where they have one would be worse than none.

    ``board.Remove`` unlinks the footprint and hands the C++ object to the SWIG
    proxy, which frees it as soon as Python lets go — and the editor's view,
    selection and undo stack may all still point at a footprint KiCad loaded
    with the board. Clearing ``thisown`` orphans it instead: those pointers stay
    valid, the next ``pcbnew.Refresh()`` rebuilds the view without it, and the
    cost is a leaked footprint until KiCad closes."""
    board.Remove(fp)
    try:
        fp.thisown = False
    except AttributeError:  # a binding that never handed ownership over
        pass
    return fp


def update_marker(fp, layer_id, width_mm):
    """Rewrite an existing feed marker's segments and feed-point dot to the
    new width/layer, in place (see _rewrite_marker). Position and rotation are
    kept; a marker drawn before the dot existed gains one."""
    return _rewrite_marker(
        fp, _local_segments(width_mm), _local_dots(width_mm), layer_id
    )


def _drop_at_center(board, fp):
    """Add ``fp`` to the board at its bounding-box center — the fallback when
    the clipboard/cursor placement path is unavailable. Returns the (x, y)
    position in KiCad mm for the log."""
    import pcbnew

    from ..kicad.compat import vec2

    bbox = board.GetBoundingBox()
    pos = vec2(bbox.GetX() + bbox.GetWidth() // 2, bbox.GetY() + bbox.GetHeight() // 2)
    board.Add(fp)
    fp.SetPosition(pos)
    pcbnew.Refresh()
    return (round(pcbnew.ToMM(int(pos.x)), 3), round(pcbnew.ToMM(int(pos.y)), 3))


def place_marker(board, user_n, width_mm):
    """Create the feed-marker footprint at the board's bounding-box center —
    the fallback when the clipboard/cursor path is unavailable. Only called
    with no marker on the board; regenerating an existing one goes through
    update_marker instead (never remove + re-add)."""
    layer_id = check_layer(board, user_n)
    return _drop_at_center(board, make_footprint(board, layer_id, width_mm))


def _segment_items(fp):
    """A marker footprint's line-segment items on User layers, in draw order
    -- the marker drawing itself (its geometry is read back and reshaped as
    line segments). The feed-point dot is a circle, so it never lands here."""
    user_ids = {user_layer_id(n) for n in range(1, 10)} - {None}
    seg_t = boardshapes.shape_type_id("SHAPE_T_SEGMENT", "S_SEGMENT")
    return [item for item in _shape_items(fp, seg_t) if item.GetLayer() in user_ids]


def _filled_poly_items(fp):
    """A footprint's filled-polygon graphics, in draw order -- the wizard's
    antenna preview (preview.items), and nothing else the plugin draws as a
    polygon.

    Selected by shape rather than by layer, because the preview moves between
    layers: copper while the candidate fits the area, the area marker's own
    User layer while it doesn't (preview.draw). A marker's own drawing is line
    segments, so a stray polygon on one is never taken for marker geometry
    whichever layer it is on."""
    return _shape_items(fp, boardshapes.shape_type_id("SHAPE_T_POLYGON", "S_POLYGON"))


def _circle_items(fp):
    """A marker footprint's filled-circle graphics, in draw order -- its
    feed-point dot(s) (_add_filled_circle), and nothing else the plugin draws
    as a circle. Selected by shape like _filled_poly_items, so it never picks
    up the marker's own line segments or the wizard's antenna preview."""
    return _shape_items(fp, boardshapes.shape_type_id("SHAPE_T_CIRCLE", "S_CIRCLE"))


def _marker_segments(fp):
    """A marker footprint's segment items on User layers, as drawn (the two
    base halves, the two triangle slopes and the stem on a healthy marker).
    The feed-point dot is a circle, so it stays out of the decode."""
    return _segment_items(fp)


def _segment_points_mm(fp):
    """A marker footprint's User-layer segments as ((x0,y0),(x1,y1)) mm
    pairs in board coordinates, ready for _decode_segments."""
    import pcbnew

    pts = []
    for item in _marker_segments(fp):
        s, e = item.GetStart(), item.GetEnd()
        pts.append(
            (
                (pcbnew.ToMM(int(s.x)), pcbnew.ToMM(int(s.y))),
                (pcbnew.ToMM(int(e.x)), pcbnew.ToMM(int(e.y))),
            )
        )
    return pts


def marker_layer_id(fp):
    """The pcbnew layer id a placed marker's segments are drawn on, or None
    when it has none. The area marker's is also where the wizard draws a
    candidate that doesn't fit (area_marker.marker_layer)."""
    segs = _marker_segments(fp)
    return segs[0].GetLayer() if segs else None


def marker_layer_name(fp):
    """The ``User.N`` name of the layer a placed marker's segments sit on, or
    None when it has no segments or they're off the User layers. Shared by the
    feed marker (describe_marker) and the area marker (area_marker.py)."""
    layer = marker_layer_id(fp)
    return (
        None
        if layer is None
        else next(
            (f"User.{n}" for n in range(1, 10) if user_layer_id(n) == layer), None
        )
    )


def describe_marker(fp):
    """Human-readable facts about a placed marker, for the GUI status line:
    position in KiCad mm, its ``User.N`` layer name (None when off the User
    layers), and the decoded width (None when the marker was edited and no
    longer decodes)."""
    import pcbnew

    pos = fp.GetPosition()
    layer = marker_layer_name(fp)
    width = None
    try:
        _, _, width, _, _ = _decode_segments(_segment_points_mm(fp))
    except ValueError:
        pass
    return {
        "x_mm": round(pcbnew.ToMM(int(pos.x)), 2),
        "y_mm": round(pcbnew.ToMM(int(pos.y)), 2),
        "layer": layer,
        "width_mm": width,
    }


def find_markers(board):
    """Decode every placed feed-marker footprint into a feed dict:
    ``{"x_mm", "y_mm", "width_mm", "dir_x", "dir_y"}`` in gerber coordinates
    (KiCad mm with Y negated -- the direction too), everything the explicit
    feed_ports entry needs (see feed_dict)."""
    found = []
    for fp in marker_footprints(board):
        try:
            x, y, width, dx, dy = _decode_segments(_segment_points_mm(fp))
        except ValueError as exc:
            ref = fp.GetReference() or MARKER_NAME
            raise RuntimeError(f"{ref}: {exc}") from exc
        found.append(
            {
                "x_mm": round(x, 4),
                "y_mm": round(-y, 4),
                "width_mm": round(width, 4),
                "dir_x": round(dx, 4),
                "dir_y": round(-dy, 4),
            }
        )
    return found


def feed_dict(marker):
    """The feed for ``config.write_yaml`` (``params['feed']``) built from a
    decoded marker (a find_markers dict, already gerber mm): the arrow's base
    centre and the direction it points (the runner infers the trace and severs
    a one-cell gap on the grid, so the drawn width is visual). See
    markergeom.explicit_feed, the shared builder the wizard also
    uses."""
    return markergeom.explicit_feed(
        marker["x_mm"], marker["y_mm"], marker["dir_x"], marker["dir_y"]
    )


def single_marker(board):
    """The one placed marker's feed dict (see find_markers), or None when
    the board has none. The more-than-one error lives here so every caller
    reports it the same way."""
    markers = find_markers(board)
    if len(markers) > 1:
        raise RuntimeError(
            "multiple feed-marker footprints found; keep only one -- the "
            "run simulates a single port"
        )
    return markers[0] if markers else None
