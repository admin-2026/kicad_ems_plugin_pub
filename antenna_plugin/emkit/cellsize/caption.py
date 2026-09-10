"""The sentence under the Cell size box: two numbers read back as one rule.

A typed pair means something no pair of placeholders can carry -- "0 = auto"
and "0 = no ceiling" say what each field does alone, never what the two of them
do together -- so the box captions itself on every keystroke, the way the
Speed/accuracy slider captions its stops, and each sentence leads with the
guarantee (*the cell is never coarser than X*) rather than with the mechanism
behind it.

An untouched pair is captioned with nothing at all: the two placeholders
already say the fields are the solver's to resolve, and a sentence restating
that would be the one caption here that never changes -- noise on the box a
user has not touched, and one more line of prose before the fields that matter.

Pure text: the caller passes the two field values and whether the Mesh box's
"Re-mesh at the finest cell that fits" tick is on, and gets a string (empty
where there is nothing to say).
"""

from .knobs import mm, problem, value

# Under the caption, unchanging: which side of the pair does what, in one line.
# It is the only thing here a user cannot work out from the fields themselves --
# both of them can refine, so which one to reach for is a choice, not a
# discovery. What follows from it (a ceiling set coarser than the automatic cell
# is silently inert; lowering copper_cells is how to coarsen with the automatic
# rule left intact) is on the ceiling's own tooltip and in the settings guide:
# a line of standing advice on a pane is a signpost, a paragraph is a document.
ADVICE = "Type on the right to refine, on the left to coarsen."


def caption(cell_mm, cell_max_mm, fit_cell=True):
    """The sentence for the pair as it currently reads, or ``""`` while both
    fields are still the solver's (see the module note).

    ``fit_cell`` is the state of the re-mesh tick, because it decides what an
    over-budget lattice does -- and with an explicit cell and the tick off, the
    ceiling has nothing left to bound, which the sentence says rather than
    leaving a knob that quietly does nothing.
    """
    empty = problem(cell_mm, cell_max_mm)
    if empty:
        return empty
    cell, ceiling = value(cell_mm), value(cell_max_mm)
    if cell is None and ceiling is None:
        return ""
    if cell is None:
        return _refined(ceiling, fit_cell)
    if ceiling is None:
        return _pinned(cell, fit_cell)
    return _bracketed(cell, ceiling, fit_cell)


def _refined(ceiling, fit_cell):
    """Ceiling alone -- the knob's main use: the automatic rule still applies,
    with the ceiling joining it as a third term. Where the ceiling is what set
    the cell, no coarser cell is allowed, so the budget re-mesh usually has
    nowhere to land."""
    text = (
        f"Auto, refined to {mm(ceiling)} -- wherever the automatic rule would "
        f"pick a coarser cell, the cell is {mm(ceiling)} instead; where it is "
        "already finer, nothing changes."
    )
    if fit_cell:
        return (
            f"{text} An over-budget lattice can only be re-meshed at a cell "
            f"still under {mm(ceiling)}, so it will often stop instead."
        )
    return f"{text} An over-budget lattice stops -- re-meshing is off."


def _pinned(cell, fit_cell):
    """Cell alone -- the way to coarsen a mesh, at the price of the rule: both
    safety terms stop applying, on this board and on every later one."""
    text = f"Mesh at {mm(cell)} -- the automatic rule (λ/20, driven copper) is off."
    if fit_cell:
        return (
            f"{text} Over the memory budget, the run re-meshes as coarse as it "
            "needs to."
        )
    return f"{text} Over the memory budget the run stops -- re-meshing is off."


def _bracketed(cell, ceiling, fit_cell):
    """Both -- the range proper: the run starts at the fine end and may walk up
    to the coarse one, but only under memory pressure and never past it."""
    if not fit_cell:
        return (
            f"Mesh at {mm(cell)}. Re-meshing is off, so an over-budget run "
            f"stops instead of coarsening: the {mm(ceiling)} ceiling binds "
            "nothing here."
        )
    return (
        f"Mesh at {mm(cell)}, and no cell coarser than {mm(ceiling)} -- over "
        "the memory budget the run may coarsen inside that range, then stops."
    )
