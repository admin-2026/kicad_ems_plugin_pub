"""The terminal log section: a thread-safe, batched run log.

LogSection is a form section like the others (base.Section): each book page
(pages.simulate.SimulatePage, pages.wizard.DesignWizardPage) composes its own into
the bottom of its scrolled body. It wraps LogCtrl, the actual widget -- a
read-only monospace wx.TextCtrl whose ``log()`` may be called from any thread,
batching lines so a fast-printing solver can't flood the wx event queue, and
holding only the newest ``MAX_LINES`` of them so a long session can't grow a
text control big enough to be slow to append to.
"""

import threading

import wx

from ..widgets import native_scroll
from .base import Section

# How much log to keep. A text control this size is still cheap to append to,
# and the interesting part of a run log is always its tail -- a long scan
# prints per-candidate solver output for as long as the sweep lasts, and a
# control grown to hold all of it is slow to append the next line to. The trim
# has to be worth doing, so it drops to KEEP_LINES rather than shaving one line
# off per flush (that would rebuild the control on every single line once full).
MAX_LINES = 5000
KEEP_LINES = 4000


class LogCtrl(wx.TextCtrl):
    """Read-only monospace log whose ``log()`` may be called from any thread.

    Lines are buffered and drained by a single pending wx.CallAfter, so a
    fast-printing solver can't flood the wx event queue and freeze the UI.

    Long lines wrap to the control's width (wx.TE_BESTWRAP): the page only
    scrolls vertically, so a no-wrap log would force the form wider than the
    window. The wheel scrolls the log itself, not the page (native_scroll).

    Only the newest MAX_LINES are kept (see the module docstring); the shown
    text is rebuilt from that history when a trim drops the older ones, and
    simply appended to the rest of the time.
    """

    def __init__(self, parent):
        super().__init__(
            parent, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP
        )
        native_scroll(self)
        self.SetFont(wx.Font(wx.FontInfo(9).Family(wx.FONTFAMILY_TELETYPE)))
        self.SetMinSize((-1, 160))
        self._lines = []
        self._lock = threading.Lock()
        self._pending = False
        self._shown = []  # the lines the control is currently showing

    def log(self, text):
        """Append a line to the log from any thread."""
        with self._lock:
            self._lines.append(text)
            if self._pending:
                return
            self._pending = True
        wx.CallAfter(self._flush)

    def Clear(self):
        """Empty the log (a run or a scan starting over), kept history and all.
        Overrides wx.TextCtrl.Clear so there is one way to empty this control
        and it can't leave the history behind to be rewritten by the next
        trim."""
        self._shown = []
        super().Clear()

    def _flush(self):
        with self._lock:
            lines, self._lines = self._lines, []
            self._pending = False
        if not self or not lines:  # control may be destroyed mid-run
            return
        self._shown.extend(lines)
        if len(self._shown) <= MAX_LINES:
            self.AppendText("\n".join(lines) + "\n")
            return
        # Over the cap: drop the oldest and rewrite the control from what's
        # left, which also puts the view back at the tail where a log is read.
        del self._shown[: len(self._shown) - KEEP_LINES]
        self.ChangeValue("\n".join(self._shown) + "\n")
        self.SetInsertionPointEnd()
        self.ShowPosition(self.GetLastPosition())


class LogSection(Section):
    """The terminal run log at the bottom of a page's scrolled body.

    Headed like every other section (its own name over the rule, so the
    monospace box at the foot of the form is labelled), but holding a single
    widget rather than a group of them: the
    page reaches that through ``ctrl`` (to clear it at the start of a run) and
    logs to it through the section's thread-safe ``log``.

    It is the section that takes the page's spare height (``last=True``), so the
    control is added stretching -- the log grows with the window, the heading
    stays put.
    """

    _TITLE = "Run log"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        box = self.box(self._TITLE)
        self.ctrl = LogCtrl(self.scroll)
        box.Add(self.ctrl, 1, wx.EXPAND)
        self.add_to_body(body, box, last=True)

    def log(self, text):
        """Append a line to this page's run log (safe from any thread)."""
        self.ctrl.log(text)
