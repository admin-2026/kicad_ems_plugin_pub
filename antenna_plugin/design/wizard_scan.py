"""Scan driver for the antenna wizards -- one loop, any design.

Sweeps ONE geometry parameter of the spec's design (registry.py) with the
others held fixed, scoring each candidate against the target frequency:

    for each candidate value of the swept parameter:
        solve the design's geometry (fixed feed point, from the area marker)
        splice its copper into a copy of the feed layer's gerber
        write a per-candidate runner YAML (feed point + direction, no
            markers; output_json for the machine-readable dump)
        run the solver, parse its pcb_data.json
        record f_res / S11(f0) / -10 dB bandwidth
    write the scan's view manifests (scan_views.py): one naming every
        candidate's pcb_data.js for the report view, one naming every
        candidate's pcb_grid.js for the grid view, so the shipped viewer
        steps through the whole sweep from either page
    save the scored rows and the spec they were measured under beside the
        runs (scan_store.py), so a later session places a footprint from
        this scan instead of paying for it twice

``run_scan(..., grid_only=True)`` runs that same loop with the solver stopped
after its meshing pass: every candidate is spliced, configured and meshed, none
is solved. It is the scan-wide twin of a single run's ``--grid-only`` pass --
the cheap way to see the mesh every candidate would be solved on before paying
for the whole sweep -- and writes only the grid view's manifest.

The design's *resonant length* (``design.LENGTH_KEY``) is special: instead of a
plain linear sweep it can use a frequency-aware ladder around the λ/4 estimate
and add one refined candidate at the length a 1/L fit predicts for f0 (blank
sweep bounds ask for that). Every other parameter sweeps linearly between the
caller's bounds -- there is no comparable closed form.

A candidate the **area marker can't hold is skipped**, never simulated: the
plan solves every value first (:class:`Plan`, one place for that decision) and
keeps only the ones with a geometry. Silence would be wrong, though -- a sweep
that quietly runs two of five candidates is not the scan that was asked for --
so the skips go to the log line by line, and ``plan_problems`` hands the
wizard's area banner one warning naming them, before a pass is paid for.

Nothing here knows what an antenna looks like: the topology enters only through
``spec['design']`` (see design/base.py), so a new one needs no edit in this
file.

No wx and no pcbnew -- the GUI gathers the board-derived inputs (plotted
gerbers, stackup, run params) on the main thread and drives this from a
worker via callbacks, and the whole scan stays testable headless. All the
board work happens in copies under ``workdir``; the open board is never
touched.

The scan ``spec`` dict:
    design                                       -- an AntennaDesign or its key
    area (x0,y0,x1,y1 KiCad mm), edge, frac      -- where the antenna lives
    rot_deg, pivot                               -- the area marker's off-grid
                                                    rotation (area/edge/frac
                                                    are in its derotated
                                                    frame; optional, 0 = on
                                                    grid)
    values {param key: mm}                       -- the fixed geometry; the
                                                    swept key's entry is a
                                                    placeholder
    gap_mm                                       -- ground-stub sizing (the
                                                    runner severs its own
                                                    one-cell gap)
    scan_param                                   -- which param key is swept
    sweep_lo, sweep_hi                           -- sweep bounds (None on the
                                                    resonant length = auto
                                                    ladder)
    f0_ghz, n, feed_layer                        -- target + scan knobs
    band_ghz, impedance_ohm, return_loss_db      -- the desired spec candidates
                                                    are judged against
"""

import os
from pathlib import Path
from typing import NamedTuple

from .. import config
from ..emkit.sim import simulate
from . import geometry, measure, registry, scan_store, scan_views, sizing

# A refined length this close to an already-scanned candidate is a re-run,
# not new information; skip it.
_REFINE_SKIP_MM = 0.15


class ScanCancelled(RuntimeError):
    """Raised between candidates when the caller's should_stop fires."""


