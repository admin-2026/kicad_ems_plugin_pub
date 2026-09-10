"""A slider is built tall enough for the knob macOS draws (no KiCad, real wx
stubbed).

wxOSX sizes a slider from its Aqua-era constants -- 18 points across for a
plain one, 24 for one with tick marks -- and AppKit's knob no longer fits the
plain figure, so every slider on the form but the tick-marked Speed one had its
knob cut off along the top. widgets.Slider therefore carries a floor on its
height, the way widgets.SpinCtrl carries one on its width. What is pinned here
is that the floor is a floor (a slider already tall enough keeps the height wx
gave it, ticks and all), that it costs the caller's fixed width nothing, and
that no other platform is resized -- forcing 24 points on a GtkScale would clip
it exactly as wx clips the NSSlider.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_mac_slider.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: E402
from bare_package import load, run_module_tests  # noqa: E402

wx = wx_stub.wx
widgets = load("emkit.gui.widgets")

_W = 220  # a form slider's fixed width, as the sections ask for it


def _slider(size=(_W, -1)):
    """A slider as the form builds one: a fixed width, and the height left to
    wx (which is where macOS answers too small)."""
    return widgets.Slider(None, value=5, minValue=0, maxValue=10, size=size)


def _mac(call):
    """Run ``call`` as it would run on macOS, then put the harness' own
    platform back."""
    wx.Platform = "__WXMAC__"
    try:
        return call()
    finally:
        wx.Platform = "__WXGTK__"


def test_off_macos_the_height_is_left_to_the_platform():
    """A GtkScale is taller than this figure, not shorter: nothing is asked of
    it, and asking would crop it."""
    slider = _slider()
    assert (slider.GetSize().x, slider.GetSize().y) == (_W, -1)


def test_on_macos_a_plain_slider_is_grown_to_fit_its_knob():
    slider = _mac(_slider)
    assert slider.GetSize().y == widgets.MAC_SLIDER_H


def test_the_fixed_width_survives_it():
    """SetInitialSize reads -1 as "ask the theme", so the width has to be
    handed back to it: a slider that sized itself would leave the form's rows
    ragged."""
    slider = _mac(_slider)
    assert slider.GetSize().x == _W


def test_a_slider_already_tall_enough_is_left_alone():
    """The Speed slider's tick marks earn it the taller of wx's two figures,
    and it is the one that looked right all along."""
    tall = widgets.MAC_SLIDER_H + 6
    slider = _mac(lambda: _slider(size=(_W, tall)))
    assert slider.GetSize().y == tall


if __name__ == "__main__":
    run_module_tests(globals())
