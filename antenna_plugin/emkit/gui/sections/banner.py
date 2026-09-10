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

**What would stop a run is the base's, not a subclass's** (``starts_runs`` ->
``_run_blockers``): the board's pre-flight (``simulate.preflight``) and whether
this machine's container is ready. Neither is a question about what a given
page is *for*, and every page a simulation can be started from has to ask both
-- the simulate view, and each designer, whose scan starts one solve per
candidate of its sweep. They used to be the simulate view's alone, which is how
a designer came to offer a Start scan button on an unsaved board with Docker
not installed and say nothing about either until it was pressed. Asked here, a
page cannot be added that quietly leaves them out.

Two banners subclass it:

* ``PreflightBanner`` (here) -- the simulate view's. All its rows are the
  base's; what it adds is gating the Run button and a status line for the fix.
* ``AreaBanner`` (area_banner.py) -- the wizard's advisory area-marker warnings
  (``markers.area_checks``), under those same blockers.

A subclass adds its own rows with ``_collect``; it may also override
``_after_refresh`` (to gate a button on the result), ``_fix_action`` (a
per-problem remedy beyond the board-save one every page gets) and ``_say``
(where a fix reports what it did). Opening a row's guide is the same for both
and lives here (``_open_help``): every problem carries its bundled help page,
and both banners open it in the shared help viewer (``page.viewers``,
gui.viewers).