# --------------------------------------------------------------------------- #
# Reading the spec
# --------------------------------------------------------------------------- #
def design_of(spec):
    """The spec's design, whether it carries the object or just its key."""
    return registry.resolve(spec["design"])


def _values(spec):
    """The fixed parameter values (the swept one is overridden per candidate).
    The resonant length may be absent on an auto ladder scan, where the ladder
    supplies it -- default it so the dict is always well-formed."""
    design = design_of(spec)
    values = dict(spec["values"])
    values.setdefault(design.LENGTH_KEY, 0.0)
    return values


def _capacity(design, spec, values):
    """The longest resonant length the area fits for ``values``."""
    return design.capacity_mm(spec["area"], spec["edge"], spec["frac"], values)


def _capacity_or_none(design, spec, values):
    """``_capacity``, or None when the area holds no antenna at all at these
    values -- for the callers that would rather quote no capacity than raise
    (an area that holds nothing is reported by the candidates themselves)."""
    try:
        return _capacity(design, spec, values)
    except ValueError:
        return None


def _label(design, param):
    return design.param_label(param).lower()


# --------------------------------------------------------------------------- #
# Planning the sweep
# --------------------------------------------------------------------------- #
class Plan(NamedTuple):
    """What a pass will actually run -- and what the area cost it.

    ``values`` are the swept parameter's candidate values that really fit the
    area marker, with ``geos`` the geometry each one solved to (index-aligned,
    so nothing solves twice). A candidate the area can't hold is **not** in
    them: it is in ``skipped`` as ``(value, why)`` -- simulating a shape that
    doesn't fit tells the user nothing they can't see, and the alternative
    (running it to record a failure) costs a solver run per miss.

    ``requested`` is the candidate count the user asked for, so ``lost`` says
    how much of the sweep the area took however it happened: a value dropped
    here, or ladder rungs collapsing onto the area's capacity (sizing.snap
    clamps them, and the duplicates dedup away). ``plan_problems`` turns that
    into the wizard's banner warning; nobody else needs to know which."""

    design: object
    param: str
    values: list
    geos: list
    auto_length: bool
    requested: int
    capacity_mm: float  # None when the area holds nothing at all
    skipped: list

    @property
    def lost(self):
        """How many of the requested candidates the sweep does not contain."""
        return max(self.requested - len(self.values), 0)


def _rounded(values):
    """The parameter dict as a candidate really carries it (``_new_result``
    rounds to 0.1 µm). Planning solves this dict, not the raw one, so a
    candidate can never be planned at a value that fits and then run at a
    rounded one that doesn't."""
    return {k: round(v, 4) for k, v in values.items()}


def _feasible(design, spec, param, candidates, base):
    """Split ``candidates`` (values of the swept parameter) into the ones the
    area holds and the ones it doesn't: ``(values, geos, skipped)``.

    The test is the design's own ``solve`` -- a candidate fits exactly when
    there is a geometry for it -- so this catches every way a value can
    overflow the marker (a length past the area's capacity, a track too wide
    for the edge, an inverted-F whose tap won't sit inside its own arm) and
    quotes the design's message for each. The solved geometry comes back with
    it: ``plan`` fills its rows from these, so the fit test is also the only
    solve the preview needs."""
    keep, geos, skipped = [], [], []
    for v in candidates:
        values = _rounded(dict(base, **{param: v}))
        length = values[design.LENGTH_KEY]
        if length < sizing.MIN_TOTAL_MM:
            skipped.append(
                (
                    v,
                    f"{_label(design, design.LENGTH_KEY)} "
                    f"{length:g} mm is below the "
                    f"{sizing.MIN_TOTAL_MM:g} mm floor",
                )
            )
            continue
        try:
            geo = design.solve(spec["area"], spec["edge"], spec["frac"], values)
        except ValueError as exc:
            skipped.append((v, str(exc)))
            continue
        keep.append(v)
        geos.append(geo)
    return keep, geos, skipped


