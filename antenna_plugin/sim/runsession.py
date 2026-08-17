"""RunSession: one solver invocation the caller can stop, sample and follow.

The GUI needs three things from a solve beyond "run it and log the lines":

  * a handle to post cooperative requests to -- Stop (end the run early but
    still write the report) and Snapshot report (write one mid-run and keep
    stepping). That is :mod:`runcontrol`, which needs the live process and
    the run's control file (the solver is launched with ``--control`` and
    polls it for request lines);
  * to know *when* a fresh set of outputs has landed on disk, so it can
    archive and show them. The solver says so on stdout: it prints
    ``--- Report sample: ... ---`` before serving a sample request and
    ``Wrote outputs to <dir>/`` once a set (page + data dump) is written.
    Watching the stream beats polling the filesystem -- no guessing whether a
    half-written page is complete;
  * a request that lands between two solver processes (the grid pass and the
    solve) not to be lost or applied to the wrong one.

A session owns exactly that: the process handle, the marker watch and the
"this session is closed" flag, with callbacks for everything it observes. No
wx and no pcbnew here -- the GUI marshals the callbacks onto its main thread
-- so the whole flow is testable headless (tests/test_runsession.py).

Typical use (from a worker thread)::

    session = RunSession(on_line=self.log, on_outputs=self._on_outputs)
    session.run(exe, yaml_path, grid_only=True)     # meshing pass
    session.run(exe, yaml_path)                     # the solve
"""

import os

from . import runcontrol

# What the solver prints around a set of outputs (RunLoop.cpp / the runners'
# writeOutputs). The sample banner comes first and only for a mid-run sample;
# the "wrote" line follows every set, including the run's final one.
_SAMPLE_MARK = "--- Report sample:"
_WROTE_MARK = "Wrote outputs to"


class RunSession:
    """One solver invocation (or a sequence of them, as the run flow's grid
    pass plus solve). ``on_line(text)`` sees every stdout line;
    ``on_outputs(sample)`` fires once the solver has written a set of outputs,
    with ``sample`` True for a mid-run snapshot and False for a run's final
    results. Both are called on the thread driving :meth:`run`."""

    def __init__(self, on_line=None, on_outputs=None, runner=None):
        self._on_line = on_line
        self._on_outputs = on_outputs
        # The solver launcher, injectable so tests can drive a session without
        # the binary; defaults to simulate.run_exe (imported lazily to keep
        # this module free of the pcbnew-adjacent one).
        self._runner = runner
        self._proc = None
        self._control = None  # the launched run's control file, if any
        self._closed = False  # stopped or killed: no further processes
        self._stop_requested = False
        self._samples_requested = 0
        self._samples_written = 0
        self._pending_sample = False

    # --- driving ------------------------------------------------------------
    def run(self, exe, yaml_path, grid_only=False):
        """Run the solver to completion, streaming its output through this
        session. Returns False without launching anything when the session has
        already been stopped or killed -- which is how a request that landed
        between two phases stops the next one from starting."""
        if self._closed:
            return False
        run_exe = self._runner
        if run_exe is None:
            from . import simulate

            run_exe = simulate.run_exe
        # The run's control file: launched with --control, requested through
        # runcontrol. A leftover file from an earlier run in the same folder
        # would replay its requests into the new process at its first poll --
        # a stale "stop" ending a run nobody stopped -- so it starts absent.
        self._control = runcontrol.control_path(yaml_path)
        try:
            os.remove(self._control)
        except OSError:
            pass  # wasn't there, which is the goal
        run_exe(
            exe,
            yaml_path,
            grid_only=grid_only,
            on_line=self._line,
            on_proc=self.attach,
            control=self._control,
        )
        return True

    def attach(self, proc):
        """``on_proc`` for the launcher: the solver process just started, so
        requests can reach it. Also the hook the wizard's scan passes down, so
        one session covers a whole sequence of per-candidate solves."""
        self._proc = proc
        if self._closed:  # closed while this process was starting
            runcontrol.kill(proc)

    def _line(self, text):
        """One stdout line: forward it, then act on the output markers (the
        line is logged first so the log reads in solver order)."""
        stripped = text.lstrip()
        if stripped.startswith(_SAMPLE_MARK):
            self._pending_sample = True
        if self._on_line:
            self._on_line(text)
        if stripped.startswith(_WROTE_MARK):
            sample, self._pending_sample = self._pending_sample, False
            if sample:
                self._samples_written += 1
            if self._on_outputs:
                self._on_outputs(sample)

    # --- requests -----------------------------------------------------------
    def request_stop(self):
        """Ask the solver to end its run early and still write the report from
        the record so far, and close the session so no further phase starts.
        Returns whether the request reached the process; on False the caller
        must fall back to :meth:`kill` (and gets no report)."""
        if not runcontrol.request_stop(self._proc, self._control):
            return False
        self._stop_requested = True
        self._closed = True
        return True

    def request_sample(self):
        """Ask the running solver for one set of outputs from the record so
        far; it keeps stepping. ``on_outputs(True)`` fires when they land.
        Returns whether the request reached the process."""
        if not runcontrol.request_sample(self._proc, self._control):
            return False
        self._samples_requested += 1
        return True

    def kill(self):
        """Take the solver down now -- nothing is written from the run -- and
        close the session. What a closing window wants."""
        self._closed = True
        return runcontrol.kill(self._proc)

    # --- state --------------------------------------------------------------
    @property
    def running(self):
        """True while a solver process of this session is alive."""
        return runcontrol.alive(self._proc)

    @property
    def stop_requested(self):
        """True once a cooperative stop was delivered (the run is winding
        down and writing its outputs)."""
        return self._stop_requested

    @property
    def samples_requested(self):
        return self._samples_requested

    @property
    def samples_written(self):
        """How many mid-run sets of outputs the solver has written so far."""
        return self._samples_written
