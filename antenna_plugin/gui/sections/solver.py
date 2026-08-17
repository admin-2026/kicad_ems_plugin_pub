"""SolverSection: the shared base for sections that drive the monopole solver.

The simulate view's Run section and the wizard's Scan section both launch the
bundled solver on a daemon worker thread and let the user cancel it. They share
the run bookkeeping (the live :class:`~...sim.runsession.RunSession`, the
running/cancelled flags), the worker launch, the cancel/shutdown that takes the
solver down, and the ``running`` flag the shell reads on focus. This base owns
that lifecycle so the two sections keep only what differs -- what they run and
how they present it.

The session is the handle on the solver process: everything that talks *to* a
running solver (stop it cooperatively, ask it for a mid-run report sample, kill
it) goes through it, so no section reaches for a Popen itself.

Both also start from the same board: the stackup is read from the saved
``.kicad_pcb``, so before either launches anything the file on disk has to
exist and match the board being edited (``_ensure_board_saved``, which asks
before saving on the user's behalf). And both carry a button that can only
*start* something -- Generate grid(s) beside Run simulation / Start scan --
whose tooltip explains why it is unavailable right now (``_start_tip``).

Several passes at once
----------------------
The shell can drive one run plus one scan per registered design, and they are
genuinely independent -- a thread, a session, a solver process, a work folder
and a control file each (see dev_docs/concurrent-runs.md). What they do share is
the machine: every solver sizes its mesh as if it owned the box, so a second
pass makes both slower and can run a tight machine out of memory. They also
share the result-viewer windows, so the newest page written takes the screen.

That is a cost to consent to, not one to forbid: a section asks
``confirm_concurrent()`` before it starts anything, which warns (naming what is
already in flight) only when something else *is*, and the user decides. The
list of live passes is this class's, since there is one shell per editor
(gui.show raises the existing window rather than opening a second), and it is
kept by ``_claim`` / ``_release`` -- the one pair that also owns the
``_running`` flag, so what a section believes about itself and what the shell
believes about it cannot drift apart.

Subclass contract:
  * implement ``_worker(*args)`` -- the thread body, which drives the session
    (``session.run(...)``, or hands ``session.attach`` to a driver that
    launches the solver itself) and reports back to the main thread with
    ``wx.CallAfter``;
  * ask ``confirm_concurrent()`` before doing any work for a pass, and give up
    on False (the user declined to run a second one);
  * name the pass for that warning with ``busy_label``;
  * open the session with ``_begin_session()`` before launching the worker
    with ``_start_worker(*args)``; mark the pass live with ``_claim()`` first;
  * cancel with ``_request_cancel()`` (a Cancel button and shutdown) -- that is
    the hard stop, which discards the run; a section that wants the solver's
    "stop early but still write the report" asks its session for it (see
    RunSection._stop_run);
  * clear the session with ``_end_session()`` and end the pass with
    ``_release()`` when the run finishes -- on every path, including the
    failed and cancelled ones;
  * a subclass that owns result viewers overrides ``shutdown`` to tear them
    down after ``super().shutdown()``.
"""

import threading

import wx

from ...sim.runsession import RunSession
from .base import Section


def _and_list(items):
    """``a``, ``a and b``, ``a, b and c`` -- for naming the live passes in one
    sentence."""
    items = list(items)
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


