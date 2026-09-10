"""CliSection: the About page's command line — the guide, and the shortcut.

Everything about the other frontend in one box: the button that opens its
guide (moved here from the Documentation box, because a reader wanting the
command line looks where the command line is), and one tick that makes it
short to type.

Ticking does two things, and both come back off untick:

  1. writes the shortcut (agent/shim.py) — KiCad's Python and this install
     baked into a small script;
  2. puts the folder it is in on the user's PATH (agent/userpath.py) — a
     fenced block in a shell startup file, or the ``HKCU\\Environment`` value
     on Windows. Never the machine's PATH; nothing that needs a password.

The file's existence is the tick's whole state: nothing else records it, so
there is no setting to fall out of step with the disk, and a user who deletes
the shortcut by hand finds the box unticked next time. The PATH entry is
reported separately for the same reason — it is somebody else's file, it can
be edited behind this window's back, and a box that assumed otherwise would be
lying on the line below itself.

**A shell that is already open keeps its own PATH**, because an environment is
inherited. The line under the box says so, and gives the command to try in a
new one — the point of the whole box being that it is one word long.

**Neither half is instant**, which is why the tick is not applied on the wx
thread. Windows writes the registry and then broadcasts the change to every
top-level window, and a broadcast waits on whatever is slow to answer it; a
POSIX write is a startup file read, edited and written back. So the checkbox
gives way to a spinner while the work happens on a worker thread, and comes
back — set from the disk, not from what was clicked — when it is done. Both
ends of that dance are on the wx thread (``wx.CallAfter``); nothing else here
touches a widget.

What it still does not do: enable or disable the command line. ``run_agent.py``
is a file inside the install and runs tick or no tick. The tick installs a
name.

**Every ``agent`` import here is inside the method that uses it**, which is why
they repeat. This is the one module of the window that reaches across to the
other frontend, and the seam is worth more than the six lines: nothing under
``agent/`` is loaded because a toolbar button was pressed, only because this
box was drawn or ticked (dev_docs/frontend-lazy-loading.md).
"""

import os
import threading

import wx

from ..theme import PAD
from ..widgets import set_tip
from .base import Section
from .guides import open_guide

# The guide this box opens: (button label, help/ file, help-window title,
# button tooltip) -- the same shape as the Documentation box's list, which is
# where this entry used to live.
GUIDE = (
    "Command line guide",
    "cli.html",
    "Driving this plugin from a command line",
    "Run this plugin's work from a shell, a script or an agent",
)


def run_async(work):
    """Do ``work`` off the wx thread. The one seam this section has: a test
    replaces it with something that just calls ``work``, so what is checked is
    the sequence and not a race."""
    threading.Thread(target=work, daemon=True).start()


