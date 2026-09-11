"""The EM-simulation pipeline: what a plugin does with the board.

Turns the board open in pcbnew into a finished FDTD report, sourcing the
stackup and gerbers straight from the live board:

    1. collect_stackup(board)  -> per-layer physical stackup (thickness_mm and
                                   eps for every copper foil and dielectric
                                   gap) parsed from the saved .kicad_pcb's
                                   Physical Stackup block (stackup.py); the
                                   GUI prompts to save an out-of-date board
                                   first. Raises if any thickness is unset
    2. plot_gerbers(board,dir) -> writes the copper/edge/paste gerbers and
                                   PTH/NPTH drills, returning the resolved paths
                                   by role
    3. write_config(...)       -> emits the runner YAML in-process via the
                                   plugin-local config module (the plugin
                                   depends on nothing in ./ems)
    4. run_exe(..., grid_only) -> the bundled solver binary: --grid-only
                                   first (writes the pcb_grid.js lattice dump
                                   fast), then the run (writes the pcb_data.js
                                   dump: every series it measured). Those are
                                   the whole deliverable -- the solver writes
                                   data, never pages. The binary overwrites both
                                   in the outdir, so the GUI archives each run's
                                   dumps into a timestamped folder
                                   (results/<stamp>/) via archive_dump, and
                                   latest_result finds the newest one
    5. viewer_url(...)         -> what draws them: the plugin's own copy of the
                                   viewer (emkit/viewer/), installed
                                   once per board under simulation/viewer/ and
                                   opened pointed at a dump

The board-touching steps (1, 2) must run on the wx main thread; the two
run_exe calls are the slow part and are meant to be driven from a worker
thread (see gui.start_simulation). Everything here is stdlib + pcbnew only, and
pcbnew is imported lazily so the pure helpers stay unit-testable off-KiCad.
"""

import hashlib
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ... import product
from . import builds, hostos

# Non-copper layers: (plot suffix, pcbnew layer-id attr, config role). The
# suffix becomes "<board>-<suffix>.gbr"; the role keys the paths passed to the
# config emitter.
_AUX_LAYERS = [
    ("Edge_Cuts", "Edge_Cuts", "edge"),
    ("F_Paste", "F_Paste", "paste_top"),
    ("B_Paste", "B_Paste", "paste_bottom"),
    ("F_Mask", "F_Mask", "mask_top"),
    ("B_Mask", "B_Mask", "mask_bottom"),
    ("F_Silk", "F_SilkS", "silk_top"),
    ("B_Silk", "B_SilkS", "silk_bottom"),
]

# Solder paste feeds the solver's ground detection: a paste aperture over
# copper IS a pad, and pad density is one of the signals that picks the board's
# ground pour, so the paste gerbers are plotted and handed to config.write_yaml.
# The solder mask is plotted unconditionally too, though only a run that asks
# for it emits the entries (config's ``include_mask``): the alternative is a
# flag threaded through every caller of this function, where the one that
# forgot it would drop the coating out of a run that asked for it *silently* --
# an unplotted layer is an entry with no gerber, and an entry with no gerber is
# skipped. Two gerbers are the cheaper mistake.
# Silkscreen stays informational only -- the solver uses it for nothing, so
# plotting it just costs time and leaves an unused gerber in the run folder.
# Flip this to True to plot silk again. The edge outline is never gated -- the
# runner requires it.
_PLOT_SILK = False


# --------------------------------------------------------------------------- #
# Pre-flight
# --------------------------------------------------------------------------- #
# Bundled per-problem HTML guides, shipped as plugin assets like vendor/ and
# binaries/. Plain static HTML: each links ../assets/palette.css and
# ../assets/help_theme.css and is displayed straight from the install tree, so
# there is nothing to render, template or copy at display time. (A stylesheet
# link resolves from a file:// page; only ES-module fetches are CORS-blocked,
# which is why nothing the plugin shows is an ES module -- see docs/viewer.md.)
# Scripts and network resources stay banned: KiCad's WebView is offline.
# Where a bundled guide may be: the plugin's own help/ first, the core's
# second. A guide lives beside the check that names it -- the stackup and
# board ones here, an antenna's area advice in the plugin -- and a caller asks
# for a file name without having to know which of the two wrote it.
_HELP_DIRS = (
    Path(__file__).resolve().parents[2] / "help",
    Path(__file__).resolve().parents[1] / "help",
)

# Short caption per problem id, used as the help window's title suffix.
_PROBLEM_TITLES = {
    "board-unsaved": "Save the board first",
    "no-stackup": "Set up the physical stackup",
    "copper-count": "Copper layer count mismatch",
    "copper-thickness": "Copper thickness missing",
    "dielectric-thickness": "Dielectric thickness missing",
    "dielectric-eps": "Dielectric permittivity missing",
    "dielectric-count": "Dielectric gap count",
    "no-outline": "Board outline missing",
    "mask-material": "Solder mask material missing",
    "stackup-dirty": "Unsaved stackup changes",
    "docker-not-ready": "The container is not ready",
}

# Where a problem's guide is not help/<id>.html. One entry so far, and it is
# the shape of the exception that matters: the container has seven states with
# one story behind them (install it, build it, rebuild it), so they share a
# page rather than repeating it seven times. Data rather than an argument at
# the call site, so that everything reading the catalogue -- including the test
# that insists every id ships a page -- resolves the same file.
_PROBLEM_GUIDES = {
    "docker-not-ready": "docker.html",
}


