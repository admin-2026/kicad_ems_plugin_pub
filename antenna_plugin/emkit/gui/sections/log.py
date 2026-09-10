"""The terminal log section: a thread-safe, batched run log.

LogSection is a form section like the others (base.Section): each book page
(pages.simulate.SimulatePage, pages.wizard.DesignWizardPage) composes its own into
the bottom of its scrolled body. It wraps LogCtrl, the actual widget -- a
read-only monospace wx.TextCtrl whose ``log()`` may be called from any thread,
batching lines so a fast-printing solver can't flood the wx event queue, and
holding only the newest ``MAX_LINES`` of them so a long session can't grow a
text control big enough to be slow to append to.

**A warning is not news, it is a state.** The solver says what it made of the
board once, at meshing time, framed with a stable id -- ``WARNING [GND-004]:
...`` -- and then prints thousands of step lines over it (sim.diagnostics).
Pre-flight cannot cover that ground: it reads the board and answers before a
solver has been launched, so its banner is empty and honest while the run below
it warns about the ground plane. So this section does two things with those
lines: it writes them in **bold**, and it keeps a standing line under the log
naming every one the run has printed, which stays put however far the log has
scrolled past them. The same pair the command line answers with
(``run log --severity warning``).

Weight and not colour, deliberately: the window sits inside whatever theme
KiCad is wearing, dark ones included, and nothing here invents a colour of its
own (gui.theme).
"""

import threading
from itertools import groupby

import wx

from ...sim import diagnostics, runcontrol
from ..theme import HAIR
from ..widgets import emphasize, native_scroll
from .base import Section

# How much log to keep. A text control this size is still cheap to append to,
# and the interesting part of a run log is always its tail -- a long scan
# prints per-candidate solver output for as long as the sweep lasts, and a
# control grown to hold all of it is slow to append the next line to. The trim
# has to be worth doing, so it drops to KEEP_LINES rather than shaving one line
# off per flush (that would rebuild the control on every single line once full).
MAX_LINES = 5000
KEEP_LINES = 4000

# How many ids the standing line names before it says how many more there are.
# It is one line under a log, not a report: the log above it has the messages.
NAMED = 6


def _weights(font):
    """The two weights a log line is written in: the log's own monospace face,
    and the same face bold for a line the solver framed as a warning or an
    error. A control whose font this cannot read (the test harness answers
    nothing) gets one weight for both -- the standing line under the log is
    the half that must be right on every platform."""
    plain, loud = wx.TextAttr(), wx.TextAttr()
    bold = font.Bold() if isinstance(font, wx.Font) else None
    if bold is not None:
        plain.SetFont(font)
        loud.SetFont(bold)
    return plain, loud


