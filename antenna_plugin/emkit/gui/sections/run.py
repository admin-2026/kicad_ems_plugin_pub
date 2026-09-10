"""The Run section of a simulate view: one solve of the open board.

Every flow runs the same way -- read the stackup, plot the gerbers, write the
config, mesh, solve, archive what the solver wrote -- so all of that is here,
and what differs is three methods a plugin fills in: what the run is scored
against (``start_target``), how the board's markers become the config's ports
(``apply_ports``), and what to do with a report once it is archived
(``score_report``).

RunSection owns what starts and ends a run: the knobs of the pass itself
(sections.passknobs -- the simulation time and Auto ground/source, built here
because this is the button that spends them), the buttons (Run simulation,
Generate grid and Snapshot report), the board-facts and status lines at the foot
of the section, and the whole run flow behind them -- the run config params, the
worker thread and stop/cancel/shutdown. Showing what a run produced belongs to
the Results section below it (sections.results), which this section hands each
archived page to; the viewer windows themselves are the page's (gui.viewers).

The solve is interruptible, which shapes this section's buttons. A run has two
phases, and only the second one has results:

  * meshing (``--grid-only``) -- the Run button reads Cancel and kills it;
    there is nothing to report yet;
  * the FDTD solve -- the Run button reads Stop and asks the solver to end the
    run early and still write its report from the data simulated so far;
    Snapshot report asks for one such report *without* stopping -- and reads
    Snapshotting, disabled, until that report lands, since writing one takes
    as long as a normal report. Once that stop is asked for, the Run button
    reads Stopping and is disabled: the report is on its way and nothing
    should throw it away. (A solver that can't be reached to stop
    cooperatively is killed outright, as is one cancelled during the meshing
    pass or by closing the window.)

Generate grid runs the first phase alone: the same preparation and config as a
full run, ending once the grid preview is written (``_start_run(grid_only)``,
which both buttons share, and the ``grid_only`` arm of ``_worker``). It is the
cheap way to check the mesh a board produces before paying for a solve.

Either way the solver announces every set of outputs it writes on stdout, and
the session watching that stream calls ``_on_outputs``, which archives the
report and hands it to the Results section -- one path for a mid-run snapshot,
an interrupted run and a finished one, so a partial report is presented
exactly like a complete one, labelled with what it covers (``sim.runinfo``).

Three collaborators meet here:
  * the pre-flight banner (PreflightBanner) recomputes the blockers and calls
    ``on_preflight`` so this section can gate the buttons that start a run; at
    the top of a run this section asks the banner to refresh
    (``page.banner.refresh``) and reads back the problem list;
  * the run params come from the other sections -- the page's form
    (``contribute``: the frequency target), its Feed layer and
    AdvancedSection.contribute -- plus this section's own pass knobs
    (see ``run_params``);
  * every dump the run archives goes to the Results section
    (``page.results.present``), which owns how a grid/report is titled and
    shown -- so a result opened as the solver writes it and one re-opened later
    look the same.

Threading: the board-touching steps (stackup read, gerber plot, config write)
run on the wx main thread because pcbnew objects aren't thread-safe; the slow
solver passes stream from a daemon worker via the batched log. Stop and
Snapshot report are posted from the main thread to the live solver process
through the run session (sim.runsession / sim.runcontrol).
"""

import time
from pathlib import Path

import pcbnew
import wx

from ...kicad.version import get_kicad_version
from ...sim import launch
from ...sim.runner import MESH as _MESH
from ...sim.runner import SOLVE as _SOLVE
from ..board import board_info
from ..theme import HAIR, PAD
from ..widgets import enable, set_tip
from .passknobs import PassKnobs
from .solver import SolverSection


