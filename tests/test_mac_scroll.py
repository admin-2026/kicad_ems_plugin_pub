"""The form is laid out again after it scrolls, on macOS and nowhere else (no
KiCad, real wx stubbed).

Scrolling a form on macOS moves its children one at a time (there is no
scrolling view under them), and the sliders are the ones it leaves behind: they
keep the place on screen they had while the sections scroll over them.
gui.mac_scroll lays the form out again once the scroll has happened, which puts
every child where the scrolled sizer says it goes, and redraws the sliders
there. What is pinned here is that it runs *after* the scroll and without
stopping it, that a burst of scroll events costs one layout, and that no other
platform binds anything at all.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_mac_scroll.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: E402
from bare_package import load, run_module_tests  # noqa: E402

wx = wx_stub.wx
mac_scroll = load("emkit.gui.mac_scroll")
widgets = load("emkit.gui.widgets")

_CALL_AFTER = wx.CallAfter  # the stub's, which runs the call inline


class _Slider(widgets.Slider):
    """A slider that counts the redraws it is asked for."""

    def __init__(self):
        super().__init__(None, value=0, minValue=0, maxValue=10)
        self.painted = 0

    def Refresh(self):
        self.painted += 1

    def Update(self):
        pass


class _Box(wx.Panel):
    """A sizer's worth of the form: a window with children under it, which the
    stub's own widgets don't have."""

    def __init__(self, *children):
        super().__init__()
        self._children = list(children)

    def GetChildren(self):
        return self._children


class _Scroll(_Box, wx.ScrolledWindow):
    """The page's scrolled form, counting the times it was laid out."""

    laid_out = 0

    def Layout(self):
        self.laid_out += 1


class _Scrolled:
    """The wxEVT_SCROLLWIN wx sends as the form is about to scroll: it is
    skipped handlers that let the scroll happen (wxScrollHelper does nothing
    more if one of them claims the event)."""

    def __init__(self):
        self.skipped = False

    def Skip(self, skip=True):
        self.skipped = skip


def _form():
    """A page with two sliders on it, one of them nested a box deep."""
    top, nested = _Slider(), _Slider()
    scroll = _Scroll(top, _Box(wx.StaticText(), nested))
    return scroll, [top, nested]


def _mac(call):
    """Run ``call`` as it would run on macOS, then put the harness' own
    platform back."""
    wx.Platform = "__WXMAC__"
    try:
        return call()
    finally:
        wx.Platform = "__WXGTK__"


def _scroll_the_page(scroll):
    """Fire one scroll event at the page, as the trackpad, the wheel and the
    scrollbar all do."""
    event = _Scrolled()
    scroll.fire("EVT_SCROLLWIN", event)
    return event


def test_off_macos_nothing_is_bound():
    """Every other platform scrolls a form without losing anything on it, and
    must not pay for a layout per notch to find that out."""
    scroll, sliders = _form()
    assert mac_scroll.watch(scroll) is False
    _scroll_the_page(scroll)
    assert scroll.laid_out == 0
    assert [s.painted for s in sliders] == [0, 0]


def test_a_scroll_lays_the_form_out_where_it_now_is():
    """The layout is the fix: it asks the sizer where every child goes for the
    scroll position the form is now at, which is what puts back the one the
    scroll left behind."""
    scroll, sliders = _form()
    assert _mac(lambda: mac_scroll.watch(scroll)) is True
    _scroll_the_page(scroll)
    assert scroll.laid_out == 1
    assert [s.painted for s in sliders] == [1, 1]


def test_the_scroll_itself_is_left_to_wx():
    """The handler runs *before* the scrolling does -- wxScrollHelper offers
    the event to the window's own handlers first and stops if one of them
    claims it -- so not skipping would trade a blank slider for a form that
    doesn't scroll at all."""
    scroll, _ = _form()
    _mac(lambda: mac_scroll.watch(scroll))
    assert _scroll_the_page(scroll).skipped is True


def test_the_layout_waits_for_the_scroll_to_happen():
    """Laying the form out from inside the handler would place every child for
    the scroll position the form is about to leave: the children move when wx
    handles the event, after this."""
    scroll, sliders = _form()
    _mac(lambda: mac_scroll.watch(scroll))
    deferred = []
    wx.CallAfter = lambda fn, *args: deferred.append((fn, args))
    try:
        _scroll_the_page(scroll)
        assert scroll.laid_out == 0  # not yet
        assert len(deferred) == 1
        _scroll_the_page(scroll)  # the rest of the same burst
        _scroll_the_page(scroll)
        assert len(deferred) == 1  # still one layout
        fn, args = deferred[0]
        fn(*args)
    finally:
        wx.CallAfter = _CALL_AFTER
    assert scroll.laid_out == 1
    assert [s.painted for s in sliders] == [1, 1]
    # and the next burst is settled again, not swallowed by the first
    _scroll_the_page(scroll)
    assert scroll.laid_out == 2


def test_a_page_that_went_away_is_not_settled():
    """The idle comes after the window closed: the deferred repaint is asking a
    destroyed control to draw, which wx answers with RuntimeError."""
    scroll, _ = _form()

    def gone():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    scroll.Layout = gone
    mac_scroll.resettle(scroll)  # no raise


if __name__ == "__main__":
    run_module_tests(globals())