@dataclass
class Problem:
    """One pre-flight blocker/warning for the GUI banner (see preflight)."""

    id: str  # stable key; also selects the help page help/<id>.html
    severity: str  # "block" (Run disabled) | "warn" (Run prompts/continues)
    message: str  # one line for the banner row
    title: str = ""  # short caption for the help window
    help: str = ""  # help page filename under emkit/help/
    # The reporting check's own sub-state, where it has one worth acting on:
    # the container probe's (sim.container.probe -- no_image, stale, ...). One
    # id covers every way a container can be unready, because they are one
    # story and one guide; the window offers a *different button* for the two
    # of them it can fix from here, and that needs the finer answer without a
    # frontend picking sentences apart to get it.
    state: str = ""

    def __post_init__(self):
        self.title = self.title or _PROBLEM_TITLES.get(self.id, self.id)
        self.help = self.help or _PROBLEM_GUIDES.get(self.id) or f"{self.id}.html"


def guide_page(filename):
    """The path of the bundled guide ``help/<filename>``, ready for the viewer
    to load. Returns None when the asset is missing (partial install) -- the
    GUI then says so rather than opening a blank viewer.

    The guide is displayed where it is installed, never copied: its stylesheet
    links are relative to the tree it is installed in and only resolve there.

    Not every guide belongs to a pre-flight problem: the settings reference the
    About page opens is one of the whole form. So the lookup is by file name,
    and ``help_page`` is the Problem-shaped way in."""
    for directory in _HELP_DIRS:
        src = directory / filename
        if src.is_file():
            return str(src)
    return None


def help_page(problem):
    """The path of ``problem``'s bundled HTML guide (``guide_page`` of its
    ``help`` file), or None when the asset is missing -- the GUI then falls
    back to the banner's one-line message."""
    return guide_page(problem.help)


def stackup_problems(entries, copper_names, basename="the board file"):
    """Validate a parsed stackup (``stackup.read_stackup`` output) against the
    board's enabled copper layers; returns [Problem] in file order. Pure (no
    pcbnew), shared by :func:`preflight` (the banner) and
    :func:`collect_stackup` (which raises the first message), so the
    predicates live in exactly one place."""
    hint = " in Board Setup > Physical Stackup (then save the board)"
    if entries is None:
        return [
            Problem(
                "no-stackup",
                "block",
                f"{basename} has no physical stackup; open Board Setup > "
                "Physical Stackup, set every thickness, and save the board",
            )
        ]

    problems = []
    n_file_cu = sum(1 for e in entries if e["kind"] == "copper")
    if n_file_cu != len(copper_names):
        problems.append(
            Problem(
                "copper-count",
                "block",
                f"the saved stackup lists {n_file_cu} copper layer(s) but the "
                f"board has {len(copper_names)} enabled; fix the layer count"
                f"{hint}",
            )
        )

    # Walk the entries in board order; a dielectric gap is a maximal run of
    # consecutive dielectric entries (collect_stackup merges each run into
    # one core), so count runs against the copper-1 expectation.
    gaps, in_gap, cu = 0, False, 0
    for e in entries:
        kind = e["kind"]
        if kind == "dielectric":
            if not in_gap:
                gaps += 1
                in_gap = True
            for t, eps, _tand in e["sublayers"]:
                if not t or t <= 0:
                    problems.append(
                        Problem(
                            "dielectric-thickness",
                            "block",
                            f"dielectric layer '{e['name']}' has no thickness "
                            f"set{hint}",
                        )
                    )
                # No εr default either: resonance scales with sqrt(eps).
                if not eps or eps <= 0:
                    problems.append(
                        Problem(
                            "dielectric-eps",
                            "block",
                            f"dielectric layer '{e['name']}' has no epsilon r "
                            f"set{hint}",
                        )
                    )
                # loss_tangent is NOT required here: a dielectric with no board
                # loss can still get one from a picked substrate material, so
                # that check lives in config._apply_overrides (which sees the
                # material picks), not in this board-only preflight.
            continue
        in_gap = False
        if kind == "copper":
            name = copper_names[cu] if cu < len(copper_names) else e["name"]
            t = e["thickness_mm"]
            if not t or t <= 0:
                problems.append(
                    Problem(
                        "copper-thickness",
                        "block",
                        f"copper layer {name} has no thickness set{hint}",
                    )
                )
            cu += 1
        # Nothing to validate on an overlay here: silk and paste are geometry
        # and carry no constants at all, and the solder mask's are required
        # only of a run that asked to simulate it -- that check needs the run's
        # own parameters and is mask_problems, below.

    expected = max(1, len(copper_names) - 1)
    if gaps != expected:
        problems.append(
            Problem(
                "dielectric-count",
                "block",
                f"the saved stackup has {gaps} dielectric gap(s) for "
                f"{len(copper_names)} copper layer(s) (expected {expected}); "
                f"fix the dielectrics{hint}",
            )
        )
    return problems


