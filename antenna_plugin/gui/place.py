"""Cursor placement for generated marker footprints.

Shared by the feed-marker box (marker.py) and the wizard's area section: the
footprint's .kicad_mod text goes on the system clipboard and a synthetic
Ctrl+V fires KiCad's own paste tool, which puts it on the cursor — the
Python API exposes no interactive move, and a paste is undoable.
watch_placement polls the board afterwards, because the paste tool gives no
done-callback.
"""

import wx


def to_clipboard(text):
    """Put ``text`` on the system clipboard (Flush keeps it available for a
    manual paste). On Linux/GTK verify it landed by reading it back — KiCad's
    own trick (CLIPBOARD_IO::clipboardWriter) against asynchronous clipboard
    managers (KDE's Klipper, WSLg's bridge) still serving stale content to
    the paste that follows, which KiCad then drops on the board as a
    plain-text item. Mac and Windows skip the read-back (see below). False
    when the clipboard is busy or the text never sticks; the caller falls
    back to placing the footprint through the API."""
    for attempt in range(3):
        if attempt:
            wx.MilliSleep(100)  # let an async clipboard manager settle
        # wx.LogNull swallows the popup wx raises when a clipboard op fails:
        # on Windows the read-back below races Clipboard History's snapshot of
        # our fresh Flush and gets CLIPBRD_E_CANT_OPEN ("OpenClipboard
        # failed"), which is harmless (the SetData/Flush already stuck) but
        # otherwise surfaces as a scary error dialog to the user.
        with wx.LogNull():
            if not wx.TheClipboard.Open():
                continue
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Flush()
                # Skip the read-back where it can't be trusted: Mac's clipboard
                # is synchronous (read-back is unsafe) and Windows' is racy
                # against Clipboard History — a failed GetData there is a
                # transient open-conflict, not a stale write, so reading back
                # would only produce false negatives (needless center-drop
                # fallback) and the OpenClipboard-failed popup. The paste-as-
                # text safety net (feed_marker.pasted_as_text + _marker_watch)
                # still catches a genuinely degraded paste after the fact.
                if wx.Platform in ("__WXMAC__", "__WXMSW__"):
                    return True
                data = wx.TextDataObject()
                if wx.TheClipboard.GetData(data) and data.GetText() == text:
                    return True
            finally:
                wx.TheClipboard.Close()
    return False


def editor_frame(window):
    """The PCB editor frame: the plugin windows' root ancestor (gui.show
    opens the main dialog on the active editor window, the wizard opens on
    the dialog), else a title scan — translated, and skipping KiCad's
    scripting console."""
    w = window
    while w is not None and w.GetParent() is not None:
        w = w.GetParent()
    if w is not None and w is not window:
        return w
    for w in wx.GetTopLevelWindows():
        title = w.GetTitle()
        if "python" in title.lower():
            continue
        if wx.GetTranslation("PCB Editor") in title or "pcbnew" in title.lower():
            return w
    return None


def trigger_paste(window):
    """Fire the editor's paste tool so the pasted footprint rides the cursor.

    Primary path (KiBuzzard's technique): post a synthetic Ctrl+V CHAR_HOOK
    straight to the editor's drawing canvas — KiCad's tool dispatcher is
    bound there, so it works no matter which window holds the focus (a
    plugin window usually does). Fallback: an OS-level keystroke via
    UIActionSimulator after handing the editor the focus; the wx.Yield is
    essential, or the keys fire before the focus change is processed and
    land back in the plugin window. False when neither could be attempted;
    the footprint is on the clipboard either way."""
    frame = editor_frame(window)
    if frame is None:
        return False
    frame.Raise()  # editor in front: placement is visible
    try:
        evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        evt.SetKeyCode(ord("V"))
        evt.SetControlDown(True)
        canvas = [w for w in frame.GetChildren() if w.GetClassName() == "wxWindow"][0]
        wx.PostEvent(canvas, evt)
        return True
    except Exception:
        pass
    sim_cls = getattr(wx, "UIActionSimulator", None)
    if sim_cls is None:
        return False
    frame.SetFocus()
    wx.MilliSleep(100)
    wx.Yield()  # let the focus change land
    ok = bool(sim_cls().Char(ord("V"), getattr(wx, "MOD_CMD", wx.MOD_CONTROL)))
    wx.MilliSleep(100)
    return ok


def watch_placement(
    window, snapshot, on_settled, interval_ms=750, stable_polls=2, max_ticks=400
):
    """Poll the board after a paste and fire ``on_settled`` once the pasted
    footprint lands. KiCad's paste tool gives no done-callback, and the
    footprint is on the board already while it still rides the cursor — so
    "placed" is ``snapshot()`` (a comparable placement state, or None while
    there is nothing to watch) holding still across polls; the watcher then
    keeps following until its cap (~5 min) so a stale reading — grid snap
    can hold the state still while the user is only aiming — corrects
    itself on the next stillness. Stops when ``window`` is destroyed."""

    def poll(last, ticks, stable, settled):
        if not window:  # owner window closed in the meantime
            return
        cur = snapshot()
        if cur is not None:
            stable = stable + 1 if cur == last else 0
            last = cur
            if stable >= stable_polls and cur != settled:
                settled = cur
                on_settled()
        if ticks < max_ticks:
            wx.CallLater(interval_ms, poll, last, ticks + 1, stable, settled)

    poll(None, 0, 0, None)
