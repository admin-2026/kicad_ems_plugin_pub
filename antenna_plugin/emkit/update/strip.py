"""UpdateStrip: the one-line "there is a newer version" bar on the shell.

The only module in this folder that knows what a window is, and it holds the
whole of the feature's UI: an info-coloured strip across the top of the shell
(gui.shell builds it and calls ``start``; that is the shell's entire share of
the feature), hidden until a check comes back with something to say.

It says the two versions, links to the release page and carries a ✕. Hidden is
its normal state: it appears only for a genuinely newer release, and a check
that is switched off, unconfigured or simply couldn't be made leaves the window
exactly as it was, with one line in the run log for anyone wondering. Nothing
here gates anything -- no button is disabled, no dialog is raised, and the user
can dismiss the strip and never see it again this session.

Threading is the usual wx contract, and the reason ``checker.check_async``
hands its Outcome to a callback rather than picking a loop itself: the check
lands on a worker thread, ``_deliver`` bounces it to the wx thread with
CallAfter, and ``_landed`` -- which is the first line that touches a widget --
tolerates the window having been closed while the request was in flight.

Being the folder's one wx module, it is also the only one that borrows from the
GUI package: the Download link is the shared one (gui.widgets.hyperlink), the
same control the About page's project links are built from, so the wx.adv
fallback is written once.

Top of the window, not a page footer (where the pre-flight and area banners
live, gui.sections.banner): those belong to one page's form and come and go as
the board is edited, while this belongs to the install, arrives once and is
true on every page.
"""

import wx

from ... import product
from .. import versions
from ..gui.widgets import hyperlink
from . import checker

# The strip's own spacing. gui.theme owns the form's scale, but this is not a
# form section -- it is a bar on the frame, and it only needs one gap.
_PAD = 8


class UpdateStrip(wx.Panel):
    """The launch-time update notice. Build it on the frame, add it to the
    frame's sizer (it takes no room while hidden) and call ``start`` once."""

    def __init__(self, parent, log=None):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_INFOBK))
        # Where a failed or skipped check says so. The window shows nothing for
        # either, so this is the only trace: the shell passes its run log.
        self._log = log if callable(log) else (lambda text: None)
        self._outcome = None  # the answer, once one has landed
        self._started = False  # the check runs once per window
        self._current = ""  # the running version, as ``start`` was told it
        self._sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self._sizer)
        self.Hide()

    # --- the check ------------------------------------------------------------
    @property
    def outcome(self):
        """The Outcome of this window's check, or None while it is in flight
        (the About page's version table reads it -- gui.sections.versions)."""
        return self._outcome

    def start(self, current_version=None, source=None):
        """Kick the check off, once per window. Returns immediately -- the
        request runs on a daemon thread and lands through ``_deliver`` -- with
        the started thread, or None if this strip has already been started.

        ``current_version`` defaults to what this install says it is
        (emkit.versions); ``source`` to the GitHub releases API
        (update.github), and is here so a caller -- a test, or a build pointed
        at another release source -- can hand in its own."""
        if self._started:
            return None
        self._started = True
        if current_version is None:
            current_version = versions.plugin_version()
        self._current = current_version
        return checker.check_async(current_version, self._deliver, source)

    def _deliver(self, outcome):
        """Called on the worker thread: hand the Outcome to the wx thread."""
        wx.CallAfter(self._landed, outcome)

    def _landed(self, outcome):
        """Back on the wx thread with the answer. Everything below touches
        widgets, so a window closed mid-check (its children destroyed under the
        pending CallAfter) is caught here and forgotten."""
        try:
            self._outcome = outcome
            if outcome.status == checker.UPDATE:
                self._show_update(outcome.release)
            elif outcome.detail:
                self._log(f"update check: {outcome.detail}")
        except RuntimeError:
            pass  # the shell went away while the check was in flight

    # --- the strip ------------------------------------------------------------
    def _show_update(self, release):
        """Build the row for ``release`` and show the strip."""
        self._sizer.Clear(True)
        text = wx.StaticText(
            self,
            label=(
                f"⚠  {product.NAME} {release.version} is available — "
                f"this install is {self._current}."
            ),
            style=wx.ST_ELLIPSIZE_END,
        )
        text.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_INFOTEXT))
        text.SetToolTip(release.name or release.url)
        self._sizer.Add(text, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, _PAD)
        self._sizer.Add(
            self._link(release), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, _PAD
        )
        close = wx.Button(self, label="✕", style=wx.BU_EXACTFIT)
        close.SetToolTip("Dismiss (the check runs again next launch)")
        close.Bind(wx.EVT_BUTTON, self._on_dismiss)
        self._sizer.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, _PAD)
        self.Show()
        self._relayout()
        self._log(f"update available: {release.version} — {release.url}")

    def _link(self, release):
        """The download link (widgets.hyperlink: a real hyperlink where the
        host's wx has one, else a button that opens the browser through wx --
        the same link the About page's rows are built from)."""
        return hyperlink(self, "Download", release.url)

    def _on_dismiss(self, event=None):
        """The ✕: hide the strip for the rest of this session. Not persisted --
        the check is cheap, the next launch asks again, and a version the user
        keeps declining costs them one click a launch."""
        self.Hide()
        self._relayout()

    def _relayout(self):
        """The strip just appeared or went away: re-lay the frame around it (a
        hidden panel takes no height, so the pages get it all back)."""
        parent = self.GetParent()
        if parent is not None:
            parent.Layout()
