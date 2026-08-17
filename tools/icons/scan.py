"""One illustration per geometry parameter the wizard's Scan section sweeps.

A scan row asks the user to pick *which* knob the sweep turns, and words
("Stem length", "Feed-to-short spacing") are only half the answer — the other
half is which piece of the drawn antenna moves. These are that half, and since
the Scan section dropped the words they are now the *whole* of a row's label:
the design's antenna on the same shaded board as its sidebar tab (tabs.py),
with

- the **nominal** antenna in full colour,
- the ends of the swept range **ghosted** around it (shapes.GHOST_ALPHA), so
  the picture shows the sweep rather than one candidate, and
- a **dimension mark** (shapes.dimension) on the quantity being swept.

The ghosts are honest about the topology: every design's resonant length is a
budget its other knobs spend, so a ghost that lengthens an L-monopole's stem
gets the shorter arm, and a ghost that raises an inverted-F's height gets the
shorter run — the way lmonopole.solve and ifa.solve divide it. A knob that
spends none of that budget moves nothing else, and the drawing has to say so
too: an inverted-F's tap is not in its resonant length, so its ghost slides the
short pin and leaves the arm exactly where the nominal one has it. Only the
swept quantity and what it pays for ever move.

Files land in ``antenna_plugin/assets/icons/`` as ``scan_<design>_<param>.png``
-- one per :class:`~antenna_plugin.design.base.Param` of the design, keyed by
the same ``param.key`` the scan spec and the result rows use.

Geometry is in fractions of the canvas; the board and the outlines come from
shapes.py, so an illustration and its tab icon stay the same antenna.
"""

from . import shapes
from .draw import Canvas, out_path

# Exported resolution. Larger than the 64 px tab icons on purpose: these are
# illustrations, not glyphs, and since the Scan section shows one *as* a row's
# label rather than beside its name, it shows it big -- a ghosted range and a
# dimension mark read at about 96 px (gui/sections/scan.py's ICON_SIZE), so 192
# leaves a HiDPI display room to draw that at 2x. Nothing below is in pixels
# (see draw.Canvas), so this number is the only thing a resolution change
# touches.
SIZE = 192
OUT_DIR = ("assets", "icons")


def _illustration(
    design_key, param_key, ghosts, nominal, feeds, mark, dot=shapes.FEED_DOT_RADIUS
):
    """Compose one scan illustration: the shaded board, the ghosted ends of
    the swept range, the nominal antenna over them, and the dimension mark.

    ``ghosts`` and ``nominal`` are ``(polylines, stroke)`` pairs; ``mark`` is
    called with the annotation stencil, which is the nominal layer -- a
    dimension is never ghosted.
    """
    canvas = Canvas(SIZE)
    pcb = canvas.stencil()
    shapes.board(pcb)
    canvas.paste(pcb, alpha=shapes.PCB_ALPHA)

    ghost = canvas.stencil()
    for polylines, stroke in ghosts:
        shapes.antenna(ghost, polylines, stroke)
    canvas.paste(ghost, alpha=shapes.GHOST_ALPHA)

    stencil = canvas.stencil()
    polylines, stroke = nominal
    shapes.antenna(stencil, polylines, stroke, feeds, dot)
    mark(stencil)
    canvas.paste(stencil)

    canvas.save(out_path(*OUT_DIR, f"scan_{design_key}_{param_key}.png"))


# --- the box every design draws in ------------------------------------------
# One antenna size for the whole set: an L-monopole row and an inverted-F row
# are the same picture at two topologies, so they must fill the canvas alike --
# a design whose drawing sat smaller would read as a smaller antenna. Every
# design's *nominal* shape therefore spans the same box: its leftmost pin at
# LEFT_X, its topmost copper at TOP_Y, its run ending at TIP_X, standing on the
# shared board (shapes.PCB_TOP). Only a **ghost** leaves the box -- a swept
# range reaches past the nominal shape by definition -- and a length ghost
# stops at RUN_MAX_X, the board's own right edge, because an antenna that
# overhangs its PCB is what the wizard refuses to draw as copper.
LEFT_X = 0.24
TOP_Y = 0.26
TIP_X = 0.68
RUN_MAX_X = shapes.PCB_RIGHT
DIM_ABOVE_Y = 0.13  # a dimension line clear above the antenna

