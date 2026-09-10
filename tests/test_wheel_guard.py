"""The mouse wheel must not change a slider or a spin control (no KiCad, real
wx stubbed).

The dialog's rule is that the wheel scrolls the page and nothing else: a value
the user never meant to set is worse than a page that didn't move, because the
form is long and a knob changed in passing is invisible until a simulation
comes back wrong. widgets.no_scroll states that rule, but it can only *enforce*
it where wx sees the notch before the control does -- on MSW. On GTK a
wx.Slider is a GtkScale and a wx.SpinCtrl a GtkSpinButton, each of which
consumes the notch and moves itself first; that is why the wheel slid these
controls on Linux and not on Windows.

So widgets._WheelGuard undoes such a change afterwards, and what it has to go
on is whether any deliberate input can account for it. Pinned here: the wheel
is undone and never reaches the caller, while every real way of driving these
controls -- dragging, clicking an arrow, typing, arrow keys on a focused
slider, and code calling SetValue -- still gets through untouched.

macOS is the third platform and takes neither half: no native control there
acts on a notch it wasn't given, and a notch nothing wants is passed up to the
scroll view by AppKit itself. So no_scroll binds nothing at all there -- what
is pinned is that absence, because binding was what made the hovered slider
disappear (the page was being scrolled, and every control on it moved, from
inside that control's own event dispatch).

See wx_stub.py for what "stubbed" means here; its ``adjust`` (button held) and
``wheel`` (nothing held) are the two sides being told apart.

    python3 tests/test_wheel_guard.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: E402
from bare_package import load, run_module_tests  # noqa: E402

wx = wx_stub.wx
widgets = load("emkit.gui.widgets")
gtk_wheel = load("emkit.gui.gtk_wheel")

_CALL_AFTER = wx.CallAfter  # the stub's, which runs the call inline


def _slider(value=50):
    """A slider like the scan's preview row, and the list its handler appends
    to (one entry per change the user is credited with)."""
    heard = []
    sl = widgets.Slider(None, value=value, minValue=0, maxValue=100)
    sl.bind_change(lambda event: heard.append(sl.GetValue()))
    return sl, heard


class _Page(wx.ScrolledWindow):
    """The scrolled form a section's controls are built on, counting what it
    was asked to scroll by (one entry per notch that reached it)."""

    def __init__(self):
        super().__init__()
        self.scrolled = []

    def ScrollLines(self, lines):
        self.scrolled.append(lines)


class _Field(wx.TextCtrl):
    """A control on that page: the parent chain _redirect_wheel walks up to
    find the scroll (the stub's own widgets have no tree)."""

    def __init__(self, page):
        super().__init__()
        self._page = page

    def GetParent(self):
        return self._page


class _Notch:
    """The EVT_MOUSEWHEEL wx delivers for one wheel notch, and whether the
    handler skipped it (skipping is what leaves the event to the platform)."""

    def __init__(self, ctrl, rotation=120, delta=120, lines=3):
        self._ctrl, self._rotation, self._delta, self._lines = (
            ctrl,
            rotation,
            delta,
            lines,
        )
        self.skipped = False

    def GetEventObject(self):
        return self._ctrl

    def GetWheelRotation(self):
        return self._rotation

    def GetWheelDelta(self):
        return self._delta

    def GetLinesPerAction(self):
        return self._lines

    def Skip(self, skip=True):
        self.skipped = skip


def _form():
    """A page that scrolls, and one control built on it."""
    page = _Page()
    return page, _Field(page)


def _bound_to_wheel(ctrl):
    """Does ``ctrl`` answer the mouse wheel itself?"""
    return wx.EVT_MOUSEWHEEL in getattr(ctrl, "handlers", {})


def _on_platform(platform, call):
    """Run ``call`` as it would run on ``platform``, then put the harness'
    own back (GTK, the one the controls above are played on)."""
    wx.Platform = platform
    try:
        return call()
    finally:
        wx.Platform = "__WXGTK__"


def _spin(value=5):
    heard = []
    sp = widgets.SpinCtrl(None, min=1, max=50, initial=value)
    sp.bind_change(lambda event: heard.append(sp.GetValue()))
    return sp, heard


def _typed(ctrl, value, event="EVT_TEXT"):
    """A keystroke that changes the value: the key goes down, the control
    fires its change event, the key comes up."""
    ctrl.fire("EVT_KEY_DOWN")
    ctrl.wheel(value)  # the same bare change event -- the key is what differs
    ctrl.fire("EVT_KEY_UP")


def test_a_wheel_notch_over_a_slider_is_undone():
    sl, heard = _slider()
    sl.wheel(80)
    assert sl.GetValue() == 50
    assert heard == []  # and the caller redraws nothing


def test_the_revert_waits_for_the_next_idle():
    """The event is delivered from inside GTK's own scroll handler, which is
    still walking the widget: moving it from there takes KiCad down (the same
    trap UnitSlider's focus-out commit is deferred around). So the notch stands
    until the idle, and only the deferred call puts it back."""
    sl, heard = _slider()
    deferred = []
    wx.CallAfter = lambda fn, *args, **kwargs: deferred.append(fn)
    try:
        sl.wheel(80)
        assert sl.GetValue() == 80  # not touched from inside the handler
        assert len(deferred) == 1
        sl.wheel(90)  # the notch's other events queue no second revert
        assert len(deferred) == 1
        deferred[0]()
    finally:
        wx.CallAfter = _CALL_AFTER
    assert sl.GetValue() == 50
    assert heard == []


def test_a_notch_that_changes_nothing_is_not_reverted():
    """A revert that sets the value it already holds can be answered by another
    change event -- a loop of reverts, which is worse than the notch."""
    sl, _ = _slider()
    calls = []
    wx.CallAfter = lambda fn, *args, **kwargs: calls.append(fn)
    try:
        sl.wheel(50)  # the slider is already at 50
    finally:
        wx.CallAfter = _CALL_AFTER
    assert calls == []


def test_dragging_the_slider_still_works():
    sl, heard = _slider()
    sl.adjust(80)
    assert sl.GetValue() == 80
    assert heard == [80]


def test_a_keystroke_still_moves_the_slider():
    """Arrow/Home/End on a focused control: wx delivers the key, so the change
    that follows it is accounted for."""
    sl, heard = _slider()
    _typed(sl, 51)
    assert sl.GetValue() == 51
    assert heard == [51]


def test_the_key_only_covers_the_keystroke():
    """The excuse ends when the key comes up -- or holding an arrow once would
    leave the wheel free for the rest of the session."""
    sl, heard = _slider()
    _typed(sl, 51)
    sl.wheel(90)
    assert sl.GetValue() == 51
    assert heard == [51]


def test_a_focused_slider_is_driven_by_the_keyboard():
    """wxGTK doesn't deliver arrow keys for a native GtkScale, so the focus has
    to stand in for them: a change to a focused slider is let through (the
    known cost is a notch over a slider the user clicked into)."""
    sl, heard = _slider()
    sl.SetFocus()
    sl.wheel(80)
    assert sl.GetValue() == 80
    assert heard == [80]


def test_the_wheel_reverts_to_what_code_last_set():
    """A slider synced from the board (UnitSlider.set_value, the decode path)
    moved for a reason: that is the value a later notch is put back to, not
    wherever the user last left it."""
    sl, heard = _slider()
    sl.adjust(80)
    sl.SetValue(30)
    sl.wheel(90)
    assert sl.GetValue() == 30
    assert heard == [80]


def test_the_wheel_reverts_to_a_clamped_value():
    """Re-ranging a slider (the area sides follow the board outline) can clamp
    the value; the clamped position is the one to go back to."""
    sl, _ = _slider()
    sl.SetRange(0, 20)
    assert sl.GetValue() == 20
    sl.wheel(10)
    assert sl.GetValue() == 20


def test_off_gtk_the_notch_is_left_alone():
    """Where no_scroll's veto binds, the control never sees the wheel at all,
    so there is nothing to second-guess -- undoing changes on a platform whose
    input we don't model is how a real edit gets eaten."""
    sl, heard = _slider()
    _on_platform("__WXMSW__", lambda: sl.wheel(80))
    assert sl.GetValue() == 80
    assert heard == [80]


def test_on_macos_a_change_is_the_users_too():
    """The same, for the platform where the wheel never reaches a control at
    all: a value that moved there moved because someone moved it."""
    sl, heard = _slider()
    _on_platform("__WXMAC__", lambda: sl.adjust(80))
    assert sl.GetValue() == 80
    assert heard == [80]


# --- the notch that scrolls the page --------------------------------------


def test_a_notch_over_a_control_scrolls_the_page():
    """no_scroll's own half: the wheel over a field pans the form it is on,
    by the notch's worth of lines, instead of stopping at the control."""
    page, field = _form()
    widgets.no_scroll(field)
    field.fire("EVT_MOUSEWHEEL", _Notch(field))
    assert page.scrolled == [-3]


def test_on_macos_the_notch_is_left_to_the_platform():
    """Nothing is bound there: AppKit hands a notch no control wants to the
    scroll view above it, so the page scrolls without this -- and *with* it the
    form would be moved from inside the hovered control's own event dispatch,
    which is what made the slider under the pointer disappear."""
    page, field = _form()
    _on_platform("__WXMAC__", lambda: widgets.no_scroll(field))
    assert not _bound_to_wheel(field)
    field.fire("EVT_MOUSEWHEEL", _Notch(field))  # nothing to fire
    assert page.scrolled == []


def test_on_macos_a_built_form_binds_nothing_either():
    """The tree pass is the one every page makes (pages.base.BookPage.mount),
    so it is the one that has to leave the wheel alone."""
    page, field = _form()
    page.GetChildren = lambda: [field]
    _on_platform("__WXMAC__", lambda: widgets.no_scroll_tree(page))
    assert not _bound_to_wheel(field)


def test_a_control_with_no_page_under_it_swallows_the_notch():
    """The wizard doesn't scroll: there is no page to pan, and the notch must
    still not reach the control (nothing is scrolled, nothing is skipped)."""
    field = _Field(None)
    widgets.no_scroll(field)
    notch = _Notch(field)
    field.fire("EVT_MOUSEWHEEL", notch)
    assert notch.skipped is False


def test_a_wheel_notch_over_the_spin_control_is_undone():
    sp, heard = _spin()
    sp.wheel(20)
    assert sp.GetValue() == 5
    assert heard == []


def test_the_spin_arrows_and_typing_still_work():
    """Both of the count field's events (the arrows fire EVT_SPINCTRL, typing
    fires EVT_TEXT) reach the banner through one bind_change."""
    sp, heard = _spin()
    sp.adjust(9)
    _typed(sp, 12)
    assert sp.GetValue() == 12
    assert heard == [9, 12]


def test_a_focused_spin_control_is_not_excused():
    """Unlike the slider: a GtkSpinButton takes the focus when it scrolls, so
    focus there says nothing about intent -- and it doesn't have to, since a
    spin control's keystrokes do reach wx."""
    sp, heard = _spin()
    sp.SetFocus()
    sp.wheel(20)
    assert sp.GetValue() == 5
    assert heard == []


def test_a_control_with_no_gtk_widget_falls_back():
    """The block is the fix and this is the net under it: a control GTK can't
    be told about (no widget behind it, no libgobject to ask, not GTK at all)
    must answer no rather than raise, leaving the undo above to cover it -- as
    it does for every other test in this file, which run on stubs with no GTK
    anywhere near them."""
    sl, _ = _slider()
    assert gtk_wheel.block_wheel(sl) is False
    assert sl._wheel_blocked is False


if __name__ == "__main__":
    run_module_tests(globals())
