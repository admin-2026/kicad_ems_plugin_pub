"""Take the mouse wheel away from a native GTK control.

Only the Linux build needs this, and only for the two controls that act on a
wheel notch by themselves: a wx.Slider is a GtkScale and a wx.SpinCtrl a
GtkSpinButton, and each moves its own value from its own "scroll-event"
handler. wx cannot call that off. Not skipping EVT_MOUSEWHEEL withholds a
default action only where wx is in front of it, which on GTK it is not (see
widgets._WheelGuard) -- so the value moves first and anything wx does is a
correction after the fact.

GTK's own answer is a handler that says the event is dealt with: "scroll-event"
is RUN_LAST, so a handler connected to the widget runs before the class handler
that would move the value, and returning TRUE ends the emission there. That is
what the wider GTK world does about scroll-inside-a-scrolled-form, and it is
what this connects -- from ctypes, since a wx control's GTK widget is a raw
pointer (``GetHandle``) with no Python binding on it. Nothing here needs
PyGObject, and nothing here reads the event: the callback takes the pointers
and ignores them, so no struct layout is being assumed and no version of GTK 3
can be read wrong.

It composes with wx's own connection rather than replacing it. wx connected its
scroll handler when the control was built, so it runs first: if it ever does
claim the notch (widgets._redirect_wheel, which scrolls the page with it), the
emission stops there and this is never reached. This only catches what wx let
through -- which, on the sliders, is all of it.

Everything here degrades to "no": a build this can't reach, a control with no
GTK widget yet, a platform that isn't GTK. ``block_wheel`` says whether the
block took, and the caller keeps a fallback for when it didn't.
"""

import ctypes

import wx

# The signature GTK will call back on: gboolean (*)(GtkWidget*, GdkEvent*,
# gpointer). One instance serves every control -- it answers the same way for
# all of them -- and it is a module global because a callback thunk that gets
# collected while GTK still holds it is a crash, not an error.
_CALLBACK = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


def _swallow(_widget, _event, _data):
    """TRUE: the notch is dealt with. The emission stops here, so the widget's
    own handler -- the one that would move the value -- never runs."""
    return 1


_SWALLOW = _CALLBACK(_swallow)

_connect = None  # g_signal_connect_data, looked up once (None = unavailable)
_looked_up = False


def _connector():
    """libgobject's ``g_signal_connect_data``, or None if it can't be reached.

    Loaded on first use, not at import: this module is imported wherever the
    GUI is (Windows and the test harness included) and must cost nothing there.
    The library is asked for by soname first; failing that, the process's own
    symbols, since a running GTK app has already linked it."""
    global _connect, _looked_up
    if _looked_up:
        return _connect
    _looked_up = True
    for name in ("libgobject-2.0.so.0", None):
        try:
            lib = ctypes.CDLL(name)
            _connect = lib.g_signal_connect_data
        except (OSError, AttributeError):
            continue
        _connect.argtypes = [
            ctypes.c_void_p,  # instance
            ctypes.c_char_p,  # detailed_signal
            ctypes.c_void_p,  # c_handler
            ctypes.c_void_p,  # data
            ctypes.c_void_p,  # destroy_data
            ctypes.c_uint,  # connect_flags
        ]
        _connect.restype = ctypes.c_ulong
        return _connect
    return None


def block_wheel(ctrl):
    """Answer the mouse wheel over ``ctrl`` before GTK's own handler can, so a
    notch leaves the value where it was -- nothing moves, nothing is put back,
    and there is no flicker to see. Returns whether the block took."""
    if wx.Platform != "__WXGTK__":
        return False
    try:
        handle = ctrl.GetHandle()
        if not handle:
            return False  # not realised yet: nothing to connect to
        connect = _connector()
        if connect is None:
            return False
        return bool(
            connect(
                ctypes.c_void_p(int(handle)),
                b"scroll-event",
                ctypes.cast(_SWALLOW, ctypes.c_void_p),
                None,
                None,
                0,
            )
        )
    except Exception:
        # A control the wheel can still move is a nuisance; a dialog that
        # doesn't open is not. The caller's fallback covers this.
        return False
