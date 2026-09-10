"""The Results box: what a run left behind, re-opened without redoing it.

One shape, and a view per producer. ``ResultsSection`` is the reusable base:
a titled box holding one button per view it can open, over a status line that
says why a view isn't there yet. A subclass declares its buttons (``_VIEWS``:
label, key, window title, viewer slot) and what a view of each key would draw
right now (``_locate``); everything else -- building the row, the missing-view
message, the after-a-run auto-open -- is shared.

The solver writes data, never pages: what a run leaves is a dump, and what
draws it is the viewer the core ships (sim.simulate.viewer_url, emkit/viewer/).
So ``_locate`` returns the *data* -- a dump, or a manifest naming several --
and ``present`` is where it becomes a page.

``RunResultsSection`` is the one box every flow has: the newest archived
grid/report dump of this board's runs (``results/<stamp>/``,
sim.simulate.latest_result). The run section hands its freshly archived dumps
to the same ``present``, so a result shown the moment the solver wrote it and
one re-opened days later take one path: same window, same title. A plugin with
another kind of result -- a whole sweep of runs, say -- subclasses the base
beside it.

A box never knows how the data was produced, and a producer never knows how it
is shown: a run or a scan only says "here is a result" or "there are new
ones", and the window it lands in belongs to the page's ViewerHub (gui.viewers),
whose slots decide which pages share a window.
"""

from pathlib import Path

import pcbnew
import wx

from .. import viewers
from ..theme import PAD
from .base import Section


def _kind_of(path, names):
    """The view kind a file belongs to, by its name -- ``names`` maps kind to
    filename (simulate.DUMPS for a dump, scan_views.MANIFEST_FILES for a
    manifest). The name is the one thing every path of a kind shares, whichever
    run folder it sits in."""
    name = Path(path).name
    return next(kind for kind, filename in names.items() if filename == name)


class ResultsSection(Section):
    """A box of result-page buttons; see the module docstring for the subclass
    contract. Buttons never gate: a page that isn't there yet is explained on
    the status line, not hidden behind a disabled button."""

    _TITLE = "Results"
    _NOTE = ""  # the status line at rest: what these buttons open
    _TIP = ""  # button tooltip, formatted with the view key
    _MISSING = ""  # status line for a page that doesn't exist, ditto

    # The buttons, in the order they read (and stack: show_all leaves the
    # first one on top): (label, view key, window title, viewer slot).
    _VIEWS = ()

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self._build(body)

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.buttons = {}
        for label, key, title, slot in self._VIEWS:
            button = self.row_button(
                row, label, lambda event, k=key, t=title, s=slot: self.show(k, t, s)
            )
            if self._TIP:
                button.SetToolTip(self._TIP.format(key=key))
            self.buttons[key] = button
        box.Add(row, 0, wx.EXPAND)

        self._status_label = self.wrap_label(p, self._NOTE, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)

    # --- opening a view -------------------------------------------------------
    def show(self, key, title, slot):
        """A button: open the current view for ``key``, or say on the status
        line why there is none."""
        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            return
        path = self._locate(board, key)
        if path is None:
            self._set_status(self._MISSING.format(key=key))
            return
        self.present(path, title, slot)

    def show_all(self):
        """Open every view that exists, last-listed first so the first-listed
        (primary) one ends on top of the overlap. A view the producer couldn't
        write is skipped silently -- this is the auto-open after a run, which
        must not overwrite the result the producer just put on the status
        line."""
        board = pcbnew.GetBoard()
        if board is None:
            return
        for _label, key, title, slot in reversed(self._VIEWS):
            path = self._locate(board, key)
            if path is not None:
                self.present(path, title, slot)

    def present(self, path, title, slot=viewers.RESULTS):
        """Show what ``_locate`` found, in ``slot``'s viewer window. Subclasses
        turn ``path`` into the URL of a viewer page pointed at it."""
        if not self.page:
            return
        self.page.viewers.present(slot, self._url(path), title)

    # --- subclass hooks -------------------------------------------------------
    def _locate(self, board, key):
        """What view ``key`` would draw on ``board`` right now (a path to a
        dump or a manifest), or None when nothing has produced one yet."""
        raise NotImplementedError

    def _url(self, path):
        """The URL of the viewer page that draws ``path``. The file's own name
        says which page that is, so a caller who has only the path -- the run
        section, handing over what the solver just wrote -- needs nothing
        else."""
        raise NotImplementedError

    # --- shared by both subclasses' _url --------------------------------------
    def _sim_dir(self):
        """The board's simulation folder: where the viewer is installed, and
        what every result of this board is a relative path away from."""
        from ...sim import simulate

        return simulate.output_dir(pcbnew.GetBoard())


class RunResultsSection(ResultsSection):
    """The simulate view's Results box: the newest archived grid / report of
    this board's runs. Unlike the Run section's buttons these stay live during a
    run, so the last run's pages remain readable while the next one works."""

    _NOTE = (
        "The newest report and grid this board's simulation folder holds "
        "— they stay available while the next run works."
    )
    _TIP = "Open this board's newest {key} without re-running the simulation"
    _MISSING = "No {key} yet — run a simulation first."

    # The keys are simulate kinds (its DUMPS names the archived file of each).
    _VIEWS = (
        ("Show report", "report", "Simulation report", viewers.RESULTS),
        ("Show grid", "grid", "Grid preview", viewers.RESULTS),
    )

    def _locate(self, board, key):
        from ...sim import simulate

        return simulate.latest_result(simulate.output_dir(board), key)

    def present(self, path, title, slot=viewers.RESULTS):
        """Show an archived dump, titled with what the run behind it was and
        covers. Also the run section's way in, once it has archived a dump the
        solver just wrote (main thread only -- it posts this with
        wx.CallAfter)."""
        if not self.page:
            return
        from ...sim import runinfo, simulate

        # Stamp the window title with the run's generation time (parsed from
        # the archived folder name) so the page says when it was made, plus
        # what its record covers -- a snapshot or an interrupted run is shorter
        # record than a finished one, and must never look like one.
        ts = simulate.result_timestamp(path)
        if ts:
            title = f"{title} · {ts}"
        info = runinfo.read(path)
        if info and info.label():
            title = f"{title} · {info.label()}"
        super().present(path, title, slot)

    def _url(self, path):
        """The viewer page for an archived dump, pointed at it in place: the
        archive stays a faithful copy of the run, and the page reaching it is a
        relative path away (sim.simulate.viewer_url)."""
        from ...sim import simulate

        return simulate.viewer_url(
            self._sim_dir(), _kind_of(path, simulate.DUMPS), path
        )
