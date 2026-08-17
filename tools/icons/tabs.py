"""The toolbar button's glyph and one icon per tab of the plugin's window.

- icon.png: signal-strength glyph, five ascending bars. The three lowest are
  highlighted (full color, current signal level); the two highest are lit at
  reduced opacity (available but unreached headroom).
- packaging/pcm/icon.png: that same glyph at 64x64, the size the KiCad Plugin
  and Content Manager shows a package at. The only export that lands outside
  the plugin, because it is what the *installer* is shown as, not the plugin.
- play_icon.png: a solid right-pointing triangle, at twice icon.png's size.
- lmonopole_icon.png: an inverted-L monopole over a PCB (feed dot, vertical
  stub, horizontal top arm), at play_icon.png's size. The PCB is a shaded
  rectangle at reduced opacity to set it apart from the antenna.
- ifa_icon.png: a meandered inverted-F over the same shaded PCB — the short
  pin, the tapped feed pin (with the feed dot) and an arm that squares back
  and forth, each fold turning down toward the feed.
- gear_icon.png: the About tab — a cogwheel (a ring of tapered teeth around a
  hubbed disc), at the same size as the tab icons above. No PCB under it: it
  says nothing about an antenna, it stands for what the installation is made
  of.

Each antenna icon is the sidebar tab of its design (design.registry), so a new
design brings a new drawing here (and one row of scan illustrations in
scan.py); the other tab icons are named by the page that wears them
(gui.pages, ``tab_icon``).

Geometry is in fractions of the canvas, and the shared parts of it -- the board
the antennas stand on, the outlines themselves -- come from shapes.py.
"""

import math

from . import shapes
from .draw import Canvas, out_path, packaging_path

SIGNAL_SIZE = 24  # exported resolution in px; higher = crisper when scaled
# The same glyph again for the KiCad Plugin and Content Manager, which asks for
# exactly 64x64 and shows it far larger than a toolbar ever does. Geometry is
# in canvas fractions, so this is a resolution and nothing else.
PCM_SIZE = 64
PLAY_SIZE = 64
LMONOPOLE_SIZE = PLAY_SIZE
IFA_SIZE = PLAY_SIZE
GEAR_SIZE = PLAY_SIZE

# --- signal icon geometry ---------------------------------------------------
SIGNAL_BAR_COUNT = 5
SIGNAL_BAR_HEIGHTS = (0.16, 0.30, 0.44, 0.58, 0.76)  # ascending
SIGNAL_BAR_WIDTH = 0.11
SIGNAL_BAR_GAP = 0.045
SIGNAL_BAR_RADIUS = 0.025
SIGNAL_BASELINE_Y = 0.86
SIGNAL_ACTIVE_COUNT = 3  # bars drawn at full opacity
SIGNAL_LIT_ALPHA = 90  # opacity (0-255) for the remaining, lit-but-dim bars

# --- play icon geometry -----------------------------------------------------
PLAY_TRIANGLE = ((0.32, 0.22), (0.32, 0.78), (0.80, 0.50))

# --- L-monopole icon geometry -----------------------------------------------
LMONOPOLE_STROKE = 0.09
LMONOPOLE_FEED_X = 0.32
LMONOPOLE_ARM_Y = 0.46
LMONOPOLE_ARM_RIGHT_X = 0.78

# --- inverted-F icon geometry -----------------------------------------------
# The PCB rectangle is the shared one (shapes.py), so only the antenna differs
# from the L-monopole tab, and its stroke is thinner because the meander packs
# more of it into the same canvas. The run stops short of the board's right
# edge, so the antenna never overhangs the PCB under it.
IFA_STROKE = 0.07
IFA_SHORT_X = 0.22  # short pin: ties the arm to the ground plane
IFA_FEED_X = 0.36  # feed pin: the tap, a little along from the short
IFA_SPINE_Y = 0.50  # the height the two pins stand the arm off at,
# and the level each fold turns back down to
IFA_FOLD_Y = 0.24  # how far into the area the folds reach
IFA_TIP_X = 0.81  # the open tip, at the end of the last leg
IFA_LEGS = 4  # legs of the meander, feed pin to tip; each is
# half a turn, so an even count ends the run rising

# --- gear icon geometry -----------------------------------------------------
# The cogwheel is centred on the canvas and drawn as one filled layer: the body
# disc, the teeth standing out of it, and the hub cut back out (draw.hole).
# The rim left between hub and body carries about the weight of the
# L-monopole's traces, so the About tab sits at the same visual density as the
# tabs above it in the sidebar.
GEAR_CENTER = (0.50, 0.50)
GEAR_TEETH = 8
GEAR_HUB_RADIUS = 0.155  # the hole in the middle
GEAR_BODY_RADIUS = 0.265  # the disc the teeth stand out of
GEAR_TIP_RADIUS = 0.375  # the teeth's outer edge
# Each tooth as a share of its half-pitch (the angle from a tooth's centre to
# the middle of the gap beside it): wider where it leaves the body than at the
# tip, so the flanks slope and the gaps stay open at this size.
GEAR_TOOTH_BASE = 0.62
GEAR_TOOTH_TIP = 0.38


