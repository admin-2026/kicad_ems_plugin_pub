"""UnitSlider's editable readout: when a typed value takes effect (no KiCad,
real wx stubbed).

The wizard's area sliders (width, height, feed position) can be typed into for
a precise value, and the plugin's window is a frame beside the PCB editor --
"clicking away" from a field usually lands on something that never takes the
focus off it (dead space in the form, KiCad's canvas in another window). So
the commit doesn't hang off a focus-out: the field is a ``live_text``, like
the scan's min/max bounds, and applies what it holds keystroke by keystroke.

What that costs, and what is pinned here: the readout must not be rewritten
under the user's caret while they type, must be normalised once they leave,
and must not redraw the caller's marker for keystrokes that don't move the
slider.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_unit_slider.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

widgets = load("emkit.gui.widgets")

RANGE = (20, 2000)  # the area sliders' range: 2 .. 200 mm, in tenths
SCALE = 10
START = 500  # 50.0 mm


class _Grid:
    def Add(self, *args, **kwargs):
        pass


def _slider():
    """An editable UnitSlider like the area section's, its field, and the list
    its ``on_change`` appends to (one entry per live redraw)."""
    changes = []
    sl = widgets.UnitSlider(
        _Grid(),
        None,
        "Area width",
        RANGE,
        START,
        SCALE,
        lambda: changes.append(sl.value()),
        fmt="{:.1f}".format,
        editable=True,
        suffix="mm",
    )
    return sl, sl._readout, changes


def _leave(field):
    """Focus moves off the field: wx.CallAfter runs the commit once the focus
    has settled (the stub calls it inline)."""
    field.focused = False
    field.fire("EVT_KILL_FOCUS")


def test_typed_value_lands_without_any_focus_event():
    """The case a focus-out commit misses: type, then click something that
    never takes the focus. Every keystroke has already been applied."""
    sl, field, changes = _slider()
    field.type("7")
    assert sl.value() == 7.0
    field.type("7.5")
    assert sl.value() == 7.5
    assert changes == [7.0, 7.5]


def test_typing_does_not_rewrite_the_field():
    """Normalising the text under the caret ("7.5" -> "7.5 mm", a half-typed
    "1" -> "1.0") would fight the user, so a focused field is left alone."""
    sl, field, _ = _slider()
    field.type("7.5")
    assert field.GetValue() == "7.5"
    field.type("")  # cleared, still typing: left blank
    assert field.GetValue() == ""
    assert sl.value() == 7.5  # nothing to parse, nothing applied


def test_focus_out_normalises_the_text():
    sl, field, changes = _slider()
    field.type("12.34")  # finer than the slider can hold
    assert sl.value() == 12.3
    _leave(field)
    assert field.GetValue() == "12.3"
    assert changes == [12.3]  # the focus-out is not a second redraw


def test_unusable_entry_snaps_back_on_leaving():
    sl, field, changes = _slider()
    for text in ("", "  ", "mm"):
        field.type(text)
        _leave(field)
        assert sl.value() == START / SCALE
        assert field.GetValue() == "50.0"
        assert changes == []


def test_keystrokes_that_change_nothing_do_not_redraw():
    """Each on_change rewrites the marker's segments and redraws the preview,
    so only a keystroke that moves the slider may fire one."""
    sl, field, changes = _slider()
    field.type("41.2")
    field.type("41.20")  # same value, another keystroke
    field.type("41.24")  # below the slider's resolution
    _leave(field)
    assert sl.value() == 41.2
    assert changes == [41.2]


def test_typed_value_is_clamped_into_range():
    sl, field, changes = _slider()
    for text, expected in (("9999", RANGE[1] / SCALE), ("-5", RANGE[0] / SCALE)):
        field.type(text)
        assert sl.value() == expected
    assert changes == [RANGE[1] / SCALE, RANGE[0] / SCALE]


def test_focus_out_after_the_dialog_closed_is_survivable():
    """The commit is deferred to the next idle, by when the field may be gone
    -- a destroyed wx window raises instead of answering."""
    sl, field, _ = _slider()

    def gone():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    field.GetValue = gone
    _leave(field)  # must not propagate


def test_set_value_still_syncs_the_readout():
    """The decode path (a marker already on the board syncs the sliders to it)
    goes through set_value, which must not fire on_change."""
    sl, field, changes = _slider()
    sl.set_value(43.21)
    assert sl.value() == 43.2
    assert field.GetValue() == "43.2"
    assert changes == []


def test_set_range_clamps_without_redrawing():
    """An end read off the board (the area section caps its sides at the board
    outline) moves with the board. Re-ranging clamps the value and says whether
    it had to -- but fires no on_change: the caller decides what a clamp costs,
    and a re-range that changed nothing must cost nothing."""
    sl, field, changes = _slider()
    assert sl.set_range((RANGE[0], 300)) is True  # 50.0 mm -> the new 30.0 end
    assert sl.value() == 30.0
    assert field.GetValue() == "30.0"
    assert changes == []  # no redraw of the caller's marker
    assert sl.set_range((RANGE[0], 300)) is False  # same range, nothing done
    assert sl.set_range(RANGE) is False  # widened again: the value still fits
    assert sl.value() == 30.0


def test_a_typed_value_is_clamped_to_the_new_range():
    sl, field, _ = _slider()
    sl.set_range((RANGE[0], 300))
    field.type("999")
    assert sl.value() == 30.0


if __name__ == "__main__":
    run_module_tests(globals())
