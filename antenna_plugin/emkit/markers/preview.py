"""Antenna-preview footprint: the candidate the wizard draws on the board.

The preview is the shape the Scan section's rows describe right now, drawn as
solid filled polygons — the candidate's own copper — on the feed copper layer
while the candidate fits the marked area, on the area marker's own User layer while
it doesn't (the antenna hanging out of the rectangle, in the marker's colour,
rather than nothing at all). It is a sketch: nothing has been simulated and no
footprint has been placed, so what is drawn here is never the antenna's real
copper — the footprint section's is (design/footprints.py).

``draw`` takes one group of polygons per layer, because an antenna is not
always all on one: a design that radiates against a ground plane sketches that
plane too, on the layer the wizard was told carries it. One footprint holds the
lot, so the whole sketch is one thing to click, to redraw and to clear.

It is its **own** board_only footprint (``AntennaPreview``), separate from the
area marker it is solved against (area_marker.py). Two drawings the user reads
as two things are two things on the board: click the preview to select the
preview, press Del on it to lose the sketch and keep the area, press Del on the
marker to lose the area and keep the sketch. (The wizard redraws the preview
whenever the area changes — a scan row moved, or the marker found dragged into
a new shape — so a marker that moves takes the sketch with it a moment later,
without the two ever being one item.)

The preview is redrawn constantly — every scan-row nudge — so the shapes on it
are **reused**, rewritten in place rather than replaced: once the board has
been saved and reloaded they are KiCad's, and unlinking one from a plugin frees
an object the editor still points at (feed_marker._detach_item spells out the
whole rule). Only the surplus a shorter candidate leaves over is detached, and
the footprint itself only when the preview is cleared for good — through
feed_marker._detach_footprint, which leaks it for the same reason.

Coordinates are KiCad mm, Y down, in the board frame: the drawn polygons come
from design.geometry.Geometry.preview_polys already rotated onto the board, so
the footprint is squared to 0 degrees and anchored at the middle of what it
carries (_anchor) and every shape is written where it lands.
"""

from . import feed_marker

# Footprint id (LIB_ID item name) the wizard generates and looks for.
PREVIEW_NAME = "AntennaPreview"
_REFERENCE = "PREVIEW"


# --------------------------------------------------------------------------- #
# Pure geometry
# --------------------------------------------------------------------------- #
def _center_mm(rects):
    """The middle of the drawn rectangles' bounding box in KiCad mm, or None
    for nothing drawn -- where the preview footprint is anchored (_anchor), so
    its origin sits on the sketch instead of somewhere off the board."""
    pts = [pt for corners in rects for pt in corners]
    if not pts:
        return None
    xs, ys = [x for (x, _) in pts], [y for (_, y) in pts]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


# --------------------------------------------------------------------------- #
# Board-facing (pcbnew imported lazily downstream)
# --------------------------------------------------------------------------- #
def preview_footprints(board):
    """Every placed antenna-preview footprint, in board order. More than one
    means the user duplicated it: the wizard redraws the first and ``clear``
    takes them all off."""
    return feed_marker.footprints_named(board, PREVIEW_NAME)


def exists(board):
    """Whether the board carries a preview at all -- what tells the wizard,
    reopened on a board somebody previewed a candidate on yesterday, that a
    redraw is wanted (ScanSection.refresh_preview)."""
    return bool(preview_footprints(board))


def items(fp):
    """A preview footprint's drawn shapes: its filled polygons, in draw order
    (feed_marker._filled_poly_items). Found by shape rather than by layer,
    because the preview moves between the feed copper layer and the marker's
    own User layer as the candidate starts and stops fitting the area."""
    return feed_marker._filled_poly_items(fp)


def _new_footprint(board):
    """A fresh, empty preview footprint, added to the board at its origin.
    Anchored and filled by ``draw`` -- there is nothing to anchor it to until
    the shapes are known."""
    fp = feed_marker._build_footprint(
        board, PREVIEW_NAME, _REFERENCE, None, (), 0.0, ()
    )
    board.Add(fp)
    return fp


