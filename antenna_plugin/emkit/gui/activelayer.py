"""Switching the PCB editor's active layer from the plugin.

Nothing in ``pcbnew`` can do it: the scripting helpers hand out the board,
never the editor frame (pcbnew_scripting_helpers.h), ``FocusOnItem``'s layer
argument only picks which layer's shape to scroll to, and the direct
layer-switch hotkeys reach copper layers only -- so ``SetActiveLayer`` is out
of reach from Python.

What is reachable is the widget a user clicks to change layers: every row of
the Appearance panel's layer list carries the pcbnew layer id as its own wx
window id and answers a left click with ``PCB_EDIT_FRAME::SetActiveLayer``
(KiCad's ``pcbnew/widgets/appearance_controls.cpp``). So the switch here is a
synthetic ``wxEVT_LEFT_DOWN`` handed to that row -- the same trick, and for the
same reason, as the synthetic Ctrl+V in place.trigger_paste.

A row is matched on its wx id *and* the layer's name (the label KiCad puts on
it, ``BOARD::GetLayerName``), so an unrelated widget that happens to share the
id is never clicked. The whole thing is best effort: it rides along with
placing a marker, so a KiCad whose panel no longer looks like this leaves the
active layer where it was and says nothing -- the placement itself succeeded
either way.
"""

import wx

from .editor import editor_frame


def set_active_layer(window, board, layer_id):
    """Make ``layer_id`` the PCB editor's active layer, as clicking its row in
    the Appearance panel does. ``window`` is any plugin window -- the editor
    frame is found from it (editor.editor_frame). True when the click was
    delivered; False means the row wasn't there (or wx refused the event), and
    the active layer simply stays where it was."""
    try:
        frame = editor_frame(window)
        if frame is None:
            return False
        row = _layer_row(frame, layer_id, board.GetLayerName(layer_id))
        if row is None:
            return False
        event = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
        # The panel reads the layer off the event object's window id, so the
        # row widget itself has to be the event object.
        event.SetEventObject(row)
        return bool(row.GetEventHandler().ProcessEvent(event))
    except Exception:
        return False  # a nicety on top of the placement: never a failure


def _layer_row(frame, layer_id, layer_name):
    """The Appearance panel's row for ``layer_id``: its label, the widget that
    carries both the layer's wx id and its name. None when this editor has no
    such row -- a layer disabled on the board isn't listed, and a KiCad that
    builds the panel differently has nothing here to click."""
    for child in _descendants(frame):
        if (
            child.GetId() == layer_id
            and isinstance(child, wx.StaticText)
            and child.GetLabelText() == layer_name
        ):
            return child
    return None


def _descendants(window):
    """Every window below ``window``, depth first."""
    for child in window.GetChildren():
        yield child
        yield from _descendants(child)
