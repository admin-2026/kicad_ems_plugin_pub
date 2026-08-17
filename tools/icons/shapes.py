"""What the icons depict, as opposed to how it is drawn (draw.py).

The board every antenna stands on, the antenna outlines themselves, the marker
footprints the GUI's buttons place, and the dimension marks the scan
illustrations annotate them with — the vocabulary the exported pictures
(tabs.py, scan.py, markers.py) are composed from, so a tab icon and the scan
illustration of the same design cannot drift apart.

The outline builders take their own proportions as arguments: the same
L-monopole is drawn tight for a 64 px sidebar tab and roomier for a scan
illustration that has to show a swept range around it, and each exporter keeps
its own numbers. What is *shared* is here: one board rectangle and one feed
dot for every design, so the drawings read as a family.

Everything is in canvas fractions (see draw.Canvas).
"""

# --- the board every antenna stands on --------------------------------------
PCB_LEFT, PCB_RIGHT = 0.18, 0.82
PCB_TOP, PCB_BOTTOM = 0.72, 0.92
PCB_RADIUS = 0.02
PCB_ALPHA = 90  # opacity (0-255) for the shaded PCB rectangle
FEED_DOT_RADIUS = 0.08

# Opacity for a shape the drawing shows without asserting it: the ends of a
# swept range in the scan illustrations, drawn around the nominal antenna.
GHOST_ALPHA = 80

# --- dimension marks --------------------------------------------------------
# A measured span: a double-headed arrow set alongside the feature it measures.
# Thinner than any trace, so a dimension never reads as copper, and bare --
# extension lines back to the feature closed the drawing into a box at these
# sizes and cost more ink than they explained.
DIM_STROKE = 0.022
DIM_HEAD = 0.075


def board(stencil, top=PCB_TOP):
    """The shaded PCB rectangle. ``top`` lifts its edge for a drawing that
    needs more room above it."""
    stencil.rect((PCB_LEFT, top, PCB_RIGHT, PCB_BOTTOM), radius=PCB_RADIUS)


def antenna(stencil, polylines, stroke, feeds=(), dot=FEED_DOT_RADIUS):
    """An antenna drawing: each polyline stroked at ``stroke`` (the track
    width), each feed point dotted. ``dot`` shrinks the marker for a design
    that puts a second pin next to the feed (an inverted-F's short pin), where
    the full-sized one would swallow the gap between them."""
    for points in polylines:
        stencil.polyline(points, stroke)
    for feed in feeds:
        stencil.dot(feed, dot)


def lmonopole(feed_x, bend_y, arm_x, base_y=PCB_TOP):
    """The L-shaped monopole's centerline: up the stem from the feed on the
    board edge, then the arm along it — the shape design/lmonopole.py lays
    out, where **total = stem + arm**."""
    return [(feed_x, base_y), (feed_x, bend_y), (arm_x, bend_y)]


def ifa_radiator(short_x, feed_x, tip_x, spine_y, fold_y, legs, base_y=PCB_TOP):
    """The meandered inverted-F's radiator: up the short pin to the arm,
    across the tap to the feed pin, then ``legs`` square legs to the open tip.
    Both pins rise the whole way, so the tap runs flush with the first fold;
    every fold then turns back *toward* the feed, and an even leg count ends
    the run on a fold so the tip is a turn rather than a stub end -- the shape
    ifa.solve lays out."""
    points = [(short_x, base_y), (short_x, fold_y), (feed_x, fold_y)]
    leg = (tip_x - feed_x) / legs
    x, y = feed_x, fold_y
    for _ in range(legs):
        x += leg
        points.append((x, y))  # a leg at this level,
        y = spine_y if y == fold_y else fold_y
        points.append((x, y))  # then the fold
    return points


# --- the markers the plugin's buttons place ---------------------------------
# The feed marker's arrow, in the proportions the plugin actually draws it with
# (antenna_plugin/markers/markergeom.py's arrow_segments, as
# feed_marker._local_segments calls it): everything is a multiple of the base
# width, which is the feed width itself. Kept as ratios rather than as canvas
# fractions so the picture stays the marker the user gets -- change the drawn
# marker and these move with it.
FEED_ARROW_HEAD = 0.75  # triangle height, per base width
FEED_ARROW_STEM = 0.5  # stem length, per base width


def feed_arrow(cx, cy, width):
    """The feed marker's arrow as polylines: a triangle head ``width`` wide
    with its base centred on ``(cx, cy)`` -- the feed point -- and its apex
    toward −Y (the feed direction, toward the antenna), plus the stem running
    back the other way. The triangle is one closed path here where the
    footprint draws it as four segments: the drawing is the same, and a
    marker's segment count is a decode detail, not a shape."""
    half = width / 2
    base_l, base_r = (cx - half, cy), (cx + half, cy)
    apex = (cx, cy - FEED_ARROW_HEAD * width)
    tail = (cx, cy + FEED_ARROW_STEM * width)
    return [[base_l, apex, base_r, base_l], [(cx, cy), tail]]


def dimension(stencil, p0, p1, head=DIM_HEAD):
    """A measured span from ``p0`` to ``p1``, drawn beside what it measures.
    ``head`` shrinks for a span too short to carry full-sized heads (a track
    width)."""
    stencil.arrow(p0, p1, DIM_STROKE, head)
