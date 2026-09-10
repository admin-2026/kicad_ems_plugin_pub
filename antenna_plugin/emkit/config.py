"""The runner YAML, as far as it is the same YAML for every flow.

A self-contained port of the config half of ``ems/scripts/pcb_config.py``:
stdlib only, writing the file by hand, so a plugin has no runtime dependency
on the ``ems`` tree (only the bundled binary). Instead of scanning a
directory it takes the gerber paths ``simulate.plot_gerbers`` already
resolved, plus the per-layer physical stackup ``simulate.collect_stackup``
read off the board.

Every flow's runner reads the same file (``src/config/PcbRunConfig.cpp`` in
the simulator is the only reader), and yet the flows are *not* one writer:
each runner majors its schema on its own schedule -- the antenna's is 17.x
while the S-parameter one is already 18.x -- and a shared module with a branch
in it is exactly where a bump for one flow would silently break the other.

So the sharing is a base class and the difference is an override. What is here
is the mechanics and the skeleton: the YAML scalars, the block order, the
board facts, the mesh and run knobs, the validation both flows need. What is
not is the version each flow tracks and the ports it drives.

**The one rule that keeps this from rotting: a block that differs is
overridden, never branched.** Nothing in this file may ask which flow is
running. When the antenna schema changes ``mesh()`` for the antenna alone,
that becomes an override in the antenna subclass and the other plugin does not
move.

    class AntennaConfig(ConfigWriter):
        CONFIG_VERSION = "20.0.0"

        def ports(self):
            ...          # one feed port

``DEFAULTS`` is shared because it is genuinely one dict today -- every knob
below is a key of the same reader -- and a flow that needs another value says
so by overriding that key, which is not a branch either.
"""

import os

from .. import product

# The cell/ceiling pair's own module -- stdlib-only like this one, and the
# single place those two keys and the rules between them are written down (the
# window reads the same module, see emkit/cellsize).
from .cellsize import knobs as cellsize

# No material constants live here: the runner has no auto for conductivity or
# permittivity -- it refuses to invent them -- and neither does this writer.
# A copper foil's sigma comes from the Materials picker (its own catalog
# default is Copper); a dielectric's eps and loss tangent come from the board's
# Physical Stackup (or a picked substrate material that overrides both). The
# silk/paste overlays need no material at all -- they are geometry-only (never
# meshed); the solder mask does, but only in a run that includes it
# (`include_mask`), and it has the same two sources a dielectric has. A layer
# with no source for a value is a blocked run
# (stackup_problems / _apply_overrides raise), never a silently injected
# number -- see the no-silent-defaults rule.

