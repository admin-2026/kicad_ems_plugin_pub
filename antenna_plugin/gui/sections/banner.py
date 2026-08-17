"""Footer-banner sections: a strip under the form that lists checks.

``BannerSection`` is the reusable base -- a hidden ``INFOBK`` panel that renders
a list of ``sim.simulate.Problem`` as rows (severity icon + message + an
optional one-click Fix + a Help button), rebuilt only when the set changes.
Unlike an ordinary section its widget is *not* built into the scrolled body: the
banner must stay visible however far the form is scrolled, so its panel parents
on the *page*, which docks it below the scroll (``BookPage.mount footer=``).
Below the form and not above it because these rows come and go on their own -- a
focus switch back from Board Setup, a marker moved, a fix applied -- and above
the scroll each of those shoved the whole form up and down under the pointer.
Under it the form doesn't move at all; only the viewport shrinks.

Two banners subclass it:

* ``PreflightBanner`` (here) -- the simulate view's board/stackup blockers
  (``simulate.preflight``); it gates the Run button and offers a Save fix.
* ``AreaBanner`` (area_banner.py) -- the wizard's advisory area-marker warnings
  (``markers.area_checks``); non-gating, no fixes.

A subclass supplies the problem source (``_collect``); it may also override
``_after_refresh`` (to gate a button on the result) and ``_fix_action`` (a
per-problem remedy). Opening a row's guide is the same for both and lives here
(``_open_help``): every problem carries its bundled help page, and both banners
open it in the shared help viewer (``page.viewers``, gui.viewers).

Warning rows carry a dismiss (✕) button. Dismissing hides that warning without
silencing it forever: the banner only remembers a dismissal while the warning
keeps being reported unchanged, and forgets it the moment the warning clears --
so once the condition is fixed and later recurs (or the warning's specifics
change), it shows again. Blockers are never dismissible; they gate the run.
"""

import wx

from ..theme import ROW
from .base import Section


