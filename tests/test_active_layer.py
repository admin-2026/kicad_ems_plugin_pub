"""The editor's active layer, switched through the Appearance panel (no KiCad,
wx stubbed).

Placing a marker also puts the PCB editor on the marker's own layer, and the
only way there from Python is the widget a user would click: the Appearance
panel's layer row, which carries the layer id as its wx window id and calls
SetActiveLayer on a left click. gui.activelayer sends that click.

What is pinned here: the click reaches the right row (matched on the wx id
*and* the layer's name, so a stray widget sharing an id is never clicked), the
event carries the row as its object -- KiCad reads the layer off it, so an
event without it would switch to the wrong layer or none -- and that the whole
thing stays a nicety: no row, no frame, or a panel that throws, and the caller
gets a plain False instead of an exception on top of a placement that worked.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_active_layer.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

wx = wx_stub.wx

USER_2 = 42  # a pcbnew layer id, as the panel uses it for the row's wx id


class _MouseEvent:
    """The stub's wx.MouseEvent: it only has to remember its type and the
    window handed to SetEventObject (which is the whole point of the click)."""

    def __init__(self, event_type=None):
        self.event_type = event_type
        self.object = None

    def SetEventObject(self, obj):
        self.object = obj


wx.MouseEvent = _MouseEvent
wx.GetTopLevelWindows = lambda: []  # the frame is found by parent walk here

activelayer = load("gui.activelayer")


# --------------------------------------------------------------------------- #
# A fake editor: an Appearance panel of layer rows, and the board behind it
# --------------------------------------------------------------------------- #
class _Row(wx.StaticText):
    """An Appearance panel layer row's label: the layer's wx id, the layer's
    name, and KiCad's onLayerLeftClick behind ProcessEvent -- it reads the
    layer off the event's object, exactly as the C++ does."""

    def __init__(self, frame, layer_id, name):
        super().__init__()
        self.frame = frame
        self.layer_id = layer_id
        self.name = name
        self.raises = False

    def GetId(self):
        return self.layer_id

    def GetLabelText(self):
        return self.name

    def GetChildren(self):
        return []

    def GetEventHandler(self):
        return self

    def ProcessEvent(self, event):
        if self.raises:
            raise RuntimeError("the panel is having none of it")
        if event.object is None:  # no event object: no layer to switch to
            return False
        self.frame.active_layer = event.object.GetId()
        return True


class _Decoy:
    """Some other widget of the editor that happens to carry the same wx id --
    a toolbar button, a menu-ish control. Not a wxStaticText, and a click on it
    would be recorded here (nothing must)."""

    def __init__(self, layer_id):
        self.layer_id = layer_id
        self.clicked = False

    def GetId(self):
        return self.layer_id

    def GetChildren(self):
        return []

    def GetEventHandler(self):
        return self

    def ProcessEvent(self, event):
        self.clicked = True
        return True


class _Panel:
    """A window that only holds children -- the panel the rows sit in."""

    def __init__(self, *children):
        self.children = list(children)

    def GetId(self):
        return -1

    def GetChildren(self):
        return self.children


class _Frame(_Panel):
    """The PCB editor frame: the plugin window's root ancestor, with the
    active layer it would set."""

    def __init__(self, *children):
        super().__init__(*children)
        self.active_layer = None

    def GetParent(self):
        return None


class _Window:
    """A plugin window: the editor frame is its ancestor (place.editor_frame
    walks up to it)."""

    def __init__(self, frame):
        self.frame = frame

    def GetParent(self):
        return self.frame


class _Board:
    """Only what the switch asks a board: what a layer is called."""

    def __init__(self, names):
        self.names = names

    def GetLayerName(self, layer_id):
        return self.names[layer_id]


def _editor(*extra):
    """An editor frame whose Appearance panel lists User.1 and User.2 (plus
    any ``extra`` widgets), the plugin window on it, and the board."""
    rows = _Panel(
        _Row(None, 41, "User.1"),
        _Row(None, USER_2, "User.2"),
        *extra,
    )
    frame = _Frame(_Panel(), rows)
    for row in rows.GetChildren():
        if isinstance(row, _Row):
            row.frame = frame
    board = _Board({41: "User.1", USER_2: "User.2"})
    return frame, _Window(frame), board


def _row(frame, layer_id):
    for panel in frame.GetChildren():
        for child in panel.GetChildren():
            if isinstance(child, _Row) and child.GetId() == layer_id:
                return child
    raise AssertionError("no such row")


# --------------------------------------------------------------------------- #
# The click
# --------------------------------------------------------------------------- #
def test_the_layers_row_is_clicked():
    frame, window, board = _editor()
    assert activelayer.set_active_layer(window, board, USER_2) is True
    assert frame.active_layer == USER_2


def test_the_click_carries_the_row_as_its_object():
    """KiCad's handler reads the layer off the event's object, so the row has
    to be it -- an event without one switches nothing (the fake row says so)."""
    frame, window, board = _editor()
    seen = []
    row = _row(frame, USER_2)
    row.ProcessEvent = lambda event: seen.append(event) or True
    activelayer.set_active_layer(window, board, USER_2)
    assert len(seen) == 1
    assert seen[0].object is row
    assert seen[0].event_type == wx.wxEVT_LEFT_DOWN


def test_a_renamed_layer_is_matched_by_its_name():
    """The panel labels a row with board.GetLayerName, so a layer the user
    renamed is still found -- that is the same name the switch looks for."""
    frame, window, board = _editor()
    _row(frame, USER_2).name = "Antenna markers"
    board.names[USER_2] = "Antenna markers"
    assert activelayer.set_active_layer(window, board, USER_2) is True
    assert frame.active_layer == USER_2


# --------------------------------------------------------------------------- #
# What must not be clicked, and what must not throw
# --------------------------------------------------------------------------- #
def test_a_stray_widget_with_the_same_id_is_left_alone():
    decoy = _Decoy(USER_2)
    frame, window, board = _editor(decoy)
    activelayer.set_active_layer(window, board, USER_2)
    assert decoy.clicked is False
    assert frame.active_layer == USER_2


def test_a_row_whose_name_disagrees_is_not_the_layers_row():
    """Id and name both have to match: a panel that no longer labels its rows
    the way the board names its layers is a panel this can't read."""
    frame, window, board = _editor()
    _row(frame, USER_2).name = "Something else entirely"
    assert activelayer.set_active_layer(window, board, USER_2) is False
    assert frame.active_layer is None


def test_a_layer_without_a_row_leaves_the_active_layer_alone():
    """A layer disabled on the board isn't listed in the panel."""
    frame, window, board = _editor()
    board.names[49] = "User.9"
    assert activelayer.set_active_layer(window, board, 49) is False
    assert frame.active_layer is None


def test_a_panel_that_throws_is_not_the_callers_problem():
    frame, window, board = _editor()
    _row(frame, USER_2).raises = True
    assert activelayer.set_active_layer(window, board, USER_2) is False


def test_no_editor_frame_is_no_switch():
    _, _, board = _editor()

    class _Orphan:
        def GetParent(self):
            return None

    assert activelayer.set_active_layer(_Orphan(), board, USER_2) is False


if __name__ == "__main__":
    run_module_tests(globals())