def mask_problems(entries, params, basename="the board file"):
    """What stops a run that asked to simulate the solder mask (``params``, the
    run parameters: ``include_mask`` and the ``mask_material`` the Materials
    pane picked for it). [] for a run that did not ask -- the coating is then
    not part of the board being solved and nothing about it can be missing.

    A coating is a dielectric slab: it needs a thickness and a permittivity,
    and neither has a safe default (a run that meshed 0.01 mm of nothing would
    quietly answer for a different board). The thickness has one source, the
    board's own stackup; the εr has two, the board and the mask material pick,
    and only a layer with neither blocks. Pure (no pcbnew), over
    ``stackup.read_stackup`` entries, so the banner and the command line ask
    the same question of the same file."""
    if not params.get("include_mask"):
        return []
    where = " in Board Setup > Physical Stackup (then save the board)"
    masks = [e for e in entries or [] if e["kind"] == "mask"]
    if not masks:
        return [
            Problem(
                "mask-material",
                "block",
                f"the solder mask is to be simulated, but {basename} has no "
                f"solder mask layer in its stackup; enable one{where}, or "
                "untick 'Simulate the solder mask coating' in "
                "Advanced > Materials",
            )
        ]
    # A Custom material pick with nothing usable typed into it (the pane hands
    # the reason over rather than raising into the banner, see
    # AdvancedSection.mask_params): the pick names no material, so no layer
    # below can take its εr from one.
    typed = params.get("mask_material_error")
    if typed:
        return [
            Problem(
                "mask-material",
                "block",
                f"the solder mask is to be simulated, but its material is not "
                f"set: {typed}",
            )
        ]
    material = params.get("mask_material")
    problems = []
    for entry in masks:
        name = entry["name"]
        if not entry.get("thickness_mm"):
            problems.append(
                Problem(
                    "mask-material",
                    "block",
                    f"solder mask layer '{name}' has no thickness set{where}",
                )
            )
        if material is None and not entry.get("eps"):
            problems.append(
                Problem(
                    "mask-material",
                    "block",
                    f"solder mask layer '{name}' has no epsilon r set{where}, "
                    "and no mask material is picked in Advanced > Materials",
                )
            )
    return problems


def preflight(board, params=None):
    """Everything that would stop a run, as a structured list -- the GUI
    renders it in the pre-flight banner and disables Run while any "block"
    problem exists, instead of discovering the same RuntimeErrors mid-run.
    collect_stackup / plot_gerbers / the config writer keep their raises as the
    last-line guard; this consolidates the same predicates up front. Blockers
    come first, warnings last.

    ``params`` are the run parameters as far as they are known (the window's
    Advanced pane, or a saved form -- emkit.formparams): the board alone cannot say
    whether the solder mask is part of this run, and what the mask needs
    depends on that. Without them only the board-only checks run.

    Everything here is a question about *this board*. The other kind of
    run-stopper -- whether this machine's container is ready -- is
    :func:`container_problems`, asked separately by each of the three places
    that can start a run (every banner on a page that starts one, the
    ``preflight`` verb, a run's own launch). It was folded in here once, which
    read well until a designer's banner needed the same row: a board check that
    quietly probed Docker is a board check nobody can call cheaply."""
    from ..kicad.stackup import read_stackup

    params = params or {}
    problems = []
    fname = board.GetFileName()
    saved = bool(fname) and os.path.isfile(fname)
    if not saved:
        problems.append(
            Problem(
                "board-unsaved",
                "block",
                "the board has never been saved -- the stackup is read from the "
                ".kicad_pcb file; save the board first",
            )
        )
    else:
        entries = read_stackup(fname)
        basename = os.path.basename(fname)
        problems += stackup_problems(
            entries, [s for s, _ in copper_layers(board)], basename
        )
        problems += mask_problems(entries, params, basename)

    if _outline_missing(board):
        problems.append(
            Problem(
                "no-outline",
                "block",
                "board needs an Edge.Cuts outline and at least one copper layer",
            )
        )

    if saved and board_needs_save(board):
        problems.append(
            Problem(
                "stackup-dirty",
                "warn",
                "the Physical Stackup in the editor differs from the saved "
                ".kicad_pcb; save the board (Run also offers Save & Continue)",
            )
        )
    return problems


def container_problems():
    """Whether the container this machine solves in is ready, as [Problem].

    Not a board question at all, which is why it is its own function -- but it
    is a run-stopper, and the alternative to reporting it up front is worse:
    found only at launch, "Docker isn't running" is a failed spawn in the
    middle of a log, minutes of gerber plotting after the user pressed Run.
    Reported alongside the pre-flight, it is a row in the banner with the fix
    on it, before anything has been written.

    Whoever can start a run asks this. In the window that is the banner base
    (gui.sections.banner.container_rows, which caches the answer for a few
    seconds because a banner refreshes on a keystroke); on the command line it
    is the ``preflight`` verb and ``launch.prepare``.

    Nothing is asked unless this machine actually solves in a container: on
    Linux and Windows with the tick off, this costs nothing at all. Where it
    does ask, it is one short call to the engine.

    The message is the probe's own (sim.container.probe) -- state and remedy,
    per host -- so the banner, the command line and a refused run say the same
    thing.
    """
    from .. import hostprefs

    if not hostprefs.use_docker():
        return []
    from . import container

    try:
        status = container.status(kicad_version=_host_kicad())
    except Exception as exc:  # a probe must never be what stops the window
        return [Problem("docker-not-ready", "block", str(exc))]
    if status.ready:
        return []
    return [
        Problem(
            "docker-not-ready",
            "block",
            f"{status.detail}. {status.remedy}".strip(),
            state=status.state,
        )
    ]


def _host_kicad():
    """This KiCad's ``(major, minor)``, or None where there is no pcbnew --
    which is a real case (a command line on a headless box) and not a
    failure."""
    try:
        from ..kicad.version import get_kicad_version

        return get_kicad_version()
    except Exception:
        return None


