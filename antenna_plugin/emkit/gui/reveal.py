"""Taking the PCB editor to a board item the plugin is talking about.

A marker the plugin refuses to replace is a marker the user has to *find*, and
a line of text saying where it is competes with a canvas they are already
looking at. ``reveal_item`` moves that canvas instead: it scrolls the editor to
the item, brightens it, and brings the editor window to the front so the move
is seen.

``pcbnew.FocusOnItem`` does the scroll-and-brighten (it also un-brightens
whatever it was last handed, so a second call tidies up after the first); the
window in front is wx's job, from the editor frame gui.editor finds.
The whole thing is best effort, like activelayer.set_active_layer: it rides
along with a message that already says everything the user needs in words, so a
KiCad without the helper -- or a wx that won't raise the window -- simply leaves
the screen alone and lets the caller say so.
"""


def reveal_item(window, item):
    """Scroll the PCB editor to ``item``, brighten it, and raise the editor
    window (``window`` is any plugin window -- the editor frame is found from
    it). True when the editor was taken there; False when this KiCad exposes no
    FocusOnItem, or the attempt raised, in which case nothing on screen moved.
    """
    import pcbnew

    from .editor import editor_frame

    focus = getattr(pcbnew, "FocusOnItem", None)
    if focus is None:  # a KiCad whose scripting helpers lack it
        return False
    try:
        focus(item)
        pcbnew.Refresh()
        # After the scroll, not before: raising the frame first would show the
        # old viewport, and the user would watch the wrong part of their board.
        frame = editor_frame(window)
        if frame is not None:
            frame.Raise()
    except Exception:
        return False  # a nicety on top of the message: never a failure
    return True
