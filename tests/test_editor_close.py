"""The plugin window belongs to the PCB editor: it is built on it, and it goes
with it (no KiCad, real wx stubbed).

Closing the PCB editor closed the plugin window on Windows and left it standing
on macOS. The parent was why -- ``wx.GetActiveWindow``, which the shell used to
be built on, answers on MSW and GTK only -- so what is pinned here is the whole
chain that replaced it: the editor frame is *found* (a parent walk, then the
name KiCad gives the frame, then a title scan), the window is built on what was
found, and the frame's destruction takes the window through its own close
handler rather than around it -- so the form is saved and a run in flight is
stopped, which a window merely deleted with its parent would skip.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_editor_close.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_pcbnew  # noqa: E402,F401  (shell -> pages -> pcbnew)
import wx_stub  # noqa: E402,F401
from bare_package import load, run_module_tests  # noqa: E402

wx = wx_stub.wx
# The window lookups: the stub invents a widget class for an unknown wx name,
# which is right for a control and useless for a function, so the three this
# module calls are answered here. A test that needs another answer says so.
wx.GetTranslation = lambda text: text
wx.GetTopLevelWindows = lambda: []
wx.FindWindowByName = lambda name: None

editor = load("emkit.gui.editor")
shell = load("emkit.gui.shell")


# --------------------------------------------------------------------------- #
# The stand-ins
# --------------------------------------------------------------------------- #
class _Destroyed:
    """The wxEVT_DESTROY wx sends from a top-level window's destructor. It
    carries the window being destroyed -- which is not always the one the
    handler is bound to, because the event propagates up the parent chain."""

    def __init__(self, window):
        self.window = window
        self.skipped = False

    def GetWindow(self):
        return self.window

    def Skip(self, skip=True):
        self.skipped = skip


class _Closed:
    """The wxEVT_CLOSE ``Close`` sends: the shell's handler reads the window
    off it."""

    def __init__(self, window):
        self.window = window

    def GetEventObject(self):
        return self.window


class _Window:
    """Anything with a wx parent chain and an event table -- the base of both
    the editor frame and the plugin window below."""

    def __init__(self, parent=None, title=""):
        self.parent = parent
        self.title = title
        self.handlers = {}

    def GetParent(self):
        return self.parent

    def GetTitle(self):
        return self.title

    def IsTopLevel(self):
        return self.parent is None

    def Bind(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def Unbind(self, event, handler=None):
        bound = self.handlers.get(event, [])
        self.handlers[event] = [h for h in bound if h is not handler]
        return len(bound) != len(self.handlers[event])

    def fire(self, event_type, event):
        for handler in list(self.handlers.get(event_type, [])):
            handler(event)
        return event


class _Frame(_Window):
    """The PCB editor frame. ``destroy`` is KiCad closing it: wx sends the
    event from the destructor, before the frame's children are deleted."""

    def destroy(self):
        return self.fire(wx.EVT_WINDOW_DESTROY, _Destroyed(self))


