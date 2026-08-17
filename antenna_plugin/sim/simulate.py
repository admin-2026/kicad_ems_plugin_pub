"""EM-simulation pipeline for the Antenna Designer plugin.

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
    4. run_exe(..., grid_only) -> the bundled monopole binary: --grid-only
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
                                   viewer (antenna_plugin/viewer/), installed
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
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import hostos, os_support

# Non-copper layers: (plot suffix, pcbnew layer-id attr, config role). The
# suffix becomes "<board>-<suffix>.gbr"; the role keys the paths passed to the
# config emitter.
_AUX_LAYERS = [
    ("Edge_Cuts", "Edge_Cuts", "edge"),
    ("F_Paste", "F_Paste", "paste_top"),
    ("B_Paste", "B_Paste", "paste_bottom"),
    ("F_Silk", "F_SilkS", "silk_top"),
    ("B_Silk", "B_SilkS", "silk_bottom"),
]

# Solder paste feeds the solver's ground detection: a paste aperture over
# copper IS a pad, and pad density is one of the signals that picks the board's
# ground pour, so the paste gerbers are plotted and handed to config.write_yaml.
# The solder mask is not plotted: with the paste stating the pads directly, the
# mask has no consumer in the runner at all (it is not meshed, and the plugin
# never drew it in the grid view).
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
_HELP_DIR = Path(__file__).resolve().parents[1] / "help"

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
    "stackup-dirty": "Unsaved stackup changes",
}


@dataclass
class Problem:
    """One pre-flight blocker/warning for the GUI banner (see preflight)."""

    id: str  # stable key; also selects the help page help/<id>.html
    severity: str  # "block" (Run disabled) | "warn" (Run prompts/continues)
    message: str  # one line for the banner row
    title: str = ""  # short caption for the help window
    help: str = ""  # help page filename under antenna_plugin/help/

    def __post_init__(self):
        self.title = self.title or _PROBLEM_TITLES.get(self.id, self.id)
        self.help = self.help or f"{self.id}.html"


def guide_page(filename):
    """The path of the bundled guide ``help/<filename>``, ready for the viewer
    to load. Returns None when the asset is missing (partial install) -- the
    GUI then says so rather than opening a blank viewer.

    The guide is displayed where it is installed, never copied: its stylesheet
    links are relative to ``antenna_plugin/assets/`` and only resolve there.

    Not every guide belongs to a pre-flight problem: the settings reference the
    About page opens is one of the whole form. So the lookup is by file name,
    and ``help_page`` is the Problem-shaped way in."""
    src = _HELP_DIR / filename
    return str(src) if src.is_file() else None


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
        # Silk/paste overlays carry no thickness or material at all (they are
        # never meshed), so there is nothing left to validate on them.

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


def preflight(board):
    """Everything that would stop a run, as a structured list -- the GUI
    renders it in the pre-flight banner and disables Run while any "block"
    problem exists, instead of discovering the same RuntimeErrors mid-run.
    collect_stackup / plot_gerbers keep their raises as the last-line guard;
    this consolidates the same predicates up front. Blockers come first,
    warnings last."""
    from ..kicad.stackup import read_stackup

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
        problems += stackup_problems(
            read_stackup(fname),
            [s for s, _ in copper_layers(board)],
            os.path.basename(fname),
        )

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
            # A geometry-only overlay (silk/paste): never meshed, so it carries
            # no thickness or material -- just its name and its place in the
            # stack, which is what tells the runner the side it belongs to
            # (before the first copper entry = top). config._layer_gerber folds
            # in its gerber.
            if pending:
                flush_gap()
            stackup.append({"type": kind, "name": e["name"].replace(".", "_")})
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
    ``paste_bottom``, ``silk_*``; the config emitter matches a stackup entry to
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
def locate():
    """The bundled simulator binary this host will run: ``(monopole_exe,
    root)``, or a raise that says why there is none.

    Every launch starts here -- a run, a wizard scan, the About page's version
    probe -- so this is also where "can this machine run it at all?" is asked,
    before any of them plots a gerber (sim.os_support, which is a temporary
    gate; see that module).

    Search order: ``$ANTENNA_SIM_ROOT`` -> the plugin's own parents (installer
    bundles it under the package; dev checkouts have it at the repo root).
    """
    os_support.check()  # macOS has no solver build yet -- goes with the gate

    candidates = []
    env = os.environ.get("ANTENNA_SIM_ROOT")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.extend(Path(__file__).resolve().parents)

    for root in candidates:
        exe = _find_exe(root)
        if exe:
            return str(exe), str(root)

    raise FileNotFoundError(
        "Could not find the simulator binary. Reinstall the plugin (which "
        "bundles it), or set the ANTENNA_SIM_ROOT environment variable to a "
        "folder that contains binaries/monopole (monopole.exe on Windows)."
    )


def _find_exe(root):
    """The bundled binary under ``root/binaries/``, or None. What it may be
    called is the platform's business (hostos.exe_names)."""
    for name in hostos.exe_names("monopole"):
        p = root / "binaries" / name
        if p.is_file():
            return p
    return None


