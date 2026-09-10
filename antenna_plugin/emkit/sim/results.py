"""What a finished run says about itself.

The solver writes one file: a data dump of several hundred kilobytes, built
for a browser and not even JSON (``window.FDTD={s:{…}}`` -- the outer key is
unquoted, so ``json.loads`` refuses the whole file). It is the right artifact
for the report page and the wrong one for anybody holding a terminal.

A run can be *asked* for a second, readable copy of the same object
(``output_json`` -- a tick on the Advanced pane, a key in the form), and when
one was written it is archived beside the dump and pointed at from here. That
is the whole of the machine-readable story: this module composes no second
serialization of numbers the solver already wrote.

This is the small answer: which run, how far it got, and where to look at it.
Both halves already existed and were already headless -- the window has been
reading them since long before there was a command line -- but only the window
knew how to put them together. That composition is here now, so a run read
from a script and a run logged in the window are read by the same code.

**Nothing here computes anything, and that is deliberate.** Scalars the dump
carries ride through verbatim (``runinfo``); anything *judged* is the
product's, because nothing shared can know what a board was for. An antenna is
designed for a band and an impedance; a sweep's numbers are the answer
already. So the verdict arrives through ``<product>.runjob`` the same way the
config block does, and this module never learns which flow it is in.

Every result carries the ``viewer_url`` of the page that draws it, so an agent
can hand a human the graphical view of the exact thing it just described.
"""

import os

from . import runinfo, simulate


def latest(sim_dir, kind=None):
    """The newest archived dump for this board, or None if it has never run.

    Archived rather than live: ``simulation/pcb_data.js`` is whatever the
    solver last overwrote, while ``results/<stamp>/`` is a run somebody kept.
    Reading the archive is what makes "the results" mean the same thing here
    as in the window and in the report page's address bar.
    """
    found = simulate.latest_result(sim_dir, kind or simulate.REPORT)
    return None if found is None else str(found)


def for_job(sim_dir, job_id, kind=None):
    """Where run ``job_id`` archived its report, whether or not it got that
    far. A path, not an answer: a caller asking about a run that never wrote
    one wants to say so itself (:func:`stamps` is what it says it *with*).

    The id needs no lookup because it is the folder's name -- ``run start``
    answers the timestamp its outputs are archived under (``sim.jobs``), so
    every verb can speak in job ids and none of them has to know this shape.
    """
    folder = simulate.run_results_dir(sim_dir, job_id)
    return str(folder / simulate.DUMPS[kind or simulate.REPORT])


def job_of(dump_path):
    """Which run a dump belongs to -- the same rule as :func:`for_job` read the
    other way round: the folder holding it is named by the run's id. So a
    caller holding a path (the newest result, say) can still ask the run's own
    record what that run was started for, without a second lookup table.

    Whatever the parent folder is called, for a path that is not an archived
    dump: the id is then simply one no job was ever recorded under, which is
    the same answer a run started from the window gives.
    """
    return os.path.basename(os.path.dirname(dump_path))


def data_json(dump_path):
    """The machine-readable flavour of an archived dump -- the bare JSON the
    solver writes beside it when ``output_json`` is on -- or None when this run
    did not ask for one.

    Asked of the archive rather than of the form: whether a run wrote one is a
    fact about that run, and the form may have been retargeted since. Off the
    dump's own path, which is the same rule ``archive_dump`` copied it by.
    """
    data = f"{os.path.splitext(dump_path)[0]}.json"
    return data if os.path.isfile(data) else None


def grid_only(sim_dir, job_id):
    """Did run ``job_id`` write a lattice and no report? That is what
    ``run start --grid-only`` produces, and the guide pushes it hard enough
    that "no results" would be the wrong thing to tell whoever asks for one."""
    grid = os.path.isfile(for_job(sim_dir, job_id, simulate.GRID))
    return grid and not os.path.isfile(for_job(sim_dir, job_id))


def stamps(sim_dir):
    """Every run of this board with numbers to read, newest first -- exactly
    the ids ``--job`` can be given and get an answer to.

    Read off the folders rather than the job records, so a run started from
    the window is in the list too. A folder holding no report is *not*: a run
    that meshed and stopped, or died before its first report, has a name but
    nothing to show, and naming it here would be an invitation to a second
    refusal."""
    found = simulate.results_dir(sim_dir).glob(f"*/{simulate.DUMPS[simulate.REPORT]}")
    return sorted((p.parent.name for p in found), reverse=True)


def read(sim_dir, dump_path, verdicts=None):
    """Everything worth saying about the run whose dump is at ``dump_path``.

    ``verdicts`` is the product's judgement of it, or None -- an argument
    rather than something read here, because "was this good?" is a question
    only the flow that knows what the board is for can supply the terms of.
    Without one the numbers still come back, unjudged, which is honest and
    better than scoring against a target this side picked.
    """
    if not os.path.isfile(dump_path):
        raise RuntimeError(f"no results at {dump_path}")
    info = runinfo.read(dump_path)
    return {
        "dump": str(dump_path),
        # Two clocks, because they are two facts: the run's id time, and when
        # the numbers below it were actually written. A sampled report is
        # written minutes into the run its stamp names, so reporting the stamp
        # as the writing time dates a fresh reading to before it existed.
        "stamp": simulate.result_timestamp(dump_path),
        "written": simulate.dump_written(dump_path),
        # How far the run got, and why it stopped. What keeps an interrupted
        # or sampled result honest: a report written from a 2 ns record must
        # not read like a converged 20 ns one.
        "run": _run(info),
        "verdicts": verdicts,
        "viewer_url": _viewer_url(sim_dir, dump_path),
        # Where the numbers themselves are, for a reader that is not a page --
        # None unless the run was asked to write them readably (output_json).
        "data": data_json(dump_path),
    }


def _run(info):
    if info is None:
        return None
    return {
        "steps": info.steps,
        "planned_steps": info.planned_steps,
        "time_ns": info.time_ns,
        "planned_time_ns": info.planned_time_ns,
        "ring_down_db": info.ring_down_db,
        "stop": info.stop,
        "partial": info.partial,
        "sample": info.sample,
        # The solver's own sentence, preferred over anything composed here so
        # this can never disagree with the report page about what a run
        # covered.
        "summary": info.summary(),
    }


def _viewer_url(sim_dir, dump_path):
    """The page that draws this dump. Best effort: installing the viewer
    copies a folder, and a result that cannot be linked is still a result."""
    try:
        return simulate.viewer_url(sim_dir, simulate.REPORT, dump_path)
    except OSError:
        return None
