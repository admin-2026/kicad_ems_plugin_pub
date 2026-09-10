"""A run's state on disk, for a caller that is not waiting for it.

A solve is minutes -- 429 s for a small board on a coarse mesh -- so a command
line cannot hold one in the foreground and still be usable. ``run start``
returns a job id at once and the work goes on in a detached process;
everything after that is somebody reading this file.

Here rather than in the verb package because it is a *file format in the run
folder*, which is where the run folder's other formats already live: the
control file the solver polls (``runcontrol``), the run series it writes
(``runinfo``), the archived dumps (``simulate.archive_dump``). A caller that
knows where ``simulation/`` is knows where this is.

**One folder per run, and this is one file in it.** The id is the run's own
timestamp, which is also the stamp its dumps are archived under, so the record
lives in the folder holding them: ``simulation/results/<id>/job.json``, with
the solver's output beside it as ``run.log``. Everything one run produced is
one directory, and the id names it -- there is nothing to look up to get from
a job to its results, and no second place to list runs from.

The file is rewritten as the run moves on, and the last write is the one that
says how it ended. A job whose process dies without writing that is not
"running forever": :func:`read` reports it as lost, because the pid is gone
and nothing will ever finish it.

Pure stdlib -- no wx, no pcbnew.
"""

import json
import os
import time
from typing import NamedTuple

from . import hostos, simulate

# What a job's record and its log are called inside the run's own folder. Fixed
# names rather than the id again: the folder is already named by the id, and
# one run's files never share a directory with another's -- which matters
# because a run and a scan are allowed to be in flight at once, and a single
# log would have the two workers fighting over one file.
FILE = "job.json"
LOG = "run.log"

# How long a job may sit with no pid before it counts as never started. Long
# enough for a cold interpreter to import pcbnew on a slow disk, short enough
# that nobody watches a dead job for a minute.
STARTUP_GRACE_S = 30

# What a job can be. RUNNING is the only one written by the run itself; the
# rest are how it ended, and LOST is inferred rather than written -- see read().
RUNNING, DONE, FAILED, STOPPED, LOST = (
    "running",
    "done",
    "failed",
    "stopped",
    "lost",
)


class Job(NamedTuple):
    id: str
    state: str
    pid: int
    board: str
    # The form this run was built from (emkit.settings), carried whole rather
    # than as the path it was read from: the window rewrites its own file
    # whenever it closes, so a path would say what the board is set to *now*
    # and not what this run was asked for. It is also what the worker reads
    # back to score the reports, which is the one question a dump cannot
    # answer for itself.
    form: dict = {}
    grid_only: bool = False
    # Whether this run was asked to go through a container, when the caller
    # said so outright (`run start --docker` / `--no-docker`); None means they
    # did not, and the worker asks the machine's own preference. Carried for
    # the same reason the form is: the worker is another process, started
    # later, and a flag that stayed in the shell it was typed in would be a
    # flag that did nothing.
    docker: object = None
    started: float = 0.0
    ended: float = 0.0
    error: str = ""
    phase: str = ""

    @property
    def finished(self):
        return self.state != RUNNING

    def elapsed_s(self):
        return (self.ended or time.time()) - self.started


def directory(sim_dir, job_id):
    """This run's own folder -- its record, its log and its dumps. Named by
    ``simulate`` rather than spelled here, so the layout has one author."""
    return str(simulate.run_results_dir(sim_dir, job_id))


def path(sim_dir, job_id):
    return os.path.join(directory(sim_dir, job_id), FILE)


def log_path(sim_dir, job_id):
    """Where this job's worker writes the solver's stdout."""
    return os.path.join(directory(sim_dir, job_id), LOG)


def write(sim_dir, job):
    """Record ``job``. Written whole each time rather than patched: a job is a
    handful of fields, and a partial update is one more thing to get wrong."""
    os.makedirs(directory(sim_dir, job.id), exist_ok=True)
    target = path(sim_dir, job.id)
    # Written beside and renamed, so a reader polling this file never catches
    # it half-written -- which on a run somebody is watching would otherwise
    # happen exactly at the moments that matter.
    temporary = target + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(job._asdict(), handle, indent=1)
    os.replace(temporary, target)
    return target


def read(sim_dir, job_id):
    """The job, or None if there is no such id.

    A job still marked running whose process is gone comes back as LOST. That
    is the honest answer: nothing will ever write its ending, so reporting it
    as running would leave a caller waiting for a result that cannot arrive.

    A job with no pid is one whose file has been written but whose worker has
    not reported in yet. That is a real state and it is reported as running --
    but only briefly: a worker that never starts at all (the wrong
    interpreter, a package it cannot import) would otherwise leave the job
    running forever, which is the one answer a caller can never act on. After
    :data:`STARTUP_GRACE_S` it is lost like any other.
    """
    try:
        with open(path(sim_dir, job_id), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    fields = {k: v for k, v in data.items() if k in Job._fields}
    try:
        job = Job(**fields)
    except TypeError:
        return None
    if job.state != RUNNING:
        return job
    if not job.pid:
        if job.elapsed_s() < STARTUP_GRACE_S:
            return job
        return job._replace(
            state=LOST,
            error="the worker never started; nothing is running this job",
        )
    if not hostos.alive(job.pid):
        return job._replace(
            state=LOST,
            error="the process running this job is gone; it wrote no ending",
        )
    return job


def recent(sim_dir, limit=10):
    """The newest jobs first -- what ``run status`` shows when asked for no id
    in particular. Ids are timestamps and they name the folders, so directory
    order is time order.

    A run folder with no record in it is skipped rather than reported empty:
    that is a run the *window* started, which archives its dumps here and
    keeps no job file. Its numbers are still readable by id (``results show``);
    its state was never written down by anybody."""
    try:
        names = sorted(os.listdir(simulate.results_dir(sim_dir)), reverse=True)
    except OSError:
        return []
    out = []
    for name in names:
        job = read(sim_dir, name)
        if job is not None:
            out.append(job)
        if len(out) >= limit:
            break
    return out


def log_lines(sim_dir, job_id):
    """This job's whole log, or [] if it has written none yet.

    Read whole, once, because a caller wants two things out of it -- the
    stretch it has not seen and what the run has warned about anywhere in it
    (``sim.diagnostics``) -- and the file is a flood somebody is polling.
    """
    try:
        with open(log_path(sim_dir, job_id), encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


class Stretch(NamedTuple):
    """One read of a log: the lines, how many came before them, and the offset
    to ask for next time. ``first`` is carried rather than left to be worked
    out from the other two, so a caller can say which lines it read (and a
    renderer can say so to a reader) without doing the arithmetic itself."""

    lines: list
    first: int
    next: int


def resume(lines, since=0):
    """The stretch of a log from offset ``since`` on.

    The solver's output is a flood, so a poller reads from where it stopped
    rather than re-reading all of it. The offset is a line count, which
    survives the file growing between two reads -- a byte offset into a file
    being written line-buffered does too, but a caller cannot say "the last 20"
    with one.

    An offset past the end (a log that was truncated under a poller, or a
    caller's nonsense) is an empty stretch rather than an error: the answer to
    "what is new" is "nothing", and the next offset says where it really is.
    """
    since = min(max(0, int(since or 0)), len(lines))
    return Stretch(lines[since:], since, len(lines))
