"""How far a solve actually got: the ``run`` series a solver output carries.

Every data dump the solver writes ships a ``run`` series describing the
*record its numbers were computed from* -- the steps taken, the equivalent
simulated time (ns) against the planned length, the ring-down level reached,
why the run ended, and which mid-run sample this is. That is what keeps an
interrupted or sampled result honest: a report written from a 2 ns record must
not read like a converged 20 ns one.

The report page renders it itself; this module is how the *plugin* gets at the
same numbers -- for the run log, the status line and the result window's
title -- by reading the dump:

    window.FDTD={s:{...,"run":{"steps":3850,"plannedSteps":33856,
                               "timeNs":2.2743,"plannedTimeNs":19.9998,
                               "dtPs":0.59073,"ringDownDb":0.0,
                               "stop":"interrupted","partial":true,
                               "sample":0,"text":"..."},...}};

``pcb_data.js`` -- the dump every run writes, and what the report page draws --
is that assignment; ``pcb_data.json`` is the bare object. Both carry the same
series, so one parser covers them. The grid dump has no ``run`` series: a mesh
is not a record of anything, so a grid preview stays unlabelled rather than
borrowing the solve's.

Nothing is invented here: a field the solver didn't write stays None and is
left out of the text rather than shown as a zero. A file carrying no ``run``
series at all makes :func:`parse` return None, and callers simply say nothing
about the record length.

Pure stdlib (no wx / pcbnew), so it stays unit-testable off KiCad.
"""

import json
import re
from pathlib import Path
from typing import NamedTuple, Optional

# The run series inside a data file. RunSeries.cpp emits it as a flat object
# (no nested braces), which is what lets a plain regex lift it out of a file
# that is JS, not JSON ("window.FDTD={s:{...}};" -- the outer object has
# unquoted keys, so json.loads can't take the whole file).
_RUN_RE = re.compile(r'"run"\s*:\s*(\{[^{}]*\})')


class RunInfo(NamedTuple):
    """One set of results' coverage: what the solver recorded before the
    numbers were read off its monitors. Every field is optional -- it is
    whatever the solver wrote."""

    steps: Optional[int] = None
    planned_steps: Optional[int] = None
    time_ns: Optional[float] = None
    planned_time_ns: Optional[float] = None
    dt_ps: Optional[float] = None
    # None until the record covers a full ring-down window -- there is
    # nothing to peak-hold against before that, so it is "not measured yet",
    # not 0 dB.
    ring_down_db: Optional[float] = None
    # "running" (a mid-run sample) | "fixed length" | "rung down" | "capped" |
    # "interrupted".
    stop: str = ""
    # True when the results don't cover a finished run: a mid-run sample or an
    # interrupted solve. A capped run is not partial -- it ran its full
    # planned length, it just never went quiet.
    partial: bool = False
    # The solver's own key; the plugin's text calls it a snapshot, after the
    # button that asks for one (Snapshot report).
    sample: int = 0  # 0 = a run's final results; n = n-th snapshot
    text: str = ""  # the solver's own one-line description

    @property
    def progress(self):
        """Fraction of the planned run the record covers (0..1), or None when
        the solver didn't say how long the plan was."""
        if not self.planned_steps or self.steps is None:
            return None
        return self.steps / self.planned_steps

    def summary(self):
        """One line for the run log / status line. Prefers the solver's own
        ``text`` so the plugin can never disagree with the report page about
        what a run covered; falls back to composing the same facts from the
        numeric fields when an output carries no text."""
        return self.text or self._composed()

    def _composed(self):
        parts = []
        if self.time_ns is not None:
            if self.partial and self.planned_time_ns:
                parts.append(
                    f"{self.time_ns:.2f} of {self.planned_time_ns:.2f} ns simulated"
                )
            else:
                parts.append(f"{self.time_ns:.2f} ns simulated")
        if self.ring_down_db is not None:
            parts.append(f"ring-down {self.ring_down_db:.1f} dB")
        elif self.time_ns is not None:
            parts.append("ring-down not measured yet")
        line = ", ".join(parts)
        if self.sample:
            line = (
                f"{line}, snapshot {self.sample}" if line else f"snapshot {self.sample}"
            )
        if self.stop:
            line = f"{line} ({self.stop})" if line else f"({self.stop})"
        return line

    def label(self):
        """A short tag for a result window's title -- the simulated length,
        plus what makes this result less than a finished run. Empty when the
        solver reported no time at all. A mid-run set is named after the
        button that asked for it (Snapshot report), not after the solver's
        ``sample`` data key."""
        if self.time_ns is None:
            return f"snapshot {self.sample}" if self.sample else ""
        if self.partial and self.planned_time_ns:
            span = f"{self.time_ns:.2f}/{self.planned_time_ns:.2f} ns"
        else:
            span = f"{self.time_ns:.2f} ns"
        if self.sample:
            return f"{span} · snapshot {self.sample}"
        if self.partial:
            return f"{span} · {self.stop or 'partial'}"
        return span


def parse(text):
    """The :class:`RunInfo` in a solver data file's ``text`` (the ``.js``
    assignment or the bare ``.json`` dump), or None when it carries no ``run``
    series, e.g. a file that isn't a solver data file at all."""
    m = _RUN_RE.search(text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return None
    return RunInfo(
        steps=_int(d, "steps"),
        planned_steps=_int(d, "plannedSteps"),
        time_ns=_float(d, "timeNs"),
        planned_time_ns=_float(d, "plannedTimeNs"),
        dt_ps=_float(d, "dtPs"),
        ring_down_db=_float(d, "ringDownDb"),
        stop=str(d.get("stop") or ""),
        partial=bool(d.get("partial")),
        sample=_int(d, "sample") or 0,
        text=str(d.get("text") or ""),
    )


def read(path):
    """The :class:`RunInfo` in the data file at ``path``, or None when the
    file is missing, unreadable or carries no ``run`` series."""
    try:
        return parse(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None


def _num(d, key, cast):
    v = d.get(key)
    if v is None or isinstance(v, bool):
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _int(d, key):
    return _num(d, key, int)


def _float(d, key):
    return _num(d, key, float)
