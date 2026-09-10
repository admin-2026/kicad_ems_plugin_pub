"""Take the sliders with the form when it scrolls -- the macOS half of it.

A scrolled form there has no scrolling view under it: wxWindowMac::ScrollWindow
walks every child of the scroll and re-frames it by the distance scrolled, one
control at a time. The sliders are the ones it leaves behind. Everything else
moves -- the headings, the fields, the dropdowns, the spin controls with their
arrows -- and each wx.Slider (an NSSlider, the only control in the form wxOSX
gives its own DoSetSize) keeps the place on screen it already had, until the
sections that did move are drawn over it and it is gone from the form as far as
anyone using it can tell. Something that redraws the whole page from its sizer
-- resizing the window, leaving the view and coming back -- puts it right,
which is the shape of the cure.

So after the form has scrolled, this lays it out again. ``wxScrolled``'s own
Layout places the body sizer at the scrolled origin, i.e. exactly where the
scroll now is, and every child is asked for the position that leaves it at;
wxOSX answers that question against the control's *real* frame (it reads the
NSView), so a control already in the right place costs nothing and one left
behind is moved. It reconciles the form with the screen rather than repeating
the arithmetic that lost a control in the first place -- which also means it
does not matter which side of wx was the one out of step. The sliders are then
refreshed where they now are, since a parent's Refresh on macOS is not its
native children's.

Three things about when.

It runs *after* the scroll, not with it. A handler bound for wxEVT_SCROLLWIN on
a scrolled window runs before wxScrollHelper does the scrolling (the helper's
event handler passes the event to the window's own handlers first and does
nothing more if one of them claims it -- hence the Skip, without which the form
would stop scrolling altogether). So the work is deferred to the next idle, by
when the children have moved.

It runs once per idle, not once per event. A wheel notch or a trackpad gesture
is delivered as one scroll event per line, so a single flick is a burst of
them; the pending flag folds the burst into one layout of the form.

And it runs on macOS alone: ``watch`` binds nothing anywhere else, and says so,
so the caller can leave the call unconditional.
"""

import wx

# wx.Platform for the Cocoa port -- both spellings, since wxPython answers
# "__WXMAC__" and the port's own name is OSX.
_MAC = ("__WXMAC__", "__WXOSX__")


def watch(scroll):
    """Re-place the sliders on ``scroll`` whenever it scrolls. Returns whether
    the watch was needed -- False everywhere but macOS, where nothing is bound
    and nothing is laid out."""
    if wx.Platform not in _MAC:
        return False
    # The scroll itself, not event.GetEventObject(): every scroll event this
    # window sees is its own, and a handler that doesn't have to trust the
    # event for that can't be given a child's.
    scroll.Bind(wx.EVT_SCROLLWIN, lambda event: _on_scroll(event, scroll))
    return True


def _on_scroll(event, scroll):
    """The form is about to scroll: let it (Skip -- see the module docstring),
    and queue the re-placement for when it has."""
    event.Skip()
    _queue(scroll)


def _queue(scroll):
    """Ask for one pass over ``scroll`` on the next idle, however many scroll
    events the burst is made of."""
    if getattr(scroll, "_slider_resettle_queued", False):
        return
    scroll._slider_resettle_queued = True
    wx.CallAfter(resettle, scroll)


def resettle(scroll):
    """Lay the form out where the scroll now is, and draw the sliders there."""
    scroll._slider_resettle_queued = False
    try:
        scroll.Layout()
        for slider in sliders(scroll):
            slider.Refresh()
    except RuntimeError:
        pass  # the page went away with the window before the idle came


def sliders(window):
    """Every wx.Slider under ``window``, at any depth: the form's rows are
    nested in sizers and panes, and a designer's scan rows are rebuilt as the
    design changes, so this is walked when it is needed rather than collected
    once."""
    for child in window.GetChildren():
        if isinstance(child, wx.Slider):
            yield child
        else:
            yield from sliders(child)
