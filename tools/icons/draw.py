"""How the generated PNGs are drawn — the engine, with no opinion on what.

Every icon this package exports is built the same way: a square
:class:`Canvas` supersampled by ``SS``, one or more :class:`Stencil` layers
drawn on it, each pasted in the flat :data:`COLOR` at its own opacity, and the
whole thing downscaled at the end for anti-aliasing. So a size change never
touches a drawing: geometry is written in **fractions of the canvas** (0..1,
origin top-left), never in pixels, and a larger export just renders the same
numbers crisper.

Layers rather than one mask, because opacity is how these drawings say
"secondary": the PCB under an antenna, the ghosted ends of a swept range
(shapes.GHOST_ALPHA). One flat colour throughout — change :data:`COLOR` to
restyle the whole set.

What the icons *depict* lives next door: shapes.py (the board, the antennas,
the dimension marks), tabs.py and scan.py (the pictures actually exported).
"""

import math
import os

from PIL import Image, ImageDraw

SS = 8  # supersampling factor for smooth anti-aliasing

COLOR = (37, 99, 235)  # single flat color (blue-600); change to restyle

# The installed package the icons are written into; the tools/ tree ships
# nothing itself.
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG_DIR = os.path.join(REPO_DIR, "antenna_plugin")


def _made(path):
    """*path* with its directory created."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def out_path(*parts):
    """A path under the plugin package, its directory created if needed."""
    return _made(os.path.join(PKG_DIR, *parts))


def packaging_path(*parts):
    """A path under ``packaging/``, for artwork that ships *around* the plugin
    rather than inside it -- the store front of an install package, which the
    installed plugin itself never reads."""
    return _made(os.path.join(REPO_DIR, "packaging", *parts))


class Canvas:
    """A square RGBA image drawn in canvas fractions and saved downscaled.

    ``size`` is the exported resolution in px; everything in between is
    rendered at ``size * SS`` and resized on ``save``.
    """

    def __init__(self, size):
        self.size = size
        self.px = size * SS
        self.image = Image.new("RGBA", (self.px, self.px), (0, 0, 0, 0))

    # --- fractions -> supersampled pixels -------------------------------------
    def at(self, fraction):
        """A length (radius, offset) in supersampled pixels."""
        return fraction * self.px

    def xy(self, point):
        """A point ``(x, y)`` in supersampled pixels."""
        x, y = point
        return (x * self.px, y * self.px)

    def line_width(self, fraction):
        """A stroke width in whole supersampled pixels (ImageDraw wants int)."""
        return max(1, int(fraction * self.px))

    # --- layers ---------------------------------------------------------------
    def stencil(self):
        """A blank :class:`Stencil` sized to this canvas."""
        return Stencil(self)

    def paste(self, stencil, alpha=255, color=COLOR):
        """Paste a stencil onto the canvas in the flat colour at ``alpha``."""
        layer = Image.new("RGBA", (self.px, self.px), (*color, alpha))
        self.image.paste(layer, (0, 0), stencil.image)

    def save(self, path):
        img = self.image.resize((self.size, self.size), Image.LANCZOS)
        img.save(path)
        print("wrote", os.path.normpath(path), img.size)


class Stencil:
    """One layer of a drawing: a single-channel mask, drawn in the canvas'
    fractions, that :meth:`Canvas.paste` turns into coloured pixels at
    whatever opacity that layer wants. Every coordinate *and every size* below
    is a fraction of the canvas."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.image = Image.new("L", (canvas.px, canvas.px), 0)
        self._d = ImageDraw.Draw(self.image)

    def rect(self, box, radius=0.0, stroke=None):
        """A rounded rectangle ``(x0, y0, x1, y1)``, filled — or stroked at
        ``stroke`` when one is given (an outline, e.g. a chat bubble)."""
        c = self.canvas
        x0, y0, x1, y1 = box
        style = (
            {"outline": 255, "width": c.line_width(stroke)} if stroke else {"fill": 255}
        )
        self._d.rounded_rectangle(
            [c.xy((x0, y0)), c.xy((x1, y1))], radius=c.at(radius), **style
        )

    def dot(self, center, radius):
        self._ellipse(center, radius, 255)

    def hole(self, center, radius):
        """The inverse of :meth:`dot`: clear a disc out of what this layer has
        drawn so far (a gear's hub), so the shape reads as a ring rather than
        needing a second layer in the background colour -- these drawings are
        pasted on transparency and have no background to paint with."""
        self._ellipse(center, radius, 0)

    def _ellipse(self, center, radius, fill):
        x, y = self.canvas.xy(center)
        r = self.canvas.at(radius)
        self._d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    def polygon(self, points):
        self._d.polygon([self.canvas.xy(p) for p in points], fill=255)

    def polyline(self, points, stroke):
        """An open path stroked at ``stroke`` with round caps and joins (a
        trace: the corners must not notch where the segments meet)."""
        width = self.canvas.line_width(stroke)
        pts = [self.canvas.xy(p) for p in points]
        for p0, p1 in zip(pts, pts[1:]):
            self._d.line([p0, p1], fill=255, width=width)
        for x, y in pts:
            r = width / 2
            self._d.ellipse([x - r, y - r, x + r, y + r], fill=255)

    def arrow(self, p0, p1, stroke, head, double=True):
        """A shaft from ``p0`` to ``p1`` with a solid head at ``p1`` (and at
        ``p0`` unless ``double`` is off). ``head`` is the head's length; it is
        half as wide again as it is long, so it stays readable when the shaft
        is short."""
        ux, uy = _unit(p0, p1)
        # The shaft stops inside the heads, so a round cap can't poke out of a
        # tip; a head's own base covers the join.
        inset = (ux * head * 0.6, uy * head * 0.6)
        self.polyline(
            [_step(p0, inset) if double else p0, _step(p1, (-inset[0], -inset[1]))],
            stroke,
        )
        tips = [(p1, (ux, uy))] + ([(p0, (-ux, -uy))] if double else [])
        for tip, (dx, dy) in tips:
            back = _step(tip, (-dx * head, -dy * head))
            half = head * 0.375
            self.polygon(
                [
                    tip,
                    _step(back, (-dy * half, dx * half)),
                    _step(back, (dy * half, -dx * half)),
                ]
            )


def _unit(p0, p1):
    """The unit vector from ``p0`` to ``p1`` (canvas fractions, so isotropic
    on the square canvas)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def _step(point, delta):
    return (point[0] + delta[0], point[1] + delta[1])