def _outline_missing(board):
    """True when the board has no Edge.Cuts outline (degenerate edge bounding
    box) or no enabled copper layer -- plot_gerbers would fail on it."""
    if not copper_layers(board):
        return True
    bb = board.GetBoardEdgesBoundingBox()
    return bb.GetWidth() <= 0 or bb.GetHeight() <= 0


# --------------------------------------------------------------------------- #
# Stackup
# --------------------------------------------------------------------------- #
def collect_stackup(board):
    """Physical stackup, top to bottom, parsed from the saved .kicad_pcb
    file -- the ``(stackup ...)`` block Board Setup > Physical Stackup
    writes. pcbnew's ``GetStackupDescriptor()`` binding is an opaque
    SwigPyObject in some KiCad builds, so the file is the source of truth;
    ``gui.on_run`` keeps it current by prompting to save when the in-memory
    board differs from disk (see ``board_needs_save``).

    There is no safe default for a missing thickness or permittivity --
    guessing would silently distort the simulated impedance/resonance -- so
    this raises RuntimeError when the board was never saved, the file has no
    stackup block, its copper layers don't line up with the enabled ones, or
    any copper/dielectric entry has no thickness (or dielectric no epsilon_r)
    set. The stackup checks are the shared :func:`stackup_problems`
    predicates (the same ones the pre-flight banner shows before Run); the
    first problem's message is raised, so this stays the last-line guard
    even if the GUI skipped preflight.

    Returns a dict with the ordered ``stackup`` list plus
    ``substrate_thickness_mm``/``copper_thickness_mm``/``copper_layer_count``
    summaries for the GUI log.
    """
    from ..kicad.stackup import read_stackup

    copper_pairs = copper_layers(board)  # [(suffix, layer_id), ...], top->bottom
    if not copper_pairs:
        raise RuntimeError("board has no enabled copper layers")

    fname = board.GetFileName()
    if not fname or not os.path.isfile(fname):
        raise RuntimeError(
            "the board has never been saved -- the stackup is read from the "
            ".kicad_pcb file; save the board and run again"
        )
    entries = read_stackup(fname)
    problems = stackup_problems(
        entries, [s for s, _ in copper_pairs], os.path.basename(fname)
    )
    if problems:
        raise RuntimeError(problems[0].message)

    # Walk the file entries in board order. A dielectric gap may span
    # several plies (KiCad sublayers, or back-to-back core/prepreg
    # entries); they accumulate in `pending` and merge into one core entry
    # at the next non-dielectric layer.
    stackup, cores, pending = [], [], []
    gap_name = ""
    cu = 0

    def flush_gap():
        t, eps, tand = _merge_dielectrics(pending)
        cores.append(t)
        # The board carries the dielectric loss as a loss tangent; pass it on
        # when present. A picked substrate material overrides it in
        # config._apply_overrides, which blocks the run only when neither the
        # board nor a material supplies a loss.
        core = {"type": "core", "name": gap_name, "thickness_mm": t, "eps": eps}
        if tand is not None:
            core["loss_tangent"] = tand
        stackup.append(core)
        pending.clear()

    for e in entries:
        kind = e["kind"]
        if kind == "copper":
            if pending:
                flush_gap()
            # sigma (foil conductivity) is filled in by the Materials picker in
            # config._apply_overrides; the board stackup carries no conductivity.
            stackup.append(
                {
                    "type": "copper",
                    "name": copper_pairs[cu][0],
                    "thickness_mm": round(e["thickness_mm"], 4),
                }
            )
            cu += 1
        elif kind == "dielectric":
            if not pending:
                gap_name = e["name"]
            pending.extend(e["sublayers"])
        else:
            # An overlay (silk/paste/mask): its name and its place in the stack,
            # which is what tells the runner the side it belongs to (before the
            # first copper entry = top), plus whatever constants the board
            # states for it -- none for silk and paste, thickness and eps for
            # the solder mask, which is a coating a run may mesh rather than
            # geometry alone. config._layer_gerber folds in its gerber, and
            # config._apply_overrides drops the mask again unless this run
            # asked for it.
            if pending:
                flush_gap()
            overlay = {"type": kind, "name": e["name"].replace(".", "_")}
            for key in ("thickness_mm", "eps", "loss_tangent"):
                if e.get(key) is not None:
                    overlay[key] = e[key]
            stackup.append(overlay)
    if pending:
        flush_gap()

    first_cu = next(x for x in stackup if x["type"] == "copper")
    return {
        "stackup": stackup,
        "substrate_thickness_mm": round(sum(cores), 4),
        "copper_thickness_mm": first_cu["thickness_mm"],
        "copper_layer_count": len(copper_pairs),
    }


def _merge_dielectrics(subs):
    """Collapse the plies of one dielectric gap (KiCad sublayers, e.g.
    prepreg + core) into a single physical entry: thicknesses add, eps and
    loss tangent are thickness-weighted. Each sublayer is an
    ``(mm, eps, loss_tangent)`` triple; the loss tangent comes back as None if
    any ply omits it (the caller then leaves the loss to a material pick). Pure
    (no pcbnew), so it stays unit-testable."""
    total = sum(t for t, _, _ in subs)
    eps = sum(t * e for t, e, _ in subs) / total if total > 0 else subs[0][1]
    if any(ld is None for _, _, ld in subs):
        tand = None
    elif total > 0:
        tand = sum(t * ld for t, _, ld in subs) / total
    else:
        tand = subs[0][2]
    return (round(total, 4), round(eps, 3), None if tand is None else round(tand, 5))