# --- the L-monopole the illustrations annotate ------------------------------
# The sidebar tab's antenna (tabs.LMONOPOLE_*) opened out into the shared box:
# a long stem to the arm, and the arm most of the way across, so the sweeps
# have room to move it.
LM_STROKE = 0.085  # not shared: the monopole has one track to
# draw and can afford a fatter one than a
# meander that folds back on itself
LM_FEED_X = LEFT_X  # the feed, on the board's edge
LM_BEND_Y = TOP_Y  # nominal bend: stem = PCB_TOP - LM_BEND_Y
LM_ARM_X = TIP_X  # nominal arm end

# Total length sweep: the stem is held, so the arm end travels along the row's
# min/max.
LM_LENGTH_MIN_X = 0.46
LM_LENGTH_MAX_X = RUN_MAX_X
LM_LENGTH_DIM_Y = DIM_ABOVE_Y

# Stem sweep: the bend slides up and down the stem at a held total length, so
# each ghost's arm gains exactly what its stem gives up (lmonopole.solve). The
# shallow end is as shallow as the arm allows: any more stem given back would
# run the arm off the board's right edge.
LM_STEM_SHALLOW_Y = 0.40
LM_STEM_DEEP_Y = 0.14
LM_STEM_DIM_X = 0.12  # the dimension line, left of the stem

# Track width sweep: same centerline, a fatter track. One ghost only -- a
# thinner variant would vanish under the nominal trace drawn over it. The
# dimension stands just off the arm's end cap and is the one span too short for
# full-sized arrow heads.
LM_WIDTH_FAT = 0.20
LM_WIDTH_DIM_X = 0.78  # the dimension line, right of the arm end
LM_WIDTH_HEAD = 0.055


def _lmonopole(bend_y=LM_BEND_Y, arm_x=LM_ARM_X):
    return [shapes.lmonopole(LM_FEED_X, bend_y, arm_x)]


def _lm_illustration(param_key, ghosts, nominal, mark):
    _illustration(
        "lmonopole", param_key, ghosts, nominal, [(LM_FEED_X, shapes.PCB_TOP)], mark
    )


def draw_lmonopole_length():
    """Total track length: the stem stays put and the arm end travels, so the
    dimension measures how far it travels."""
    _lm_illustration(
        "length",
        [
            (_lmonopole(arm_x=LM_LENGTH_MIN_X), LM_STROKE),
            (_lmonopole(arm_x=LM_LENGTH_MAX_X), LM_STROKE),
        ],
        (_lmonopole(), LM_STROKE),
        lambda s: shapes.dimension(
            s, (LM_LENGTH_MIN_X, LM_LENGTH_DIM_Y), (LM_LENGTH_MAX_X, LM_LENGTH_DIM_Y)
        ),
    )


def draw_lmonopole_width():
    """Track width: the same centerline drawn fat behind the nominal trace,
    with the dimension across the track."""
    half = LM_WIDTH_FAT / 2
    _lm_illustration(
        "width",
        [(_lmonopole(), LM_WIDTH_FAT)],
        (_lmonopole(), LM_STROKE),
        lambda s: shapes.dimension(
            s,
            (LM_WIDTH_DIM_X, LM_BEND_Y - half),
            (LM_WIDTH_DIM_X, LM_BEND_Y + half),
            head=LM_WIDTH_HEAD,
        ),
    )


def draw_lmonopole_stem():
    """Stem length: the bend slides along the stem, the arm taking back
    whatever the stem gives up, so the total length never moves."""

    def ghost(bend_y):
        # Whatever the stem loses, the arm gains -- the total is held.
        return _lmonopole(bend_y, LM_ARM_X + (bend_y - LM_BEND_Y))

    _lm_illustration(
        "stem",
        [(ghost(LM_STEM_SHALLOW_Y), LM_STROKE), (ghost(LM_STEM_DEEP_Y), LM_STROKE)],
        (_lmonopole(), LM_STROKE),
        lambda s: shapes.dimension(
            s, (LM_STEM_DIM_X, LM_STEM_DEEP_Y), (LM_STEM_DIM_X, LM_STEM_SHALLOW_Y)
        ),
    )


