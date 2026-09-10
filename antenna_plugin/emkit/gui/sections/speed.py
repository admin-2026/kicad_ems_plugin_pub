"""The Speed / accuracy section of the simulate view.

One slider drives the six optimization toggles (which live in the Advanced
section) along a fast->accurate preset sweep; editing a toggle by hand snaps
this slider to "Custom", the same way Application<->frequency snap each other.

The toggles the slider drives live in another section, so the slider talks to
an *optimizations provider* -- an object (AdvancedSection) that owns those
toggles and exposes two calls: ``apply_preset(preset)`` to set the toggles from
a preset, and ``preset_index()`` to report which preset the current toggles
match (or None for a hand-made "Custom" combination). The provider is wired
after both sections exist (set_optimizations), since the two reference each
other.
"""

import wx

from ...options import SPEED_DEFAULT, SPEED_PRESETS
from ..theme import HAIR, PAD
from ..widgets import SLIDER_W, Slider, muted
from .base import Section


class SpeedSection(Section):
    _TITLE = "Speed / accuracy"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self._opt = None  # optimizations provider (set_optimizations)
        self._build(body)

    def set_optimizations(self, opt):
        """Wire the provider that owns the optimization toggles (AdvancedSection):
        it applies a preset's toggle state and reports the preset the current
        toggles match. Set after both sections exist, since they reference each
        other."""
        self._opt = opt

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        scroll = self.scroll
        box = self.box(self._TITLE)
        self.slider = Slider(
            scroll,
            value=SPEED_DEFAULT,
            minValue=0,
            maxValue=len(SPEED_PRESETS) - 1,
            size=(SLIDER_W, -1),
            style=wx.SL_HORIZONTAL | wx.SL_AUTOTICKS,
        )
        self.slider.bind_change(self._on_slider)
        ends = wx.BoxSizer(wx.HORIZONTAL)
        ends.Add(muted(wx.StaticText(scroll, label="◀ Fastest (less accurate)")), 0)
        ends.AddStretchSpacer(1)
        ends.Add(
            muted(wx.StaticText(scroll, label="Most accurate (more computation) ▶")), 0
        )
        self._label = self.wrap_label(scroll)
        # Slider + end labels share a non-stretching inner sizer, so the end
        # labels line up under the fixed-width slider, not the window edges.
        inner = wx.BoxSizer(wx.VERTICAL)
        inner.Add(self.slider, 0, wx.EXPAND)
        inner.Add(ends, 0, wx.EXPAND | wx.TOP, HAIR)
        box.Add(inner, 0)
        box.Add(self._label, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)

    # --- slider <-> optimization toggles --------------------------------------
    def apply_default(self):
        """Sync the toggles to the default preset and caption the slider (the
        counterpart to the manual-edit handlers, run once at construction)."""
        self.slider.SetValue(SPEED_DEFAULT)
        self._opt.apply_preset(SPEED_PRESETS[SPEED_DEFAULT])
        self._set_label(SPEED_DEFAULT)

    def _on_slider(self, event=None):
        idx = self.slider.GetValue()
        self._opt.apply_preset(SPEED_PRESETS[idx])
        self._set_label(idx)

    def on_override(self, event=None):
        """A hand-toggled optimization snaps the slider to the matching preset,
        or to 'Custom' when the combination isn't one of the stops."""
        idx = self._opt.preset_index()
        if idx is not None:
            self.slider.SetValue(idx)
            self._set_label(idx)
        else:
            self._set_text("Custom — optimizations set by hand (Advanced).")

    def _set_label(self, idx):
        self._set_text(SPEED_PRESETS[idx].desc)

    def _set_text(self, text):
        """Caption the slider. The label wraps itself to the section width
        (WrapLabel), but its line count can change, so refresh the scroll."""
        self._label.SetLabel(text)
        self._relayout()
