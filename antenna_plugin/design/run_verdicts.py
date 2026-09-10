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

from ..applications import db as applications
from . import measure, scoring

# The sidecar's name, beside the dump it judges. Fixed by convention on both
# sides: the page names it in its boot config and resolves it relative to the
# dump it was pointed at, so nothing has to be passed in the URL.
FILENAME = "run_verdicts.js"


def describe(app):
    """The design target in one line, for the page to show over the table: the
    application's name and every part of the spec it actually pins down.

    The wording belongs to the target, not to this report -- the dialog's
    Design-target section shows the same line under its picker -- so it is
    ``applications.db``'s (duck-typed there too, on the same attributes
    ``scoring.target_from_application`` reads)."""
    return applications.describe(app)


def evaluate(dump_text, app):
    """The scored payload for the run whose data dump is ``dump_text``, judged
    against the ``applications.Application`` ``app``: the target as a line of
    text plus scoring.serialize's overall status and per-property list.

    None when there is nothing to judge -- no target frequency, or a dump with
    no impedance sweep in it (a run that stopped before its first one). An
    empty verdict table would read like a verdict.

    Raises ``RuntimeError``, rather than answering None, when the run was
    solved against a different impedance than the target is specified at
    (:func:`_same_reference`): that is not "nothing to judge", it is numbers
    that would be judged wrongly, and the difference is worth a sentence."""
    if not app or not app.f0_ghz:
        return None
    _same_reference(dump_text, app)
    try:
        result = measure.score(
            dump_text, app.f0_ghz, measure.match_db(app.return_loss_db)
        )
    except RuntimeError:
        return None
    payload = {"target": describe(app)}
    payload.update(scoring.serialize(result, scoring.target_from_application(app)))
    return payload


def _same_reference(dump_text, app):
    """Refuse to score a run whose ``S11`` was normalized to one impedance
    against a target specified at another.

    The solver writes ``S11`` and ``VSWR`` already normalized to the port
    resistance it was handed, and records it as the dump's ``geometry.zref``;
    ``scoring`` reads those columns back for the return loss, the VSWR and the
    -10 dB bandwidth, then prints the *target's* impedance over them. Equal,
    that is one number said twice -- which is what ``runjob.form_params``
    now makes it. Unequal, three of the five rows are measured against a
    reference the header does not name, and there is nothing in the table to
    show it.

    That cannot happen for a run this plugin starts any more, so this is for
    the ones it does not: a dump from before that was true, a hand-edited
    ``pcb.yaml``, a ``results show --job`` reaching back into an archive.

    A free-impedance target judges nothing about the match, and a ``zref`` of
    null is an ideal current source with no reference to disagree with. Neither
    is a mismatch; both carry on.
    """
    if not app.impedance_ohm:
        return
    try:
        zref = (json.loads(measure.payload(dump_text)).get("geometry") or {}).get(
            "zref"
        )
    except ValueError:
        return  # an unreadable dump is measure.score's to refuse, in its words
    if zref is None:
        return
    # Compared loosely: both sides made the trip through a config file and a
    # JSON dump as decimal text, and 50 must not fail to equal 50.
    if abs(float(zref) - app.impedance_ohm) > 1e-6 * max(1.0, app.impedance_ohm):
        raise RuntimeError(
            f"this run was solved against {float(zref):g} Ω but {app.name} is "
            f"specified at {app.impedance_ohm:g} Ω; its S11, VSWR and "
            f"bandwidth are all measured against the port it was driven "
            f"through, so they cannot be scored against a different one. "
            f"Re-run the board with the two agreeing."
        )


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