# Simulation defaults, overridable per-run through the params dict. Every knob
# the README documents lives here so the GUI (or a hand-edited YAML) can drive
# it. Every mesh/run knob has a runner-side auto (0) resolved from the config's
# own band, stackup and trace geometry, so the defaults are the autos -- a
# value only appears here when the user typed one into an Advanced field. The
# material values (`copper_sigma`, `substrate_sigma`, `substrate_eps`) are
# intentionally absent: they have no default at all -- each layer's
# conductivity/permittivity must come from the Materials picker or the board
# stackup, and a layer with no source blocks the run rather than taking an
# invented number (see _apply_overrides).
_DEFAULTS = {
    # Whether the solder mask is part of the board being solved. The one knob
    # here that is not a key of the emitted file: it selects whether the mask
    # entries are written into `stackup:` at all (see _apply_overrides), the
    # coating being a layer a run either meshes or leaves off the board. Off by
    # default -- a bare board is what every schema before this emitted, and the
    # coating costs a slab, two gerbers, a permittivity the board has to state
    # and (meshed at its own thickness) much of the run's wall clock. One tick
    # in Advanced > Materials, and the form's own default is this one.
    "include_mask": False,
    "copper_model": "sheet",
    "conformal": True,
    "fpattern_ghz": 2.45,
    "time_ns": 0.0,  # 0 = auto: run until the port rings down
    "steps": 0,
    "threads": 0,  # 0 = auto-tune over the run's first steps
    "fmax_ghz": 0.0,  # 0 = auto: 1.6 * fpattern
    "flow_ghz": 0.0,  # 0 = auto: fpattern / 5
    "port_resistance": "50",
    "cell_mm": 0.0,  # 0 = auto: min(lambda/20, driven copper / N)
    # Ceiling on that base cell, 0 = none. It is never a target: it can only
    # make the cell finer, so a ceiling above the cell the rule already picked
    # changes nothing at all. It is the escape hatch for the one thing the
    # measurements structurally cannot see -- a clearance -- since the erosion
    # behind the copper term measures how thin the driven copper is and says
    # nothing about how close the next conductor is. The invariant is narrow
    # and exact: the base cell a run builds is never coarser than this. That
    # bounds everything the cell derives (the substrate cell, the feature
    # floor, the feed gap, the adaptive Primary band) and deliberately not what
    # is coarse on purpose (air_cell_mm, the adaptive Transition/Outer bands,
    # which the runner sizes off the cell the rule would have picked without
    # the ceiling). Halving a cell is ~8x the cells and 2x the steps -- about
    # 16x the wall clock -- so on a large board this belongs with adaptive on.
    "cell_max_mm": 0.0,
    # N of the auto cell's copper term (cell <= driven copper / N), 1..5. The
    # copper is the metal the port drives: an erosion within half a wavelength
    # of the feed says WHERE the board's thin copper is, and how thick it is
    # there is re-measured off the drawing, so N cells really do fit across the
    # drawn width rather than across one rounded up to whole raster steps.
    "copper_cells": 2,
    "margin_mm": 0.0,  # 0 = auto: lambda_air(fpattern) / 8
    "coarse_air": True,
    "air_cell_mm": 0.0,  # 0 = auto: lambda_air(fmax) / 15
    "mesh_ratio": 0.0,  # 0 = auto: 1.5
    # The lattice's memory ceiling in GB, checked once the mesh is sized and
    # before anything per-cell is allocated, so an accidentally hairline-driven
    # cell is caught there instead of being allocated until the OOM killer takes
    # the run. 0 = auto: a fraction of this machine's RAM. Raising it only
    # allows a bigger allocation -- it never changes a mesh.
    "mesh_budget_gb": 0.0,
    # What a lattice over that budget does (the runner's own default). True
    # re-meshes: the preparation runs a second time with cell_mm forced to the
    # finest value that fits, everything the cell derives (substrate cell,
    # feature floor, feed gap) follows it, and the run proceeds with MESH-028
    # warning what got built and what it costs in cells per wavelength. At most
    # once per run -- a lattice still over budget at the fitted cell is refused
    # like any other, and a board where no cell fits at all is refused whatever
    # this says. False restores the plain refusal (MESH-014, naming that same
    # cell): the Advanced pane's checkbox, for a run whose mesh has to be the
    # one asked for or nothing -- a reference run, a sweep whose points must be
    # comparable, an unattended batch that should fail rather than answer at
    # another resolution.
    "mesh_fit_cell": True,
    "boundary": "pml",
    # Feature refinement is expensive and reserved for the top accuracy tier
    # (see options.SPEED_PRESETS); off by default so a GUI run below the
    # top stop, the wizard scan and hand-edited YAMLs all skip it unless asked.
    "refine_xy": False,
    # Adaptive rastering: mesh the copper in three cell-size bands by flood-fill
    # path distance from the feed gap, so a large layout spends resolution near
    # the RF current. Off by default; the Speed/accuracy slider's fastest stops
    # turn it on. adaptive_n
    # is the Primary-band reach in wavelengths -- no runner default (write_yaml
    # only emits it when adaptive is on), so this positive value is what an
    # untouched Advanced field resolves to; 0.25 covers a typical radiator +
    # ground return (the proposal's 0.25..0.5 sweet spot).
    "adaptive": False,
    "adaptive_n": 0.25,
    # Auto grounding: let the solver detect and attach the board's ground
    # reference on its own. On by default. The strap is flooded onto the
    # simulation lattice (so it may bend around an obstacle), and
    # auto_ground_radius_mm bounds how far from the feed point that search may
    # reach: 0 = derive the
    # disk from the port itself (half the feed gap + two run limits + a trace
    # width), which is the bound the tie belongs inside -- a strap found
    # centimetres behind the gap would add series inductance the layout has not.
    "auto_ground": True,
    "auto_ground_radius_mm": 0.0,
    # Put the feed point on the centerline of the copper its driven edge
    # bridges (the runner's own default). True is what a marker on a feed line
    # means here -- it names the line to drive, not the spot across it to stand
    # on -- so two markers a
    # hair apart on the same line give the same port. The Advanced pane turns
    # it off for a launch placed by hand (an asymmetric feed, a port on one
    # edge of a wide section); the port moves and nothing else does.
    "feed_snap_to_center": True,
    "ground_check": "strict",
    # Finest cell of the copper-connectivity raster the ground check and
    # auto-ground read -- the auxiliary bitmap they flood, never the simulation
    # lattice (that is cell_mm). It decides how fine a trace those checks can
    # see: a line narrower than one cell can sample away to nothing. 0 = auto,
    # derived from the board like the mesh knobs:
    # min(0.1 mm, narrowest fed trace / 2), so a hairline-traced layout is
    # checked on a raster that resolves its line without being told. Pin a
    # positive value only to go finer still (quadratic in raster memory).
    "min_raster_mm": 0.0,
    # Whole-board rotation. The GUI overrides this per-run with the angle
    # that brings an off-grid-rotated feed/area marker onto a grid axis
    # (markergeom.align_rotation_deg), so the driven trace is always
    # axis-aligned in the simulation.
    "rotation_deg": 0.0,
    # Extra bare-JSON data dump. pcb_data.js (window.FDTD) is
    # always written; output_json: true additionally writes pcb_data.json (a
    # bare object for scripts -- the wizard scan reads it for scoring) and
    # pcb_grid.json. Off by default (js only).
    "output_json": False,
    # A ceiling on the z cell of every dielectric slab, not the cell itself:
    # 0 = no ceiling, and each slab is then sized from its own thickness and
    # its own permittivity. Set it only to bound a whole stackup from above;
    # it can never take a slab below the cells it needs.
    "substrate_cell_mm": 0.0,
    "pml_cells": 0,  # 0 = auto: 10
    "feature_max_mm": 0.0,  # 0 = auto: 3 * cell
    "feature_min_cell_mm": 0.0,  # 0 = auto: cell / 5
    "via_min_cell_mm": 0.0,  # 0 = auto: the feature floor
    # Graded feature refinement: refine_n is the Primary
    # across-feature subdivision divisor (3..5, matches the runner's own
    # default); refine_adaptive grades the coarser adaptive bands to
    # width/(N-1) and width/(N-2) instead of pinning them. Both are only
    # emitted when refine_xy is on -- see write_yaml.
    "refine_n": 3,
    "refine_adaptive": True,
    # Post-mesh node nudging (the runner's own default): after the lattice is
    # built -- and after refinement, when refine_xy is on -- its node lines
    # slide onto nearby axis-aligned material edges, copper and the board
    # outline alike, so the mesh renders a trace at its drawn width and the
    # board at its drawn size instead of at whatever the cell centres happened
    # to sample (copper outranks the substrate when both want the same node).
    # It creates and deletes no node, so it costs no cells and no memory; a move
    # may shrink a cell far enough to cost up to 5% of the time step (a run that
    # much longer), which is what serving an edge inside a uniform band costs --
    # and a fed trace always sits in one. The driven cell moves with the rest,
    # so the feed gap the run reports is the one the mesh built rather than the
    # one it was asked for (MESH-026/027). Nothing the Speed/accuracy slider
    # drives: the mesh is the same size either way. False reproduces the
    # un-nudged lattice, and its gap, exactly (an A/B, a bisect) -- the Advanced
    # pane's own checkbox.
    "mesh_nudge": True,
}


