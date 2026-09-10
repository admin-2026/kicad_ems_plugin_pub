"""Static tables for the form: the speed/accuracy presets and the Advanced
pane's fields, sorted into the functional groups it draws them in (ADV_GROUPS).

Pure data — no wx, no pcbnew, and beside ``choices.py`` rather than under
``gui/`` for the same reason that one is: a saved form is read by the command
line too (``formparams``, and the settings vocabulary ``guide`` prints), which
may not import anything under ``gui/``. The window draws these tables; it does
not own them. What only one flow's form holds is not here either: a product
keeps its own tables beside its code and hands them over through ``runjob``.
"""

from typing import NamedTuple

from .cellsize import knobs as cellsize


class SpeedPreset(NamedTuple):
    """One stop of the speed/accuracy slider: a caption spelling out the
    actual settings, and the state of the six optimization toggles (which
    live in the Advanced pane)."""

    desc: str
    coarse_air: bool
    refine_xy: bool
    boundary: str  # "pml" | "mur"
    conformal: bool
    adaptive: bool  # distance-banded copper mesh
    copper_cells: int  # cells across the driven copper, 1 or 2

    @property
    def toggles(self):
        return (
            self.coarse_air,
            self.refine_xy,
            self.boundary,
            self.conformal,
            self.adaptive,
            self.copper_cells,
        )


# One monotonic fastest->most-accurate sweep. Each stop is captioned with its
# actual settings rather than a named tier, so there is nothing to keep in
# sync with the toggle list below. Each accuracy step turns one more knob
# toward its expensive setting -- first the driven-copper mesh (1 -> 2 cells),
# then conformal metal, then drop the adaptive distance-banded mesh, then CPML
# over Mur, then the uniform air mesh (coarse air off), and finally feature
# refinement, reserved for the top stop alone.
#
# Both knobs that come before the boundary are there for the same reason:
# what they buy is worth more than the drop from Mur's ~1e-2 reflection to
# CPML's ~1e-4. Conformal metal gives sub-cell trace edges and costs the mesh
# no cells at all. Dropping the adaptive mesh restores full-resolution copper
# away from the feed, where the coarsened bands are the dominant error on a
# board whose radiator is not all near the port -- so it is spent before the
# boundary, which leaves a stop on Mur with the copper meshed uniformly: the
# cheapest boundary an otherwise-honest mesh can sit in, and the one to reach
# for when the geometry (not the truncation) is what is under test.
#
# The three fastest stops enable adaptive rastering: it coarsens copper far
# from the feed for a quick look at a large board -- fewer cells, hence the
# fast end -- at the cost of accuracy on that outer copper (config.py picks the
# band reach adaptive_n). The very fastest stop also drops copper_cells to 1
# (one cell across the driven copper instead of the default 2), coarsening the
# auto cell size further still.
SPEED_PRESETS = [
    SpeedPreset(
        "Adaptive mesh · Mur ABC · no refinement · no conformal · "
        "coarse air · 1 cell across driven copper",
        True,
        False,
        "mur",
        False,
        True,
        1,
    ),
    SpeedPreset(
        "Adaptive mesh · Mur ABC · no refinement · no conformal · "
        "coarse air · 2 cells across driven copper",
        True,
        False,
        "mur",
        False,
        True,
        2,
    ),
    SpeedPreset(
        "Adaptive mesh · Mur ABC · no refinement · conformal · "
        "coarse air · 2 cells across driven copper",
        True,
        False,
        "mur",
        True,
        True,
        2,
    ),
    SpeedPreset(
        "Mur ABC · no refinement · conformal · coarse air · "
        "2 cells across driven copper",
        True,
        False,
        "mur",
        True,
        False,
        2,
    ),
    SpeedPreset(
        "CPML · no refinement · conformal · coarse air · 2 cells across driven copper",
        True,
        False,
        "pml",
        True,
        False,
        2,
    ),
    SpeedPreset(
        "CPML · no refinement · conformal · uniform air mesh · "
        "2 cells across driven copper",
        False,
        False,
        "pml",
        True,
        False,
        2,
    ),
    SpeedPreset(
        "CPML · feature refinement · conformal · uniform air "
        "mesh · 2 cells across driven copper",
        False,
        True,
        "pml",
        True,
        False,
        2,
    ),
]
# The cheapest stop whose copper is meshed at full resolution: conformal metal
# and no adaptive bands, still inside Mur. It no longer tracks "the first stop
# on CPML" -- the combination that rule used to name (adaptive mesh *and* CPML)
# stopped being a stop when the adaptive drop moved below the boundary upgrade,
# and of the two stops that inherited it the geometry-honest one is the better
# opening bid: a first run is judged on whether the shape resonates where it
# should, which the coarsened outer copper moves and Mur's ~1e-2 reflection
# (against CPML's ~1e-4) does not. One notch up is the same mesh in CPML.
SPEED_DEFAULT = 3  # conformal + Mur, coarse air, 2 copper cells, no adaptive mesh


class AdvGroup(NamedTuple):
    """One functional group of the Advanced pane: the title of the box it is
    drawn in, and the numeric fields that go inside it as
    ``(config key, label, default hint)``. The key is not only what the field
    writes: the pane puts it on the field's placeholder after the hint
    (``0 = auto [cell_mm]``, gui.theme.hint_with_key), so a solver message
    naming a knob leads to the field that set it.

    A group may have no fields of its own (Materials, Optimizations, Markers):
    it is then only a title, and the widgets in that box are pickers,
    checkboxes or a whole sub-panel that gui.sections.advanced builds. It may
    also have fields it does not draw the usual way (Cell size, whose pair is
    laid out as a range by the cellsize package): the rows are still here, so
    the flat ADV_FIELDS list -- what the pane reads back and what it saves --
    covers every field on the pane wherever it was drawn."""

    title: str
    fields: tuple = ()