def _plan(spec, on_line=None):
    """The :class:`Plan` a pass would follow -- shared by ``plan`` (the GUI's
    preview and up-front validation), ``plan_problems`` (the banner warning)
    and ``run_scan`` (execution), so all three agree on which candidates run.
    Raises RuntimeError when nothing in the sweep fits the area."""
    design = design_of(spec)
    param = spec.get("scan_param") or design.LENGTH_KEY
    auto_length = param == design.LENGTH_KEY and spec.get("sweep_lo") is None
    base = _values(spec)
    requested = int(spec["n"])

    if auto_length:
        # The frequency-aware ladder: its rungs are already clamped to what
        # the area holds (sizing.snap), so what it loses to a small area is
        # rungs collapsing onto that ceiling, not values the filter drops.
        try:
            cap = _capacity(design, spec, base)
        except ValueError as exc:
            raise RuntimeError(f"the area cannot hold this antenna: {exc}") from exc
        est = sizing.quarter_wave_mm(spec["f0_ghz"])
        candidates = sizing.ladder(est, cap, requested)
        head = (
            f"{_label(design, param)}, lambda/4 estimate {est:.1f} mm, "
            f"area fits {cap:.1f} mm"
        )
    else:
        cap = _capacity_or_none(design, spec, base)
        candidates = sizing.sweep_values(spec["sweep_lo"], spec["sweep_hi"], requested)
        head = None

    values, geos, skipped = _feasible(design, spec, param, candidates, base)
    if skipped:
        _say(
            on_line,
            f"Skipping {len(skipped)} {_label(design, param)} "
            "value(s) the area can't hold: " + ", ".join(f"{v:g}" for v, _ in skipped),
        )
        _say(on_line, f"    {skipped[0][1]}")
    if not values:
        raise RuntimeError(_nothing_fits(design, param, auto_length, skipped))
    if head is None:
        head = f"{_label(design, param)} {values[0]:g}..{values[-1]:g} mm"
    _say(
        on_line,
        f"Scan plan: {head}, {len(values)} candidate(s): "
        + ", ".join(f"{v:g}" for v in values),
    )
    return Plan(design, param, values, geos, auto_length, requested, cap, skipped)


def _nothing_fits(design, param, auto_length, skipped):
    """The message for a sweep the area holds nothing of -- the design's own
    reason plus what to do about it. The two phrasings are the two things that
    can be wrong: on the automatic ladder the area itself is too small for the
    antenna, on a bounded sweep it is the range that was asked for."""
    why = f" ({skipped[0][1]})" if skipped else ""
    if auto_length:
        return f"the area cannot hold this antenna{why}"
    return (
        f"no {_label(design, param)} value in the requested range fits "
        f"the fixed geometry{why} -- widen the area or lower the fixed "
        "length"
    )


def plan(spec):
    """The candidate geometries a scan would run, without simulating -- the
    GUI's scan preview and its up-front validation. Same result dicts as
    ``run_scan`` but with the score fields (f_res/s11/bw) and ``outdir`` None.

    Every row is a candidate that fits the area: the ones that don't are not
    planned at all (``Plan.skipped``, surfaced by ``plan_problems``), so a row
    here never carries a fit ``error``. The auto-length refined candidate is
    not included (it depends on measured resonances). Raises when the whole
    requested range is infeasible, like ``run_scan``."""
    p = _plan(spec)
    base = _values(spec)
    rows = []
    for v, geo in zip(p.values, p.geos):
        row = _new_result(p.design, "scan", dict(base, **{p.param: v}), None)
        row["geom"] = dict(geo.metrics)
        rows.append(row)
    return rows


