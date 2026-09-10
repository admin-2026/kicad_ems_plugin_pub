"""A greyed control must not eat the mouse wheel (no KiCad, real wx stubbed).

On macOS wx drops *every* mouse event aimed at a disabled window, the scroll
wheel included, and drops it before the native implementation that would have
passed the notch up to the scroll view (``wxOSX_mouseEvent``; gui.mac_enable
quotes it). So a wx-disabled field, slider or button freezes the page under the
pointer -- and there is no wx event left to bind a workaround to.

widgets.enable is the way round it: on macOS the greying is asked of the native
control and the wx window stays enabled, so the notch keeps reaching the scroll
view; everywhere else, and wherever the native ask can't be made, it is plain
``Enable``. What is pinned here is both halves of that, and that nothing about
it raises: a control the Objective-C runtime can't be asked about must fall
back, not take the dialog down with it.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_mac_enable.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: E402
from bare_package import load, run_module_tests  # noqa: E402

wx = wx_stub.wx
mac_enable = load("emkit.gui.mac_enable")
widgets = load("emkit.gui.widgets")

_VIEW = 0x1234  # the NSView pointer a realised control hands out


class _Field(wx.TextCtrl):
    """A control on the form, with a native view behind it."""

    def __init__(self, view=_VIEW):
        super().__init__()
        self._view = view

    def GetHandle(self):
        return self._view


class _Greying:
    """The native greying, recorded instead of made: what it was asked for,
    and what it answers (True = the view had an enabled flag to set)."""

    def __init__(self, took=True):
        self.took = took
        self.asked = []

    def __call__(self, view, enabled):
        self.asked.append((view, enabled))
        return self.took


def _on_macos(call, greying=None):
    """Run ``call`` as it would run on macOS, with ``greying`` standing in for
    the Objective-C runtime, then put the harness' own platform back."""
    wx.Platform = "__WXMAC__"
    native = mac_enable._send_enabled
    if greying is not None:
        mac_enable._send_enabled = greying
    try:
        return call()
    finally:
        wx.Platform = "__WXGTK__"
        mac_enable._send_enabled = native


def test_off_macos_the_control_is_simply_disabled():
    """Every other platform passes a notch a disabled control doesn't want
    straight to the page, so there is nothing here to work around."""
    field = _Field()
    widgets.enable(field, False)
    assert field.enabled is False


def test_on_macos_only_the_native_control_is_greyed():
    """The wx window stays enabled -- that is what makes AppKit offer it the
    notch the page scrolls on -- and the greying is asked of the view."""
    field = _Field()
    greying = _Greying()
    _on_macos(lambda: widgets.enable(field, False), greying)
    assert greying.asked == [(_VIEW, False)]
    assert field.enabled is True


def test_a_control_made_live_again_says_so_natively():
    field = _Field()
    greying = _Greying()
    _on_macos(lambda: widgets.enable(field, True), greying)
    assert greying.asked == [(_VIEW, True)]
    assert field.enabled is True


def test_a_slider_is_greyed_the_same_way():
    """The scan's sliders are greyed on every row but the swept one, and a
    disabled wx.Slider swallowed the notch exactly as a field did."""
    slider = widgets.Slider(None, value=5, minValue=0, maxValue=10)
    slider.GetHandle = lambda: _VIEW
    greying = _Greying()
    _on_macos(lambda: widgets.enable(slider, False), greying)
    assert greying.asked == [(_VIEW, False)]
    assert slider.enabled is True


def test_a_view_with_no_enabled_flag_falls_back():
    """Nothing to grey natively: the control is disabled the old way, and the
    page stops scrolling over it -- where we started, and better than a
    control that doesn't look greyed."""
    field = _Field()
    _on_macos(lambda: widgets.enable(field, False), _Greying(took=False))
    assert field.enabled is False


def test_a_control_with_no_view_yet_falls_back():
    """Nothing is realised before the dialog is shown; a handle of 0 is not a
    pointer to send anything to."""
    field = _Field(view=0)
    greying = _Greying()
    _on_macos(lambda: widgets.enable(field, False), greying)
    assert greying.asked == []
    assert field.enabled is False


def test_a_control_that_cannot_be_asked_falls_back():
    """Answer no rather than raise: this runs while a section syncs its form,
    and an exception there is a dialog that doesn't open."""

    class _Unrealised(_Field):
        def GetHandle(self):
            raise RuntimeError("no peer")

    field = _Unrealised()
    _on_macos(lambda: widgets.enable(field, False))
    assert field.enabled is False


def test_the_control_is_handed_back():
    field = _Field()
    assert widgets.enable(field, False) is field


if __name__ == "__main__":
    run_module_tests(globals())