def board_needs_save(board):
    """True when the Physical Stackup in the editor differs from the one in
    the .kicad_pcb on disk (or the file is missing). Only the stackup is
    read from the file -- the gerbers are plotted from the live board -- so
    unrelated unsaved edits (moved traces etc.) neither matter nor prompt.
    pcbnew exposes no reliable dirty flag to plugins, so detection is: save
    the board to a temp file and compare the two ``(stackup ...)`` blocks
    (KiCad's writer is deterministic). Errs on the side of True (prompting
    is safe; silently simulating a stale stackup is not)."""
    import tempfile

    from ..kicad.stackup import stackup_text

    fname = board.GetFileName()
    if not fname or not os.path.isfile(fname):
        return True
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "compare.kicad_pcb")
            _save_board_file(tmp, board, skip_settings=True)
            current = stackup_text(tmp)
        return current != stackup_text(fname)
    except Exception:
        return True


def save_board(board):
    """Save the board over its own .kicad_pcb (the user already confirmed
    in the GUI). Note KiCad's editor keeps its own dirty flag, which a
    plugin save doesn't clear -- the title bar may still show '*'."""
    _save_board_file(board.GetFileName(), board, skip_settings=False)


def _save_board_file(path, board, skip_settings):
    import pcbnew

    try:  # aSkipSettings (don't rewrite the .kicad_pro) needs KiCad 7+
        ok = pcbnew.SaveBoard(path, board, skip_settings)
    except TypeError:
        ok = pcbnew.SaveBoard(path, board)
    if not ok:
        raise RuntimeError(f"could not save the board to {path}")


def project_dir(board):
    """The folder the plugin puts its own folders in: the board file's own
    directory (the KiCad project), or a temp folder when the board is unsaved
    and has no project directory yet."""
    import tempfile

    name = board.GetFileName()
    if name:
        return Path(name).resolve().parent
    return Path(tempfile.gettempdir()) / "antenna_designer"


def output_dir(board):
    """The ``simulation`` folder holding every input and output for this board.

    It lives beside the board file (under the KiCad project directory), so the
    gerbers, config and run results stay with the project.
    """
    return project_dir(board) / "simulation"


def library_dir(board):
    """The folder holding the generated footprint library (``antenna.pretty``
    is created inside it by design/footprints.py).

    It sits *beside* the simulation folder rather than inside it: the library
    is a board asset the user keeps and may re-place from, while everything
    under ``simulation/`` is regenerated output that can be deleted wholesale
    without losing anything. Burying the library there made deleting the sim
    results take the placed footprints' source with them."""
    return project_dir(board)


def scan_dir(board, design_key):
    """The wizard scan's work folder for ``board``
    (``simulation/wizard/<design>/``): where a scan plots its gerbers, runs its
    candidates and writes the combined scan_report / scan_grid views. One place
    names it, so the scan that writes there and the GUI that re-opens its views
    can't drift apart -- and each design gets its own subfolder, so scanning one
    topology never overwrites another's results."""
    return output_dir(board) / "wizard" / design_key


# --------------------------------------------------------------------------- #
# Gerber + drill export
# --------------------------------------------------------------------------- #
def copper_layers(board):
    """Enabled copper layers in stack order (top -> inner -> bottom) as
    (suffix, layer_id) pairs. The order is preserved into the config's copper
    list, which is exactly how the runner stacks the foils. Public: the GUI
    also uses it to build one material row per layer (gui/board.py)."""
    import pcbnew

    pairs = [("F_Cu", pcbnew.F_Cu)]
    count = board.GetCopperLayerCount()
    for n in range(1, count - 1):  # inner layers between the two faces
        lid = getattr(pcbnew, f"In{n}_Cu", None)
        if lid is not None and board.IsLayerEnabled(lid):
            pairs.append((f"In{n}_Cu", lid))
    if count > 1:
        pairs.append(("B_Cu", pcbnew.B_Cu))
    return pairs