def plan_problems(spec):
    """The advisory warnings about the sweep ``spec`` describes, as
    ``sim.simulate.Problem`` rows for the wizard's area banner -- said before a
    pass is paid for, not after.

    One thing is reported: candidates the **area marker can't hold**, which a
    pass skips (see :class:`Plan`). Skipping is the right answer -- an antenna
    that doesn't fit has nothing to measure -- but a sweep that quietly runs
    two of the five candidates that were asked for is a scan the user did not
    plan, so it says which values went and what the area holds. A sweep that
    fits entirely says nothing.

    Pure (no wx, no pcbnew, no board): the sweep either fits the rectangle or
    it doesn't, which is the same question headless. Never raises -- a spec too
    incomplete to plan is the form's own story, told by the Start scan
    button."""
    try:
        p = _plan(spec)
    except RuntimeError as exc:
        return [_problem(f"nothing in this sweep fits the area marker: {exc}")]
    except Exception:
        return []  # a spec too incomplete to plan: not this check's
        # story -- the Start scan button tells that one
    if not p.lost:
        return []
    design, label = p.design, _label(p.design, p.param)
    held = (
        ""
        if p.capacity_mm is None
        else f"; the area holds at most {p.capacity_mm:.1f} mm of "
        f"{_label(design, design.LENGTH_KEY)}"
    )
    if p.skipped:
        return [
            _problem(
                f"{len(p.skipped)} of the {p.requested} {label} candidates don't "
                f"fit the area marker and will be skipped ("
                + ", ".join(f"{v:g}" for v, _ in p.skipped)
                + f" mm){held} -- the pass runs the remaining {len(p.values)}. "
                f"Grow the area marker, or narrow the sweep to values that fit"
            )
        ]
    # Nothing was dropped, so the loss is the ladder: its top rungs clamped
    # onto the area's capacity and deduplicated away.
    return [
        _problem(
            f"the area marker holds only {len(p.values)} of the {p.requested} "
            f"{label} candidates asked for -- the rest run past what it can hold "
            f"and collapse onto its capacity{held}. Grow the area marker (or "
            f"lower the target frequency) to scan the full ladder"
        )
    ]


def _problem(message):
    """One banner row for the plan's advisory (see ``plan_problems``). All of
    them share an id -- and so one help page -- because they are one story:
    the area marker is too small for the sweep that was asked for."""
    return simulate.Problem(
        "area-candidates-skipped",
        "warn",
        message,
        title="Candidates don't fit the area",
    )


def spliced_rects(spec, rows):
    """The copper a pass over ``rows`` (``plan``'s candidates) splices into the
    feed layer: every candidate's rectangles in the marker's derotated frame,
    with the stubs off -- the stubs reach out of the area on purpose, and the
    one consumer is the advisory overlap check (markers.area_checks), which
    judges nothing outside it. Candidates that don't solve contribute nothing.

    The whole sweep, not one candidate: they reach differently far, so a clear
    preview never said the sweep was clear. The auto-length refined candidate
    is missing for the same reason ``plan`` omits it (its length follows from
    the measured resonances), but it is interpolated into a span the ladder
    already covers."""
    design = design_of(spec)
    rects = []
    for row in rows:
        if row["error"] is not None:
            continue
        try:
            geo = design.solve(spec["area"], spec["edge"], spec["frac"], row["values"])
        except ValueError:
            continue  # planned but unsolvable: not spliced
        rects.extend(
            geo.copper_rects(row["values"][design.WIDTH_KEY], 0.0, include_stub=False)
        )
    return rects


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def _new_result(design, kind, values, outdir):
    """A blank result row. Every consumer (the GUI table, the footprint
    placer, the combined views) reads candidates through this shape:

        design    the design key that produced it
        kind      'scan' or 'refine'
        values    the geometry parameters it was solved for, by param key
        geom      the design's derived metrics (Geometry.metrics), empty on a
                  candidate that failed to solve
        f_res_ghz resonance (None when it fell outside the sweep), s11_db at
                  f0, bw_mhz (-10 dB, None when unmatched), r_ohm / x_ohm
        outdir    where the run's files are (None for a planned candidate)
        error     None, or why this candidate has no numbers
    """
    return {
        "design": design.key,
        "kind": kind,
        "values": _rounded(values),
        "geom": {},
        "f_res_ghz": None,
        "s11_db": None,
        "bw_mhz": None,
        "r_ohm": None,
        "x_ohm": None,
        "outdir": str(outdir) if outdir else None,
        "error": None,
    }


