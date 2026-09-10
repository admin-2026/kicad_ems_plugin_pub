"""The PCB editor frame: finding it, and going away with it.

Two things every plugin window needs to know about the editor it was opened
from, and neither of them is something ``pcbnew`` will answer -- the scripting
helpers hand out the board and stop there (pcbnew_scripting_helpers.h), so the
frame itself is found from wx.

**Which window it is.** ``editor_frame`` asks three questions, cheapest and
surest first: the window's own root ancestor (gui.show parents the shell on the
editor, and every dialog and viewer hangs off that, so a plugin window
generally knows already); else the frame KiCad *named* ``PcbFrame`` -- the name
a wxWindow is constructed with, which for the PCB editor is
``PCB_EDIT_FRAME_NAME`` and is neither translated nor shown to anyone; else a
scan of the window titles, which is translated, and which has to step over
KiCad's scripting console on the way.

**That the plugin window goes when it goes.** Closing the PCB editor closed the
plugin window on Windows and left it standing on macOS, over an editor that no
longer existed. The parent is why: ``wx.GetActiveWindow`` -- which is what
gui.show used to build the shell on -- is implemented for MSW and GTK only, and
answers None everywhere else, so on macOS the shell was built parentless. A
parentless top-level window is nobody's child, and nothing destroys it. Asking
this module for the frame instead is what makes the answer the same on all
three platforms; it is also what keeps the wx parent chain under the shell
(its dialogs, its viewers) rooted in the editor rather than in nothing.

That alone would already close the window. It would not *shut it down*: a
window destroyed with its parent is deleted, not closed, so it gets no
wxEVT_CLOSE and the shell's own lifecycle -- persist the form, stop a run in
flight, tear down the viewers (gui.shell._on_close) -- would be skipped, on
every platform. So ``close_with_editor`` watches the frame and closes the
window itself, properly, while there is still an editor there to close beside.

The watch is a wxEVT_DESTROY binding on the frame. wx sends that event from
wxTopLevelWindowBase's destructor, before the window's children are deleted, so
the shell is still whole when it is asked to close. Two things about it:

  * it propagates. wxWindowDestroyEvent is a wxCommandEvent, so a *child* of
    the editor being destroyed -- one of KiCad's own dialogs, or the shell
    itself -- travels up to the frame and reaches this handler too; the handler
    is only interested in the event whose window is the frame;
  * it outlives us. The plugin window is normally closed long before KiCad is,
    and a binding left on the editor holding a destroyed window would fire into
    nothing at shutdown -- hence ``stop_watching``, which gui.show's close
    handler calls on the way out.
"""

import wx

# The name KiCad constructs the PCB editor frame with (PCB_EDIT_FRAME_NAME in
# its sources): a wxWindow name is not a label, so it is not translated and not
# shown, which makes it a better question than the title scan below.
_FRAME_NAME = "PcbFrame"

# The live watches, ``(window, frame, handler)`` each. Module-level rather than
# an attribute on the window, for the same reason gui.shell keeps its window
# list here: the objects on both ends are wx's, and one of them is KiCad's.
_watches = []


def editor_frame(window=None):
    """The PCB editor frame, or None if this wx holds no window that looks like
    one. ``window`` is any plugin window (the frame is its root ancestor); pass
    nothing when there is no window yet, which is gui.show asking what to build
    the shell on."""
    w = window
    while w is not None and w.GetParent() is not None:
        w = w.GetParent()
    if w is not None and w is not window:
        return w
    return _named_frame() or _titled_frame()


def _named_frame():
    """The frame KiCad named ``PcbFrame``. wx falls back to searching *labels*
    when no window carries the name, so what comes back is checked: the editor
    is a top-level window, and a button somebody labelled the same is not."""
    try:
        found = wx.FindWindowByName(_FRAME_NAME)
        return found if found is not None and found.IsTopLevel() else None
    except Exception:
        return None


def _titled_frame():
    """The last resort: a top-level window whose title reads like the editor's
    -- translated, and skipping KiCad's scripting console."""
    for w in wx.GetTopLevelWindows():
        title = w.GetTitle()
        if "python" in title.lower():
            continue
        if wx.GetTranslation("PCB Editor") in title or "pcbnew" in title.lower():
            return w
    return None


def close_with_editor(window, frame=None):
    """Close ``window`` when the PCB editor is destroyed, the way closing it by
    hand would (see the module docstring). Returns whether there was a frame to
    watch -- False leaves the window's fate to the wx parent chain alone."""
    frame = editor_frame(window) if frame is None else frame
    if frame is None:
        return False

    def on_destroy(event):
        # Skipped either way: the editor's own destruction is not this
        # plugin's to claim, and the event is on its way to KiCad's handlers.
        event.Skip()
        if event.GetWindow() is not frame:
            return  # something under the editor going away, not the editor
        _forget(window)  # this handler *is* the watch: nothing left to unbind
        close(window)

    frame.Bind(wx.EVT_WINDOW_DESTROY, on_destroy)
    _watches.append((window, frame, on_destroy))
    return True


def stop_watching(window):
    """Drop ``window``'s watch: it closed on its own, and the binding on the
    editor would otherwise outlive it."""
    for _, frame, handler in _forget(window):
        try:
            frame.Unbind(wx.EVT_WINDOW_DESTROY, handler=handler)
        except Exception:
            pass  # an editor already on its way out has nothing to unbind


def close(window):
    """Close ``window`` as the user closing it would, and say whether it was
    still there to close. Forced, because the editor is going whatever anyone
    thinks about it, and through Close rather than Destroy, because
    wxEVT_CLOSE is where the shell saves its form and stops a run in flight."""
    try:
        if not window:
            return False  # destroyed already: nothing to save, nothing to stop
        window.Close(True)
        return True
    except RuntimeError:
        return False  # the wx window went away under us


def _forget(window):
    """Take ``window``'s watches off the list and answer them."""
    dropped = [watch for watch in _watches if watch[0] is window]
    for watch in dropped:
        _watches.remove(watch)
    return dropped
