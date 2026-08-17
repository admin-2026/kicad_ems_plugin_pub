"""The last scan's results, kept on disk beside the runs that produced them.

A scan is the expensive part of the wizard: a solver run per candidate, minutes
at a time. Its *results* were the one thing that lived only in the open window
-- the view manifests (scan_views.py) and every candidate's own output stay in
the scan folder and re-open days later, but the ranked rows the footprint
chooser places from went away with the dialog, so closing the plugin meant
re-simulating a sweep that had already been paid for.

So a finished scan writes them down. One file per design's scan folder
(``simulation/wizard/<design>/scan.json``, beside the ``cand-*`` run dirs and
the view manifests), holding exactly what the placer needs:

    results   run_scan's best-first rows, as ``wizard_scan._new_result``
              shapes them (values + geom + the measured numbers)
    spec      the scan spec they were measured under -- the area marker as it
              was scanned, the target frequency, the feed layer and the
              desired spec they are scored against

The spec's design is stored as its registry key and resolved back on load, so
the file is plain JSON with no pickled objects in it; a file naming a design
this build doesn't have (or written by another version) is refused rather than
half-read. Nothing here judges whether the *board* still matches: the frame
travels with the results, so a candidate is always re-solved and placed in the
area it was scanned in, exactly as one from this session's own scan is.

A grid-only pass writes nothing here. It measures nothing, so it has no
results to save -- and must not overwrite the last real scan's, which are still
the last numbers anybody measured (the GUI keeps them in memory for the same
reason).

Pure stdlib -- no wx, no pcbnew -- so a headless scan persists its results too.
"""

import json
import time
from pathlib import Path
from typing import NamedTuple

from . import registry

# The file a finished scan writes into its scan folder.
FILE = "scan.json"

# Bumped when the file's layout changes in a way an older reader would
# misread. A file at another version is refused (there is nothing to migrate:
# the scan behind it is still on disk, and re-running it is the fallback).
VERSION = 1

# The spec keys a stored scan must carry to be placeable at all -- the frame a
# candidate is re-solved in and the frequency it was sized for. A file missing
# any of them is refused rather than defaulted around.
_REQUIRED = ("area", "edge", "frac", "f0_ghz", "feed_layer")


class Saved(NamedTuple):
    """A scan read back off disk: its ``results`` (best-first, as run_scan
    returned them), the ``spec`` they were measured under (with the design
    resolved back to its object, so it is the same dict the GUI would have
    built) and ``when`` the scan finished, as it was written -- the phrase the
    wizard shows to say these numbers are not from this session."""

    results: list
    spec: dict
    when: str
    path: Path


def path_for(workdir):
    """Where a scan folder keeps its results file."""
    return Path(workdir) / FILE


def save(workdir, results, spec):
    """Write ``results`` and the ``spec`` they were measured under into
    ``workdir``; returns the path. Overwrites the previous scan's file -- the
    folder describes one scan, the way its combined views do.

    Raises when the spec holds something JSON can't carry, which is a bug in
    the caller rather than something to paper over; run_scan logs it and keeps
    the finished scan."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    design = registry.resolve(spec["design"])
    stored = dict(spec, design=design.key)
    payload = {
        "version": VERSION,
        "design": design.key,
        "when": time.strftime("%Y-%m-%d %H:%M"),
        "spec": stored,
        "results": list(results),
    }
    out = path_for(workdir)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return out


def load(workdir, design_key=None):
    """The scan ``workdir`` last saved, or None when it holds none.

    Raises ValueError when there is a file but it can't be trusted -- another
    version, another design, no results, or a spec too thin to place from. A
    half-understood record would place copper in a frame nobody checked, so it
    is refused with the reason; the caller says so and carries on as if no scan
    had been saved."""
    path = path_for(workdir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not hold a saved scan")
    if payload.get("version") != VERSION:
        raise ValueError(
            f"{path} was written by another version of the plugin "
            f"(format {payload.get('version')}, this one reads {VERSION})"
        )
    stored_key = payload.get("design")
    if design_key is not None and stored_key != design_key:
        raise ValueError(f"{path} holds a scan of {stored_key}, not of {design_key}")
    spec = payload.get("spec")
    results = payload.get("results")
    if not isinstance(spec, dict) or not isinstance(results, list) or not results:
        raise ValueError(f"{path} holds no scan results")
    missing = [key for key in _REQUIRED if spec.get(key) is None]
    if missing:
        raise ValueError(f"{path} is missing {', '.join(missing)}")
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("values"), dict):
            raise ValueError(f"{path} holds a candidate with no geometry")
    return Saved(results, _spec(spec, stored_key), str(payload.get("when") or ""), path)


def _spec(spec, design_key):
    """The stored spec as the GUI's own: the design back as its object (so a
    consumer can't tell a restored scan's context from a live one) and the
    geometry frame back in tuples, JSON having flattened every one of them to a
    list."""
    spec = dict(spec)
    try:
        spec["design"] = registry.by_key(design_key)
    except KeyError as exc:
        raise ValueError(str(exc.args[0])) from exc
    for key in ("area", "pivot"):
        if isinstance(spec.get(key), list):
            spec[key] = tuple(spec[key])
    return spec