def length_of(design, result):
    """A result's resonant length (mm) -- what the ladder refinement and the
    'best' ranking talk about."""
    return result["values"].get(design.LENGTH_KEY)


def best_result(results):
    """The scan's suggested candidate: the first error-free row of the
    best-first ``results`` (None when every candidate failed). The single
    source for 'which candidate is the winner', shared by the footprint
    placer (the ★ it pre-selects) and the combined scan_report view (the ★ it
    stars) so the two never disagree."""
    return next((r for r in results if r["error"] is None), None)


# --------------------------------------------------------------------------- #
# Running the sweep
# --------------------------------------------------------------------------- #
def run_scan(
    launcher,
    gerbers,
    stack,
    base_params,
    spec,
    workdir,
    on_line=None,
    on_status=None,
    on_result=None,
    should_stop=None,
    on_proc=None,
    grid_only=False,
):
    """Run the full scan; returns the results best-first (see ``_new_result``
    for the row shape).

    ``gerbers``/``stack``/``base_params`` are exactly what a normal run
    hands to config.write_yaml (the wizard inherits the dialog's simulation
    time, material / mesh / speed settings); ``spec`` is the wizard's own
    design, geometry and scan plan. ``on_result(result)`` fires as each
    candidate finishes so the GUI can fill its table live; ``on_proc``
    receives each solver Popen for cancellation. Raises ScanCancelled when
    ``should_stop()`` turns true between candidates (a terminated solver
    surfaces as ScanCancelled too).

    ``grid_only`` meshes every candidate without solving any of them (the
    wizard's "Generate grids", the scan-wide twin of the simulate view's
    "Generate grid"): the same plan, geometry, splice and config as a real
    scan, stopped after the solver's meshing pass. The results then carry
    geometry but no numbers, so there is nothing to score, nothing to rank
    and nothing to refine -- the resonant length's refined candidate is the
    one step a grid pass skips -- and only the combined grid view is written.
    """
    workdir = Path(workdir)
    copper_text = _feed_layer_text(gerbers, spec["feed_layer"])
    p = _plan(spec, on_line)
    design, param, values = p.design, p.param, p.values
    base = _values(spec)
    what = "Meshing candidate" if grid_only else "Candidate"
    if grid_only:
        # The candidates are re-meshed into the same cand-* folders, so any
        # report manifest here starts describing data this pass overwrites.
        # Retire it now rather than only on a clean finish: a cancelled or
        # failed grid pass must not leave it standing over the new runs either.
        scan_views.remove_manifest(workdir, scan_views.REPORT)

    results = []
    for i, v in enumerate(values, start=1):
        _check_stop(should_stop)
        _status(
            on_status, f"{what} {i}/{len(values)}: {_label(design, param)} {v:g} mm…"
        )
        results.append(
            _run_candidate(
                launcher,
                gerbers,
                stack,
                base_params,
                spec,
                copper_text,
                workdir / f"cand-{i:02d}",
                "scan",
                dict(base, **{param: v}),
                on_line,
                should_stop,
                on_proc,
                grid_only,
            )
        )
        if on_result:
            on_result(results[-1])

    if p.auto_length and not grid_only:
        _refine_length(
            launcher,
            gerbers,
            stack,
            base_params,
            spec,
            copper_text,
            base,
            results,
            workdir,
            on_line,
            on_status,
            should_stop,
            on_proc,
            on_result,
        )

    if all(r["error"] is not None for r in results):
        raise RuntimeError("every candidate failed: " + results[0]["error"])
    # Best-first by match at f0. A grid pass measured nothing, so every key is
    # equal there and the sort only moves the failed candidates last, keeping
    # the plan's order.
    results.sort(key=lambda r: (r["error"] is not None, r.get("s11_db") or 0.0))

    # The record of the scan, beside the runs: the rows and the spec they were
    # measured under, so the footprint can still be placed from them after the
    # window that ran the scan is gone (scan_store). A grid pass measured
    # nothing, so it saves nothing -- and leaves the last real scan's file
    # standing, exactly as the GUI keeps its results in memory. Like the views,
    # a failure to write it must not discard a finished scan.
    if not grid_only:
        try:
            _say(on_line, f"Wrote {scan_store.save(workdir, results, spec)}")
        except Exception as exc:
            _say(on_line, f"could not save the scan's results: {exc}")

    # The view manifests: what the viewer steps through to read this scan (a
    # grid pass writes the grid one alone). Presentation only -- a failure here
    # must not discard the finished scan.
    kinds = (scan_views.GRID,) if grid_only else None
    try:
        for path in scan_views.write_manifests(workdir, results, spec, kinds):
            _say(on_line, f"Wrote {path}")
    except Exception as exc:
        _say(on_line, f"could not write the scan's view manifests: {exc}")
    return results


