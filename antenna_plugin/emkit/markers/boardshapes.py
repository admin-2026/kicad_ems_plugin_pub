"""Board-level graphics and groups: what a marker is made of when it is not a
footprint.

The feed marker is a footprint, and its shapes are the footprint's own
(feed_marker.py). The area marker is not: its rectangle has to be *draggable*,
and KiCad's point editor only ever offers handles on board-level items — a
graphic inside a placed footprint has none. So the area marker is a board-level
``PCB_SHAPE`` rectangle plus its feed arrow, held together by a ``PCB_GROUP``
whose name identifies it the way a LIB_ID item name identifies the footprint
markers.

This module is the pcbnew side of that: making board shapes and groups,
writing a shape's geometry, and reading one back as the
``((x0, y0), (x1, y1))`` mm segment pairs both markers decode from
(``outline_segments_mm`` — a rectangle answers its four sides, so a dragged
rectangle decodes through exactly the same geometry as a drawn one). The shape
*writers* are shared with the footprint markers, which parent the same
PCB_SHAPE class to a footprint instead of to the board; only the parenting and
the group handling are new here.

Everything imports pcbnew lazily, so the modules above stay importable — and
their pure geometry testable — off KiCad.
"""

# Shape kinds by a stable short name, as (KiCad 6+ enum, older enum) pairs:
# the enum was renamed SHAPE_T_* from S_*, and a marker has to be readable on
# either build.
_KIND_ENUMS = {
    "seg": ("SHAPE_T_SEGMENT", "S_SEGMENT"),
    "rect": ("SHAPE_T_RECT", "S_RECT"),
    "circle": ("SHAPE_T_CIRCLE", "S_CIRCLE"),
    "arc": ("SHAPE_T_ARC", "S_ARC"),
    "poly": ("SHAPE_T_POLYGON", "S_POLYGON"),
}


def shape_type_id(new_name, old_name):
    """A PCB_SHAPE shape-type enum on this KiCad build, by its modern name
    (``SHAPE_T_*``, KiCad 6+) with the older ``S_*`` spelling as fallback.
    Compared against None rather than trusted for truth: the first enum value
    is 0. Returns None when the build has neither name."""
    import pcbnew

    shape_t = getattr(pcbnew, new_name, None)
    return shape_t if shape_t is not None else getattr(pcbnew, old_name, None)


def kind_ids():
    """The shape-type enums this module names, keyed by short name (see
    _KIND_ENUMS). A build missing one maps it to None, which ``kind_of`` then
    never matches -- an unknown shape is reported as unknown rather than
    mistaken for the first kind."""
    return {k: shape_type_id(*names) for k, names in _KIND_ENUMS.items()}


def kind_of(shape, ids=None):
    """The short kind name of ``shape`` ("rect", "seg", ...), or None for a
    shape kind this module doesn't name -- or an item that isn't a shape at
    all (duck-typed on ``GetShape``, the way the footprint markers pick their
    graphics out: the class is FP_SHAPE on KiCad 6/7 and PCB_SHAPE from 8 on).
    Pass ``ids`` to reuse one ``kind_ids()`` reading across a whole walk."""
    getter = getattr(shape, "GetShape", None)
    if getter is None:
        return None
    st = getter()
    for name, enum in (ids or kind_ids()).items():
        if enum is not None and st == enum:
            return name
    return None


# --------------------------------------------------------------------------- #
# Making and writing shapes
# --------------------------------------------------------------------------- #
def new_shape(parent, shape_t):
    """A fresh graphic of type ``shape_t``, parented to ``parent`` (a board or
    a footprint) but not yet added to it. The class is FP_SHAPE on KiCad 6/7
    and PCB_SHAPE from 8 on for a footprint's graphics; a board's are always
    PCB_SHAPE."""
    import pcbnew

    shape_cls = getattr(pcbnew, "FP_SHAPE", None) or pcbnew.PCB_SHAPE
    if _is_board(parent):
        shape_cls = pcbnew.PCB_SHAPE
    shape = shape_cls(parent)
    shape.SetShape(shape_t)
    return shape


