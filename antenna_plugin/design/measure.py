"""Read a finished run's electrical behaviour out of the solver's data dump.

Every run writes ``pcb_data.js`` (the assignment its report page loads) and,
with ``output_json`` on, the same object as bare ``pcb_data.json``. This module
turns either into the four numbers a run is judged on -- resonant frequency,
S11 at the target, -10 dB bandwidth and input impedance -- and nothing else:
which of them count as good is design.scoring's job, and which geometry
produced them is the design's.

Pure stdlib, no wx / pcbnew, so scoring a run stays unit-testable off KiCad
(tests/test_measure.py).
"""

import json

# What the ``.js`` flavour of a dump wraps the series object in
# (viz::SeriesBundle::writeAssignment): the outer object's keys are unquoted,
# so json.loads can't take the whole file -- but everything inside the wrapper
# is plain JSON.
_JS_OPEN = "window.FDTD={s:"
_JS_CLOSE = "};"


def payload(text):
    """The series object of a solver data file as JSON text: ``text`` itself
    for a bare ``.json`` dump, the assignment's payload for a ``.js`` one. One
    reader for both, so a caller never has to know which file it was handed."""
    stripped = text.strip()
    if not stripped.startswith(_JS_OPEN) or not stripped.endswith(_JS_CLOSE):
        return text
    return stripped[len(_JS_OPEN) : -len(_JS_CLOSE)]


def parse_impedance(text):
    """The impedance sweep from a run's data dump (``.js`` or ``.json``) as
    (f_ghz, r, x, s11_db) tuples in frequency order. The dump is
    ``{"<series>": value, ...}``; its ``impedance`` series holds parallel
    ``f``/``R``/``X``/``S11`` arrays."""
    try:
        imp = json.loads(payload(text)).get("impedance") or {}
        rows = (
            list(zip(imp["f"], imp["R"], imp["X"], imp["S11"])) if imp.get("f") else []
        )
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"could not parse the run's data dump: {exc}") from exc
    if not rows:
        raise RuntimeError(
            "impedance sweep is empty (the run may have failed before writing it)"
        )
    return rows


def _interp_col(rows, f_ghz, col):
    """Column ``col`` of the impedance ``rows`` ((f, R, X, S11) tuples) at
    ``f_ghz``, linearly interpolated and clamped to the sweep's nearest end
    outside its band."""
    if f_ghz <= rows[0][0]:
        return rows[0][col]
    for a, b in zip(rows, rows[1:]):
        if a[0] <= f_ghz <= b[0]:
            t = (f_ghz - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            return a[col] + t * (b[col] - a[col])
    return rows[-1][col]


def s11_at(rows, f_ghz):
    """S11 (dB) at ``f_ghz``, linearly interpolated; clamped to the sweep's
    nearest end outside its band."""
    return _interp_col(rows, f_ghz, 3)


def z_at(rows, f_ghz):
    """Input impedance ``(R, X)`` in ohms at ``f_ghz``, each linearly
    interpolated (companion to ``s11_at``, feeding the impedance verdict)."""
    return _interp_col(rows, f_ghz, 1), _interp_col(rows, f_ghz, 2)


def resonance(rows):
    """The sweep's resonant frequency (GHz): the S11 minimum, refined by a
    parabola through its neighbours when it is interior. None when the
    minimum sits at a band edge (the resonance is outside the sweep)."""
    i = min(range(len(rows)), key=lambda k: rows[k][3])
    if i == 0 or i == len(rows) - 1:
        return None
    (fa, _, _, sa), (fb, _, _, sb), (fc, _, _, sc) = rows[i - 1 : i + 2]
    denom = sa - 2 * sb + sc
    if denom <= 0:
        return round(fb, 4)
    return round(fb + 0.5 * (sa - sc) / denom * (fc - fb), 4)


def bandwidth_mhz(rows, thresh_db=-10.0):
    """The -10 dB match bandwidth (MHz) around the sweep's S11 minimum, edges
    linearly interpolated; None when the minimum never reaches the
    threshold."""
    i = min(range(len(rows)), key=lambda k: rows[k][3])
    if rows[i][3] > thresh_db:
        return None

    def cross(a, b):
        (f0, _, _, s0), (f1, _, _, s1) = a, b
        t = (thresh_db - s0) / (s1 - s0) if s1 != s0 else 0.0
        return f0 + t * (f1 - f0)

    lo = rows[0][0]
    for k in range(i, 0, -1):
        if rows[k - 1][3] > thresh_db:
            lo = cross(rows[k - 1], rows[k])
            break
    hi = rows[-1][0]
    for k in range(i, len(rows) - 1):
        if rows[k + 1][3] > thresh_db:
            hi = cross(rows[k + 1], rows[k])
            break
    return round((hi - lo) * 1000, 1)


def score(text, f0_ghz):
    """Every number one run contributes to a result table, read from its data
    dump's ``text`` (``.js`` or ``.json``) and measured at ``f0_ghz``:
    ``f_res_ghz`` (None when the resonance fell outside the sweep), ``s11_db``,
    ``bw_mhz`` (None when unmatched) and ``r_ohm``/``x_ohm``. One call so the
    scan driver never has to remember the rounding."""
    rows = parse_impedance(text)
    r_ohm, x_ohm = z_at(rows, f0_ghz)
    return {
        "f_res_ghz": resonance(rows),
        "s11_db": round(s11_at(rows, f0_ghz), 2),
        "bw_mhz": bandwidth_mhz(rows),
        "r_ohm": round(r_ohm, 2),
        "x_ohm": round(x_ohm, 2),
    }