# The Advanced pane, grouped by what each knob does rather than by the order
# the keys were added to the schema: every remaining runner knob the README
# documents, blank = the config.py default. The mesh/run knobs all have
# runner-side autos resolved from the board and band, so a blank field means
# "auto" -- the hint says what the auto resolves to.
#
# The keys name the groups for gui.sections.advanced, which builds one titled
# box per group (and decides their order on the pane); the titles and the field
# rows live here, with the rest of the dialog's static tables.
ADV_GROUPS = {
    # The per-layer metal/substrate/solder-mask pickers (materials.ui, a box of
    # its own), the metal model they are meshed with and the tick that says
    # whether the mask is simulated at all -- no numeric fields.
    "materials": AdvGroup("Materials"),
    # The optimization toggles the Speed/accuracy slider drives, plus the
    # cells-across-driven-copper divisor. All widgets, no fields.
    "optimizations": AdvGroup("Optimizations"),
    # The base cell's range -- where a run starts and how coarse it may end up.
    # A box of its own because the two knobs are one control: neither reads
    # correctly without the other beside it, and the sentence they add up to is
    # live (the cellsize package owns the fields, the rules and that caption;
    # this is only where the pane learns the group exists).
    "cell": AdvGroup(cellsize.TITLE, cellsize.FIELDS),
    "mesh": AdvGroup(
        "Mesh",
        (
            # A ceiling, not the cell: each dielectric slab is sized from its
            # own thickness and permittivity, so 0 leaves every one of them
            # alone and a value only bounds the coarsest from above.
            ("substrate_cell_mm", "Substrate cell ceiling (mm)", "0 = none"),
            ("mesh_ratio", "Mesh grading ratio", "0 = 1.5"),
            ("margin_mm", "Air margin (mm)", "0 = auto"),
            ("air_cell_mm", "Coarse-air cell (mm)", "0 = auto"),
            ("pml_cells", "PML cells", "0 = 10"),
            # The lattice's memory ceiling: the solver prices the mesh before
            # allocating anything per-cell, instead of being OOM-killed
            # mid-build. What happens to one that does not fit is the box's
            # "Re-mesh..." checkbox (mesh_fit_cell); raising the ceiling here
            # permits a bigger allocation and so keeps the mesh the config
            # asks for.
            ("mesh_budget_gb", "Mesh memory budget (GB)", "0 = auto (75% RAM)"),
        ),
    ),
    # Everything that subdivides cells across a feature. The master switch is
    # the Optimizations box's "Skip in-plane feature refinement" (refine_xy),
    # which the speed slider drives; these grade what it does.
    "refinement": AdvGroup(
        "Feature refinement",
        (
            ("feature_max_mm", "Refine features under (mm)", "0 = 3·cell"),
            ("feature_min_cell_mm", "Min feature cell (mm)", "0 = cell/5"),
            ("via_min_cell_mm", "Min via cell (mm)", "0 = feature floor"),
            # Primary across-feature subdivision divisor; only
            # takes effect with refine_xy on -- see config.write_yaml.
            ("refine_n", "Feature subdivision N", "3..5, blank = 3"),
            # Adaptive band reach in wavelengths; only used when a speed stop
            # that turns adaptive rastering on is active (the three fastest);
            # ignored otherwise, see config.write_yaml.
            ("adaptive_n", "Fine-mesh radius (λ)", "0.25 (adaptive stops)"),
        ),
    ),
    # The excited band and how long the stepping runs for.
    "run": AdvGroup(
        "Frequencies and run",
        (
            ("fmax_ghz", "Max frequency (GHz)", "0 = auto"),
            ("flow_ghz", "Min frequency (GHz)", "0 = auto"),
            ("steps", "Fixed steps", "0 = use time"),
            ("threads", "Solver threads", "0 = auto-tune"),
        ),
    ),
    # The feed is a marker-placed point + direction, and its gap is severed on
    # the grid by the runner -- an output of the meshing, not an input -- so the
    # port's only field is the impedance it is driven through.
    "feed": AdvGroup(
        "Feed port",
        (("port_resistance", "Port resistance (Ω)", "blank = the form's own"),),
    ),
    # The two ground-check knobs. Neither touches the mesh: min_raster_mm is the
    # floor of the copper-connectivity raster the check and the automatic tie
    # flood -- blank derives it from the narrowest fed trace, so pin it only to
    # look finer still -- and the radius bounds how far from the feed point that
    # search may look for the ground (or source) to tie to. Whether it runs at
    # all is the Run / Scan section's Auto ground/source tick
    # (sections.passknobs).
    "ground": AdvGroup(
        "Ground",
        (
            ("min_raster_mm", "Connectivity raster (mm)", "0 = auto"),
            (
                "auto_ground_radius_mm",
                "Auto ground/source radius (mm)",
                "0 = from the port",
            ),
        ),
    ),
    # The User layer the page's marker footprint is drawn on -- a picker the
    # marker section owns, no numeric fields.
    "markers": AdvGroup("Markers"),
}

# Every Advanced field, flat and in pane order: what the pane parses and what
# formparams reads out of a saved form (the grouping is a layout fact).
ADV_FIELDS = [field for group in ADV_GROUPS.values() for field in group.fields]