def plot_gerbers(board, gerber_dir):
    """Plot the gerbers + drills the runner needs into ``gerber_dir``.

    Returns a dict of resolved paths keyed by role (``edge``, ``copper`` as an
    ordered [(name, path), ...], ``vias``/``npth`` drills, and one
    ``<overlay kind>_<side>`` role per plotted overlay -- ``paste_top`` /
    ``paste_bottom``, ``mask_*``, ``silk_*``; the config emitter matches a
    stackup entry to
    its gerber by exactly that convention, see config._layer_gerber).
    Filenames come from explicit per-layer suffixes, so they don't
    depend on KiCad's Protel/extension naming setting. The feed is not a gerber:
    it is resolved to a point and written into the config's ``feed_ports``.
    """
    import pcbnew

    gerber_dir = str(gerber_dir)
    os.makedirs(gerber_dir, exist_ok=True)
    # Drop every gerber/drill from a previous run first, so a stale file can
    # never be picked up by this run's config.
    for name in os.listdir(gerber_dir):
        if name.endswith((".gbr", ".drl")):
            os.remove(os.path.join(gerber_dir, name))

    pc = pcbnew.PLOT_CONTROLLER(board)
    opts = pc.GetPlotOptions()
    opts.SetOutputDirectory(gerber_dir)
    opts.SetFormat(pcbnew.PLOT_FORMAT_GERBER)
    opts.SetUseGerberProtelExtensions(False)
    opts.SetUseGerberX2format(False)
    opts.SetSubtractMaskFromSilk(False)
    opts.SetPlotFrameRef(False)
    # Gerber coordinates must equal the board coordinates the drills use, so
    # keep auxiliary-origin off (the runner works in raw gerber mm).
    if hasattr(opts, "SetUseAuxOrigin"):
        opts.SetUseAuxOrigin(False)

    def plot(suffix, layer_id):
        pc.SetLayer(layer_id)
        pc.OpenPlotfile(suffix, pcbnew.PLOT_FORMAT_GERBER, suffix)
        pc.PlotLayer()
        return pc.GetPlotFileName()

    result = {
        "edge": "",
        "copper": [],
        "vias": "",
        "npth": "",
        "paste_top": "",
        "paste_bottom": "",
        "mask_top": "",
        "mask_bottom": "",
        "silk_top": "",
        "silk_bottom": "",
    }

    for suffix, layer_id in copper_layers(board):
        result["copper"].append((suffix, plot(suffix, layer_id)))
    for suffix, id_name, role in _AUX_LAYERS:
        if role.startswith("silk") and not _PLOT_SILK:
            continue  # silk is informational only -- skip it

        layer_id = getattr(pcbnew, id_name, None)
        if layer_id is not None and board.IsLayerEnabled(layer_id):
            result[role] = plot(suffix, layer_id)
    pc.ClosePlot()

    for name in _plot_drills(board, gerber_dir):
        path = os.path.join(gerber_dir, name)
        if "-NPTH" in name:
            result["npth"] = path
        elif "-PTH" in name:
            result["vias"] = path

    if not result["edge"] or not result["copper"]:
        raise RuntimeError(
            "board needs an Edge.Cuts outline and at least one copper layer"
        )
    return result


def _plot_drills(board, gerber_dir):
    """Write separate -PTH.drl / -NPTH.drl Excellon files (unmerged, so the
    runner can drill plated vias and non-plated holes independently)."""
    import pcbnew

    from ..kicad.compat import vec2

    writer = pcbnew.EXCELLON_WRITER(board)
    writer.SetOptions(False, False, vec2(), False)  # merge PTH/NPTH = off
    writer.SetFormat(True)  # metric
    writer.CreateDrillandMapFilesSet(gerber_dir, True, False)
    return [f for f in os.listdir(gerber_dir) if f.endswith(".drl")]


# --------------------------------------------------------------------------- #
# Tool discovery + config + run
# --------------------------------------------------------------------------- #
# Where to look for the binaries before the install's own tree: a folder named
# by the environment, which is how a developer points a plugin at a solver they
# have just built. The name is the product's own -- two plugins installed side
# by side drive two different solvers, and one variable steering both would
# hand each of them the other's binary.
SIM_ROOT_ENV = f"{product.NAME_KEY.upper()}_SIM_ROOT"


def locate():
    """The bundled simulator binary this host will run *natively*:
    ``(solver_exe, root)``, or a raise that says why there is none.

    Every native launch starts here -- a run, a wizard scan -- so it is also
    the one place that decides *which* of the bundled builds this machine gets
    (sim.builds).

    Search order: ``$<PRODUCT>_SIM_ROOT`` -> the plugin's own parents
    (installer bundles it under the package; dev checkouts have it at the repo
    root).

    On a machine no build ships for this raises without searching, and says
    what is true rather than what is missing: macOS has no native solver
    because its solver runs in a container. Searching would be worse than
    pointless -- a Mac install carries the Linux builds so that its container
    has something to mount, and "found one, could not exec it" is the error
    that teaches nobody anything.
    """
    if not builds.host_ships():
        raise FileNotFoundError(
            "No native simulator binary ships for this operating system: here "
            f"{product.NAME} runs the solver inside a Docker container. The "
            "binaries in this install are the container's."
        )

    for root in _roots():
        exe = _find_exe(root)
        if exe:
            return str(exe), str(root)

    # The name this machine's own build goes by, not the whole list: the other
    # entries are the fallbacks _find_exe would have taken, and a user being
    # told to go and find a file wants one file named.
    wanted = builds.candidates(product.BINARY)[0]
    raise FileNotFoundError(
        "Could not find the simulator binary. Reinstall the plugin (which "
        f"bundles it), or set the {SIM_ROOT_ENV} environment variable to a "
        f"folder that contains binaries/{wanted}."
    )


def _roots():
    """Where a binary may be, best first: the folder the environment names,
    then the plugin's own parents (an installer bundles them under the package;
    a dev checkout has them at the repository root)."""
    env = os.environ.get(SIM_ROOT_ENV)
    if env:
        yield Path(env).expanduser()
    yield from Path(__file__).resolve().parents


def binaries_dir():
    """The install's ``binaries/`` folder, or None when there is none.

    The *directory*, not a build in it, and that is the question the container
    asks: it mounts the whole folder read-only and launches the build for its
    own architecture out of it, which on a Mac is a Linux build the host could
    not have run. So this cannot go through :func:`locate`, which answers about
    this machine -- but it must search the same places in the same order, or a
    container would run a solver from a directory the rest of the plugin has
    never heard of.
    """
    for root in _roots():
        directory = root / "binaries"
        if any(
            (directory / name).is_file()
            for name in (
                build.filename(product.BINARY) for build in builds.shipped_builds()
            )
        ):
            return str(directory)
    return None


