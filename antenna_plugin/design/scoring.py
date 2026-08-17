"""Score a scan candidate against the design target, property by property.

The wizard's parameter scan used to crown a single winner (the ★ the
footprint chooser pre-selects). This module instead judges every candidate on
each property the selected application specifies -- resonance, return loss,
VSWR, bandwidth and input impedance -- and returns a pass / warn / fail verdict
for each, so the result table shows *why* a candidate is (or isn't) usable, not
just which one ranked first.

A :class:`Target` is the desired spec (from the ``applications`` catalog, or a
hand-typed frequency's fallback). :func:`evaluate` measures a result dict
against it and returns one :class:`Verdict` per property plus an ``overall``
status (the worst of the measured ones). Each verdict carries display text that,
for a warn or fail, shows the simulated value next to the desired one
(``"8 (≥10) dB"``), so the table tells the whole story in place.

Pure and free-standing -- stdlib only, no wx / pcbnew / applications -- so it
stays unit-testable off KiCad and the ``applications`` package (which feeds it
targets) can be deleted without touching it.
"""

import math
from typing import NamedTuple, Optional

# Verdict statuses. NONE is "not measured" (an em dash, no glyph) -- distinct
# from a measured-but-bad FAIL, and left out of the overall roll-up.
PASS, WARN, FAIL, NONE = "pass", "warn", "fail", "none"

_RANK = {NONE: -1, PASS: 0, WARN: 1, FAIL: 2}

# The glyph shown before a verdict (none for NONE, i.e. "not judged"). One
# source of truth for both the wx chooser and the HTML scan views, so they
# never drift -- the views serialise it (scoring.serialize) rather than mapping
# status to a glyph again in JS.
GLYPH = {PASS: "✓", WARN: "⚠", FAIL: "✗", NONE: ""}

# Warn bands: how far short of a target still counts as "close" (warn) rather
# than fail. Return loss in dB below target; bandwidth as a fraction of the
# required span; resonance as a fractional f0 offset when no band is given;
# input impedance as a normalized distance |Z - Z0| / Z0.
_MATCH_WARN_DB = 3.0
_BW_WARN_FRAC = 0.8
_RES_PASS_TOL = 0.02
_RES_WARN_TOL = 0.05
_IMP_PASS = 0.20
_IMP_WARN = 0.50


class Verdict(NamedTuple):
    """One property's judgement: a status and the cell text to show for it
    (the simulated value, plus the desired one when not a pass)."""

    status: str
    text: str


class Target(NamedTuple):
    """The desired antenna spec a scan is judged against -- every field comes
    from the selected application; none is defaulted. A field is ``None`` when
    the target genuinely doesn't specify it (a hand-typed frequency with no
    application): that property is then *shown but not judged* (a NONE verdict)
    rather than scored against an invented value. ``f0_ghz`` is always a real
    input (the frequency field), so resonance is always judged."""

    f0_ghz: float
    band_ghz: Optional[tuple]
    impedance_ohm: Optional[float]
    return_loss_db: Optional[float]

    @property
    def vswr(self):
        """The VSWR the target return loss corresponds to, or None when the
        target doesn't specify a return loss."""
        if self.return_loss_db is None:
            return None
        return _vswr(10.0 ** (-self.return_loss_db / 20.0))

    @property
    def required_bw_mhz(self):
        """The bandwidth the band demands (MHz), or None without a band."""
        if not self.band_ghz:
            return None
        return (self.band_ghz[1] - self.band_ghz[0]) * 1000.0


def _vswr(gamma):
    """VSWR from a reflection magnitude ``gamma`` (|Γ|); infinite at a total
    reflection (|Γ| >= 1)."""
    return math.inf if gamma >= 1.0 else (1.0 + gamma) / (1.0 - gamma)


def _text(status, sim, want):
    """A verdict's cell text: just the simulated value on a pass, the desired
    one alongside it (``"8 (≥10) dB"``) on a warn or fail so the shortfall is
    visible in the table."""
    if status in (WARN, FAIL) and want:
        return f"{sim} ({want})"
    return sim


def resonance(result, target):
    """Does the candidate resonate where it should? In-band (or within a
    tight f0 tolerance when there's no band) passes; just outside warns."""
    fr = result.get("f_res_ghz")
    if fr is None:  # no resonance located in the sweep
        return Verdict(NONE, "—")
    if target.band_ghz:
        lo, hi = target.band_ghz
        margin = hi - lo  # one bandwidth of slack -> warn
        status = (
            PASS
            if lo <= fr <= hi
            else WARN
            if lo - margin <= fr <= hi + margin
            else FAIL
        )
        want = f"{lo:g}–{hi:g}"
    else:
        d = abs(fr - target.f0_ghz) / target.f0_ghz
        status = PASS if d <= _RES_PASS_TOL else WARN if d <= _RES_WARN_TOL else FAIL
        want = f"~{target.f0_ghz:g}"
    return Verdict(status, _text(status, f"{fr:g} GHz", f"{want} GHz"))


def _match_status(s11_db, target):
    """The pass/warn/fail of the in-band match -- shared by the return-loss
    and VSWR verdicts, which are two views of the same S11 (so they can never
    disagree). NONE when the target doesn't specify a return loss (nothing to
    judge against -- never an injected default)."""
    if target.return_loss_db is None:
        return NONE
    rl = -s11_db  # return loss (dB) from S11 at f0
    return (
        PASS
        if rl >= target.return_loss_db
        else WARN
        if rl >= target.return_loss_db - _MATCH_WARN_DB
        else FAIL
    )