def collect_run_params(page, run_dir):
    """The run config params for ``page``: the feed layer, plus the fields each
    section of the page owns -- its form's ``contribute`` (the frequency
    target), AdvancedSection.contribute (copper model, speed/quality toggles,
    materials, numeric knobs) and the page's pass knobs (how long to step for
    and whether the solver may find its own ground/source, see
    ``page.pass_knobs``).

    A page that starts a run answers four things: ``feed_layer_name``,
    ``form``, ``advanced`` and ``pass_knobs``. That is the whole contract, and
    it is why a sweep can reuse this without being a run."""
    params = {"outdir": run_dir, "feed_layer": page.feed_layer_name()}
    page.form.contribute(params)
    page.advanced.contribute(params)
    page.pass_knobs.contribute(params)
    return params


# The status line each phase shows (the solve's is restored after a snapshot).
# The phases themselves are sim.runner's -- the sequence lives there, and both
# frontends compare against the same two words.
_MESH_STATUS = "Meshing the grid…"
_SOLVE_STATUS = "Running the FDTD solve…"
_STATUS = {_MESH: _MESH_STATUS, _SOLVE: _SOLVE_STATUS}


class RunSection(SolverSection):
    _TITLE = "Run"

    # Why Generate grid is unavailable while a run is on (SolverSection).
    _BUSY_TIP = "Available when no run is in flight"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)  # _session / _running / _cancelled
        self._blocked = False  # a pre-flight "block" gates the Run button
        self._phase = ""  # _MESH / _SOLVE while a run is on
        self._stopping = False  # a cooperative stop is being served
        self._sampling = False  # a snapshot report was asked for and is
        # still being written
        self._grid_only = False  # this run stops after the meshing pass
        self._run_info = None  # what the last report covers (runinfo)
        self._target = None  # the design target this run was started for
        # (read off the form on the main thread at Run, scored on the worker)
        self._build(body)

    @property
    def busy_label(self):
        """How a designer's scan names this section's pass when it warns about
        starting a second one (SolverSection.confirm_concurrent). Only read
        while this one is in flight, so ``_grid_only`` is this run's."""
        if self._grid_only:
            return "the grid pass on the Simulate page"
        return "the simulation run"

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        """The pass knobs, the buttons that start (or end) a run on one row, and
        the section's two text lines at its foot. Re-opening what a run produced
        is the Results section below this one; the run log is the last section
        of the page."""
        p = self.scroll
        box = self.box(self._TITLE)

        # How long the solve steps for, and whether the solver finds its own
        # ground/source: the knobs above the button that spends them. One value
        # each with the designers' scans (sections.passknobs).
        self.knobs = PassKnobs(p, self._relayout)
        box.Add(self.knobs.sizer, 0)

        run_row = wx.BoxSizer(wx.HORIZONTAL)
        self.run_btn = self.row_button(run_row, "Run simulation", self.on_run)
        self.run_btn.SetDefault()
        # The meshing pass on its own: the grid without the solve behind it.
        self.grid_only_btn = self.row_button(
            run_row, "Generate grid", self.on_grid_only
        )
        # Ask the running solve for a report from the data simulated so far.
        # Only live during the solve phase (_sync_run_buttons).
        self.sample_btn = self.row_button(run_row, "Snapshot report", self.on_sample)
        box.Add(run_row, 0, wx.EXPAND | wx.TOP, PAD)

        # The section's text at its foot, under the buttons: which board a run
        # would use, then what the run is doing right now. Both are full-width
        # wrapping lines, so a long status message (or board path) wraps into
        # the section instead of being cut off by the button beside it.
        # The board line only has something to say from the first run on
        # (_show_board), so it starts hidden -- an empty label would still hold
        # a line's height, leaving a blank gap under the buttons.
        self._board_lbl = self.wrap_label(p, mute=True)
        self._board_lbl.Hide()
        box.Add(self._board_lbl, 0, wx.EXPAND | wx.TOP, PAD)
        self._status_label = self.wrap_label(p, "Ready.", mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, HAIR)
        self.add_to_body(body, box)
        # The at-rest state (Snapshot report disabled, tooltips set) comes from
        # the one place that decides it, rather than a second set of initial
        # values here; the pre-flight banner then gates it a moment later.
        self._sync_run_buttons()

    # --- pre-flight gate ------------------------------------------------------
    def on_preflight(self, blocked):
        """The pre-flight banner recomputed: gate the Run button on a blocker.
        While a run is in flight the button is Stop/Cancel and stays enabled
        regardless (_sync_run_buttons)."""
        self._blocked = blocked
        self._sync_run_buttons()

    def _sync_run_buttons(self):
        """Put the run row's buttons in step with the run state -- the single
        place that decides what they mean right now:

            at rest      Run simulation + Generate grid (both gated by the
                         pre-flight banner)
            meshing      Cancel          (no results yet to write)
            solving      Stop            + Snapshot report
            sampling     Stop            + Snapshotting (disabled until the
                                          snapshot report lands)
            stopping     Stopping        (disabled: the solver is writing its
                                          report and the run ends on its own)
        """
        solving = self._running and self._phase == _SOLVE and not self._stopping
        # A snapshot takes as long as a normal report to write, so the button
        # says so and locks out until it lands (_sampled) -- one request at a
        # time, and no doubt about whether the click registered.
        self.sample_btn.SetLabel(
            "Snapshotting" if self._sampling else "Snapshot report"
        )
        enable(self.sample_btn, solving and not self._sampling)
        if self._sampling:
            tip = (
                "The solver is writing the snapshot report; it appears "
                "below when it lands"
            )
        elif solving:
            tip = "Write a report from the data simulated so far and keep solving"
        else:
            tip = "Available while the FDTD solve is running"
        set_tip(self.sample_btn, tip)
        # Grid only: one run at a time, and a blocker gates a mesh exactly as
        # it gates a solve -- both write the same config from the same board.
        enable(self.grid_only_btn, not self._running and not self._blocked)
        set_tip(
            self.grid_only_btn,
            self._start_tip(
                "Mesh the board and show the grid preview, without solving it"
            ),
        )
        if not self._running:
            self.run_btn.SetLabel("Run simulation")
            enable(self.run_btn, not self._blocked)
            set_tip(self.run_btn, self._start_tip(""))
            return
        if self._stopping:
            # A stop already asked for: the solver is writing its report and
            # the run ends when it lands, so the button only reports that --
            # there is nothing left to press, and pressing must not throw the
            # report away.
            self.run_btn.SetLabel("Stopping")
            enable(self.run_btn, False)
            set_tip(
                self.run_btn,
                "The solver is writing its report; the run ends when it lands",
            )
            return
        enable(self.run_btn, True)
        if solving:
            self.run_btn.SetLabel("Stop")
            set_tip(
                self.run_btn,
                "End the run early; the solver still writes a report from "
                "the data simulated so far",
            )
        else:
            self.run_btn.SetLabel("Cancel")
            set_tip(
                self.run_btn, "Stop the run (the mesh has no results to report yet)"
            )

    def _start_tip(self, ready):
        """The shared start-only tooltip (SolverSection), plus this view's own
        gate: a pre-flight blocker keeps a run from starting at all."""
        if self._blocked and not self._running:
            return "Blocked — fix the issues listed at the top of the window"
        return super()._start_tip(ready)

    # --- status helpers -------------------------------------------------------
    def _show_board(self):
        """Name the board this run uses on the section's first text line. The
        line is hidden while it has nothing to say (see _build), so showing it
        regrows the section -- hence the relayout."""
        info = board_info()
        if info.get("ok"):
            text = (
                f"{Path(info['file']).name} — {info['footprints']}"
                f" footprints · {info['nets']} nets"
                f" · {info['thickness_mm']} mm"
                f" · {info['size_mm'][0]} × {info['size_mm'][1]} mm"
            )
        else:
            text = info.get("error", "")
        self._board_lbl.SetLabel(text)
        self._board_lbl.Show(bool(text))
        self._relayout()

    # --- run flow -------------------------------------------------------------
    def on_run(self, event=None):
        """Run button: start a full run (mesh, then solve), or -- while one is
        in flight, where the button reads Stop / Cancel -- end it
        (_stop_run)."""
        if self._running:
            self._stop_run()
            return
        self._start_run(grid_only=False)

    def on_grid_only(self, event=None):
        """Generate grid button: the meshing pass on its own. Everything up to
        the solver call is a full run's -- the same pre-flight, gerbers and
        config -- so the grid previews exactly the mesh the solve would use;
        the run just ends once the grid is written. Disabled while a run is in
        flight (_sync_run_buttons), so it never races one."""
        self._start_run(grid_only=True)

    def _start_run(self, grid_only):
        """Prepare and launch a run: pre-flight, board stackup, gerbers and the
        run config on the main thread (pcbnew objects aren't thread-safe), then
        the solver on a worker. ``grid_only`` stops it after the mesh."""
        from ...sim import simulate

        # A scan may already be running in a designer. That is allowed, but it
        # is the user's call to make (SolverSection.confirm_concurrent) -- and
        # it is asked before any of the work below, so a declined run leaves
        # the board and this section exactly as they were.
        if not self.confirm_concurrent():
            return
        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            self._report_failure("No board is open.")
            return
        self._claim()  # _running, and the board's folder now names this pass
        self._cancelled = False
        self._stopping = False
        self._sampling = False
        self._grid_only = grid_only
        self._phase = _MESH
        self._run_info = None
        # What every report of this run is scored against, taken now: the
        # archiving happens on the worker thread, where reading a wx control is
        # not allowed, and a form edited mid-run must not change what the run
        # in flight was asked to achieve.
        self._target = self.start_target()
        self._sync_run_buttons()
        self.page.log_ctrl.Clear()
        self.page.save_settings()  # capture the form even if the run fails
        self._show_board()

        try:
            # How the run starts (native or container) is decided on the
            # worker: deciding it asks the engine two questions, and a Docker
            # Desktop still waking up takes seconds to answer them -- on the wx
            # thread that is a frozen window between the click and the run.
            # The board's KiCad version is read here, where pcbnew is allowed.
            kicad_version = get_kicad_version()
            run_dir = simulate.output_dir(board)
            self._step(f"Simulation folder: {run_dir}")
            if grid_only:
                self.log("Grid only — the FDTD solve will not run.")

            # Pre-flight: the same blockers the banner shows, re-checked at
            # the moment of Run (the stackup may have changed since the
            # banner last refreshed, with the Run button still enabled).
            problems = self.page.banner.refresh()
            blocker = next((p for p in problems if p.severity == "block"), None)
            if blocker is not None:
                self._finish(False, blocker.message)
                return
            # The stackup is parsed from the saved .kicad_pcb, so the file on
            # disk must match the board being edited -- the banner has just
            # answered that, so the shared check doesn't re-derive it.
            if self._ensure_board_saved(
                board, any(p.id == "stackup-dirty" for p in problems)
            ):
                self.page.banner.refresh()  # the dirty warning is gone now

            self._step("Reading board stackup…")
            stack = simulate.collect_stackup(board)
            self.log(
                f"  substrate {stack['substrate_thickness_mm']} mm, "
                f"metal {stack['copper_thickness_mm']} mm, "
                f"{stack['copper_layer_count']} layer(s)"
            )

            self._step("Plotting gerbers from the board…")
            gerbers = simulate.plot_gerbers(board, run_dir / "gerbers")
            self.log(f"  {len(gerbers['copper'])} metal layer(s) + drills")

            params = self.run_params(str(run_dir))
            self.apply_ports(board, params)

            self._step("Writing simulation config…")
            simulate.write_config(gerbers, stack, params, str(run_dir / "pcb.yaml"))
        except Exception as exc:
            self._finish(False, str(exc))
            return

        # One stamp per run so the grid and every report of this run -- the
        # final one and any mid-run snapshot -- land in the same per-run folder
        # (results/<stamp>/); the binary itself only ever overwrites the same
        # pcb_grid.js / pcb_data.js dumps in run_dir.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self._begin_session(
            on_outputs=lambda sample: self._on_outputs(run_dir, stamp, sample)
        )
        self._start_worker(kicad_version, run_dir, stamp, grid_only)

    def _worker(self, kicad_version, run_dir, stamp, grid_only):
        """The daemon thread: mesh, then solve. The *sequence* is sim.runner's
        -- the same one a detached command-line worker drives -- and what is
        left here is this view of it, marshalled onto the main thread.

        It starts by deciding how this machine runs a solve (``launch.prepare``,
        which probes the container engine), because that is the one preparation
        step that talks to something outside this process and can take seconds
        to answer."""
        from ...sim import runner

        try:
            wx.CallAfter(self._step, "Starting the solver…")
            launcher = launch.prepare(kicad_version=kicad_version)
            runner.solve(
                self._session,
                launcher,
                run_dir,
                stamp,
                grid_only=grid_only,
                on_phase=lambda phase: wx.CallAfter(self._enter_phase, phase),
                on_grid=lambda path: wx.CallAfter(
                    self.page.results.present, path, "Grid preview"
                ),
                cancelled=lambda: self._cancelled,
            )
            wx.CallAfter(self._finish, True, None)
        except Exception as exc:
            # A killed solver exits non-zero; report the cancel, not the exit
            # code. A cooperative stop exits cleanly and lands above instead.
            msg = "run cancelled" if self._cancelled else str(exc)
            wx.CallAfter(self._finish, False, msg)

    def _enter_phase(self, phase):
        """Main thread: the run moved on to its meshing / solve phase. Only the
        solve can be snapshotted or stopped into a report, so the buttons follow
        the phase."""
        if not self.page:
            return
        self._phase = phase
        self._sync_run_buttons()
        self._set_status(_STATUS[phase])

    def _stop_run(self):
        """The Run button while a run is in flight. During the solve this is
        the cooperative stop: the solver ends the run early and still writes
        its report from the data simulated so far, which _on_outputs archives
        and shows like any other. A stop during the meshing pass, which has no
        results to write, or one the solver can't be reached for, kills it
        outright instead."""
        session = self._session
        if self._stopping:
            # The button is disabled while a stop is being served, so this is
            # at most a click that was already queued: let the report land.
            return
        if session is None or self._phase != _SOLVE:
            self._cancel_run()
            return
        if not session.request_stop():
            self.log(
                "Could not reach the solver to stop it gracefully "
                "(no control channel to it here); stopping it outright — "
                "no report will be written."
            )
            self._cancel_run()
            return
        self._stopping = True
        self._sync_run_buttons()
        self._step(
            "Stopping — the solver is writing a report from the data simulated so far…"
        )

    def _cancel_run(self):
        """The hard stop (Cancel, and window close): flag the run and kill the
        solver, writing nothing; the worker then reports back through
        _finish."""
        self._request_cancel()
        self._set_status("Cancelling…")

    def on_sample(self, event=None):
        """Snapshot report: ask the running solve for a report from the data
        simulated so far. The solve keeps stepping; the report lands through
        _on_outputs a moment later (writing it takes as long as a normal
        report), which is why the button reads Snapshotting and is disabled
        until then."""
        session = self._session
        if session is None or not self._running or self._sampling:
            return
        if not session.request_sample():
            self._set_status("Could not reach the running solver to snapshot it.")
            self.log(
                "Snapshot request could not be delivered to the solver "
                "(no control channel to it here)."
            )
            return
        self._sampling = True
        self._sync_run_buttons()
        self._step(
            "Snapshotting — writing a report from the data simulated "
            "so far; the solve continues…"
        )

    def _finish(self, ok, error):
        if not self.page:
            return
        # A stopped run is a successful one: the solver ended early but wrote
        # its report, so say what that report covers rather than "Ready."
        stopped, self._stopping = self._stopping, False
        # A run can end while a snapshot is still in flight (the solve finished,
        # or was stopped/cancelled first); the button goes back to Snapshot
        # report either way.
        self._sampling = False
        self._release()  # _running, and the pass drops its claim
        self._phase = ""
        self._end_session()
        # While running, the button is Stop/Cancel and stays enabled regardless
        # of blockers; back at rest it must honour the banner's gate again.
        self._sync_run_buttons()
        if not ok:
            self._set_status(f"✗ {error}")
            self.log(f"ERROR: {error}")
            self._report_failure(
                "The run did not complete.\n\n"
                "See the run log below for what went wrong."
            )
            return
        if self._grid_only:
            # A grid-only run has no report to describe -- say what it did
            # rather than let "Ready." imply a solve happened.
            self._set_status("Grid ready — the FDTD solve was not run.")
            return
        info = self._run_info
        # "Stopped early" only if the report really covers less than the plan:
        # a stop that lands while the solve is already writing its final
        # outputs changes nothing about the run, so don't claim it did.
        early = stopped and (info is None or info.partial)
        head = "Stopped early." if early else "Ready."
        self._set_status(f"{head} {info.summary()}" if info else head)

    # --- what a flow fills in -------------------------------------------------
    def start_target(self):
        """What this run is asked to achieve, read off the form at Run and
        carried to the worker that scores the reports. None for a flow with
        nothing to score against."""
        return None

    def apply_ports(self, board, params):
        """Resolve the board's port markers into the run config's ports.

        The flow's own: one feed marker for an antenna, one per port for an
        S-parameter run. A marker the user rotated off a grid axis may also set
        ``rotation_deg`` here, so the driven trace is axis-aligned in the
        simulation.
        """
        raise NotImplementedError

    def score_report(self, dump_path):
        """A report has just been archived (worker thread). A flow that can
        judge one leaves its verdicts beside it here; the default is that a run
        is its own answer."""

    def run_params(self, run_dir):
        """The run config params (module-level collect_run_params, shared with
        the wizard's scan): the feed layer plus the shared sections' fields."""
        return collect_run_params(self.page, run_dir)

    # --- the solver wrote something ------------------------------------------
    def _on_outputs(self, run_dir, stamp, sample):
        """The solver just wrote a set of outputs -- a mid-run snapshot
        (``sample``), or the run's final ones, which an interrupted run writes
        exactly the same way. Archive the report with its data and show it.

        Called on the worker thread, from the session watching the solver's
        stdout, so the files are known to be complete. A snapshot overwrites the
        previous report in this run's folder, mirroring the solver's own files:
        'the report' always means the newest, longest record of this run."""
        from ...sim import simulate

        try:
            path = simulate.archive_dump(run_dir, simulate.REPORT, stamp)
        except OSError as exc:
            self.log(f"could not archive the report: {exc}")
            return
        wx.CallAfter(self.page.results.present, path, "Simulation report")
        self._run_info = self._log_run_info(path)
        self.score_report(path)
        if sample:
            wx.CallAfter(self._sampled)

    def _log_run_info(self, dump_path):
        """Log what an archived report covers -- the simulated time and
        ring-down the solver recorded in its dump (sim.runinfo) -- and return
        it. None for a dump carrying no run series."""
        from ...sim import runinfo

        info = runinfo.read(dump_path)
        if info:
            self.log(f"  report covers {info.summary()}")
        return info

    def _sampled(self):
        """Main thread: a snapshot landed; the solve is still running, so free
        the Snapshot report button again and put the status back to the solve
        with what the snapshot covered."""
        if not self.page:
            return
        self._sampling = False
        if not self._running:
            return  # the run ended with it; _finish owns the state
        self._sync_run_buttons()
        # The label already names the snapshot ("… · snapshot 2", see
        # sim.runinfo), so the status line just carries it.
        label = self._run_info.label() if self._run_info else ""
        self._set_status(f"{_SOLVE_STATUS} ({label})" if label else _SOLVE_STATUS)