# --- the meandered inverted-F the illustrations annotate --------------------
# The tab icon's antenna, opened up: a thinner track than the monopole's (the
# meander packs more copper into the canvas), and **one** fold rather than the
# tab's three. A swept range draws the antenna two or three times over, and a
# meander at the tab's density turned into a hatch pattern the moment a ghost
# lay behind it -- one fold still says "this arm folds to fit" and leaves the
# board around it legible. Both pins stand on the board, as they must: the
# short pin ties to the pour and the feed pin to the port.
IFA_STROKE = 0.06  # not shared: see LM_STROKE
IFA_FEED_X = 0.44  # the feed pin, on the board's edge
IFA_SHORT_X = LEFT_X  # the short pin, a tap behind the feed
IFA_SPINE_Y = 0.50  # the level the fold turns back down to; the
# height is PCB_TOP - IFA_SPINE_Y
IFA_FOLD_Y = TOP_Y  # how deep into the area the arm reaches (and
# the level the two pins rise to, so the tap
# crossbar runs flush with the first fold)
IFA_TIP_X = TIP_X  # the open tip, at the end of the last leg
IFA_LEGS = 2
IFA_DOT = 0.065  # feed dot: smaller than the family's, or it
# would swallow the tap gap beside it

# Resonant-length sweep: the run reaches further along the area, the long end
# stopping at the board's right edge as the monopole's arm does.
IFA_LENGTH_MIN_X = 0.58
IFA_LENGTH_MAX_X = RUN_MAX_X
IFA_LENGTH_DIM_Y = DIM_ABOVE_Y

# Height sweep: the whole arm stands further off the feed edge, fold and all,
# and the run gives back what the height takes from the length budget. One
# ghost, measured against the nominal arm: two ghosted combs plus the nominal
# one read as three antennas rather than one range.
IFA_HEIGHT_HIGH_Y = 0.34
# The dimension is the height itself, not the swept range: it stands the gap
# the parameter names, from the bottom of the nominal arm down to the feed
# edge. So it hangs under the arm's lowest leg -- midway along it, clear of
# both pins and of the (shorter, higher) ghost, which lives left of here.
IFA_HEIGHT_DIM_X = IFA_TIP_X - (IFA_TIP_X - IFA_FEED_X) / (2 * IFA_LEGS)

# Tap sweep: the short pin slides back from the feed pin (ifa.solve puts it
# *behind* the feed), and the dimension lies in the gap between the two, the
# way the module drawing in design/ifa.py measures it. The arm does not follow
# it -- the tap is the match, not the resonator -- so the ghost is the pin and
# its crossbar alone, the rest of it hidden under the nominal antenna. One
# ghost: the pins are the busiest corner of the picture, and a second one only
# crowds it.
IFA_TAP_TIGHT_X = 0.36
IFA_TAP_DIM_Y = 0.62  # the dimension line, between the two pins
IFA_TAP_HEAD = 0.05
IFA_HEIGHT_HEAD = 0.06  # a shorter span than the stem's, but it clears the
# track it hangs off, so it carries near-full heads

# Track width sweep: as for the monopole, one fat ghost behind the nominal run,
# with the dimension across the open tip -- the end of the antenna with free
# area around it.
IFA_WIDTH_FAT = 0.19
IFA_WIDTH_DIM_Y = 0.09  # the dimension line, above the tip
IFA_WIDTH_HEAD = 0.05


def _ifa(spine_y=IFA_SPINE_Y, tip_x=IFA_TIP_X, short_x=IFA_SHORT_X):
    """The inverted-F's two paths -- radiator and feed pin -- for a height
    (``spine_y``), a run length (``tip_x``) and a tap (``short_x``). The folds
    ride with the height: they are measured from the arm, not from the board."""
    fold_y = IFA_FOLD_Y + (spine_y - IFA_SPINE_Y)
    return [
        shapes.ifa_radiator(short_x, IFA_FEED_X, tip_x, spine_y, fold_y, IFA_LEGS),
        [(IFA_FEED_X, shapes.PCB_TOP), (IFA_FEED_X, fold_y)],
    ]