class _Shell(_Window):
    """The plugin window, as far as gui.show and gui.editor use one: it counts
    the lifecycle calls the close handler makes on it, in the order they came.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.did = []
        self.alive = True

    def __bool__(self):
        # wx's own answer for a window whose C++ object has been deleted, which
        # is what gui.editor.close reads before touching one.
        return self.alive

    def Close(self, force=False):
        self.did.append(f"close(force={force})")
        self.fire(wx.EVT_CLOSE, _Closed(self))
        return True

    def save_settings(self):
        self.did.append("save_settings")

    def shutdown(self):
        self.did.append("shutdown")

    def Destroy(self):
        self.did.append("destroy")
        self.alive = False

    # What bring_to_front asks of a window it is putting in front.
    def IsIconized(self):
        return False

    def __getattr__(self, name):
        if not name[:1].isupper():  # Centre, Show, Raise, SetFocus, ...
            raise AttributeError(name)
        return lambda *args, **kwargs: None


def _clean():
    """No window open and no watch left over from the test before."""
    shell._windows.clear()
    editor._watches.clear()
    wx.FindWindowByName = lambda name: None
    wx.GetTopLevelWindows = lambda: []


def _open(frame=None):
    """A plugin window on ``frame``, opened the way the toolbar button opens
    one -- so it carries the close handler and the watch gui.show gives it."""
    _clean()
    window = shell.show(_Shell, frame)
    assert window.GetParent() is frame
    return window


# --------------------------------------------------------------------------- #
# Finding the editor
# --------------------------------------------------------------------------- #
def test_a_plugin_window_knows_the_frame_it_hangs_off():
    """The cheapest and surest question: the shell is built on the editor and
    every dialog and viewer hangs off the shell, so the frame is the root."""
    _clean()
    frame = _Frame()
    dialog = _Window(_Window(frame))
    assert editor.editor_frame(dialog) is frame


def test_with_no_window_the_frame_is_the_one_kicad_named():
    """gui.show has no window yet -- that is what it is asking in order to
    build one. KiCad names the frame ``PcbFrame``, which is not translated and
    not shown to anyone, so it is asked before the titles are."""
    _clean()
    frame = _Frame(title="Untranslatable")
    wx.FindWindowByName = lambda name: frame if name == "PcbFrame" else None
    assert editor.editor_frame() is frame


def test_a_window_that_only_wears_the_name_as_a_label_is_not_the_frame():
    """wx.FindWindowByName searches labels when no window carries the name, so
    what it answers has to be a top-level window before it is believed."""
    _clean()
    frame = _Frame(title="board.kicad_pcb — PCB Editor")
    button = _Window(parent=frame, title="PcbFrame")
    wx.FindWindowByName = lambda name: button
    wx.GetTopLevelWindows = lambda: [frame]
    assert editor.editor_frame() is frame  # the title scan, not the label


def test_the_title_scan_steps_over_the_scripting_console():
    """KiCad's Python console is a top-level window of the editor's, and its
    title says pcbnew too."""
    _clean()
    console = _Frame(title="pcbnew Python console")
    frame = _Frame(title="board.kicad_pcb — PCB Editor")
    wx.GetTopLevelWindows = lambda: [console, frame]
    assert editor.editor_frame() is frame


def test_no_editor_anywhere_is_no_frame():
    _clean()
    assert editor.editor_frame() is None
    assert editor.close_with_editor(_Shell()) is False


# --------------------------------------------------------------------------- #
# Going with it
# --------------------------------------------------------------------------- #
def test_the_editor_closing_closes_the_window():
    frame = _Frame()
    window = _open(frame)
    frame.destroy()
    assert window.did == ["close(force=True)", "save_settings", "shutdown", "destroy"]


def test_it_is_closed_and_not_merely_destroyed():
    """The point of the watch: a window deleted with its parent gets no
    wxEVT_CLOSE, so the form would never be saved and a run in flight never
    stopped. Closing it is what runs both."""
    frame = _Frame()
    window = _open(frame)
    frame.destroy()
    assert window.did.index("save_settings") < window.did.index("destroy")
    assert "shutdown" in window.did


def test_the_editors_own_destruction_is_left_to_kicad():
    """The plugin is a guest in that event: KiCad's handlers are behind this
    one, and the frame is being torn down whatever the plugin thinks."""
    frame = _Frame()
    _open(frame)
    assert frame.destroy().skipped is True


def test_something_else_under_the_editor_going_away_closes_nothing():
    """wxWindowDestroyEvent is a wxCommandEvent: it propagates, so every dialog
    KiCad opens and closes -- and the plugin window itself -- reaches this
    handler on the way up."""
    frame = _Frame()
    window = _open(frame)
    dialog = _Window(frame)
    frame.fire(wx.EVT_WINDOW_DESTROY, _Destroyed(dialog))
    assert window.did == []


def test_a_window_closed_by_hand_leaves_no_binding_on_the_editor():
    """The editor outlives the plugin window by far: a watch left on it would
    fire into a destroyed window when KiCad is closed hours later."""
    frame = _Frame()
    window = _open(frame)
    window.Close()
    assert window.did == ["close(force=False)", "save_settings", "shutdown", "destroy"]
    assert frame.handlers.get(wx.EVT_WINDOW_DESTROY) == []
    frame.destroy()  # nothing bound: the closed window is not closed twice
    assert window.did.count("save_settings") == 1


def test_a_window_already_gone_is_not_closed_again():
    """Belt and braces for the watch that got past the release above: wx
    answers False for a window whose C++ object has been deleted."""
    window = _Shell()
    window.alive = False
    assert editor.close(window) is False
    assert window.did == []


def test_a_destroyed_window_raising_is_not_the_editors_problem():
    """wxPython raises RuntimeError for a call on a deleted object; KiCad is
    shutting down and a traceback out of this handler helps nobody."""
    window = _Shell()

    def gone(force=False):
        raise RuntimeError("wrapped C/C++ object has been deleted")

    window.Close = gone
    assert editor.close(window) is False


# --------------------------------------------------------------------------- #
# What the window is built on
# --------------------------------------------------------------------------- #
def test_the_window_is_built_on_the_frame_that_was_found():
    """The bug itself: with no parent handed in, the shell used to ask
    wx.GetActiveWindow -- None on macOS, and a parentless top-level window is
    nobody's child to close."""
    _clean()
    frame = _Frame()
    wx.FindWindowByName = lambda name: frame if name == "PcbFrame" else None
    window = shell.show(_Shell)
    assert window.GetParent() is frame
    frame.destroy()
    assert "destroy" in window.did


def test_one_window_per_plugin_still_holds():
    """show() raises the open window rather than opening a second one -- and
    the second call must not leave a second watch on the editor behind it."""
    frame = _Frame()
    window = _open(frame)
    assert shell.show(_Shell, frame) is window
    assert len(frame.handlers[wx.EVT_WINDOW_DESTROY]) == 1


if __name__ == "__main__":
    run_module_tests(globals())
