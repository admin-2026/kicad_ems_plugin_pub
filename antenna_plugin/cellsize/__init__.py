"""The cell-size range: the two knobs that bound the lattice's base cell.

``cell_mm`` is the cell a run starts from (blank = the solver derives it from
the band and the driven copper); ``cell_max_mm`` is a ceiling on that cell --
never a target, so it can only ever refine. The pair is one control with two
sides: the left one is the only field that can make a mesh coarser (it replaces
the automatic rule), the right one the only field that refines without
discarding it.

Self-contained, one directory per concern:

    knobs   -- the two fields as data, plus the two rules that make a pair of
               them valid (the solver refuses the rest at config load); pure
               stdlib, read by gui.options and by sim.config
    caption -- the live sentence the box shows, one per state of the pair
    ui      -- CellSizeBox, the Advanced pane's "Cell size" group; the only
               module here that imports wx

Nothing outside reaches past these: the Advanced pane builds the box and
registers its two controls like any other Advanced field, and the config writer
asks ``knobs.problem`` whether the numbers it is about to emit are a range at
all.
"""