Warning rows carry a dismiss (✕) button. Dismissing hides that warning without
silencing it forever: the banner only remembers a dismissal while the warning
keeps being reported unchanged, and forgets it the moment the warning clears --
so once the condition is fixed and later recurs (or the warning's specifics
change), it shows again. Blockers are never dismissible; they gate the run.
"""

import time

import wx

from ..theme import ROW
from ..widgets import enable
from .base import Section
from .cli import run_async

# --------------------------------------------------------------------------- #
# is this machine's container ready? -- asked off the wx thread, once for the
# whole window
# --------------------------------------------------------------------------- #
# Two subprocesses (sim.container.probe: the engine's version, then the image's
# labels), which on Docker Desktop is comfortably half a second. A banner
# refreshes on things as small as a keystroke in a designer's sweep count, so
# neither doing that on the wx thread nor doing it per banner is available:
# there are four banners in an antenna window, and the machine has one answer.
#
# So the answer is remembered for a few seconds and fetched on a worker, the
# same seam the About page's box uses (sections.cli.run_async, which a test
# replaces). A refresh renders the answer it has -- nothing, the first time --
# and the probe's landing refreshes the banners that asked, which is a beat
# later and looks like the row arriving with the page.
#
# Nothing is asked at all on a machine that solves natively, which is Linux and
# Windows with the tick off: simulate.container_problems returns before it
# reaches the engine.
PROBE_TTL_S = 5.0

_probed = None  # (monotonic seconds, rows) or None
_probing = False  # a worker is out asking
_waiting = []  # what to call when it comes back


def container_rows(when_ready=None):
    """The rows saying this machine's container is not ready, or [].

    Answers immediately, from the last probe: this is called from a keystroke
    and must not be where a subprocess happens. When there is nothing recent
    enough, a probe goes out on a worker and *when_ready* is called once it
    lands -- pass the caller's own refresh, and the row appears a beat after
    the page does.
    """
    if _probed is not None and time.monotonic() - _probed[0] < PROBE_TTL_S:
        return list(_probed[1])
    _probe_soon(when_ready)
    return list(_probed[1]) if _probed is not None else []


def recheck_container():
    """Ask again at the next refresh: something the user just did changed the
    answer -- the About page's tick, either page's Build button.

    The last answer is *kept* rather than dropped, and only marked stale. A
    dropped one means every banner in the window has nothing to show for the
    half second the probe takes, so the row a user is looking at blinks out and
    returns -- which reads as the fix having worked when it has not.
    """
    global _probed

    if _probed is not None:
        _probed = (0.0, _probed[1])


def _probe_soon(when_ready):
    """Send one worker after the answer, however many banners are asking."""
    global _probing

    if when_ready is not None and when_ready not in _waiting:
        _waiting.append(when_ready)
    if _probing:
        return
    _probing = True
    run_async(_probe)


def _probe():
    """Worker: ask, remember, and tell whoever asked. No widget is touched."""
    global _probed, _probing

    try:
        from ...sim import simulate

        rows = tuple(simulate.container_problems())
    except Exception:
        # An engine that misbehaves is already a row of its own
        # (container_problems catches that itself), so what lands here is a
        # bug rather than a state -- and the banner's standing rule is that a
        # broken check costs a row and never the window.
        rows = ()
    _probed = (time.monotonic(), rows)
    _probing = False
    wx.CallAfter(_tell)


def _tell():
    """Back on the wx thread: refresh the banners that were waiting.

    Each is called once and dropped. A refresh finds the answer fresh, so this
    cannot start another probe; a page that has gone away since raises, and
    that is not the other pages' problem.
    """
    waiting, _waiting[:] = list(_waiting), []
    for refresh in waiting:
        try:
            refresh()
        except Exception:
            pass


class BannerSection(Section):
    """Base pinned banner; see the module docstring for the subclass contract."""

    # A short noun for the log line when the check itself raises.
    _check_name = "check"

    # What a build started from a row says, and where: through ``_say``, which
    # is the Run section's status line on the simulate view and the run log
    # elsewhere. Four short sentences for a thing that takes minutes -- the
    # engine's own output is printed by the box doing the work, into the About
    # page's terminal (sections.docker, pages.info).
    _BUILDING = (
        "Building the container image — this installs KiCad, so it takes "
        "minutes; the About page prints it as it goes."
    )
    _BUILDING_LABEL = "Building…"
    _BUILDING_ALREADY = "The image is already being built."
    _BUILT = "✓ Built the container image."
    _BUILD_FAILED = "✗ The build failed. The last line was: {line}"

    # Whether a solver run can be started from the page this banner is on.
    # It decides one thing, and it is the whole of _run_blockers: whether this
    # banner carries what would stop such a run -- the board's pre-flight and
    # this machine's container. A page that starts nothing has no use for
    # either; a page that does must say them before the button is pressed
    # rather than after.
    starts_runs = False

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
        # What would stop a run first, then this page's own check: a blocker is
        # not something to find underneath three advisory warnings.
        problems = self._run_blockers() + self._safe_collect()
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

    def _run_blockers(self):
        """Everything that would stop a run started from this page: the board's
        pre-flight (simulate.preflight) and this machine's container.

        Neither is about what the page is *for* -- a designer's banner is about
        its area marker -- but both stop the button on it, so they belong to
        the page rather than to the check. Empty for a banner whose page starts
        nothing (``starts_runs``).
        """
        if not self.starts_runs:
            return []
        rows = []
        for name, source in (
            ("pre-flight", self._board_problems),
            ("container", self._container_problems),
        ):
            try:
                rows += source()
            except Exception as exc:
                # Same rule as the subclass check below: a check that breaks
                # costs a row, and never stops the window drawing the rest.
                self.log(f"{name} check failed: {exc}")
        return rows

    def _board_problems(self):
        """The board's own blockers, for whichever board is open."""
        import pcbnew

        from ...sim import simulate

        board = pcbnew.GetBoard()
        if board is None:
            return []
        # Not every blocker is a fact about the board alone: whether the solder
        # mask has to state a material depends on whether this form asked for
        # it. The Advanced pane is where that pick lives, and it re-runs this
        # check whenever one of them moves (AdvancedSection._recheck) -- both
        # pages that start runs have one.
        advanced = getattr(self.page, "advanced", None)
        params = advanced.mask_params() if advanced is not None else {}
        return simulate.preflight(board, params)

    def _container_problems(self):
        """...and whether the container a solve would run in is ready. Refreshes
        again when the probe lands, since what comes back here is the answer
        from before it was sent."""
        return container_rows(when_ready=self.refresh)

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
        """This page's own check, as [Problem]; a live-board one reads pcbnew
        here. Default: none -- a banner whose page starts runs already has the
        rows that matter most (``_run_blockers``)."""
        return []

    def _after_refresh(self, problems):
        """React to a fresh problem list (e.g. gate a button). Default: none."""

    def _fix_action(self, problem):
        """(label, handler) for a problem with a one-click remedy, else None.

        Both fixes here are for run blockers, which is why they are here rather
        than in a subclass: a board that was never saved, or an image that was
        never built, stops a run from whichever page it was started on. The
        stackup problems have no such remedy -- their fix lives in KiCad's Board
        Setup, which no plugin API opens reliably, and the help page describes
        the path instead.
        """
        if problem.id in ("board-unsaved", "stackup-dirty"):
            import pcbnew

            board = pcbnew.GetBoard()
            # A board with no filename yet needs Save As, which a plugin
            # can't drive; only offer Save once there is a path to save to.
            if board is not None and board.GetFileName():
                return "Save board", self._on_fix_save
        if problem.id == "docker-not-ready":
            return self._container_fix(problem)
        return None

    def _container_fix(self, problem):
        """The button for a container that is not ready, or None.

        Offered for the states this window can do something about -- no image
        built, or one this release has outgrown -- and not for a Docker that is
        not installed or not running, which is fixed outside the window
        entirely. A button that could not do what it says is worse than the
        sentence the user already has.

        It is the same build the About page's box runs, started from the row
        that asked for it: the row is where the user is when they find out, and
        sending them somewhere else to press a second button is a step that
        exists only because of how this window is arranged.
        """
        from ...sim import container

        label = {
            container.NO_IMAGE: "Build image",
            container.STALE: "Rebuild image",
            container.KICAD_OLDER: "Rebuild image",
        }.get(problem.state)
        if label is None or self._docker_box() is None:
            return None
        return label, (
            lambda event, rebuild=problem.state != container.NO_IMAGE: self._on_build(
                event, rebuild
            )
        )

    def _on_build(self, event=None, rebuild=False):
        """Build the image from the row that asked for it.

        The work is the About page's Docker box's (``start_build``), and so is
        the output: it prints into that page's terminal, line by line, where a
        four-minute build can actually be watched. What happens *here* is what
        a row can hold -- the button gives way, and one sentence says it
        started and one says how it ended.
        """
        box = self._docker_box()
        if box is None:
            return  # a window with no such box never offered this button
        button = event.GetEventObject() if event is not None else None
        if not box.start_build(rebuild=rebuild, on_done=self._built):
            self._say(self._BUILDING_ALREADY)
            return
        if button is not None:
            button.SetLabel(self._BUILDING_LABEL)
            enable(button, False)
        self._say(self._BUILDING)

    def _built(self, ok, last_line):
        """The build ended (on the wx thread): say how, and ask again."""
        self._say(self._BUILT if ok else self._BUILD_FAILED.format(line=last_line))
        # The answer this row was drawn from is stale whichever way it went.
        # The rows are forced to rebuild as well, because a failed build leaves
        # the *same* row on screen -- and that row still has a disabled
        # "Building…" where its button was.
        recheck_container()
        self._state = None
        self.refresh()

    def _docker_box(self):
        """The window's Docker box, or None.

        Found by what a page *has* rather than by what it is: which view holds
        that box is the shell's arrangement, and a banner that imported the
        About page to ask would be one core page knowing another's job. None
        off a shell entirely, which is how a test builds one of these -- and
        then no button is offered at all.
        """
        shell = getattr(self.page, "shell", None)
        pages = shell.pages() if shell is not None else ()
        boxes = (getattr(page, "docker", None) for page in pages)
        return next((box for box in boxes if box is not None), None)

    def _on_fix_save(self, event=None):
        """The Save board button on such a row."""
        import pcbnew

        from ...sim import simulate

        try:
            simulate.save_board(pcbnew.GetBoard())
            self._say("Board saved.")
        except Exception as exc:
            self._say(f"✗ {exc}")
        self.refresh()

    def _say(self, text):
        """Where a fix reports what it did. The run log by default, since every
        page has one; a page with a status line of its own overrides this."""
        self.log(text)

    # --- guides ---------------------------------------------------------------
    def _open_help(self, problem):
        """A row's Help button: open ``problem``'s bundled guide in the page's
        help viewer (viewers.show_guide, the one path every guide takes). A
        missing page (partial install) leaves the row's own one-line message as
        the explanation, so nothing more is said here."""
        from ..viewers import show_guide

        show_guide(self.page, problem.help, problem.title)


class PreflightBanner(BannerSection):
    """The simulate view's pre-flight banner: what would stop a run, one row per
    problem, and nothing else -- the rows are all the base's (``_run_blockers``:
    the board's pre-flight and this machine's container), because on this page
    the run *is* the subject. What this class adds is what to do about them:
    it gates the Run button while any "block" problem exists, and reports a fix
    on the Run section's own status line. Refreshed at dialog open, on window
    focus (the user may fix the stackup in Board Setup and come back) and at
    the top of a run."""

    _check_name = "pre-flight"
    starts_runs = True

    def _after_refresh(self, problems):
        # The Run section owns the Run button; hand it the blocked state so it
        # can gate the button (it stays Cancel while a run is in flight).
        self.page.run.on_preflight(any(p.severity == "block" for p in problems))

    def _say(self, text):
        # This page has a line for exactly this, right under the button the
        # problem is about.
        self.page.run._set_status(text)