def _refine_length(
    launcher,
    gerbers,
    stack,
    base_params,
    spec,
    copper_text,
    base,
    results,
    workdir,
    on_line,
    on_status,
    should_stop,
    on_proc,
    on_result,
):
    """Add one candidate at the length a 1/L fit predicts for f0 (auto
    length scan only) -- unless the area can't hold it, which is skipped like
    any other candidate that doesn't fit (the fit clamps to the capacity, so
    this is the rounding edge of it rather than a common case)."""
    design = design_of(spec)
    length_key = design.LENGTH_KEY
    cap = _capacity(design, spec, base)
    refined = sizing.refine_total(
        [(length_of(design, r), r["f_res_ghz"]) for r in results if r["error"] is None],
        spec["f0_ghz"],
        cap,
    )
    if refined is None:
        _say(
            on_line, "No in-band resonance to refine from; keeping the ladder results."
        )
        return
    if any(abs(refined - length_of(design, r)) <= _REFINE_SKIP_MM for r in results):
        # Typically the fit asks for more length than the area holds and
        # got clipped onto the longest ladder stop.
        _say(
            on_line,
            f"Refined length {refined:g} mm is already covered "
            "by a scanned candidate; skipping the extra run.",
        )
        return
    values, _geos, skipped = _feasible(design, spec, length_key, [refined], base)
    if not values:
        _say(
            on_line,
            f"Refined length {refined:g} mm doesn't fit the area "
            f"({skipped[0][1]}); keeping the ladder results.",
        )
        return
    _check_stop(should_stop)
    _status(on_status, f"Refining: {refined:g} mm…")
    results.append(
        _run_candidate(
            launcher,
            gerbers,
            stack,
            base_params,
            spec,
            copper_text,
            workdir / "cand-refine",
            "refine",
            dict(base, **{length_key: refined}),
            on_line,
            should_stop,
            on_proc,
        )
    )
    if on_result:
        on_result(results[-1])