class BannerSection(Section):
    """Base pinned banner; see the module docstring for the subclass contract."""

    # A short noun for the log line when the check itself raises.
    _check_name = "check"

    def __init__(self, page):
        super().__init__(page)
        self._state = None  # last-rendered rows (skip rebuilds)
        self._dismissed = set()  # dismissed-warning keys, re-armed on clear
        self._build_panel()

    # --- construction ---------------------------------------------------------
    def _build_panel(self):
        """The banner panel (docked below the scroll by the page, so it parents
        on the page, not the scroll). The top border is what separates the strip
        from the form above it. Rows are (re)built by ``refresh``."""
        self.panel = wx.Panel(self.page, style=wx.BORDER_SIMPLE)
        self.panel.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_INFOBK)
        )
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel.SetSizer(self._sizer)
        self.panel.Hide()

    # --- refresh --------------------------------------------------------------
    def refresh(self):
        """Re-run the check, rebuild the banner rows and let the subclass react
        to the result. Never lets the check itself break the dialog. Returns the
        full problem list (the caller sees every problem, dismissed or not)."""
        problems = self._safe_collect()
        # Forget any dismissal whose warning is no longer reported: dismissing
        # hides a warning only while it keeps recurring unchanged, so a warning
        # that clears and later comes back (or whose message changes) shows
        # again rather than staying hidden forever.
        self._dismissed &= {self._key(p) for p in problems}
        visible = [p for p in problems if self._key(p) not in self._dismissed]
        self._rows(visible)
        # Gate on the real problem set, never the dismissed-filtered one: a
        # blocker isn't dismissible, and a dismissed warning must not change
        # what a run is allowed to do.
        self._after_refresh(problems)
        return problems

    @staticmethod
    def _key(problem):
        """A warning's dismissal identity: its id plus its exact message, so a
        warning whose specifics change (e.g. copper now on more layers) counts
        as a new one and reappears after an earlier dismissal."""
        return (problem.id, problem.message)

    def _dismiss(self, problem):
        """A warning's ✕ button: hide it until it clears and recurs (see
        refresh); re-run so the row disappears now."""
        self._dismissed.add(self._key(problem))
        self.refresh()

    def _safe_collect(self):
        try:
            return self._collect()
        except Exception as exc:
            # The run/scan flow's own raises still catch whatever the banner
            # missed, so a broken check just hides the banner, never blocks.
            self.log(f"{self._check_name} check failed: {exc}")
            return []

    def _rows(self, problems):
        """Rebuild the banner rows to match ``problems`` (already
        dismissed-filtered); skipped when they haven't changed (a focus switch
        fires refresh, and a rebuild would flicker)."""
        state = [(p.id, p.severity, p.message) for p in problems]
        if state == self._state:
            return
        self._state = state
        self._sizer.Clear(True)  # destroys the previous rows' widgets
        text_fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_INFOTEXT)
        for p in problems:
            self._add_row(p, text_fg)
        if problems:
            self._sizer.AddSpacer(ROW)
        self.panel.Show(bool(problems))
        # The strip just changed height (or went away): let the page re-fit the
        # scroll around it. A hidden panel takes no room in the page sizer, so
        # a cleared banner gives all the height back.
        self.page.relayout_footer()

    def _add_row(self, problem, text_fg):
        row = wx.BoxSizer(wx.HORIZONTAL)
        icon = "⛔" if problem.severity == "block" else "⚠"
        txt = wx.StaticText(
            self.panel, label=f"{icon}  {problem.message}", style=wx.ST_ELLIPSIZE_END
        )
        txt.SetToolTip(problem.message)  # the row may be ellipsized
        txt.SetForegroundColour(text_fg)
        row.Add(txt, 1, wx.ALIGN_CENTER_VERTICAL)
        fix = self._fix_action(problem)
        if fix is not None:
            label, handler = fix
            btn = wx.Button(self.panel, label=label, style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, handler)
            row.Add(btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, ROW)
        help_btn = wx.Button(self.panel, label="? Help", style=wx.BU_EXACTFIT)
        help_btn.SetToolTip("Open the guide for this issue")
        help_btn.Bind(wx.EVT_BUTTON, lambda event, prob=problem: self._open_help(prob))
        row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, ROW)
        # Warnings are dismissible; blockers stay put (they gate the run). The
        # dismissal is remembered only while the warning keeps recurring
        # unchanged -- see the module docstring / refresh.
        if problem.severity == "warn":
            close = wx.Button(self.panel, label="✕", style=wx.BU_EXACTFIT)
            close.SetToolTip("Dismiss this warning (it returns if it recurs)")
            close.Bind(wx.EVT_BUTTON, lambda event, prob=problem: self._dismiss(prob))
            row.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, ROW)
        self._sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, ROW)

    # --- subclass hooks -------------------------------------------------------
    def _collect(self):
        """Return the current [Problem]; a live-board check reads pcbnew here."""
        raise NotImplementedError

    def _after_refresh(self, problems):
        """React to a fresh problem list (e.g. gate a button). Default: none."""

    def _fix_action(self, problem):
        """(label, handler) for a one-click remedy, or None (the default)."""
        return None

    # --- guides ---------------------------------------------------------------
    def _open_help(self, problem):
        """A row's Help button: open ``problem``'s bundled guide in the page's
        help viewer (viewers.show_guide, the one path every guide takes). A
        missing page (partial install) leaves the row's own one-line message as
        the explanation, so nothing more is said here."""
        from ..viewers import show_guide

        show_guide(self.page, problem.help, problem.title)


class PreflightBanner(BannerSection):
    """The simulate view's pre-flight banner: everything that would stop a run
    (simulate.preflight), one row per problem. It gates the Run button while any
    "block" problem exists and offers a Save fix for the board/stackup ones;
    hidden while the board is runnable. Refreshed at dialog open, on window
    focus (the user may fix the stackup in Board Setup and come back) and at the
    top of a run."""

    _check_name = "pre-flight"

    def _collect(self):
        import pcbnew

        from ...sim import simulate

        board = pcbnew.GetBoard()
        return simulate.preflight(board) if board is not None else []

    def _after_refresh(self, problems):
        # The Run section owns the Run button; hand it the blocked state so it
        # can gate the button (it stays Cancel while a run is in flight).
        self.page.run.on_preflight(any(p.severity == "block" for p in problems))

    def _fix_action(self, problem):
        """(label, handler) for a problem with a one-click remedy, else None.
        The stackup problems have none: their fix lives in KiCad's Board
        Setup, which no plugin API opens reliably -- the help page describes
        the path instead."""
        if problem.id in ("board-unsaved", "stackup-dirty"):
            import pcbnew

            board = pcbnew.GetBoard()
            # A board with no filename yet needs Save As, which a plugin
            # can't drive; only offer Save once there is a path to save to.
            if board is not None and board.GetFileName():
                return "Save board", self._on_fix_save
        return None

    def _on_fix_save(self, event=None):
        import pcbnew

        from ...sim import simulate

        try:
            simulate.save_board(pcbnew.GetBoard())
            self.page.run._set_status("Board saved.")
        except Exception as exc:
            self.page.run._set_status(f"✗ {exc}")
        self.refresh()