class CliSection(Section):
    _TITLE = "Command line"
    _LABEL = "Install the {command} shortcut"
    _TIP = (
        "Write a small script that runs this plugin's command line with "
        "KiCad's own Python and this install already filled in, and put its "
        "folder on your PATH. One shortcut for this machine, not for this "
        "board"
    )

    # The line under the box, in the four states it can be in.
    #
    # Unticked it is an invitation, not an inventory: what gets written and
    # which file gets a PATH line are answers to "what did that just do",
    # which is a question nobody has yet. They are on the tick's tooltip, and
    # on this line the moment there is something to point at.
    _OFF = (
        "Tick to set up this plugin's command line for a script, a CI job or "
        "an AI agent."
    )
    # Ticked, the line leads with what the user can now *do* and leaves the
    # paths to the last line, because the command is the answer and the
    # bookkeeping is only ever the follow-up question. It says what the
    # command is *for* -- a line of terminal with no reason given is a line
    # nobody types. One sentence for every state, because the command below it
    # is already spelled the way that works in that state.
    _READY = "✓ Ready. Open a new terminal and run this to check it works:"
    # The one command worth showing, once there is something to type it into:
    # the verb that needs no board and no solver, so it answers on any machine
    # the moment the shortcut is written -- which makes it the check for the
    # whole chain (shell, PATH, interpreter, package) rather than an example of
    # anything. Filled in with whatever actually works right now -- the bare
    # name once a shell can find it, the whole path until then -- so the line is
    # never a command that would fail if it were copied.
    _EXAMPLE = "    {command} versions"
    # The last line: where it went, and who put it on PATH. It follows a line
    # that *is* a command, so it says up front that it is not one -- two
    # monospaced-looking paths under something you were just told to type read
    # as more of it otherwise.
    _DETAIL_PREFIX = "For reference: "
    _DETAIL = "the shortcut is at {path}, and your PATH was set in {where}."
    _DETAIL_ALREADY = "the shortcut is at {path}; its folder was already on your PATH."
    _DETAIL_NONE = "the shortcut is at {path}. Add {folder} to your PATH to shorten it."
    # The shell whose startup file this cannot know: it wrote ~/.profile, and
    # that shell will not read it. Better said than found out.
    _DETAIL_SHELL = (
        "the shortcut is at {path}, and your PATH was set in {where}, which "
        "your shell may not read — check it, or add {folder} yourself."
    )
    # What a write that failed says, on the line below whatever is true anyway.
    _FAILED = "✗ could not {verb}: {error}"
    # While it happens. Both halves touch the disk and one of them broadcasts
    # to every window on the desktop, so this is a wait worth showing.
    _WORKING = "Installing the shortcut…"
    _UNDOING = "Removing the shortcut…"

    def __init__(self, page, body):
        super().__init__(page)
        self._build(body)

    def _build(self, body):
        from ...agent import shim

        box = self.box(self._TITLE)
        row = wx.BoxSizer(wx.HORIZONTAL)
        label, filename, title, tip = GUIDE
        button = self.row_button(row, label, self._open_guide)
        set_tip(button, tip)
        box.Add(row, 0, wx.EXPAND)

        # The tick and the spinner take each other's place: one row, one of
        # them shown at a time, so nothing moves on the page when they swap.
        self.check = wx.CheckBox(
            self.scroll, label=self._LABEL.format(command=shim.STEM)
        )
        self.check.SetValue(shim.installed())
        self.check.Bind(wx.EVT_CHECKBOX, self._toggle)
        set_tip(self.check, self._TIP)
        box.Add(self.check, 0, wx.TOP, PAD)
        self.busy = self._spinner()
        self.busy.Hide()
        box.Add(self.busy, 0, wx.TOP, PAD)

        self._status_label = self.wrap_label(self.scroll, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self._say_where()
        self.add_to_body(body, box)

    def _spinner(self):
        """The in-progress indicator. ``wx.ActivityIndicator`` where the wx
        build has one -- an animation needs no timer of ours -- and a still
        label where it has not, which is a thing a KiCad build can be short of
        and not worth a second widget's worth of guessing about."""
        indicator = getattr(wx, "ActivityIndicator", None)
        if indicator is None:
            return self.wrap_label(self.scroll, self._WORKING, mute=True)
        return indicator(self.scroll)

    def refresh(self):
        """Re-read the disk: the shortcut and the PATH entry are both files
        somebody else can change -- another window, an uninstall, an editor.
        Called when the About page is shown."""
        from ...agent import shim

        self.check.SetValue(shim.installed())
        self._say_where()

    # --- the guide ------------------------------------------------------------
    def _open_guide(self, event=None):
        label, filename, title, _tip = GUIDE
        if open_guide(self, label, filename, title):
            self._say_where()

    # --- the shortcut ---------------------------------------------------------
    def _toggle(self, event=None):
        """The tick changed: show the spinner and do the work off the wx
        thread. Everything that decides anything happens in ``_apply``; this
        only reads what was clicked, because by the time the work ends the
        widget is not what the answer comes from."""
        wanted = self.check.GetValue()
        self._busy(True, self._WORKING if wanted else self._UNDOING)
        run_async(lambda: self._apply(wanted))

    def _busy(self, working, text=""):
        """Swap the tick for the spinner, or back. Called on the wx thread at
        both ends."""
        self.check.Show(not working)
        self.busy.Show(working)
        start = getattr(self.busy, "Start" if working else "Stop", None)
        if start is not None:
            start()
        if working:
            self._set_status(text)
        self._relayout()

    def _apply(self, wanted):
        """Write the shortcut and add its folder to PATH, or take both away.
        **Runs on a worker thread**: it touches the disk and no widget, and
        hands the outcome back through ``wx.CallAfter``.

        The two halves are reported apart because they can fail apart: a
        shortcut that was written is worth having even when the PATH entry
        could not be, and it still runs by its full path.
        """
        from ...agent import shim, userpath

        try:
            shim.write() if wanted else shim.remove()
        except OSError as exc:
            wx.CallAfter(
                self._done,
                self._FAILED.format(
                    verb=("write " if wanted else "remove ") + shim.path(), error=exc
                ),
            )
            return
        try:
            folder = os.path.dirname(shim.path())
            if wanted:
                userpath.add(folder, shim.STEM)
            else:
                userpath.remove(folder, shim.STEM)
        except OSError as exc:
            verb = "add it to" if wanted else "take it off"
            wx.CallAfter(
                self._done,
                self._FAILED.format(
                    verb=f"{verb} your PATH ({userpath.where()})", error=exc
                ),
            )
            return
        wx.CallAfter(self._done, None)

    def _done(self, problem):
        """Back on the wx thread: the tick returns, set from the disk rather
        than from what was clicked -- a half that failed leaves the box saying
        what is actually there, which is the only thing worth showing."""
        from ...agent import shim

        self.check.SetValue(shim.installed())
        self._busy(False)
        self._say_where(problem)

    # --- the line under it ----------------------------------------------------
    def _say_where(self, problem=None):
        """What is true right now: where the shortcut is (or would go), what
        its folder's PATH entry is doing, and the command to try. ``problem``
        is appended rather than substituted -- what succeeded is still worth
        saying."""
        from ...agent import shim

        if not shim.installed():
            lines = [self._OFF]
        else:
            lines = self._ready_lines()
        if problem:
            lines.append(problem)
        self._set_status("\n".join(lines))

    def _ready_lines(self):
        """The three lines of an installed shortcut: what can be done, the
        command that does it, and where the pieces went.

        Two questions decide them, and they are different questions: did *we*
        put the folder on PATH (a block in a file, which the user can undo
        behind this window's back), and is the folder on the PATH this process
        inherited (which is how a user who did it themselves shows up).
        """
        from ...agent import shim, userpath

        path = shim.path()
        folder = os.path.dirname(path)
        ours = userpath.installed(folder, shim.STEM)
        short = ours or userpath.on_path(folder)
        if ours and not userpath.known_shell():
            detail = self._DETAIL_SHELL.format(
                path=path, where=userpath.where(), folder=folder
            )
        elif ours:
            detail = self._DETAIL.format(path=path, where=userpath.where())
        elif short:
            detail = self._DETAIL_ALREADY.format(path=path)
        else:
            detail = self._DETAIL_NONE.format(path=path, folder=folder)
        return [
            self._READY,
            self._EXAMPLE.format(command=shim.STEM if short else path),
            self._DETAIL_PREFIX + detail,
        ]
