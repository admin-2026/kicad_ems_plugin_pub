"""Grey a control without freezing the page under it -- the macOS half.

A greyed control on macOS eats the mouse wheel. wx's own view methods are
installed on every control it builds, and the one AppKit calls for a notch
starts like this (``wxOSX_mouseEvent``, src/osx/cocoa/window.mm)::

    // We shouldn't let disabled windows get mouse events.
    if (impl->GetWXPeer()->IsEnabled())
        impl->mouseEvent(event, self, _cmd);

-- so for a disabled window the method returns having done nothing at all. It
is not only wx that hears nothing: the *native* implementation is reached from
inside ``mouseEvent`` (it calls super for a scroll wheel it didn't handle,
which is how NSView passes the notch to the next responder and how the page
scrolls today), and that call is what the early return skips. The notch dies on
the control. Hovering a greyed field, or a greyed slider, freezes a form that
scrolls perfectly well an inch to either side.

Nothing on the wx side can catch it -- there is no event to bind to -- so the
cure is not to disable the wx window in the first place. Greying is drawn by
the native control anyway, so this asks the native control for it directly and
leaves the wx window enabled. The notch then takes exactly the path an enabled
control's notch takes today: offered to the control, wanted by nobody, passed
up to the scroll view by AppKit itself.

What a natively disabled NSControl refuses is what "disabled" means to anyone
using it: it draws greyed, it won't track a click or a drag, it won't become
the first responder, and it fires no action -- so no value moves and no handler
runs. This is also precisely what wx asks for when it disables a control
(``wxWidgetCocoaImpl::Enable``, same file: the NSScrollView hop below and a
``setEnabled:`` guarded by ``respondsToSelector:``); the difference is only
that wx first tells its own window to swallow the events that would have
reached it.

What it costs is that wx still counts the control as one that can take the
keyboard focus, since that is decided by the wx window's own flag. AppKit
refuses -- a disabled control is not made first responder -- so nothing can be
typed into a greyed field either way; a Tab that would have landed there simply
doesn't move (only with Full Keyboard Access on, which is off by default). A
page that stops scrolling under the pointer is the worse of the two by a long
way, and it is the one every user meets.

Two things follow for callers. Ask ``widgets.enable`` for this, not
``ctrl.Enable`` -- it is the one that knows about the fallback. And read the
form's own state, never ``IsEnabled()``, to find out whether a knob is live:
on macOS that answers for the wx window, which stays enabled the whole time.

Everything here degrades to "no": a platform that isn't macOS, a control with
no view behind it yet, a runtime that can't be reached, a view with no enabled
flag to set (an NSScrollView whose document view isn't a control). ``grey``
says whether the greying took, and the caller disables the wx window the old
way when it didn't -- a page that doesn't scroll under one greyed control,
which is where we started, rather than a control that doesn't look greyed.
"""

import ctypes

import wx

# wx.Platform for the Cocoa port -- both spellings, as in gui.mac_scroll.
_MAC = ("__WXMAC__", "__WXOSX__")


def grey(ctrl, enabled):
    """Draw ``ctrl`` the way ``enabled`` says -- greyed when False -- without
    disabling the wx window. Returns whether that took; False everywhere but
    macOS, where nothing is asked of anything."""
    if wx.Platform not in _MAC:
        return False
    try:
        handle = ctrl.GetHandle()
        if not handle:
            return False  # not realised yet: no view to grey
        # The wx window stays enabled: it is what makes AppKit offer this
        # control the notch that the page scrolls on. It goes first because
        # wx's Enable(True) sets the native flag too -- after the greying
        # below, it would undo it -- and it costs nothing when, as usually,
        # the window is enabled already.
        ctrl.Enable(True)
        return _send_enabled(int(handle), bool(enabled))
    except Exception:
        # A control that doesn't grey is a blemish; a dialog that doesn't open
        # is not. The caller's fallback covers this.
        return False


# --- the Objective-C runtime ----------------------------------------------

# objc_msgSend is one symbol with a different signature per selector, so each
# call shape gets its own prototype rather than one function object whose
# argtypes are rewritten per call (which is how this goes wrong on arm64, where
# arguments are not all passed the same way).
_ID = ctypes.c_void_p  # an object, a class, or a selector

_ASK = ctypes.CFUNCTYPE(ctypes.c_bool, _ID, _ID, _ID)  # respondsTo/isKindOf
_SET_BOOL = ctypes.CFUNCTYPE(None, _ID, _ID, ctypes.c_bool)  # setEnabled:
_GET = ctypes.CFUNCTYPE(_ID, _ID, _ID)  # documentView

_runtime = None  # a _Runtime, or None where there is none to reach
_looked_up = False


class _Runtime:
    """The handful of Objective-C calls this module makes, bound once."""

    def __init__(self, objc):
        objc.sel_registerName.restype = _ID
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = _ID
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        self._objc = objc
        self._ask = _ASK(("objc_msgSend", objc))
        self._set_bool = _SET_BOOL(("objc_msgSend", objc))
        self._get = _GET(("objc_msgSend", objc))

    def sel(self, name):
        return self._objc.sel_registerName(name)

    def cls(self, name):
        return self._objc.objc_getClass(name)

    def is_kind_of(self, obj, klass):
        return bool(klass) and self._ask(obj, self.sel(b"isKindOfClass:"), klass)

    def responds(self, obj, selector):
        return self._ask(obj, self.sel(b"respondsToSelector:"), selector)

    def document_view(self, obj):
        return self._get(obj, self.sel(b"documentView"))

    def set_enabled(self, obj, enabled):
        self._set_bool(obj, self.sel(b"setEnabled:"), enabled)


def _library():
    """The Objective-C runtime, or None if it can't be reached.

    Loaded on first use, not at import: this module is imported wherever the
    GUI is (Linux and the test harness included) and must cost nothing there.
    The library is asked for by path first -- dyld answers that from the shared
    cache, where the file itself hasn't been on disk since Big Sur -- and
    failing that from the process's own symbols, since a running Cocoa app has
    already linked it. Same two questions gui.gtk_wheel asks about GTK."""
    global _runtime, _looked_up
    if _looked_up:
        return _runtime
    _looked_up = True
    for name in ("/usr/lib/libobjc.A.dylib", None):
        try:
            _runtime = _Runtime(ctypes.CDLL(name))
        except (OSError, AttributeError):
            continue
        return _runtime
    return None


def _send_enabled(view, enabled):
    """Set the native enabled flag on ``view`` (an NSView pointer), and say
    whether there was one to set."""
    runtime = _library()
    if runtime is None:
        return False
    target = _control(runtime, view)
    if not runtime.responds(target, runtime.sel(b"setEnabled:")):
        return False  # a plain view, e.g. a panel: nothing to grey
    runtime.set_enabled(target, enabled)
    return True


def _control(runtime, view):
    """The view carrying the enabled flag. A text control that scrolls is an
    NSScrollView with the field inside it, and the flag belongs to the field --
    wxWidgetCocoaImpl::Enable makes the same hop."""
    if runtime.is_kind_of(view, runtime.cls(b"NSScrollView")):
        return runtime.document_view(view) or view
    return view