def _scalar(v):
    """Render a Python value as a YAML scalar."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def kv(key, val):
    """One ``key: value`` config line -- the one helper a subclass's own
    block needs."""
    return f"{key}: {_scalar(val)}"


def _reject_negatives(p, keys):
    """Check the knobs whose 0 means "leave it to the runner": a negative one
    is a typo, and every runner-side reaction to it is the wrong kind of quiet
    (mesh_budget_gb silently falls back to the auto budget, min_raster_mm and
    auto_ground_radius_mm fail deep in the run with a config error). Raise
    naming the field instead -- never a silently substituted number."""
    for key in keys:
        if float(p[key]) < 0:
            raise RuntimeError(
                f"{key}: {p[key]} is negative -- give a positive value, or 0 "
                "for the automatic one"
            )


def _relpath(path, base_dir):
    """``path`` relative to ``base_dir`` (the yaml's own folder), with
    forward slashes so the config -- and the run_dir it lives in -- stays
    portable if the user moves or renames the parent folder. The runner
    resolves relative paths against its own cwd, so ``simulate.run_exe``
    launches it with cwd set to this same folder."""
    rel = os.path.relpath(path, base_dir)
    return rel.replace(os.sep, "/")


def _layer_gerber(entry, gerbers, copper_paths):
    """The gerber path for one stackup entry, or "" for a layer that has no
    gerber -- a core/dielectric gap, or an overlay whose layer wasn't plotted.
    Copper foils match the gerber list by name (``collect_stackup`` names each
    foil after its plot suffix, e.g. ``F_Cu``); the silk/paste overlays match
    the ``<kind>_<side>`` roles ``plot_gerbers`` returns, keyed off the F./B.
    prefix KiCad always gives these technical layers."""
    kind = entry["type"]
    if kind == "copper":
        return copper_paths.get(entry["name"], "")
    if kind == "core":
        return ""
    side = "top" if entry["name"][:1].upper() == "F" else "bottom"
    return gerbers.get(f"{kind}_{side}", "")


def _apply_overrides(stackup, p):
    """Fold the Materials picker's per-layer choices into the board-read
    stackup, requiring every conductor/dielectric to have a material source.

    The solder mask is the one layer this can *remove*: the coating is part of
    the board only in a run that asked for it (``include_mask``), so a run that
    did not drops its entries here rather than emitting layers the solver would
    mesh. One that did needs a thickness (the board's own) and an εr, from the
    board or from ``mask_material`` -- the same two sources a dielectric has,
    and the same refusal to invent one.

    ``metal_layers`` and ``substrate_layers`` are the ordered lists the
    Materials UI emits (one item per copper foil / dielectric gap in board
    order): each metal item is ``{"sigma": ...}``; each substrate item is
    ``{"eps": ..., "loss_tangent": ...}`` (a picked material forces both) or
    ``None`` for the "from board stackup" pick, which keeps the board's eps and
    the loss tangent read from the board. There is no invented fallback: a
    copper foil with no metal pick, or a dielectric whose loss has no source at
    all (no board loss tangent and no picked material), blocks the run with a
    message naming the layer -- never a silently defaulted number. Pick a
    substrate material, or set the loss tangent in the board's Physical Stackup,
    to supply a missing loss."""
    metals = p.get("metal_layers") or []
    substrates = p.get("substrate_layers") or []
    mask_material = p.get("mask_material")
    ci = di = 0
    out = []
    for entry in stackup:
        entry = dict(entry)
        if entry["type"] == "mask":
            if not p.get("include_mask"):
                continue  # not part of this board: leave the coating off
            if mask_material is not None:
                entry["eps"] = float(mask_material["eps"])
                entry["loss_tangent"] = float(mask_material["loss_tangent"])
            if not entry.get("thickness_mm") or not entry.get("eps"):
                raise RuntimeError(
                    f"solder mask layer {entry['name']} has no thickness or "
                    "epsilon r -- set them in Board Setup > Physical Stackup, "
                    "choose a solder mask material in the Materials panel, or "
                    "untick 'Simulate the solder mask coating'"
                )
        elif entry["type"] == "copper":
            metal = metals[ci] if ci < len(metals) else None
            ci += 1
            if metal is None:
                raise RuntimeError(
                    f"copper layer {entry['name']} has no metal assigned -- "
                    "choose one in the Materials panel"
                )
            entry["sigma"] = float(metal["sigma"])
        elif entry["type"] == "core":
            sub = substrates[di] if di < len(substrates) else None
            di += 1
            if sub is not None:
                # A picked substrate material forces both eps and loss tangent.
                entry["eps"] = float(sub["eps"])
                entry["loss_tangent"] = float(sub["loss_tangent"])
            elif entry.get("loss_tangent") is None:
                # "From board stackup" but the board gave no loss tangent.
                raise RuntimeError(
                    f"dielectric layer {entry['name']} has no loss tangent -- "
                    "set one in Board Setup > Physical Stackup, or choose a "
                    "substrate material in the Materials panel"
                )
            # else: keep the board's own eps + loss_tangent, already on entry.
        out.append(entry)
    return out


class ConfigWriter:
    """One run's config file, block by block.

    Subclass it, set ``CONFIG_VERSION`` to the schema the flow's own binary
    reads, and implement ``ports()``. Override any other block that has to
    differ; do not branch inside one.
    """

    # The schema this flow's runner reads, as semver. The reader refuses a
    # config whose MAJOR differs from the build's (CFG-005), so a writer must
    # track its own binary's major -- and a major bump is not always a key
    # change: the schema also majors when the same config on the same board
    # comes out different (a derived mesh that moves, geometry that is newly
    # read), because carrying it over unchanged would silently simulate
    # another board.
    CONFIG_VERSION = ""

    DEFAULTS = _DEFAULTS

    # The file, in order. Each name is a method returning its lines.
    BLOCKS = (
        "header",
        "geometry",
        "stackup_block",
        "copper_model",
        "sim_params",
        "mesh",
        "outputs",
        "ports",
    )

    def __init__(self, gerbers, stack, params=None):
        self.gerbers = gerbers
        self.stack = stack
        self.p = dict(self.DEFAULTS)
        self.p.update({k: v for k, v in (params or {}).items() if v is not None})
        self.yaml_dir = ""
        self.outdir = ""
        self.stackup = []

    # --- the file ---------------------------------------------------------
    def write(self, yaml_path):
        """Write the config to *yaml_path*; returns the outdir written into it."""
        self.yaml_dir = os.path.dirname(os.path.abspath(yaml_path))
        self.outdir = self.p.get("outdir") or self.yaml_dir
        self.validate()
        self.stackup = _apply_overrides(self.stack.get("stackup") or [], self.p)

        lines = [line for block in self.BLOCKS for line in getattr(self, block)()]
        text = "\n".join(lines) + "\n"
        os.makedirs(self.yaml_dir, exist_ok=True)
        with open(yaml_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return self.outdir

    def validate(self):
        """What no flow can run without. Raises RuntimeError naming the field.

        A subclass that has more to insist on overrides this and calls up
        first -- the S-parameter flow's finite ``port_resistance`` is the
        example.
        """
        if not self.gerbers.get("edge") or not self.gerbers.get("copper"):
            raise RuntimeError("board needs an Edge.Cuts outline and copper")
        # An entry with no gerber is skipped when the stackup is written, which
        # for the mask would mean a run that asked for the coating quietly
        # solving a board without it. The layers are always plotted, so this is
        # a board that has none enabled.
        if self.p["include_mask"] and not (
            self.gerbers.get("mask_top") or self.gerbers.get("mask_bottom")
        ):
            raise RuntimeError(
                "the solder mask is to be simulated, but the board has no "
                "F.Mask/B.Mask layer to plot -- enable one in Board Setup, or "
                "untick 'Simulate the solder mask coating'"
            )
        _reject_negatives(
            self.p,
            ("mesh_budget_gb", "min_raster_mm", "auto_ground_radius_mm", "cell_max_mm"),
        )
        # The cell and its ceiling are a range, and two ways of typing them are
        # not one: a start above the ceiling (no cell satisfies both) and a
        # feature floor above it (a floor that can never bind on any lattice
        # this config permits). The runner refuses both at config load; refuse
        # them here, in the same words, before a run is prepared -- the rule
        # itself lives with the knobs it is about (cellsize.knobs), which is
        # also what the window captions the pair with while it is being typed.
        clash = cellsize.problem(
            self.p["cell_mm"],
            self.p["cell_max_mm"],
            floors=(
                ("feature_min_cell_mm", self.p["feature_min_cell_mm"]),
                ("via_min_cell_mm", self.p["via_min_cell_mm"]),
            ),
        )
        if clash:
            raise RuntimeError(clash)

    def rel(self, path):
        """*path* relative to the config's own folder."""
        return _relpath(path, self.yaml_dir)

    # --- the blocks -------------------------------------------------------
    def header(self):
        return [
            f"config_version: {self.CONFIG_VERSION}",
            f"# generated by {product.PACKAGE}/config.py",
        ]

    def geometry(self):
        """The board outline and the drills -- the only top-level gerbers.

        Every other gerber rides on the stackup entry it belongs to, so the
        runner reads each layer's artwork off the stack it meshes. Holes need
        no key of their own: the plated drills become via columns, the
        non-plated ones remove laminate and copper as the shapes they are (a
        routed slot is a slot, not two round holes at its ends), and whatever
        the outline layer draws that is not a closed boundary loop -- where
        KiCad puts a mounting slot or a cutout -- is material removed too. The
        schema's optional ``holes:`` gerber is for boards that draw their
        cutouts on a layer of their own, which KiCad does not have, so it is
        never emitted.
        """
        lines = [
            "",
            "# --- geometry (paths relative to this file's folder) ---",
            "# The copper/paste/silk gerbers ride on their stackup entries below;",
            "# only the board outline and the two drill files are top-level. The",
            "# plated drills are via columns; the non-plated ones and anything the",
            "# outline layer draws that is not the board's boundary (a mounting",
            "# slot, a cutout) take laminate and copper out where they sit.",
            f"edge: {self.rel(self.gerbers['edge'])}",
        ]
        for key in ("vias", "npth"):
            if self.gerbers.get(key):
                lines.append(kv(key, self.rel(self.gerbers[key])))
        return lines

    def stackup_block(self):
        """The physical stackup, KiCad board-setup order, top to bottom.

        ``copper`` foils (each with its ``sigma``) and ``core`` gaps
        (``thickness_mm``, ``eps``, ``loss_tangent``) are simulated; ``paste``
        and ``silk`` are geometry-only overlays with no thickness and no
        material. The paste apertures are the ground check's pad signal -- a
        paste aperture on copper IS a pad. The solder mask is between the two:
        an overlay carrying the thickness and permittivity of a coating, and
        emitted only by a run that asked for it (``include_mask`` --
        _apply_overrides has already dropped the entries otherwise).
        """
        lines = [
            "",
            "# --- physical stackup (KiCad board-setup order, top to bottom) ---",
            "# Each layer carries its own gerber `path` (copper/paste/silk/mask); a",
            "# core gap is a bare dielectric with no gerber. copper/core entries are",
            "# simulated (foil z-heights follow from the cumulative dielectric",
            "# thicknesses); paste/silk entries are geometry-only overlays with no",
            "# thickness or material -- the paste apertures are the ground check's",
            "# pad signal (a paste aperture on copper is a pad), silk is",
            "# informational -- and a mask entry, present only when this run asked",
            "# for the coating, carries the thickness and eps it is meshed with.",
            "# An overlay's side comes from its position here:",
            "# before the first copper entry is top, after it is bottom.",
            "stackup:",
        ]
        copper_paths = dict(self.gerbers.get("copper") or [])
        for entry in self.stackup:
            kind = entry["type"]
            path = _layer_gerber(entry, self.gerbers, copper_paths)
            if not path and kind not in ("copper", "core"):
                # An overlay whose layer wasn't plotted (silk while _PLOT_SILK
                # is off, or a board with no paste layer) tells the runner
                # nothing -- leave it out rather than emit a gerber-less entry.
                continue
            prefix = "  - "
            for key in ("type", "name", "thickness_mm", "eps", "loss_tangent", "sigma"):
                if key not in entry:
                    continue
                lines.append(f"{prefix}{key}: {_scalar(entry[key])}")
                prefix = "    "
            if path:
                lines.append(f"{prefix}path: {self.rel(path)}")
                prefix = "    "
            # KiCad plots the paste layer positive -- the drawn regions ARE the
            # stencil apertures, i.e. the pads -- so no `is_negative` here.
            #
            # The grid dump carries every layer but the paste: its apertures sit
            # on the copper cells it marks, so drawing them only overdraws the
            # foil. The layer is here for the ground check, not for the view.
            lines.append(f"{prefix}show_in_grid: {_scalar(kind != 'paste')}")
        return lines

    def copper_model(self):
        return [
            "",
            "# --- copper model ---",
            kv("copper_model", self.p["copper_model"]),
            kv("conformal", bool(self.p["conformal"])),
        ]

    def sim_params(self):
        p = self.p
        return [
            "",
            "# --- simulation parameters ---",
            kv("outdir", self.rel(self.outdir)),
            "# 0 = auto: run until the port rings down (steps wins if both set)",
            kv("time_ns", float(p["time_ns"])),
            kv("steps", int(p["steps"])),
            kv("threads", int(p["threads"])),
            kv("fpattern_ghz", float(p["fpattern_ghz"])),
            kv("fmax_ghz", float(p["fmax_ghz"])),
            kv("flow_ghz", float(p["flow_ghz"])),
            kv("port_resistance", p["port_resistance"]),
        ]

    def mesh(self):
        """Every mesh knob, in schema order.

        Two are conditional rather than always spelled out -- ``adaptive_n``
        and the ``refine_n``/``refine_adaptive`` pair -- because the runner
        rejects each of them without the switch it grades.
        """
        p = self.p
        lines = [
            kv("cell_mm", float(p["cell_mm"])),
            "# 0 = no ceiling. A third term in the min above, never a target: the",
            "# base cell a run builds -- including one the budget re-mesh below",
            "# lands on -- is never coarser than this, and a ceiling above the cell",
            "# the rule already picked does nothing (MESH-029 refuses a re-mesh",
            "# that would land past it)",
            kv("cell_max_mm", float(p["cell_max_mm"])),
            "# N of the auto cell's copper term: cell <= driven copper / N",
            kv("copper_cells", int(p["copper_cells"])),
            kv("margin_mm", float(p["margin_mm"])),
            kv("coarse_air", bool(p["coarse_air"])),
            kv("air_cell_mm", float(p["air_cell_mm"])),
            kv("mesh_ratio", float(p["mesh_ratio"])),
            "# 0 = auto: a fraction of this machine's RAM. Priced before anything",
            "# per-cell is allocated, so an oversized lattice is caught before it is",
            "# built rather than by the OOM killer half way through.",
            kv("mesh_budget_gb", float(p["mesh_budget_gb"])),
            "# what a lattice over that budget does: true re-resolves the whole run",
            "# at the finest cell_mm that fits (once, warning MESH-028); false",
            "# refuses it (MESH-014) and names the same cell instead",
            kv("mesh_fit_cell", bool(p["mesh_fit_cell"])),
            kv("rotation_deg", float(p["rotation_deg"])),
            kv("substrate_cell_mm", float(p["substrate_cell_mm"])),
            kv("boundary", p["boundary"]),
            kv("pml_cells", int(p["pml_cells"])),
            kv("refine_xy", bool(p["refine_xy"])),
            kv("feature_max_mm", float(p["feature_max_mm"])),
            kv("feature_min_cell_mm", float(p["feature_min_cell_mm"])),
            kv("via_min_cell_mm", float(p["via_min_cell_mm"])),
        ]
        if p["refine_xy"]:
            # refine_n / refine_adaptive act only through refine_xy -- the
            # runner rejects either key with refine_xy: false -- so emit them
            # only when it's on; an Advanced refine_n typed with refine_xy off
            # is then harmlessly ignored, same as adaptive_n below.
            lines.append(kv("refine_n", int(p["refine_n"])))
            lines.append(kv("refine_adaptive", bool(p["refine_adaptive"])))
        lines += [
            # Post-mesh nudging, unconditional -- unlike the refine knobs above
            # it needs nothing else turned on, and with refine_xy on it simply
            # runs on the refined mesh.
            "# slide the built lattice's nodes onto axis-aligned material edges --",
            "# copper first, then the board outline; no node created or deleted,",
            "# so the cells and the memory don't move (dt may give up to 5%, and",
            "# the driven cell moves too, so the feed gap is what got built)",
            kv("mesh_nudge", bool(p["mesh_nudge"])),
            # Adaptive rastering. adaptive_n has no runner default, and an
            # adaptive_n without adaptive: true is a config error, so emit the
            # reach only when adaptive is on -- an Advanced adaptive_n typed
            # while the slider is off an adaptive stop is then harmlessly
            # ignored.
            kv("adaptive", bool(p["adaptive"])),
        ]
        if p["adaptive"]:
            lines.append(kv("adaptive_n", float(p["adaptive_n"])))
        lines += [
            kv("auto_ground", bool(p["auto_ground"])),
            "# 0 = derive the strap search's disk from the port (half the feed gap",
            "# + two run limits + a trace width)",
            kv("auto_ground_radius_mm", float(p["auto_ground_radius_mm"])),
            kv("ground_check", p["ground_check"]),
            "# floor for the ground check's copper-connectivity raster, not the mesh;",
            "# 0 = auto: min(0.1 mm, narrowest fed trace / 2)",
            kv("min_raster_mm", float(p["min_raster_mm"])),
        ]
        return lines

    def outputs(self):
        """A run writes data and nothing else, and always writes both dumps,
        so there is no key here for choosing them. ``output_json`` asks for the
        data dump a second time as bare JSON, which is a different file, not a
        different deliverable."""
        data, grid = product.DUMPS
        return [
            "",
            f"# --- outputs to write. Both dumps ({data}.js, {grid}.js) are",
            "# always written; output_json asks for the data one as bare JSON too.",
            kv("output_json", bool(self.p["output_json"])),
            "",
        ]

    def ports(self):
        """The ``feed_ports:`` list -- one entry per port, in port order.

        The flow's own: one port for an antenna, N for an S-parameter run, and
        each is only a point plus a direction (the runner infers the driven
        trace from the copper under the point and severs a one-cell gap on the
        simulation grid).
        """
        raise NotImplementedError

    def port_entry(self, point, layer):
        """One ``feed_ports`` entry: a point + direction on a copper layer.

        *point* is the ``{"x", "y", "dir_x", "dir_y"}`` dict a placed marker
        (``feed_marker.feed_dict``) or a wizard produces; *layer* is the copper
        foil it sits on, by its stackup entry name (e.g. ``F_Cu``).
        """
        fields = (
            ("x_mm", float(point["x"])),
            ("y_mm", float(point["y"])),
            ("layer", layer),
            ("dir_x", float(point["dir_x"])),
            ("dir_y", float(point["dir_y"])),
        )
        lines = []
        prefix = "  - "
        for key, value in fields:
            lines.append(f"{prefix}{key}: {_scalar(value)}")
            prefix = "    "
        return lines

    def top_copper(self):
        """The name of the board's top copper foil -- the default port layer."""
        return self.gerbers["copper"][0][0]