def _is_board(parent):
    """Whether ``parent`` is the board itself rather than a footprint. A
    binding that doesn't expose ``BOARD`` answers no, which lands on the
    footprint class -- the only parent such a build ever has here."""
    import pcbnew

    board_cls = getattr(pcbnew, "BOARD", None)
    return board_cls is not None and isinstance(parent, board_cls)


def add_shape(board, kind):
    """A fresh board-level graphic of ``kind`` (a _KIND_ENUMS short name),
    added to ``board``. Raises when this KiCad build doesn't name that kind --
    which would otherwise leave an untyped shape on the user's board."""
    shape_t = shape_type_id(*_KIND_ENUMS[kind])
    if shape_t is None:
        raise RuntimeError(
            f"this KiCad build has no {kind} graphic type; the area marker "
            "cannot be drawn on it"
        )
    shape = new_shape(board, shape_t)
    board.Add(shape)
    return shape


def set_segment(shape, layer_id, seg_mm, stroke_mm):
    """Write a line segment into ``shape``: ``seg_mm`` is an
    ``((x0, y0), (x1, y1))`` pair in KiCad mm, in the frame the shape's parent
    sits in (board coordinates for a board shape, footprint-local for one
    being built at a footprint's origin). ``layer_id`` of None leaves the shape
    on the layer it is already on."""
    import pcbnew

    from ..kicad.compat import vec2

    (x0, y0), (x1, y1) = seg_mm
    shape.SetStart(vec2(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
    shape.SetEnd(vec2(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    if layer_id is not None:
        shape.SetLayer(layer_id)
    shape.SetWidth(pcbnew.FromMM(stroke_mm))
    _sync_local(shape)
    return shape


def set_rect(shape, layer_id, rect_mm, stroke_mm):
    """Write an unfilled rectangle into ``shape``: ``rect_mm`` is
    ``(x0, y0, x1, y1)`` in KiCad mm (Y down), stored as KiCad stores one --
    two opposite corners, which is what gives the placed shape its four drag
    handles."""
    import pcbnew

    from ..kicad.compat import vec2

    x0, y0, x1, y1 = rect_mm
    shape.SetStart(vec2(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
    shape.SetEnd(vec2(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    if layer_id is not None:
        shape.SetLayer(layer_id)
    shape.SetFilled(False)
    shape.SetWidth(pcbnew.FromMM(stroke_mm))
    _sync_local(shape)
    return shape


def set_outline_poly(shape, layer_id, points_mm, stroke_mm):
    """Write an unfilled polygon outline into ``shape`` — the marker rectangle
    once it has been turned off a cardinal angle, where KiCad's own rectangle
    cannot follow (a PCB_SHAPE rectangle is two opposite corners, so it is
    always axis-aligned). Same drawing as ``set_rect``, four corners instead of
    two, and the same handle on every corner."""
    import pcbnew

    from ..kicad.compat import vec2

    shape.SetPolyPoints(
        [vec2(pcbnew.FromMM(x), pcbnew.FromMM(y)) for (x, y) in points_mm]
    )
    if layer_id is not None:
        shape.SetLayer(layer_id)
    shape.SetFilled(False)
    shape.SetWidth(pcbnew.FromMM(stroke_mm))
    _sync_local(shape)
    return shape


def become(shape, kind):
    """Turn an existing graphic into another ``kind`` (a _KIND_ENUMS short
    name) in place, so the caller can write the other kind's geometry into it.

    In place, and never a fresh shape: a graphic KiCad loaded with the board is
    KiCad's, and unlinking one from a plugin is a use-after-free
    (feed_marker._detach_item spells the rule out). The area marker's rectangle
    goes back and forth this way — a rectangle while it sits on the grid, a
    polygon once it is turned off one — and stays the same item across both, so
    the group, the selection and the undo stack keep pointing at something
    real. A no-op when the shape is already that kind, and a plain refusal on a
    build that doesn't name it."""
    shape_t = shape_type_id(*_KIND_ENUMS[kind])
    if shape_t is None:
        raise RuntimeError(
            f"this KiCad build has no {kind} graphic type; the area marker "
            "cannot be drawn on it"
        )
    if shape.GetShape() != shape_t:
        shape.SetShape(shape_t)
    return shape


def set_filled_circle(shape, layer_id, center_mm, radius_mm):
    """Write a solid-filled circle into ``shape`` -- a marker's feed-point dot.
    A circle is stored as its centre plus a point on it, so the radius goes in
    as an end point ``radius_mm`` to the right of the centre; rotating the
    placed shape leaves both correct. The outline stroke is zero-width, so the
    drawn dot is exactly ``radius_mm``."""
    import pcbnew

    from ..kicad.compat import vec2

    (x, y) = center_mm
    shape.SetStart(vec2(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    shape.SetEnd(vec2(pcbnew.FromMM(x + radius_mm), pcbnew.FromMM(y)))
    if layer_id is not None:
        shape.SetLayer(layer_id)
    shape.SetFilled(True)
    shape.SetWidth(0)
    _sync_local(shape)
    return shape


def set_filled_poly(shape, layer_id, points_mm):
    """Write a solid-filled polygon into ``shape`` -- the wizard's antenna
    preview (preview.draw). ``points_mm`` is a list of (x, y) corners in KiCad
    mm; the outline stroke is zero-width so only the fill shows."""
    import pcbnew

    from ..kicad.compat import vec2

    shape.SetPolyPoints(
        [vec2(pcbnew.FromMM(x), pcbnew.FromMM(y)) for (x, y) in points_mm]
    )
    if layer_id is not None:
        shape.SetLayer(layer_id)
    shape.SetFilled(True)
    shape.SetWidth(0)
    _sync_local(shape)
    return shape


def _sync_local(shape):
    """KiCad 6's FP_SHAPE keeps a footprint-local copy of the points beside the
    board-frame ones; writing the board frame means telling it to re-derive
    that copy. Board shapes have no local frame and no such method."""
    if hasattr(shape, "SetLocalCoord"):
        shape.SetLocalCoord()


# --------------------------------------------------------------------------- #
# Reading shapes back
# --------------------------------------------------------------------------- #
def _mm(pt):
    import pcbnew

    return (pcbnew.ToMM(int(pt.x)), pcbnew.ToMM(int(pt.y)))


def outline_segments_mm(shape, ids=None):
    """``shape`` as ``((x0, y0), (x1, y1))`` mm segment pairs in board
    coordinates -- the one form the markers decode from (markergeom).

    A segment answers itself; a rectangle answers its four sides, walked from
    the min-Y/min-X corner, so a rectangle the user resized by dragging a
    handle decodes through the same code as one the plugin drew; a polygon
    answers its closed outline, which is what KiCad turns a rectangle into
    when it is rotated off a cardinal angle. Anything else (a circle -- the
    feed-point dot -- or an arc) answers nothing: it carries no marker
    geometry."""
    kind = kind_of(shape, ids)
    if kind == "seg":
        return [(_mm(shape.GetStart()), _mm(shape.GetEnd()))]
    if kind == "rect":
        return _closed(rect_corners_mm(shape))
    if kind == "poly":
        return _closed(poly_points_mm(shape))
    return []


def _closed(points):
    """The closed outline through ``points`` as consecutive mm segment pairs
    (the last point joins back to the first). Fewer than three points enclose
    nothing and give no segments."""
    if len(points) < 3:
        return []
    return [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]


def rect_corners_mm(shape):
    """A rectangle graphic's four corners in KiCad mm, clockwise from the
    min-X/min-Y one (top-left in KiCad's Y-down frame). KiCad stores the
    rectangle as two opposite corners and does not promise which two, so they
    are sorted rather than trusted."""
    a, b = _mm(shape.GetStart()), _mm(shape.GetEnd())
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def poly_points_mm(shape):
    """A polygon graphic's outer outline as (x, y) mm vertices, or an empty
    list when this build's SHAPE_POLY_SET binding won't answer (the caller
    then reports a marker it cannot read, which is the truth)."""
    try:
        sps = shape.GetPolyShape()
        chain = sps.Outline(0)
        return [_mm(chain.CPoint(i)) for i in range(chain.PointCount())]
    except Exception:
        return []


def circle_center_mm(shape):
    """A circle graphic's centre in KiCad mm (its stored start point)."""
    return _mm(shape.GetStart())


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #
def new_group(board, name):
    """A fresh, empty ``PCB_GROUP`` named ``name``, added to ``board``. The
    name is the group's identity to the plugin, the way a LIB_ID item name is a
    marker footprint's (feed_marker.footprints_named): it is what
    ``groups_labelled`` finds again on the next launch. KiCad also *draws* it
    over the group, so it is a caption as well as an identity."""
    import pcbnew

    group_cls = getattr(pcbnew, "PCB_GROUP", None)
    if group_cls is None:  # a binding with no groups at all (pre-KiCad 6)
        raise RuntimeError(
            "this KiCad build has no board groups, which the area marker is "
            "made of; KiCad 6 or newer is required"
        )
    group = group_cls(board)
    group.SetName(name)
    board.Add(group)
    return group


def groups_labelled(board, prefix):
    """Every group on ``board`` whose name starts with ``prefix``, in board
    order.

    Starts-with rather than equals because KiCad draws a group's name on the
    canvas: the plugin's marker carries a caption after its identity
    (area_marker.GROUP_NAME), so the name is a label the user reads and the
    prefix is the part that means "this is ours". Rewording the caption then
    doesn't orphan every marker already on a board.

    A build whose binding has no ``Groups()`` answers none -- the caller then
    behaves as it does on a board with no marker, rather than raising at the
    user."""
    getter = getattr(board, "Groups", None)
    if getter is None:
        return []
    try:
        groups = list(getter())
    except Exception:
        return []
    return [g for g in groups if str(g.GetName()).startswith(prefix)]


def group_items(group):
    """A group's member items, in a stable order.

    ``PCB_GROUP::GetItems`` answers an unordered set, so the order KiCad hands
    them back in is not the order they were added: sorting by KIID keeps a
    marker's shapes in one order across calls, which is what makes a rewrite
    land on the same shape twice running. Nothing here depends on *which*
    order it is -- the marker's parts are told apart by what they are, not by
    where they sit in this list."""
    try:
        items = list(group.GetItems())
    except Exception:
        return []
    return sorted(items, key=_kiid_of)


def _kiid_of(item):
    """A board item's KIID as a string, for a stable sort. Through
    ``AsString()`` where the binding offers it: ``str()`` on the KIID proxy
    itself would be the proxy's own repr -- a fresh object, and so a fresh
    address, every time GetItems() is called, which is the opposite of
    stable."""
    uuid = getattr(item, "m_Uuid", None)
    as_string = getattr(uuid, "AsString", None)
    return str(as_string()) if as_string is not None else str(uuid)


def add_to_group(group, item):
    """Put ``item`` (already on the board) into ``group``."""
    group.AddItem(item)
    return item


def group_position_mm(group):
    """A group's position in KiCad mm -- the middle of what it holds, which is
    what the status line means by "where the marker is"."""
    import pcbnew

    pos = group.GetPosition()
    return (round(pcbnew.ToMM(int(pos.x)), 3), round(pcbnew.ToMM(int(pos.y)), 3))
