"""A picture of each marker footprint the GUI's buttons place.

The Feed marker box asks the user to press a button and then click somewhere on
their board, and until they have done it once the words are the only clue what
lands there. This is the other clue: the marker as it is actually drawn -- the
triangle head, the stem behind it and the dot on the feed point, and nothing
else -- so the button's picture is the thing the button makes. The feed track
it is placed across is the user's own copper, not part of the footprint, so it
is not in the picture either.

Geometry comes from shapes.py in the marker's own proportions (shapes.feed_arrow
mirrors markers/markergeom.py), so a change to the drawn marker moves the
picture with it rather than leaving the two to drift.

Files land in ``antenna_plugin/assets/icons/`` as ``marker_<what>.png``,
alongside the scan illustrations (scan.py), and are loaded by gui/icons.py like
any other bundled drawing.
"""

from . import shapes
from .draw import Canvas, out_path

# Exported resolution. Shown at 64 px beside the Generate button
# (gui/sections/marker.py's ICON_SIZE) -- a small drawing rather than a
# glyph -- so 128 leaves a HiDPI display 2x to scale from. Nothing below is in
# pixels (see draw.Canvas), so this number is the only thing a resolution
# change touches.
SIZE = 128
OUT_DIR = ("assets", "icons")

# --- the feed marker --------------------------------------------------------
# The arrow alone, on transparency: the base width (the feed width) is the one
# size everything else is a ratio of, and the drawing fills the canvas because
# there is nothing else in it.
ARROW_WIDTH = 0.56
ARROW_X = 0.50
# The feed point (the arrow's base centre). The head reaches further above it
# than the stem does below, so the centre sits low and the arrow as a whole
# lands in the middle of the canvas.
FEED_Y = 0.5 + ARROW_WIDTH * (shapes.FEED_ARROW_HEAD - shapes.FEED_ARROW_STEM) / 2

# The marker's own lines are a tenth of its base width on the board; drawn a
# little heavier here so the outline survives the downscale to 64 px. The feed
# dot likewise: markergeom sizes it a quarter of the arrow's half-base, which
# at icon size is a speck, and the point it marks is the whole reason the
# marker exists.
STROKE = 0.06
FEED_DOT = 0.075


def draw_feed_marker():
    """The feed marker: the arrow, its apex pointing along the feed direction
    (toward the antenna), with the stem behind it and the dot on the feed
    point. One layer, so it is flat colour on transparency throughout."""
    canvas = Canvas(SIZE)
    stencil = canvas.stencil()
    for points in shapes.feed_arrow(ARROW_X, FEED_Y, ARROW_WIDTH):
        stencil.polyline(points, STROKE)
    stencil.dot((ARROW_X, FEED_Y), FEED_DOT)
    canvas.paste(stencil)
    canvas.save(out_path(*OUT_DIR, "marker_feed.png"))


def draw_all():
    draw_feed_marker()