def _find_exe(root):
    """The bundled binary under ``root/binaries/``, or None. Which build of it
    belongs to this machine is sim.builds' answer -- the builds sit side by
    side there, each under the name that says which machine it is for."""
    for name in builds.candidates(product.BINARY):
        p = root / "binaries" / name
        if p.is_file():
            return p
    return None


def write_config(gerbers, stack, params, yaml_path):
    """Emit the runner YAML in-process, seeding it with the measured stack
    thicknesses and the GUI parameters/feed. No dependency on ./ems -- the
    schema lives in the plugin-local ``config`` module."""
    from ... import config

    return config.write_yaml(gerbers, stack, params, yaml_path)


def _spawn(cmd, **popen_kwargs):
    """Start a solver process -- the one place in the plugin that does.

    Two things are true of every launch, wherever it comes from, and are
    stated here rather than at each caller:

    * ``stdin`` is DEVNULL, never inherited. The solver reads nothing, and the
      host's own stdin is not always a handle worth inheriting -- a GUI process
      may have none, and Popen duplicating a stale one is a ``[WinError 6] The
      handle is invalid`` before the solver even starts.
    * the platform's launch flags (hostos.launch_kwargs) come along, which is
      what keeps a console window from flashing up on Windows.

    Everything else -- what to do with the output streams, which folder to run
    in -- is the caller's, and passed through.
    """
    return subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, **popen_kwargs, **hostos.launch_kwargs()
    )


def run_exe(
    solver_exe,
    yaml_path,
    grid_only,
    on_line=None,
    on_proc=None,
    control=None,
    mount=None,
):
    """Run the FDTD binary, streaming stdout lines to ``on_line`` as they
    arrive. ``on_proc`` (if given) receives the Popen right after launch, so
    the caller can hold a handle for cancelling; ``control`` (if given) is
    passed as the solver's ``--control`` file, the channel the
    stop/sample requests are appended to (sim.runcontrol) -- without it the
    run can only be killed. Raises RuntimeError on a non-zero exit.

    Runs with cwd set to the yaml's own folder: config.write_yaml writes every
    gerber/outdir path relative to that folder (so the run_dir stays portable
    if moved), and the runner's ifstream opens are resolved against its cwd.

    stdout and stderr are merged into the pipe the GUI logs from, so no console
    output is lost; stdin and the platform's launch flags are :func:`_spawn`'s
    business.

    ``solver_exe`` may be a path to the binary, as it always was, or a
    ``sim.launch.Launcher`` -- which is how a run happens inside a container
    without this function growing a branch. What the command line *is* belongs
    to that module; what this one does is stream it and check how it ended.

    ``mount`` is for the caller whose config reaches outside its own folder
    (the designer's scan, whose candidates share one set of gerbers): the
    directory all of it lives under, so a containerised run can see the lot.
    """
    from . import launch

    launcher = launch.of(solver_exe)
    cmd, cwd, name = launcher.command(
        yaml_path, grid_only=grid_only, control=control, mount=mount
    )
    proc = _spawn(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd,
        # None for a native run, which is Popen's own "inherit mine"; a
        # container run gets a PATH the engine's helpers are on (launch.env).
        env=launcher.env,
    )
    # A container run is not killed by killing the process we hold: that is the
    # engine's client, and the container outlives it. The name travels on the
    # handle so that runcontrol.kill -- the one place a run is taken down --
    # knows which of the two it has (sim/runcontrol.py).
    proc.container_name = name
    if on_proc:
        on_proc(proc)
    with proc:  # closes the pipe and waits on exit
        for line in proc.stdout:
            line = line.rstrip()
            if line and on_line:
                on_line(line)
    if proc.returncode != 0:
        raise RuntimeError(f"{product.BINARY} exited with code {proc.returncode}")


# The binary always overwrites the same pcb_*.js dumps in the outdir, so each
# run's are archived verbatim into a per-run folder results/<stamp>/
# (archive_dump). The stamp (time.strftime('%Y%m%d-%H%M%S')) names the folder
# and sorts lexically, so latest_result just takes the newest.
#
# That folder is the whole of one run: a run started from the command line
# keeps its record and its log there too (sim.jobs), so the id `run start`
# answers names one directory holding everything that run produced.
_RESULTS_SUBDIR = "results"

# The two kinds of result a run produces, as the GUI names them.
GRID, REPORT = "grid", "report"

# Per kind: the file the binary writes into the outdir, and the viewer page
# that draws it. A dump is the whole deliverable -- the solver writes no HTML
# at all -- and this is the one place the pairing is stated.
DUMPS = {REPORT: f"{product.DUMPS[0]}.js", GRID: f"{product.DUMPS[1]}.js"}
PAGES = {GRID: "grid.html", REPORT: product.REPORT_PAGE}

# The same object as a dump, without the assignment the page needs around it:
# written beside the ``.js`` only when the run asked for it (``output_json``,
# a tick on the Advanced pane and a key in the form). Named here, once, so the
# archiver and every reader of an archived run agree on where it is.
JSON_DUMPS = {kind: f"{Path(name).stem}.json" for kind, name in DUMPS.items()}


def results_dir(run_dir):
    """The archive root (``results/``), one folder per run inside it."""
    return Path(run_dir) / _RESULTS_SUBDIR


def run_results_dir(run_dir, stamp):
    """The per-run folder (``results/<stamp>/``) holding one run's ``pcb_*.js``
    dumps, and -- for a run started from the command line -- its job record and
    its log beside them."""
    return results_dir(run_dir) / stamp


