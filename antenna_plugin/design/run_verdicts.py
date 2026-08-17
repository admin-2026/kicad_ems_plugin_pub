"""What a single run was aiming at, and how close it came.

A scan's report page shows a pass / warn / fail verdict per candidate
(design.scan_views): resonance, return loss, VSWR, bandwidth, input impedance,
each against the selected application's spec. One run deserves the same
sentence -- a plot of |S11| says what the antenna does, never whether that is
what was asked for -- and this module is the single-run half of it. The judging
itself is design.scoring's in both cases, so a run and a scan candidate can
never be scored by different rules.

The verdicts cannot come from the solver: the binary is handed a board and a
frequency, never a purpose, so nothing in its dump knows what "good" would have
been. They are written *beside* the dump instead, in the sidecar the report
page probes for (``run_verdicts.js``, see ``viewer/js/dump.js``):

    window.FDTD_VERDICTS={"target": "…", "overall": "warn", "props": [...]};

Beside it rather than in the run folder's index, because an archived result is
a folder somebody copies: the verdicts travel with the numbers they are about.
An assignment rather than JSON because the page loads it as a classic
``<script src>`` -- a subresource load, which ``file://`` allows, where a fetch
of the same file would be CORS-blocked (design.scan_views says the same of its
manifests).

Pure stdlib -- no wx, no pcbnew -- so it stays unit-testable off KiCad.
"""

import json
from pathlib import Path

from . import measure, scoring

# The sidecar's name, beside the dump it judges. Fixed by convention on both
# sides: the page names it in its boot config and resolves it relative to the
# dump it was pointed at, so nothing has to be passed in the URL.
FILENAME = "run_verdicts.js"


def describe(app):
    """The design target in one line, for the page to show over the table:
    the application's name and every part of the spec it actually pins down.
    A field the target leaves free is left out rather than printed as a
    default the user never chose."""
    parts = [app.name, f"{app.f0_ghz:g} GHz"]
    if app.band:
        parts.append(f"band {app.band[0]:g}–{app.band[1]:g} GHz")
    if app.impedance_ohm:
        parts.append(f"{app.impedance_ohm:g} Ω")
    if app.return_loss_db:
        parts.append(f"return loss ≥{app.return_loss_db:g} dB")
    return " · ".join(parts)


def evaluate(dump_text, app):
    """The scored payload for the run whose data dump is ``dump_text``, judged
    against the ``applications.Application`` ``app``: the target as a line of
    text plus scoring.serialize's overall status and per-property list.

    None when there is nothing to judge -- no target frequency, or a dump with
    no impedance sweep in it (a run that stopped before its first one). An
    empty verdict table would read like a verdict."""
    if not app or not app.f0_ghz:
        return None
    try:
        result = measure.score(dump_text, app.f0_ghz)
    except RuntimeError:
        return None
    payload = {"target": describe(app)}
    payload.update(scoring.serialize(result, scoring.target_from_application(app)))
    return payload


def write(dump_path, app):
    """Score the run whose dump is at ``dump_path`` against ``app`` and write
    the sidecar next to it; returns the payload written, or None when the run
    could not be judged (see :func:`evaluate`) -- in which case any sidecar
    left there by an earlier, longer record of this run is removed, so a page
    never shows verdicts belonging to numbers that are no longer beside them.
    """
    dump = Path(dump_path)
    out = dump.parent / FILENAME
    payload = evaluate(dump.read_text(encoding="utf-8"), app)
    if payload is None:
        out.unlink(missing_ok=True)
        return None
    out.write_text(
        "window.FDTD_VERDICTS=" + json.dumps(payload) + ";\n", encoding="utf-8"
    )
    return payload
