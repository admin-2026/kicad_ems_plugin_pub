"""Driving one run to completion.

Everything up to here -- the stackup, the gerbers, the config -- has happened;
this is what comes next. A run is *one* solver invocation with two phases:

    the meshing phase   builds the lattice and writes the grid dump
    the solve           steps the fields and writes the report

and the solver does both, in that order, in the same process. It used to be
two invocations, the first with ``--grid-only``, which meshed the board twice:
a solve begins by building exactly the same lattice and writing exactly the
same grid dump before it steps anything, so the extra pass bought nothing and
cost a full meshing (minutes on a fine cell). What it did buy was the *moment*
-- the grid archived and shown while the fields were still stepping -- and that
is what the session's grid marker now supplies: the solver's own "Wrote
<...>_grid.js" line, which lands at precisely the same point in the run.

``--grid-only`` remains what a grid-only run asks for: there, stopping after
the lattice is the point.

The sequence used to live in the window's worker thread, wrapped in
``wx.CallAfter``. What was actually wx about it was the *reporting* -- which
phase the buttons should show, which archived file to put on screen -- and not
the sequence, so the sequence is here and the reporting is a pair of
callbacks. The window marshals them onto its main thread; a command line
writes them to a job file. Without this split the command line would
reimplement the run flow, which is the duplication CLAUDE.md forbids in so
many words.

No wx, no pcbnew. What is deliberately *not* here:

  * **the session.** :class:`sim.runsession.RunSession` already owns one
    solver invocation, its control file and the stop/sample requests, and it
    is already headless. This drives one; it does not replace it.
  * **the interactive parts.** Offering to save the board, asking whether to
    start a second pass -- conversations, which need somebody to have them.
"""

import os

# The two phases of a run, in order. Only the solve produces results, so only
# it can be snapshotted or stopped into a report. Both frontends name them
# from here: the window puts them on a button, a job file records them, and a
# caller polling from a shell compares against the same two words.
MESH, SOLVE = "mesh", "solve"


def _ignore(*_args):
    """The default callbacks: drive the run and say nothing about it."""


def _never():
    return False


def solve(
    session,
    exe,
    run_dir,
    stamp,
    grid_only=False,
    on_phase=_ignore,
    on_grid=_ignore,
    cancelled=_never,
):
    """Run the solver, archiving the grid the moment it is written and moving
    the run to its solve phase there.

    ``session`` is the :class:`~sim.runsession.RunSession` the run goes
    through -- the caller opens it, because the caller is what holds the
    handle a Stop needs. Its ``on_outputs`` is where a *report* is archived
    from: the solver may write several (a mid-run snapshot, then the run's
    final set), and only the session knows when each has landed. The grid is
    archived here instead, from the session's grid marker, because it is
    written exactly once and this is the only moment it is the newest thing in
    the folder.

    ``on_phase`` reports :data:`MESH` at the start and :data:`SOLVE` when the
    grid lands, which is the boundary that matters to a caller: only the solve
    can be sampled or stopped into a report, and before it a stop has to kill.

    ``cancelled()`` is asked after the run, and a True answer raises. That is
    not the same as the hard cancel, which takes the solver down mid-step
    through the session; this is the narrower case of a request that arrived
    while nothing was running.

    Raises whatever the run raised. A half-finished run has no useful return
    value, and the caller's finish path wants the exception either way.
    """
    from . import simulate

    yaml_path = os.path.join(str(run_dir), "pcb.yaml")
    on_phase(MESH)

    archived = []

    def grid_written():
        # Called from the session's line watch, so it runs while the solver is
        # still going: the phase first, then the archive, so a caller told the
        # solve has begun cannot be told it after the grid it produced.
        if not grid_only:
            on_phase(SOLVE)
        archived.append(simulate.archive_dump(run_dir, simulate.GRID, stamp))
        on_grid(archived[-1])

    session.on_grid = grid_written
    # The reports are archived by whoever is watching the session's output
    # markers: one per snapshot, plus the run's final set -- and an interrupted
    # run writes its final set just the same, from the record so far, which is
    # the whole point of the cooperative stop.
    session.run(exe, yaml_path, grid_only=grid_only)
    # A run that finished without ever saying so -- a solver too old to print
    # the marker -- still wrote the dump, and a run with no archived grid is a
    # run nobody can check the mesh of. Late is better than never.
    if not archived and os.path.isfile(
        os.path.join(str(run_dir), simulate.DUMPS[simulate.GRID])
    ):
        grid_written()
    _check(cancelled)


def _check(cancelled):
    if cancelled():
        raise RuntimeError("cancelled")
