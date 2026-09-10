"""What is already simulating this board, across every process on the machine.

Concurrency here is allowed on purpose. Two passes on one board do not collide
-- each gets its own thread, session, solver process, work folder and control
file -- but they do share the machine, and every solver sizes its mesh as if it
owned the box. So a second pass makes both slower and can run a tight machine
out of memory. That is a cost to consent to, not one to forbid, and the window
has always asked before starting one.

What it asked was a list held in memory (``gui.sections.solver.SolverSection``'s
``_live``), which could only ever see the passes of its own process. One window
and one window only was a safe assumption right up until a command line
existed. Now a run started from a shell and a run started from the window
cannot see each other at all, and both write into the same ``simulation/``
folder.

**One file per claim**, under ``simulation/running/``. Not one file holding a
list: a list has to be read, edited and written back, and two processes doing
that at once lose one of the entries. Creating and removing a file of its own
is the whole of the coordination, and there is nothing to race over.

**A dead process leaves nothing behind.** A claim names the pid that made it,
and a claim whose process is gone is ignored and swept up by the next reader --
so a killed window, or a machine that lost power mid-run, does not leave a
board that can never be run again. Whether that pid is still there is
``hostos.alive``'s answer and nothing else's -- the portable-looking one-liner
it replaced terminates the process it claims to be probing on Windows, so the
probe lives in one module and every caller reads it from there.

**A pid only means something where it was issued**, and there is now more than
one such place: a run started inside the container writes a claim into the
mounted project, and a window on the host reads it. Pid 7 in a container is not
pid 7 here -- it is likely nothing at all, and if it is something it is
somebody else's process. Asking ``hostos.alive`` about it gives an answer that
is right by coincidence: usually "dead", which sweeps a live run's claim and
lets a second run start on top of it, and occasionally "alive" about a wholly
unrelated program. So a claim records *where* it was made (:func:`origin`), and
a claim from somewhere else is **left alone and counted as live** -- which is
the bias ``hostos.alive`` already documents for anything it cannot establish.
It costs one warning nobody needed; the other way costs a run.

The cost of that bias, stated plainly: a container that is killed outright
leaves a claim nothing here will ever sweep, and this board warns about a run
that ended. It is a warning and not a refusal -- a second pass has always been
the user's to consent to -- and deleting ``simulation/running/`` clears it. The
alternative, ageing foreign claims out after some interval, would be this
module guessing at exactly the thing it has just admitted it cannot see.

Pure stdlib -- no wx, no pcbnew.
"""

import json
import os
import tempfile
import time
from typing import NamedTuple

from . import hostos

# Where the claims live, beside the run they are about. A directory rather than
# a file, since each claim is its own file.
DIRNAME = "running"


class Claim(NamedTuple):
    """One pass in flight: which process, where, what it calls itself, since
    when."""

    pid: int
    label: str
    started: float
    path: str = ""
    origin: str = ""  # where the pid was issued; "" for a claim written before

    @property
    def mine(self):
        return self.pid == os.getpid() and self.here

    @property
    def here(self):
        """Whether this claim's pid belongs to this machine's numbering.

        A claim with no origin at all is one written by an older version of
        this plugin, and on the machine it was written on -- there was nowhere
        else to write one from. Treating it as ours keeps the sweep working
        across an upgrade.
        """
        return self.origin in ("", origin())

    def age_s(self):
        return max(0.0, time.time() - self.started)


def origin():
    """Where this process's pids mean something, as one short word.

    The hostname, which a container has one of its own -- Docker gives each
    one the short form of its id unless told otherwise, and that is exactly the
    boundary this needs to notice. It does not have to be a *good* identifier:
    it only has to differ between two pid namespaces sharing one directory, and
    to be stable for as long as a run.
    """
    try:
        import socket

        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


def directory(sim_dir):
    return os.path.join(str(sim_dir), DIRNAME)


def claim(sim_dir, label):
    """Record that this process has started ``label`` on this board.

    Returns the claim, whose ``path`` is what :func:`release` takes. The label
    is what another caller's warning will name, so it is a noun phrase somebody
    can act on -- "the simulation run", not "run".
    """
    where = directory(sim_dir)
    os.makedirs(where, exist_ok=True)
    entry = Claim(os.getpid(), label, time.time(), origin=origin())
    # The name has to be unique per *claim*, not per process: one process may
    # hold a run and a scan at once, which is exactly what the window allows.
    # mkstemp both picks the name and creates the file in one step, so two
    # claims made in the same millisecond -- or by two processes at once --
    # cannot land on the same one. A timestamp would; it was tried, and two
    # claims in a row overwrote each other.
    handle, path = tempfile.mkstemp(prefix=f"{entry.pid}-", suffix=".json", dir=where)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "pid": entry.pid,
                "label": label,
                "started": entry.started,
                "origin": entry.origin,
            },
            stream,
        )
    return entry._replace(path=path)


def release(entry):
    """Drop a claim. Safe to call twice, and on a claim whose file somebody
    else already swept up -- every finish path calls it, including the ones
    that failed."""
    if entry is None or not entry.path:
        return
    try:
        os.remove(entry.path)
    except OSError:
        pass  # already gone, which is the goal


def live(sim_dir, exclude=()):
    """Every pass currently in flight on this board, oldest first.

    ``exclude`` drops claims by path -- how a caller leaves its own out of the
    list it is about to warn about. Stale claims (the process is gone) are
    removed as they are found, so the sweep costs nothing extra and no board
    stays wedged after a crash.
    """
    where = directory(sim_dir)
    try:
        names = sorted(os.listdir(where))
    except OSError:
        return []  # no directory means nothing has ever run here
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(where, name)
        entry = _read(path)
        if entry is None:
            _sweep(path)
            continue
        # Only a claim from this machine's numbering can be asked about, and
        # only one that answers "dead" is swept: see the module docstring.
        if entry.here and not hostos.alive(entry.pid):
            _sweep(path)
            continue
        if path not in exclude:
            out.append(entry)
    return sorted(out, key=lambda c: c.started)


def labels(sim_dir, exclude=()):
    """Just the names of what is in flight -- what a warning or a report
    lists."""
    return [entry.label for entry in live(sim_dir, exclude)]


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return Claim(
            int(data["pid"]),
            str(data["label"]),
            float(data["started"]),
            path,
            str(data.get("origin", "")),
        )
    except (OSError, ValueError, KeyError, TypeError):
        # A half-written or corrupt claim is not evidence that anything is
        # running, and leaving it would block the board's warning forever.
        return None


def _sweep(path):
    try:
        os.remove(path)
    except OSError:
        pass
