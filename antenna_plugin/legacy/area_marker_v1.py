"""The area marker as one footprint (v1), converted to the marker the wizard
drags today.

Up to 2026-09-01 the area marker was a single ``board_only`` footprint named
``AntennaAreaMarker``: the area rectangle drawn as four line segments and the
feed arrow as five more, every one of them a graphic *inside* the footprint. It
could be moved and rotated as a whole and nothing else -- KiCad's point editor
gives drag handles only to board-level items, and a footprint's graphics have
none -- so the area was sized by sliders in the wizard.

Today's marker is a ``PCB_GROUP`` holding a board-level rectangle (draggable)
and a feed-arrow footprint (rigid), and the sliders are gone;
``markers/area_marker.py`` knows only that one. This is what closes the gap for
a board an older plugin drew: the v1 marker is read exactly as it stands --
same rectangle, same feed edge and position along it, same rotation, same layer,
same drawn triangle width -- today's marker is built from that reading, and the
old footprint is unlinked from the board.

It is one way, and it is not asked about first: a v1 marker cannot be dragged,
and dragging is the whole interface now, so leaving one in place would leave the
user with a marker none of the wizard's instructions fit. What it cannot read it
does not touch (``upgrade`` reports those instead) -- rebuilding a marker whose
drawing no longer decodes would mean guessing at an area the user drew.
"""

from ..emkit.markers import feed_marker, markergeom
from ..markers import area_marker


def find(board):
    """Every v1 area marker on ``board``, in board order: footprints whose
    LIB_ID item name is the marker name -- which today's marker carries as its
    group name instead, so the two can never be confused for one another."""
    return feed_marker.footprints_named(board, area_marker.MARKER_NAME)


def upgrade(board):
    """Convert every v1 area marker on ``board``, and say what happened:
    ``(converted, skipped)`` -- the new marker groups, and ``(footprint,
    reason)`` pairs for the ones whose drawing no longer decodes as an area
    marker (those are left exactly as they are, for the user to delete).

    The canvas refresh is the caller's: this runs as part of the wizard's board
    sync, which has its own."""
    converted, skipped = [], []
    for fp in find(board):
        try:
            converted.append(convert(board, fp))
        except ValueError as exc:
            skipped.append((fp, str(exc)))
    return converted, skipped


def convert(board, fp):
    """One v1 marker footprint into today's marker group, in the same place and
    on the same layer, and the footprint off the board. Returns the new group;
    raises ValueError when ``fp``'s drawing doesn't decode as an area marker.

    The new marker is built before the old one is unlinked, so a marker that
    cannot be converted is still on the board when this raises."""
    segments = feed_marker._segment_points_mm(fp)
    corners = _outline_corners(area_marker._decode_segments(segments))
    # No triangle width asked for: the arrow is repinned at the width it was
    # drawn with, because a conversion redraws nothing the user chose.
    arrow, dots, _pinned = area_marker.repin_geometry(segments)
    group = area_marker.build_marker(
        board, feed_marker.marker_layer_id(fp), corners, arrow, dots
    )
    # The one footprint the plugin does take off a user's board (see
    # feed_marker._detach_footprint): it has just been replaced, drawing for
    # drawing, by the group above, and leaving it would be two area markers
    # where the user has one.
    feed_marker._detach_footprint(board, fp)
    return group


def _outline_corners(decoded):
    """A decoded v1 marker's rectangle as four corners in *board* mm. The
    decode reports the area in its own derotated frame, so a marker the user
    turned off the grid is that rectangle rotated back onto the board
    (``rot_deg`` about ``pivot``) -- which is how the converted marker keeps the
    angle the old one was left at."""
    corners = area_marker.rect_corners(decoded["area"])
    rot, pivot = decoded["rot_deg"], decoded["pivot"]
    if not rot:  # on the grid: the corners are the drawn ones, to the float
        return corners
    return [markergeom.rotate_pt(p, rot, pivot) for p in corners]