def _signal_bars(canvas, indices):
    stencil = canvas.stencil()
    total = (
        SIGNAL_BAR_COUNT * SIGNAL_BAR_WIDTH + (SIGNAL_BAR_COUNT - 1) * SIGNAL_BAR_GAP
    )
    start_x = 0.5 - total / 2
    for i in indices:
        x0 = start_x + i * (SIGNAL_BAR_WIDTH + SIGNAL_BAR_GAP)
        stencil.rect(
            (
                x0,
                SIGNAL_BASELINE_Y - SIGNAL_BAR_HEIGHTS[i],
                x0 + SIGNAL_BAR_WIDTH,
                SIGNAL_BASELINE_Y,
            ),
            radius=SIGNAL_BAR_RADIUS,
        )
    return stencil


def _signal_canvas(size):
    """The signal glyph at *size* px: the lit bars, then the dim headroom."""
    canvas = Canvas(size)
    canvas.paste(_signal_bars(canvas, range(SIGNAL_ACTIVE_COUNT)))
    canvas.paste(
        _signal_bars(canvas, range(SIGNAL_ACTIVE_COUNT, SIGNAL_BAR_COUNT)),
        alpha=SIGNAL_LIT_ALPHA,
    )
    return canvas


def draw_signal_icon():
    _signal_canvas(SIGNAL_SIZE).save(out_path("icon.png"))


def draw_pcm_icon():
    _signal_canvas(PCM_SIZE).save(packaging_path("pcm", "icon.png"))


def draw_play_icon():
    canvas = Canvas(PLAY_SIZE)
    stencil = canvas.stencil()
    stencil.polygon(PLAY_TRIANGLE)
    canvas.paste(stencil)
    canvas.save(out_path("play_icon.png"))


def _antenna_icon(size, polylines, feeds, name, stroke=LMONOPOLE_STROKE):
    """One antenna tab icon: the shaded PCB with the antenna over it."""
    canvas = Canvas(size)
    pcb = canvas.stencil()
    shapes.board(pcb)
    canvas.paste(pcb, alpha=shapes.PCB_ALPHA)
    stencil = canvas.stencil()
    shapes.antenna(stencil, polylines, stroke, feeds)
    canvas.paste(stencil)
    canvas.save(out_path(name))


def draw_lmonopole_icon():
    """Feed dot on the board edge, a stub straight up, then the "L" arm."""
    trace = shapes.lmonopole(LMONOPOLE_FEED_X, LMONOPOLE_ARM_Y, LMONOPOLE_ARM_RIGHT_X)
    _antenna_icon(LMONOPOLE_SIZE, [trace], [trace[0]], "lmonopole_icon.png")


def draw_ifa_icon():
    """Short pin and tapped feed pin off the board edge, both rising to a
    meandering arm whose folds turn back toward the feed."""
    feed = (IFA_FEED_X, shapes.PCB_TOP)
    radiator = shapes.ifa_radiator(
        IFA_SHORT_X, IFA_FEED_X, IFA_TIP_X, IFA_SPINE_Y, IFA_FOLD_Y, IFA_LEGS
    )
    _antenna_icon(
        IFA_SIZE,
        [radiator, [feed, (IFA_FEED_X, IFA_FOLD_Y)]],  # the feed pin, tapped on the arm
        [feed],
        "ifa_icon.png",
        stroke=IFA_STROKE,
    )


def _polar(angle, radius, center=GEAR_CENTER):
    """A point ``radius`` out from ``center`` at ``angle`` radians, in canvas
    fractions (square canvas, so the same radius in x and y)."""
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))


def _gear_tooth(angle):
    """One tapered tooth, as a quadrilateral from inside the body disc out to
    the tip. Its base sits a little under GEAR_BODY_RADIUS so tooth and disc
    merge into one outline instead of meeting on a seam."""
    half_pitch = math.pi / GEAR_TEETH
    base = half_pitch * GEAR_TOOTH_BASE
    tip = half_pitch * GEAR_TOOTH_TIP
    root = GEAR_BODY_RADIUS * 0.9
    return [
        _polar(angle - base, root),
        _polar(angle - tip, GEAR_TIP_RADIUS),
        _polar(angle + tip, GEAR_TIP_RADIUS),
        _polar(angle + base, root),
    ]


def draw_gear_icon():
    """The About tab: a cogwheel — the body disc with GEAR_TEETH teeth around
    it, then the hub cut out of the lot, so the teeth, rim and hole read as one
    part rather than a stack of circles."""
    canvas = Canvas(GEAR_SIZE)
    stencil = canvas.stencil()
    stencil.dot(GEAR_CENTER, GEAR_BODY_RADIUS)
    for i in range(GEAR_TEETH):
        stencil.polygon(_gear_tooth(2 * math.pi * i / GEAR_TEETH))
    stencil.hole(GEAR_CENTER, GEAR_HUB_RADIUS)
    canvas.paste(stencil)
    canvas.save(out_path("gear_icon.png"))


def draw_all():
    draw_signal_icon()
    draw_pcm_icon()
    draw_play_icon()
    draw_lmonopole_icon()
    draw_ifa_icon()
    draw_gear_icon()