def _anchor(fp, rects):
    """Square the preview footprint to 0 degrees and move its origin to the
    middle of what it is about to carry, so the shapes below can be written
    straight in board coordinates (the frame ``draw`` is handed) and the
    footprint's own anchor sits on the drawing the user clicks.

    Both moves carry the shapes already on the footprint along with them --
    that is FOOTPRINT::SetPosition's whole job -- which is exactly why they
    come first: every shape is rewritten right after, from board coordinates
    the move cannot disturb."""
    import pcbnew

    from ..kicad.compat import vec2

    if fp.GetOrientationDegrees():
        fp.SetOrientationDegrees(0)
    center = _center_mm(rects)
    if center is not None:
        fp.SetPosition(vec2(pcbnew.FromMM(center[0]), pcbnew.FromMM(center[1])))


def draw(board, layers):
    """Draw (or redraw) the wizard's antenna preview on ``board``: ``layers``
    is a sequence of ``(layer_id, polys_mm)`` groups -- board-frame KiCad mm
    corner lists (design.geometry.Geometry.preview_polys) drawn as solid filled
    polygons on that layer, so the preview reads as the copper the footprint
    would place. The caller hands over the shapes rather than a centerline and
    a width because the copper is the design's own arithmetic: which piece is a
    millimetre of track and which is a patch tens of millimetres across is
    something only it knows (geometry.Path.width). Returns the preview
    footprint, creating it the first time -- or None for a candidate with
    nothing to draw at all, which clears instead: an empty footprint would be
    an invisible item to click and to save.

    The candidate's own layer is the feed copper layer while it fits the area
    and the area marker's own User layer (area_marker.marker_layer) while it
    doesn't: the same drawing either way, but only real metal is ever drawn as
    metal -- an antenna hanging out of the rectangle is a sketch, not copper
    anyone would fabricate. More than one group is for an antenna that is not
    all on one layer: a design radiating against a ground plane sketches that
    plane on the layer carrying it, and the two halves are one preview, drawn,
    clicked and cleared together.

    A redraw **reuses the shapes already on the footprint**, rewriting each in
    place (feed_marker._rewrite_filled_poly): a preview that was saved with the
    board and loaded back is KiCad's, and unlinking one of those from a plugin
    is a use-after-free (feed_marker._detach_item spells it out). Only the
    surplus a shorter candidate leaves over is detached -- and the count only
    changes when the candidate's shape does (straight vs folded), so the common
    redraw touches the footprint's item list not at all. A shape reused across
    a redraw is told its layer every time, so a group that moved layers (the
    candidate spilling out of the area) carries its shapes with it."""
    rects = [
        (layer_id, corners)
        for layer_id, polys_mm in layers
        for corners in polys_mm
        if len(corners) >= 3
    ]
    if not rects:
        clear(board)
        return None
    fps = preview_footprints(board)
    fp = fps[0] if fps else _new_footprint(board)
    _anchor(fp, [corners for _, corners in rects])
    drawn = items(fp)
    for poly, (layer_id, corners) in zip(drawn, rects):
        feed_marker._rewrite_filled_poly(poly, layer_id, corners)
    for layer_id, corners in rects[len(drawn) :]:
        feed_marker._add_filled_poly(fp, layer_id, corners)
    for poly in drawn[len(rects) :]:
        feed_marker._detach_item(fp, poly)
    return fp


def clear(board):
    """Take the drawn antenna preview off the board for good; returns how many
    preview footprints went (0 = there was none). The scan calls this before
    plotting gerbers -- a preview on the feed layer is real copper and would
    otherwise be spliced under every candidate -- and the footprint step once
    the real copper is placed.

    The whole footprint goes, shapes and all, so nothing invisible is left
    behind on the board: an emptied husk would still be an item to select and a
    footprint to save. It goes through feed_marker._detach_footprint, which
    unlinks it without letting it be freed, since a preview loaded off the
    board is one KiCad's own selection and undo stack may point at.

    Nothing else clears a preview, so a caller that is about to draw another
    one should call ``draw`` directly, which reuses these shapes rather than
    orphaning them."""
    fps = preview_footprints(board)
    for fp in fps:
        feed_marker._detach_footprint(board, fp)
    return len(fps)
