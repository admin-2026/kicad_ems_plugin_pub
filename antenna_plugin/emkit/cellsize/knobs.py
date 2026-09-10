"""The two cell-size knobs as data, and the rules a pair of them must satisfy.

Pure stdlib -- no wx, no pcbnew -- because three places read it: the Advanced
pane's field table (``options``), the box that draws the pair
(``cellsize.ui``, through ``cellsize.caption``) and the config writer
(``sim.config``). A key, a label and what makes two of them contradictory are
written once, here.

Both knobs spell "leave it to the solver" as 0, like every other mesh knob, so
a blank field and a typed 0 mean the same thing -- see ``value``.
"""

CELL = "cell_mm"
CELL_MAX = "cell_max_mm"

# The Advanced group these two live in: their own box, because the pair is one
# control (options names the group, gui.sections.advanced draws it).
TITLE = "Cell size"

# (config key, field label, what a blank field resolves to) -- the ADV_FIELDS
# row shape, so the rest of the pane (snapshot, restore, contribute) handles
# these two like any other numeric field.
FIELDS = (
    (CELL, "Start at (mm)", "0 = auto"),
    (CELL_MAX, "Never coarser than (mm)", "0 = no ceiling"),
)

# Each field's tooltip: what the number is, not what the key is called (the
# key rides the placeholder and the box's greyed sub-label). The ceiling's says
# where its value comes from, because it is the one number on this pane the
# solver cannot measure for itself: erosion measures how thin the driven copper
# is and knows nothing about how close the next conductor is, so a clearance
# that has to survive on the lattice is the user's to state.
TIPS = {
    CELL: (
        "The cell the run starts from. Typing one switches the automatic rule "
        "off -- the wavelength and driven-copper terms stop applying -- so it "
        "is the field to use for a deliberately coarser mesh."
    ),
    CELL_MAX: (
        "The smallest gap or clearance that has to survive on the lattice. "
        "The base cell is never coarser than this, however the automatic rule "
        "or a re-mesh would have sized it. It only ever refines."
    ),
}


def value(text):
    """One field's value as a positive float, or ``None`` for "left to the
    solver" -- blank, 0, or something that is not a number at all.

    A half-typed field ("0.", "-") is not an error here: the caption is redrawn
    on every keystroke, and the strict parse that names the field belongs to
    the run (gui.sections.advanced._adv_value), not to the sentence under it.
    """
    try:
        num = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def mm(num):
    """A cell size the way the box and the messages write it: ``0.2 mm``."""
    return f"{num:g} mm"


def problem(cell_mm, cell_max_mm, floors=()):
    """The message for a pair the solver would refuse at config load, or
    ``None`` when there is nothing wrong with it.

    Two rules, both the solver's, checked here so the window can say it while
    the number is being typed instead of after a run has been prepared:

    * an empty range (CFG-042) -- a run asked to start above its own ceiling.
      There is no cell that satisfies both keys, so neither key can be the one
      that wins;
    * a floor above the ceiling (CFG-043) -- ``feature_min_cell_mm`` or
      ``via_min_cell_mm`` typed coarser than the ceiling. Because the ceiling
      bounds every base cell the config permits, such a floor can never bind on
      any lattice this run could build; it is a knob that silently does
      nothing, which this project refuses on sight.

    ``floors`` is ``(key, value)`` pairs, so the caller decides which floors it
    has in hand: the box under the two fields has none, the config writer has
    both. Only an explicit floor is checked -- the automatic ones derive from
    the cell and follow the ceiling for free.
    """
    ceiling = value(cell_max_mm)
    if ceiling is None:  # no ceiling: nothing to contradict
        return None
    cell = value(cell_mm)
    if cell is not None and cell > ceiling:
        return (
            f"{CELL} {mm(cell)} is above {CELL_MAX} {mm(ceiling)} -- an empty "
            "range: the run would start coarser than its own ceiling."
        )
    for key, floor_text in floors:
        floor = value(floor_text)
        if floor is not None and floor > ceiling:
            return (
                f"{key} {mm(floor)} is above {CELL_MAX} {mm(ceiling)} -- a "
                "floor above the ceiling can never bind, on any lattice this "
                "config permits."
            )
    return None