def write_config(gerbers, stack, params, yaml_path):
    """Emit the runner YAML in-process, seeding it with the measured stack
    thicknesses and the GUI parameters/feed. No dependency on ./ems -- the
    schema lives in the plugin-local ``config`` module."""
    from . import config

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


def capture(monopole_exe, *args, timeout=None):
    """Run the solver with ``args`` and return what it printed on stdout.

    For the short, chatty invocations -- ``--version`` -- where the output is
    a fact to parse rather than a log to stream. ``timeout`` (seconds) bounds
    the wait: a binary that cannot run on this host must not wedge the caller's
    thread. Raises whatever the spawn raises (a binary that isn't executable),
    and ``subprocess.TimeoutExpired`` when the clock runs out; the exit status
    is not checked, because a tool that printed what was asked for has already
    answered.
    """
    proc = _spawn(
        [str(monopole_exe), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    with proc:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()  # SIGKILL/TerminateProcess: it is not answering
            proc.communicate()
            raise
    return out


def run_exe(
    monopole_exe, yaml_path, grid_only, on_line=None, on_proc=None, control=None
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
    """
    cmd = [str(monopole_exe), str(yaml_path)]
    if grid_only:
        cmd.append("--grid-only")
    if control:
        cmd += ["--control", str(control)]
    proc = _spawn(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=os.path.dirname(os.path.abspath(yaml_path)),
    )
    if on_proc:
        on_proc(proc)
    with proc:  # closes the pipe and waits on exit
        for line in proc.stdout:
            line = line.rstrip()
            if line and on_line:
                on_line(line)
    if proc.returncode != 0:
        raise RuntimeError(f"monopole exited with code {proc.returncode}")


# The binary always overwrites the same pcb_*.js dumps in the outdir, so each
# run's are archived verbatim into a per-run folder results/<stamp>/
# (archive_dump). The stamp (time.strftime('%Y%m%d-%H%M%S')) names the folder
# and sorts lexically, so latest_result just takes the newest.
_RESULTS_SUBDIR = "results"

# The two kinds of result a run produces, as the GUI names them.
GRID, REPORT = "grid", "report"

# Per kind: the file the binary writes into the outdir, and the viewer page
# that draws it. A dump is the whole deliverable -- the solver writes no HTML
# at all -- and this is the one place the pairing is stated.
DUMPS = {GRID: "pcb_grid.js", REPORT: "pcb_data.js"}
PAGES = {GRID: "grid.html", REPORT: "report.html"}


def run_results_dir(run_dir, stamp):
    """The per-run archive folder (``results/<stamp>/``) holding one run's
    ``pcb_*.js`` dumps."""
    return Path(run_dir) / _RESULTS_SUBDIR / stamp


def archive_dump(run_dir, kind, stamp):
    """Archive this run's ``kind`` dump (:data:`DUMPS`) from ``run_dir`` into
    the per-run folder ``results/<stamp>/``, verbatim, and return its path.

    Copied as-is: the archive stays a faithful copy of what the solver wrote,
    and a dump moved nowhere near a viewer is still the file every reader of
    these results -- the pages, :mod:`sim.runinfo`, a script -- opens.
    """
    dest_dir = run_results_dir(run_dir, stamp)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / DUMPS[kind]
    shutil.copyfile(Path(run_dir) / DUMPS[kind], dest)
    return str(dest)


def latest_result(run_dir, kind):
    """Newest archived ``kind`` dump (a Path) across the per-run
    ``results/<stamp>/`` folders, or None. The stamp folder names sort
    chronologically, so plain path order wins."""
    matches = sorted((Path(run_dir) / _RESULTS_SUBDIR).glob(f"*/{DUMPS[kind]}"))
    return matches[-1] if matches else None


def result_timestamp(path):
    """Human-readable generation time parsed from an archived dump's run
    folder name (``results/YYYYmmdd-HHMMSS/pcb_*.js``), or None if the
    parent folder isn't a run stamp."""
    m = re.match(r"(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$", Path(path).parent.name)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:{s}"


# --------------------------------------------------------------------------- #
# The viewer
# --------------------------------------------------------------------------- #
# The plugin's own copy of the simulator's front end -- plain HTML/CSS/JS that
# reads a dump and draws it, shipped like binaries/monopole is (docs/viewer.md
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