def archive_dump(run_dir, kind, stamp):
    """Archive this run's ``kind`` dump (:data:`DUMPS`) from ``run_dir`` into
    the per-run folder ``results/<stamp>/``, verbatim, and return its path.

    Copied as-is: the archive stays a faithful copy of what the solver wrote,
    and a dump moved nowhere near a viewer is still the file every reader of
    these results -- the pages, :mod:`sim.runinfo`, a script -- opens.

    The bare-JSON flavour travels with it when the run wrote one
    (:data:`JSON_DUMPS`): the outdir holds one of each and the next run
    overwrites both, so the copy kept here is the only one that will still
    describe *this* run afterwards.
    """
    dest_dir = run_results_dir(run_dir, stamp)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / DUMPS[kind]
    shutil.copyfile(Path(run_dir) / DUMPS[kind], dest)
    data = Path(run_dir) / JSON_DUMPS[kind]
    if data.is_file():
        shutil.copyfile(data, dest_dir / data.name)
    return str(dest)


def latest_result(run_dir, kind):
    """Newest archived ``kind`` dump (a Path) across the per-run
    ``results/<stamp>/`` folders, or None. The stamp folder names sort
    chronologically, so plain path order wins."""
    matches = sorted(results_dir(run_dir).glob(f"*/{DUMPS[kind]}"))
    return matches[-1] if matches else None


def result_timestamp(path):
    """Human-readable time an archived dump's run *started*, parsed from its
    folder name (``results/YYYYmmdd-HHMMSS/pcb_*.js``), or None if the parent
    folder isn't a run stamp.

    The stamp is minted when the run is, so this is the run's own clock and
    not the dump's: a solve is minutes and a sampled report can be written
    long after. :func:`dump_written` is the other one.
    """
    m = re.match(r"(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$", Path(path).parent.name)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:{s}"


def dump_written(path):
    """When the dump at ``path`` was written, in :func:`result_timestamp`'s
    format, or None if it cannot be read.

    The file's own mtime, which is the archiving copy's (``archive_dump`` uses
    ``copyfile``, which does not carry one over) -- so it is when this run's
    numbers were put here, within a second of when the solver produced them.
    Worth having beside the run stamp rather than folded into it: the gap
    between the two is the solve, and for a ``run sample`` mid-flight it is
    the whole difference between a fresh reading and a stale one.
    """
    try:
        when = os.stat(path).st_mtime
    except OSError:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))


# --------------------------------------------------------------------------- #
# The viewer
# --------------------------------------------------------------------------- #
# The plugin's own copy of the simulator's front end -- plain HTML/CSS/JS that
# reads a dump and draws it, shipped like the solver binary is (docs/viewer.md
# says what it is and how to keep the copy in step). It is installed into the
# board's simulation folder rather than displayed from the install tree,
# because a page resolves its stylesheet, its scripts and the dump it was
# pointed at *relative to itself*: one copy per board, and every result of that
# board is a relative path away from it.
#
# The folder is copied wholesale, so it holds only what a page loads -- notes
# about it go in docs/, or they end up in every user's project.
_VIEWER_SRC = Path(__file__).resolve().parents[1] / "viewer"
_VIEWER_SUBDIR = "viewer"
# What the installed copy was made from, so a reinstalled or edited viewer
# replaces it and an unchanged one costs a single file read.
_VIEWER_STAMP = ".installed"

# The two things a page can be pointed at, as the query key that names each:
# one run's dump, or a manifest naming several (design.scan_views).
DUMP, SCAN = "d", "scan"


def install_viewer(sim_dir):
    """Put this install's copy of the viewer in ``<sim_dir>/viewer/`` and
    return that folder. Re-copied only when the shipped files have changed, so
    opening a result twice costs one digest of the source tree."""
    dest = Path(sim_dir) / _VIEWER_SUBDIR
    want = _viewer_digest()
    stamp = dest / _VIEWER_STAMP
    try:
        if stamp.read_text(encoding="utf-8") == want:
            return dest
    except OSError:
        pass  # never installed, or a partial copy: install it again
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(_VIEWER_SRC, dest)
    stamp.write_text(want, encoding="utf-8")
    return dest


def _viewer_digest():
    """A fingerprint of the shipped viewer: every file's path, size and
    modification time. Cheap (no file is read) and exact enough -- a
    reinstall rewrites mtimes, and an edit changes one."""
    h = hashlib.sha256()
    for path in sorted(_VIEWER_SRC.rglob("*")):
        if path.is_file():
            st = path.stat()
            rel = path.relative_to(_VIEWER_SRC).as_posix()
            h.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def viewer_url(sim_dir, kind, target, what=DUMP):
    """The URL that shows ``target`` in the viewer: ``kind``'s page
    (:data:`PAGES`) in ``<sim_dir>/viewer/``, with ``target`` named in the
    query relative to that folder (``?d=`` a dump, ``?scan=`` a manifest).

    Relative, not absolute, because the whole point of one installed viewer is
    that the pages and the results move together: a project folder copied to
    another machine still opens. Installs the viewer if it isn't there yet.
    """
    viewer = install_viewer(sim_dir)
    rel = os.path.relpath(os.path.abspath(str(target)), str(viewer))
    query = urllib.parse.quote(rel.replace(os.sep, "/"), safe="/._-")
    return f"{(viewer / PAGES[kind]).resolve().as_uri()}?{what}={query}"
