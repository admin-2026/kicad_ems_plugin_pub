"""The manifest that turns the viewer into a browser over a whole scan.

A scan is a folder of runs -- one ``cand-*`` directory per candidate, each
holding the dumps its solver pass wrote. Reading it means stepping between them
under the same axes, which is exactly what the shipped viewer does when it is
pointed at a *manifest* instead of a single dump (``report.html?scan=<file>.js``,
see ``docs/viewer.md``): the page grows a run switcher, and everything below it
is redrawn from whichever candidate is selected.

So a finished scan writes no pages of its own. It writes the manifests -- one
per view, beside the ``cand-*`` dirs -- naming the candidates in ascending
swept-value order, each with the dump to draw it from and the verdicts to paint
beside it:

    scan_report.js   opened by report.html, over each cand-NN/pcb_data.js
    scan_grid.js     opened by grid.html,   over each cand-NN/pcb_grid.js

A candidate whose dump is missing (a failed run) still gets an entry, without
one: it is part of the scan's story, and the page says so when it is selected
rather than leaving it out of the list.

A grid-only pass (the wizard's "Generate grids": every candidate meshed, none
solved) writes ``scan_grid.js`` alone -- there is nothing to report on -- and
removes the report manifest, so the folder's views always describe the runs
actually in it.

Nothing is judged here either: ``scoring.serialize`` turns a result into
pass/warn/fail glyphs in Python, and the page paints what it is given.

Pure stdlib -- no wx, no pcbnew -- so the scan stays testable headless.
"""

import json
import time
from pathlib import Path

from ..emkit.sim import simulate
from . import scoring

# The two kinds of view, named once (sim.simulate) so the scan that writes a
# manifest, the GUI box that opens it and the archive of a single run all use
# one vocabulary.
GRID, REPORT = simulate.GRID, simulate.REPORT

# Per kind: the manifest written into the scan folder, and the title its page
# takes while showing it. The dump each entry names comes from simulate.DUMPS,
# so a scan and a single run never disagree about which file holds what.
MANIFEST_FILES = {REPORT: "scan_report.js", GRID: "scan_grid.js"}
_TITLES = {REPORT: "Antenna scan — report", GRID: "Antenna scan — grids"}


def _design_name(spec):
    """The topology the scan designed, for the page header."""
    from . import wizard_scan  # local: wizard_scan imports this module

    return wizard_scan.design_of(spec).name


def _swept(spec):
    """The parameter this scan swept, as ``(key, label)`` -- read off the
    spec's design, so a new topology labels its own pages."""
    from . import wizard_scan  # local: wizard_scan imports this module

    design = wizard_scan.design_of(spec)
    key = spec.get("scan_param") or design.LENGTH_KEY
    return key, design.param_label(key).lower()


def write_manifests(workdir, results, spec, kinds=None):
    """Write the scan's manifests; returns the paths written. ``results`` is
    ``run_scan``'s best-first list (the first error-free row is the winner);
    ``spec`` the scan spec (swept parameter and target frequency feed the
    subtitle).

    ``kinds`` selects which views to write (default both). A grid-only pass
    asks for ``(GRID,)``: its candidates were meshed, not solved, so there is
    nothing to report on. Any manifest NOT written is removed, so the folder
    never keeps a view describing runs that are no longer the ones on disk (a
    stale scan_report.js beside freshly meshed candidates would plot the
    previous scan's data under this pass's geometry)."""
    workdir = Path(workdir)
    runs = _run_meta(workdir, results, spec)
    kinds = tuple(kinds) if kinds else tuple(MANIFEST_FILES)
    _key, label = _swept(spec)
    subtitle = (
        f"{_design_name(spec)} · {label} sweep · "
        f"target {spec['f0_ghz']:g} GHz · "
        f"{sum(1 for r in runs if not r['error'])} run(s) · "
        f"generated {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    if REPORT not in kinds:
        subtitle += " · grids only (not solved)"

    written = []
    for kind, name in MANIFEST_FILES.items():
        if kind not in kinds:
            remove_manifest(workdir, kind)
            continue
        out = workdir / name
        page = {"title": _TITLES[kind], "subtitle": subtitle}
        out.write_text(
            _manifest(workdir, runs, page, simulate.DUMPS[kind]), encoding="utf-8"
        )
        written.append(str(out))
    return written


def remove_manifest(workdir, kind):
    """Delete a manifest if it is there. Used to retire a view whose data is
    about to be (or has been) overwritten by runs it doesn't describe -- the
    folder's views must always match the candidates in it."""
    (Path(workdir) / MANIFEST_FILES[kind]).unlink(missing_ok=True)


def _run_meta(workdir, results, spec):
    """One meta dict per candidate, in ascending swept-value order (so the list
    follows the geometry, not the ranking). ``best`` marks the scan's winner --
    the first row of the best-first ``results``.

    Only what the switcher paints goes in here: the label, the star, the error
    and the scored verdicts. What each candidate *was* is the scan's record,
    and that has one home already (``scan_store``)."""
    from . import wizard_scan  # local: wizard_scan imports this module

    key, _label = _swept(spec)
    # The winner, when there is one to have: a grid-only pass measured nothing,
    # so no candidate is starred rather than the first one being crowned on
    # equal (absent) numbers.
    scored = any(r["s11_db"] is not None for r in results)
    best = wizard_scan.best_result(results) if scored else None
    target = scoring.target_from_spec(spec)
    runs = []
    for r in sorted(results, key=lambda r: r["values"].get(key) or 0.0):
        swept = r["values"].get(key)
        label = f"{swept:g} mm" if swept is not None else "—"
        if r["kind"] == "refine":
            label += " · refined"
        run = {
            "dir": Path(r["outdir"]).name if r["outdir"] else "",
            "label": label,
            "best": r is best,
            "error": r["error"],
        }
        # The candidate's pass/warn/fail verdicts, scored + glyphed here so the
        # switcher's strip and detail table just paint them (viewer/js/runs.js).
        run.update(scoring.serialize(r, target))
        runs.append(run)
    return runs


def _manifest(workdir, runs, page, dump):
    """One manifest's text: the ``window.FDTD_SCAN`` assignment the viewer
    loads (js/dump.js). Each candidate's dump is named relative to the manifest
    -- so the scan folder stays portable as a whole, and the viewer reading it
    can live anywhere -- and a candidate that wrote none is named without one.

    An assignment rather than JSON because the page loads it as a classic
    ``<script src>``: a subresource load, which ``file://`` allows, where a
    fetch of the same file would be CORS-blocked."""
    entries = []
    for run in runs:
        entry = {"meta": {k: v for k, v in run.items() if k != "dir"}}
        rel = f"{run['dir']}/{dump}"
        if run["dir"] and (workdir / run["dir"] / dump).is_file():
            entry["data"] = rel
        entries.append(entry)
    return "window.FDTD_SCAN=" + json.dumps({"page": page, "runs": entries}) + ";\n"