class LogCtrl(wx.TextCtrl):
    """Read-only monospace log whose ``log()`` may be called from any thread.

    Lines are buffered and drained by a single pending wx.CallAfter, so a
    fast-printing solver can't flood the wx event queue and freeze the UI.

    Long lines wrap to the control's width (wx.TE_BESTWRAP): the page only
    scrolls vertically, so a no-wrap log would force the form wider than the
    window. The wheel scrolls the log itself, not the page (native_scroll).
    ``wx.TE_RICH2`` is what makes a line's weight stick on MSW; GTK and macOS
    style a plain multiline control anyway.

    Only the newest MAX_LINES are kept (see the module docstring); the shown
    text is rebuilt from that history when a trim drops the older ones, and
    simply appended to the rest of the time.

    Every line is read for a diagnostic on its way in (sim.diagnostics). Those
    are written bold, and ``on_diagnostics`` -- if the section gave one -- is
    handed the run's whole list each time it grows, and an empty one when the
    log is cleared for a new run.
    """

    def __init__(self, parent, on_diagnostics=None):
        super().__init__(
            parent,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP | wx.TE_RICH2,
        )
        native_scroll(self)
        font = wx.Font(wx.FontInfo(9).Family(wx.FONTFAMILY_TELETYPE))
        self.SetFont(font)
        self._plain, self._loud = _weights(font)
        self.SetMinSize((-1, 160))
        self.on_diagnostics = on_diagnostics
        self._lines = []
        self._lock = threading.Lock()
        self._pending = False
        self._shown = []  # (text, loud) for every line the control is showing
        self._found = []  # every diagnostic this run has printed, in order

    def log(self, text):
        """Append a line to the log from any thread.

        Restated on the way in, not on the way out, so the trim, the
        diagnostic scan and the standing line all see the one text the reader
        sees: the solver's signal advice names a console this window does not
        have (sim.runcontrol.restate_signal_hint).
        """
        text = runcontrol.restate_signal_hint(text)
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
        trim. The diagnostics go with it: the standing line is about the run
        that is starting, not the one before it."""
        self._shown = []
        self._found = []
        super().Clear()
        self._announce()

    def _flush(self):
        with self._lock:
            lines, self._lines = self._lines, []
            self._pending = False
        if not self or not lines:  # control may be destroyed mid-run
            return
        read = [(text, diagnostics.parse(text)) for text in lines]
        fresh = [one for _text, one in read if diagnostics.loud_enough(one)]
        rows = [(text, diagnostics.loud_enough(one)) for text, one in read]
        self._shown.extend(rows)
        if len(self._shown) <= MAX_LINES:
            self._write(rows)
        else:
            # Over the cap: drop the oldest and rewrite the control from what's
            # left, which also puts the view back at the tail where a log is
            # read. Written again rather than assigned (ChangeValue), because
            # the weight goes with the text -- assigning it back would leave
            # every warning still on screen in the plain face.
            del self._shown[: len(self._shown) - KEEP_LINES]
            super().Clear()
            self._write(self._shown)
            self.SetInsertionPointEnd()
            self.ShowPosition(self.GetLastPosition())
        if fresh:
            self._found.extend(fresh)
            self._announce()

    def _write(self, rows):
        """Append ``(text, loud)`` rows, one call per run of the same weight.

        The weight is set as the control's *default style* and the text
        appended under it, rather than restyled by position afterwards: a
        position in a multiline control is not a Python string offset on every
        platform, and a batch of a thousand step lines is still one
        ``AppendText``.
        """
        for loud, group in groupby(rows, key=lambda row: row[1]):
            self.SetDefaultStyle(self._loud if loud else self._plain)
            self.AppendText("".join(f"{text}\n" for text, _loud in group))

    def _announce(self):
        """Tell the section what this run has warned about (on the main
        thread: every caller is a flush, and a flush is a CallAfter)."""
        if self.on_diagnostics is not None:
            self.on_diagnostics(list(self._found))


class LogSection(Section):
    """The terminal run log at the bottom of a page's scrolled body.

    Headed like every other section (its own name over the rule, so the
    monospace box at the foot of the form is labelled), but holding a single
    widget rather than a group of them: the
    page reaches that through ``ctrl`` (to clear it at the start of a run) and
    logs to it through the section's thread-safe ``log``.

    Under the box is the standing warning line -- what the solver has said
    about this board *anywhere* in the run, kept in front of the reader after
    the log itself has scrolled past it. Hidden while there is nothing to say,
    so a clean run's form has no empty strip under its log.

    It is the section that takes the page's spare height (``last=True``), so the
    control is added stretching -- the log grows with the window, the heading
    stays put.

    ``title`` names the box for a page whose log is not a run's: the About
    page's is where the container image's build is printed, and calling that a
    run log would be the one word on that page that is not true.
    """

    _TITLE = "Run log"

    def __init__(self, page, body, step=None, title=None):
        super().__init__(page, step)
        box = self.box(title or self._TITLE)
        self.ctrl = LogCtrl(self.scroll, on_diagnostics=self.on_diagnostics)
        box.Add(self.ctrl, 1, wx.EXPAND)
        # Full contrast, not the muted grey the rest of the form's prose is
        # in: this is the line a reader must not skip past (widgets.emphasize).
        self.warnings = emphasize(self.wrap_label(self.scroll))
        self.warnings.Hide()
        self.standing = ""  # what that line currently says
        box.Add(self.warnings, 0, wx.EXPAND | wx.TOP, HAIR)
        self.add_to_body(body, box, last=True)

    def log(self, text):
        """Append a line to this page's run log (safe from any thread)."""
        self.ctrl.log(text)

    def on_diagnostics(self, found):
        """The log's diagnostics changed (one more printed, or the log cleared
        for a new run): restate the standing line, or take it away.

        The ids and not the messages: a message is a sentence and this is one
        line under a box that already holds every one of them in full. The
        whole text is on the tooltip, for a reader who has scrolled away.

        Nothing happens when the line would say what it already says: it is
        rebuilt from the whole list each time, a wrapping label changes the
        section's height, and this is the section that takes the page's spare
        height -- so an unchanged line must not relayout the form under a
        reader's pointer once per flush."""
        text = _standing(found)
        if text == self.standing:
            return
        self.standing = text
        self.warnings.SetLabel(text)
        self.warnings.SetToolTip("\n".join(one.text for one in found))
        self.warnings.Show(bool(text))
        self._relayout()


def _standing(found):
    """The one line under the log: how many the run has printed and which,
    or "" for a run that has printed none.

    "In this run", not "from the solver": a failure on this side of the binary
    is written into the same log and counted here too, and it carries no
    catalogue id -- so the ids are named where there are ids and the line is
    the tally alone where there are none.
    """
    if not found:
        return ""
    tally = f"⚠ {diagnostics.summary(diagnostics.counts(found))} in this run"
    ids = [one.id for one in found if one.id]
    if not ids:
        return tally
    named = ids[:NAMED]
    rest = ids[NAMED:]
    if rest:
        named.append(f"and {len(rest)} more")
    return f"{tally} — " + ", ".join(named)