def return_loss(result, target):
    """Return loss at f0 vs the target (higher is better); shown but not judged
    when the target has no return-loss spec."""
    s11 = result.get("s11_db")
    if s11 is None:
        return Verdict(NONE, "—")
    status = _match_status(s11, target)
    want = "" if target.return_loss_db is None else f"≥{target.return_loss_db:g}"
    return Verdict(status, _text(status, f"{-s11:g} dB", want))


def vswr(result, target):
    """VSWR at f0 vs the target (lower is better); shares return loss's status,
    shown but not judged without a target."""
    s11 = result.get("s11_db")
    if s11 is None:
        return Verdict(NONE, "—")
    status = _match_status(s11, target)
    v = _vswr(10.0 ** (s11 / 20.0))
    sim = "∞" if math.isinf(v) else f"{v:.2f}"
    want = "" if target.vswr is None else f"≤{target.vswr:.2f}"
    return Verdict(status, _text(status, sim, want))


def bandwidth(result, target):
    """The -10 dB match bandwidth vs the band the application needs. Without a
    band (a hand-typed frequency) the value is shown but not judged."""
    bw = result.get("bw_mhz")
    if bw is None:
        return Verdict(NONE, "—")
    req = target.required_bw_mhz
    if req is None:
        return Verdict(NONE, f"{bw:g} MHz")
    status = PASS if bw >= req else WARN if bw >= req * _BW_WARN_FRAC else FAIL
    return Verdict(status, _text(status, f"{bw:g} MHz", f"≥{req:g}"))


def impedance(result, target):
    """Input impedance at f0 vs the desired value: how close ``R + jX`` sits to
    the desired resistance (with zero reactance), as a distance normalized by
    the desired impedance."""
    r, x = result.get("r_ohm"), result.get("x_ohm")
    if r is None or x is None:
        return Verdict(NONE, "—")
    z0 = target.impedance_ohm
    sim = f"{r:.0f}{x:+.0f}j Ω"
    if not z0:  # no desired impedance -> not judged
        return Verdict(NONE, sim)
    d = math.hypot(r - z0, x) / z0
    status = PASS if d <= _IMP_PASS else WARN if d <= _IMP_WARN else FAIL
    return Verdict(status, _text(status, sim, f"~{z0:g} Ω"))


# The properties a candidate is judged on, in table order: (key, display
# label, verdict function). The single ordering + labelling shared by the wx
# chooser columns and the HTML views' verdict table.
PROPERTIES = (
    ("resonance", "Resonance", resonance),
    ("return_loss", "Return loss", return_loss),
    ("vswr", "VSWR", vswr),
    ("bandwidth", "Bandwidth", bandwidth),
    ("impedance", "Input Z", impedance),
)


def evaluate(result, target):
    """Judge ``result`` against ``target``: a dict of one :class:`Verdict` per
    property (``resonance``/``return_loss``/``vswr``/``bandwidth``/
    ``impedance``) plus ``overall`` -- the worst measured status (PASS when all
    measured pass, NONE when nothing could be measured)."""
    verdicts = {key: fn(result, target) for key, _label, fn in PROPERTIES}
    measured = [v.status for v in verdicts.values() if v.status is not NONE]
    verdicts["overall"] = max(measured, key=_RANK.get) if measured else NONE
    return verdicts


def target_from_spec(spec):
    """A :class:`Target` from a wizard scan spec / footprint ctx dict -- the
    desired-spec fields ``scan._target_fields`` stashes there (``band_ghz`` /
    ``impedance_ohm`` / ``return_loss_db``) plus the always-present
    ``f0_ghz``. Absent fields stay ``None`` (shown but not judged, never
    defaulted). Shared by the footprint chooser and the HTML scan views so the
    spec-to-target mapping lives in one place."""
    band = spec.get("band_ghz")
    return Target(
        f0_ghz=spec["f0_ghz"],
        band_ghz=tuple(band) if band else None,
        impedance_ohm=spec.get("impedance_ohm"),
        return_loss_db=spec.get("return_loss_db"),
    )


def target_from_application(app):
    """A :class:`Target` from an ``applications.Application`` -- the design
    target a *run* was started for, where :func:`target_from_spec` takes the
    one a scan was stored with. Same four fields either way, so a single run
    and a scan candidate are judged by exactly the same rules; a field the
    application leaves free stays None (shown but not judged).

    Duck-typed on purpose: this module stays free of the ``applications``
    package, which is the one that may be deleted."""
    return Target(
        f0_ghz=app.f0_ghz,
        band_ghz=tuple(app.band) if app.band else None,
        impedance_ohm=app.impedance_ohm,
        return_loss_db=app.return_loss_db,
    )


def serialize(result, target):
    """Evaluate ``result`` for a data-only consumer (the HTML scan views' run
    meta): ``overall`` status + glyph and a per-property list
    ``[{key,label,status,glyph,text}, ...]`` in table order. The pass/warn/fail
    logic and glyphs stay here; the JS only paints what this returns."""
    verdicts = evaluate(result, target)
    return {
        "overall": verdicts["overall"],
        "overall_glyph": GLYPH[verdicts["overall"]],
        "props": [
            {
                "key": key,
                "label": label,
                "status": verdicts[key].status,
                "glyph": GLYPH[verdicts[key].status],
                "text": verdicts[key].text,
            }
            for key, label, _fn in PROPERTIES
        ],
    }
