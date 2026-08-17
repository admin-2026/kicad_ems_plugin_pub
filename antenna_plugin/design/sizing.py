"""Candidate sizing: how long to make the antenna, and which lengths to try.

The frequency-aware half of a scan, shared by every design (design/base.py) and
free of any geometry: the free-space quarter wave a resonant length starts
from, the ladder of candidate lengths a scan walks around it, the plain linear
sweep the non-resonant parameters use, and the 1/L interpolation that turns
measured resonances into the length the target frequency asks for.

Pure stdlib, no wx / pcbnew / design import, so it stays unit-testable off
KiCad (tests/test_sizing.py).
"""

import math

# Ladder span around the quarter-wave estimate: resonance moves roughly as
# 1/length, so +-28 % in length covers a wide misestimate in either
# direction.
LADDER_LO = 0.72
LADDER_HI = 1.28

MIN_TOTAL_MM = 2.0  # shortest candidate worth simulating


def quarter_wave_mm(f0_ghz):
    """A free-space quarter wavelength (mm) at ``f0_ghz`` -- about 30 mm at
    2.45 GHz. This is the first-cut resonant length for every design here (a
    monopole's total track, an inverted-F's short-to-tip path) and the centre
    of the scan ladder; the simulation finds the true resonant length from
    there. These antennas radiate mostly into air, so free space (not a
    substrate-loaded effective permittivity) is the right start."""
    if f0_ghz <= 0:
        raise ValueError("frequency must be positive")
    return 299.792458 / f0_ghz / 4


def snap(value_mm, cap_mm):
    """A candidate length on the 0.01 mm grid that still fits ``cap_mm``.

    Clamping to the capacity and *then* rounding can round back over it -- an
    area holding 34.7563 mm would be handed a 34.76 mm candidate, which fails
    to solve by a hundredth of a millimetre. So round down at the ceiling.
    (Below ``MIN_TOTAL_MM`` nothing is worth simulating anyway; a capacity
    that small is reported by the design's own solve.)
    """
    value_mm = min(max(value_mm, MIN_TOTAL_MM), cap_mm)
    snapped = round(value_mm, 2)
    return snapped if snapped <= cap_mm else math.floor(cap_mm * 100) / 100


def ladder(est_mm, cap_mm, n):
    """The scan lengths: ``n`` totals spread over [0.72, 1.28] x the
    estimate, clipped to what fits and deduplicated (so a small area
    degrades to fewer, still-useful candidates)."""
    if n < 1:
        raise ValueError("need at least one candidate")
    lengths = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.5
        val = snap(est_mm * (LADDER_LO + t * (LADDER_HI - LADDER_LO)), cap_mm)
        if not any(abs(val - v) < 0.05 for v in lengths):
            lengths.append(val)
    return lengths


def sweep_values(lo, hi, n):
    """A plain linear sweep of ``n`` values across [lo, hi] inclusive,
    rounded and de-duplicated. Used for every non-resonant parameter (track
    width, an L-monopole's stem, an inverted-F's height or tap), where there
    is no 1/length physics to exploit -- the resonant length uses the
    frequency-aware ``ladder`` + ``refine_total`` instead."""
    if n < 1:
        raise ValueError("need at least one candidate")
    if hi < lo:
        lo, hi = hi, lo
    vals = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.5
        v = round(lo + t * (hi - lo), 3)
        if not any(abs(v - u) < 1e-6 for u in vals):
            vals.append(v)
    return vals


def refine_total(pairs, f0_ghz, cap_mm):
    """The interpolated resonant length for ``f0`` from scanned (length,
    f_res) pairs. Resonance scales close to 1/length but the constant
    k = L * f_res drifts slowly with length, so a global fit is biased by
    far-off candidates; instead the two pairs resonating nearest the target are
    interpolated linearly in L vs 1/f (a single usable pair falls back to
    its own k). None when no pair has a usable resonance."""
    usable = [(length, f) for length, f in pairs if f and f > 0]
    if not usable:
        return None
    if len(usable) == 1:
        (length, f) = usable[0]
        val = length * f / f0_ghz
    else:
        (l1, f1), (l2, f2) = sorted(usable, key=lambda p: abs(p[1] - f0_ghz))[:2]
        if abs(1 / f1 - 1 / f2) < 1e-9:
            val = l1 * f1 / f0_ghz
        else:
            val = l1 + (1 / f0_ghz - 1 / f1) * (l2 - l1) / (1 / f2 - 1 / f1)
    return snap(val, cap_mm)