class SolverSection(Section):
    # Why a start-only button is unavailable while this section is busy
    # (_start_tip); subclasses word it for what they run.
    _BUSY_TIP = "Available when nothing is running"

    # Every pass in flight right now, across the whole shell, in start order
    # (see the module docstring). Class-level on purpose: the sections of one
    # window have no other way to see each other, and there is only ever one
    # window. Kept by _claim / _release alone.
    _live = []

    def __init__(self, page, step=None):
        super().__init__(page, step)
        self._session = None  # the live solver session (None at rest)
        self._running = False  # a run/scan is in flight
        self._cancelled = False  # the current run/scan was cancelled

    @property
    def running(self):
        """True while a run/scan is in flight (the shell reads this on focus)."""
        return self._running

    @property
    def busy_label(self):
        """How another section names this one's pass when it warns about
        starting a second (``confirm_concurrent``) -- a lower-case noun phrase
        that says which view to go to if the user would rather stop it, e.g.
        "the simulation run". Subclasses word it for what they run."""
        return "a run"

    # --- one pass, or several -------------------------------------------------
    def confirm_concurrent(self):
        """Ask, if anything else is already in flight, whether to start this
        pass as well; returns whether to go ahead. True at once when nothing
        else is running, which is the ordinary case -- so this is called first
        thing, before any of the board work a declined pass shouldn't do.

        Concurrency is allowed (the passes don't collide on disk or on the
        board); what it costs is CPU, memory and the shared viewer windows,
        which is what the warning is about."""
        others = [s.busy_label for s in SolverSection._live if s is not self]
        return not others or self._confirm_concurrent(others)

    def _confirm_concurrent(self, others):
        """The warning itself, split out so a headless test can answer it."""
        already = _and_list(others)
        verb = "is" if len(others) == 1 else "are"
        dlg = wx.MessageDialog(
            self.page,
            f"{already[0].upper()}{already[1:]} {verb} already running.\n\n"
            "Running another simulation at the same time splits this "
            "machine's CPU and memory between them: both will be slower, and "
            "a large mesh may run the machine out of memory. The results "
            "windows are shared, so the newest report replaces whichever one "
            "is on screen.\n\n"
            "Start this one as well?",
            "Antenna Designer",
            wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT | wx.ICON_WARNING,
        )
        dlg.SetOKCancelLabels("Start anyway", "Cancel")
        ok = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        return ok

    def _claim(self):
        """This section's pass is starting: flag it running and add it to the
        shell's live list, which is what another section's warning reads."""
        self._running = True
        if self not in SolverSection._live:
            SolverSection._live.append(self)

    def _release(self):
        """The pass is over, however it ended: clear the flag and leave the
        live list. Called from every finish path -- and from ``shutdown``, so a
        window closed mid-run doesn't leave a pass behind that nothing will
        ever end."""
        self._running = False
        if self in SolverSection._live:
            SolverSection._live.remove(self)

    def _begin_session(self, on_outputs=None):
        """Open the session the coming run drives; its lines go to this page's
        log, and ``on_outputs(sample)`` fires (on the worker thread) whenever
        the solver has written a set of outputs."""
        self._session = RunSession(on_line=self.log, on_outputs=on_outputs)
        return self._session

    def _end_session(self):
        """The run is over: drop the session handle."""
        self._session = None

    def _start_worker(self, *args):
        """Run ``self._worker(*args)`` on a daemon thread (the board-touching
        setup has already run on the main thread)."""
        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _request_cancel(self):
        """Hard cancel: flag the run/scan and take the solver down at once,
        writing nothing. The worker then reports back through its own finish
        path (a killed solver exits non-zero, which the worker maps to a
        cancel)."""
        self._cancelled = True
        if self._session is not None:
            self._session.kill()

    def shutdown(self):
        """The window is closing: never leave the solver running detached.
        The pass is released here rather than waiting for the worker's finish
        path, which bails out on a page that is going away. Subclasses that own
        viewers extend this to tear them down too."""
        self._request_cancel()
        self._release()

    # --- shared button wording -------------------------------------------------
    def _start_tip(self, ready):
        """Tooltip for a button that can only start something: why it is
        unavailable right now, or ``ready`` when it is. Subclasses with further
        gates (the simulate view's pre-flight blockers) extend this."""
        return self._BUSY_TIP if self._running else ready

    # --- the board a run reads -------------------------------------------------
    def _ensure_board_saved(self, board, dirty=None):
        """The simulation reads the stackup from the saved ``.kicad_pcb``, so
        the board must be on disk and current before anything is launched: an
        unsaved board raises, and a stale one is saved after asking. ``dirty``
        (the caller's own answer to "does the file differ from the editor?",
        e.g. the pre-flight banner's) skips re-deriving it. Returns True when
        the board was saved here; raises when it can't be."""
        from ...sim import simulate

        if not board.GetFileName():
            raise RuntimeError(
                "save the board first -- the stackup is read from the .kicad_pcb file"
            )
        if dirty is None:
            dirty = simulate.board_needs_save(board)
        if not dirty:
            return False
        if not self._confirm_save():
            raise RuntimeError("cancelled -- the board was not saved")
        self._step("Saving the board…")
        simulate.save_board(board)
        return True

    def _report_failure(self, message):
        """Modal, must-be-dismissed notice that a pass failed or never
        started. The status line and log already carry the same word of it,
        but both are easy to miss: the button that started the pass simply
        becomes available again a moment later, with nothing else to draw
        the eye. A dialog the user has to click through is not -- but the
        pass stopping is routine (the user can just try again), not the
        alarming, something-is-broken event ``ICON_ERROR`` implies."""
        dlg = wx.MessageDialog(
            self.page, message, "Antenna Designer", wx.OK | wx.ICON_WARNING
        )
        dlg.ShowModal()
        dlg.Destroy()

    def _confirm_save(self):
        """Ask before saving the board on the user's behalf. Shown only when
        the Physical Stackup in the editor differs from the saved .kicad_pcb
        (which is where the simulation reads it from)."""
        dlg = wx.MessageDialog(
            self.page,
            "The board's Physical Stackup has unsaved changes, and the "
            "simulation reads it from the saved .kicad_pcb file.\n\n"
            "Save the board and continue?",
            "Antenna Designer",
            wx.OK | wx.CANCEL | wx.ICON_WARNING,
        )
        dlg.SetOKCancelLabels("Save && Continue", "Cancel")
        ok = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        return ok