def _run_candidate(
    launcher,
    gerbers,
    stack,
    base_params,
    spec,
    copper_text,
    cand_dir,
    kind,
    values,
    on_line,
    should_stop,
    on_proc,
    grid_only=False,
):
    """Simulate one geometry (``values`` = the design's parameters) in its own
    directory; a failed solve is recorded on the result (error) instead of
    aborting the scan -- unless it was a cancellation, which propagates.
    ``grid_only`` stops the solver after its meshing pass, which leaves the
    candidate's grid but no data to score."""
    design = design_of(spec)
    result = _new_result(design, kind, values, cand_dir)
    # Solve from the *recorded* values, not the raw ones: the footprint placer
    # re-solves a chosen result from exactly this dict, so what it places is
    # what was simulated, down to the last decimal.
    values = result["values"]
    try:
        trace_w = values[design.WIDTH_KEY]
        geo = design.solve(spec["area"], spec["edge"], spec["frac"], values)
        result["geom"] = dict(geo.metrics)
        _say(
            on_line,
            f"--- {kind} candidate: {geo.total_mm:g} mm "
            f"({design.describe(geo)}), width {trace_w:g} mm ---",
        )

        os.makedirs(cand_dir, exist_ok=True)
        # Geometry solved in the area marker's derotated frame; the spliced
        # copper polygons rotate back onto the board, and the runner gets the
        # rotation_deg that re-aligns the feed with a grid axis.
        rot, pivot = spec.get("rot_deg") or 0.0, spec.get("pivot") or (0, 0)
        polys = geometry.candidate_polys(
            geo.copper_rects(trace_w, spec["gap_mm"]), rot, pivot
        )
        patched = cand_dir / "antenna_copper.gbr"
        patched.write_text(
            geometry.splice_copper(copper_text, polys, design.key), encoding="utf-8"
        )

        cand_gerbers = dict(gerbers)
        cand_gerbers["copper"] = [
            (name, str(patched) if name == spec["feed_layer"] else path)
            for name, path in gerbers["copper"]
        ]

        params = dict(base_params)
        params.update(
            {
                "outdir": str(cand_dir),
                "fpattern_ghz": spec["f0_ghz"],
                "feed": geo.feed_dict(rot, pivot),
                "feed_layer": spec["feed_layer"],
                # The marker's KiCad-frame (Y-down) residual is exactly the CCW
                # gerber-frame rotation that re-aligns the feed: the Y flip
                # negates angles, and undoing -rot is +rot.
                "rotation_deg": rot,
                # Both dumps come with every run, so a candidate needs no
                # output keys to be readable: pcb_grid.js is the lattice the
                # scan's grid view steps through, pcb_data.js the series its
                # report view does.
                # The bare-JSON dump (pcb_data.json) feeds the resonance/S11
                # scoring below (output_json adds it beside pcb_data.js).
                "output_json": True,
            }
        )
        config.write_yaml(cand_gerbers, stack, params, str(cand_dir / "pcb.yaml"))
        simulate.run_exe(
            launcher,
            str(cand_dir / "pcb.yaml"),
            grid_only=grid_only,
            on_line=on_line,
            on_proc=on_proc,
        )

        if grid_only:
            # The meshing pass wrote the candidate's grid and stopped; there
            # is no data dump to score, and the result stays numberless.
            _say(on_line, "    => grid only, not solved")
            return result
        result.update(
            measure.score(
                (cand_dir / "pcb_data.json").read_text(encoding="utf-8"),
                spec["f0_ghz"],
                measure.match_db(spec.get("return_loss_db")),
            )
        )
        _say(
            on_line,
            f"    => f_res {result['f_res_ghz'] or '—'} GHz, "
            f"S11({spec['f0_ghz']:g} GHz) = {result['s11_db']} dB, "
            f"BW {result['bw_mhz'] or '—'} MHz",
        )
    except Exception as exc:
        if should_stop and should_stop():
            raise ScanCancelled("scan cancelled") from exc
        result["error"] = str(exc)
        _say(on_line, f"    candidate failed: {exc}")
    return result


def _feed_layer_text(gerbers, feed_layer):
    for name, path in gerbers["copper"]:
        if name == feed_layer:
            return Path(path).read_text(encoding="utf-8")
    raise RuntimeError(
        f"feed layer {feed_layer} is not among the plotted copper layers"
    )


def _check_stop(should_stop):
    if should_stop and should_stop():
        raise ScanCancelled("scan cancelled")


def _say(on_line, text):
    if on_line:
        on_line(text)


def _status(on_status, text):
    if on_status:
        on_status(text)