def _ifa_illustration(param_key, ghosts, nominal, mark):
    _illustration(
        "ifa",
        param_key,
        ghosts,
        nominal,
        [(IFA_FEED_X, shapes.PCB_TOP)],
        mark,
        dot=IFA_DOT,
    )


def draw_ifa_length():
    """Resonant length: the run the feed drives, from the feed pin up to the
    arm and along it to the open tip (the tap is not in it), so the run reaches
    further along the area and the dimension measures how much further."""
    _ifa_illustration(
        "length",
        [
            (_ifa(tip_x=IFA_LENGTH_MIN_X), IFA_STROKE),
            (_ifa(tip_x=IFA_LENGTH_MAX_X), IFA_STROKE),
        ],
        (_ifa(), IFA_STROKE),
        lambda s: shapes.dimension(
            s,
            (IFA_LENGTH_MIN_X, IFA_LENGTH_DIM_Y),
            (IFA_LENGTH_MAX_X, IFA_LENGTH_DIM_Y),
        ),
    )


def draw_ifa_width():
    """Track width: the same run drawn fat behind the nominal one, with the
    dimension across the open tip."""
    half = IFA_WIDTH_FAT / 2
    _ifa_illustration(
        "width",
        [(_ifa(), IFA_WIDTH_FAT)],
        (_ifa(), IFA_STROKE),
        lambda s: shapes.dimension(
            s,
            (IFA_TIP_X - half, IFA_WIDTH_DIM_Y),
            (IFA_TIP_X + half, IFA_WIDTH_DIM_Y),
            head=IFA_WIDTH_HEAD,
        ),
    )


def draw_ifa_height():
    """Minimum height over the feed edge: the arm — folds and all — stands
    further off the board edge, which is the loop that widens the match. The
    length budget pays for it, so the run gives back exactly what the height
    takes.

    The ghost shows the sweep; the dimension shows the quantity, so it spans
    the gap the name promises -- from the bottom of the nominal arm down to
    the feed edge itself -- rather than the distance between the two arms.

    A meandered arm is drawn, which is the sweep the knob describes: the
    minimum is the level a *folded* arm's folds turn down to (ifa._split lifts
    an unfolded one off it onto the far border, where the knob no longer moves
    it), so the drawing shows the fold the dimension measures from."""

    def ghost(spine_y):
        return _ifa(spine_y, IFA_TIP_X + (spine_y - IFA_SPINE_Y))

    _ifa_illustration(
        "height",
        [(ghost(IFA_HEIGHT_HIGH_Y), IFA_STROKE)],
        (_ifa(), IFA_STROKE),
        lambda s: shapes.dimension(
            s,
            # Off the drawn track's underside rather than its centerline: half
            # a track is nothing next to the height, and an arrow head buried
            # in the copper reads as a stub instead of a measurement.
            (IFA_HEIGHT_DIM_X, IFA_SPINE_Y + IFA_STROKE / 2),
            (IFA_HEIGHT_DIM_X, shapes.PCB_TOP),
            head=IFA_HEIGHT_HEAD,
        ),
    )


def draw_ifa_tap():
    """Feed-to-short spacing: the short pin slides back from the feed pin (and
    the tap crossbar with it), the dimension lying in the gap it opens. Nothing
    else moves -- the tap is not part of the resonant length, so the arm keeps
    its run, its folds and its height (ifa.solve), and the ghost shows exactly
    that: a second pin, the same antenna."""

    def ghost(short_x):
        return _ifa(short_x=short_x)

    _ifa_illustration(
        "tap",
        [(ghost(IFA_TAP_TIGHT_X), IFA_STROKE)],
        (_ifa(), IFA_STROKE),
        lambda s: shapes.dimension(
            s,
            (IFA_SHORT_X, IFA_TAP_DIM_Y),
            (IFA_FEED_X, IFA_TAP_DIM_Y),
            head=IFA_TAP_HEAD,
        ),
    )


def draw_all():
    draw_lmonopole_length()
    draw_lmonopole_width()
    draw_lmonopole_stem()
    draw_ifa_length()
    draw_ifa_width()
    draw_ifa_height()
    draw_ifa_tap()
