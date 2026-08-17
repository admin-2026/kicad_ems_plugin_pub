"""The design-target form of the simulate view (pages.simulate.SimulatePage).

PatternFreqSection owns the top of the form -- the "Design target" section: the
Application picker, the pattern frequency and the Custom-only bandwidth /
input-impedance fields, plus the one-line resonant-length hint below them.
Everything here describes the antenna being designed; how long to solve for is
the pass' own knob and lives with the button that spends it (sections.simtime,
built by the Run and Scan sections).

The picker and the frequency field snap each other: choosing a named
application fills its pattern frequency, and hand-editing the frequency snaps
the picker to "Custom…" (which then reveals the band / impedance fields a named
application already carries). ``current_application`` reads the whole thing back
as an :class:`Application` — a catalog pick, or one synthesized from the Custom
fields — so the scan and the run score against the same target.

``contribute`` adds the frequency to a run's params (parsed strictly, naming the
field), mirroring AdvancedSection.contribute. The resonant-length hint reads the
substrate's permittivity from the Advanced section's material picker
(``page.advanced``) when one is chosen, so the two stay in step.
"""

import math

import wx

from ...applications.db import Applications
from ..theme import PAD, ROW
from ..widgets import FIELD_W, set_choice, to_float
from .base import Section


class PatternFreqSection(Section):
    _TITLE = "Design target"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self._syncing_app = False  # guard against app<->freq feedback loop
        self._build(body)

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        """Application pick, pattern frequency and the Custom-only spec."""
        p = self.scroll
        box = self.box(self._TITLE)
        form = wx.FlexGridSizer(2, ROW, PAD)

        def row(label, ctrl):
            text = wx.StaticText(p, label=label)
            form.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(ctrl, 0)
            return text

        self.app = wx.Choice(p, size=(FIELD_W, -1), choices=Applications.choices())
        self.app.SetSelection(0)
        self.app.Bind(wx.EVT_CHOICE, self._on_app)
        row("Application", self.app)

        self.freq = wx.TextCtrl(p, value="2.45", size=(FIELD_W, -1))
        row("Pattern frequency (GHz)", self.freq)

        # Custom-only spec fields: a named application carries its own band and
        # input impedance, but 'Custom…' has none, so these let the user type
        # the bandwidth (band = pattern frequency ± bandwidth/2) and impedance
        # the scan result table scores each candidate against. Shown only while
        # the picker is on Custom (see sync_custom_fields); defaults 100 MHz /
        # 50 Ω (the feed port resistance).
        self.bandwidth = wx.TextCtrl(p, value="100", size=(FIELD_W, -1))
        self._bandwidth_lbl = row("Bandwidth (MHz)", self.bandwidth)
        self.impedance = wx.TextCtrl(p, value="50", size=(FIELD_W, -1))
        self._impedance_lbl = row("Input impedance (Ω)", self.impedance)
        box.Add(form, 0, wx.EXPAND)

        # Resonant-length hint, live off the frequency field; wraps to width.
        self._hint = self.wrap_label(p, mute=True)
        box.Add(self._hint, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)
        self.freq.Bind(wx.EVT_TEXT, self._on_freq_edit)
        self._on_app()  # seed the frequency from the default pick

    # --- form sync ------------------------------------------------------------
    def _on_app(self, event=None):
        """A high-level application pick fills the frequency field from its
        pattern frequency. 'Custom…' (an unknown label) leaves whatever is
        there for hand editing."""
        app = Applications.get(self.app.GetStringSelection())
        if app is not None:
            self._syncing_app = True
            self.freq.ChangeValue(f"{app.f0_ghz:g}")  # ChangeValue: no EVT_TEXT
            self._syncing_app = False
        self.sync_custom_fields()
        self.update_hint()

    def _on_freq_edit(self, event=None):
        """Hand-editing the frequency snaps the picker to 'Custom…' (unless the
        edit came from selecting an application)."""
        if not self._syncing_app:
            self.app.SetStringSelection(Applications.CUSTOM)
            self.sync_custom_fields()
        self.update_hint()

    def sync_custom_fields(self):
        """Reveal the bandwidth / impedance fields only when the picker is on
        'Custom…'; a named application supplies its own band and impedance, so
        for it they stay hidden."""
        custom = self.app.GetStringSelection() == Applications.CUSTOM
        for w in (
            self._bandwidth_lbl,
            self.bandwidth,
            self._impedance_lbl,
            self.impedance,
        ):
            w.Show(custom)
        self._relayout()

    # --- shared-form state (model / persistence) ------------------------------
    def snapshot(self):
        """This section's fields as a flat string dict (see gui.model /
        settings): the application pick, frequency and Custom band/impedance."""
        return {
            "app": self.app.GetStringSelection(),
            "freq": self.freq.GetValue(),
            "bandwidth": self.bandwidth.GetValue(),
            "impedance": self.impedance.GetValue(),
        }

    def restore(self, data):
        """Set the fields from a ``snapshot`` dict without firing edit events
        (ChangeValue/SetValue); the caller re-derives the dependent UI
        (sync_custom_fields / update_hint)."""
        set_choice(self.app, data.get("app"))
        if "freq" in data:
            self.freq.ChangeValue(data["freq"])  # ChangeValue: no EVT_TEXT
        if "bandwidth" in data:
            self.bandwidth.ChangeValue(data["bandwidth"])
        if "impedance" in data:
            self.impedance.ChangeValue(data["impedance"])

    # --- values ---------------------------------------------------------------
    def freq_ghz(self, default=None):
        """The pattern frequency (GHz) as a float, or ``default`` when the field
        is blank/unparseable."""
        return to_float(self.freq.GetValue(), default)

    def current_application(self):
        """The design target the form describes, as an :class:`Application`: the
        catalog pick, or -- on 'Custom…' -- one synthesized from the hand-typed
        pattern-frequency / bandwidth / impedance fields (persisted with the
        rest of the form). A Custom target is thus carried and scored exactly
        like a catalog one, so the scan needs no special-casing."""
        app = Applications.get(self.app.GetStringSelection())
        if app is not None:
            return app
        return Applications.custom(
            f0_ghz=to_float(self.freq.GetValue(), None),
            bandwidth_mhz=to_float(self.bandwidth.GetValue(), None),
            impedance_ohm=to_float(self.impedance.GetValue(), None),
        )

    def update_hint(self, event=None):
        """Refresh the resonant-length hint from the frequency field, using the
        Advanced section's substrate permittivity when a material is picked
        (thin-microstrip FR-4 otherwise)."""
        f = self.freq_ghz(0.0) * 1e9
        if f <= 0:
            self._hint.SetLabel("")
            self._relayout()
            return
        quarter = 299792458.0 / f * 1000 / 4  # mm
        eps_r, name = 4.4, "FR-4"  # thin microstrip default
        adv = getattr(self.page, "advanced", None)  # built after the form
        mats = adv.materials if adv is not None else None
        sub = mats.substrate_material() if mats is not None else None
        if sub is not None:
            eps_r, name = sub.eps, sub.name
        e_eff = (eps_r + 1) / 2
        self._hint.SetLabel(
            f"λ/4 ≈ {quarter:.1f} mm free-space · "
            f"{quarter / math.sqrt(e_eff):.1f} mm on {name}"
        )
        self._relayout()

    # --- run parameters -------------------------------------------------------
    def contribute(self, params):
        """Add the pattern frequency to a run's params, parsed strictly and
        naming the field -- never silently substituted. The run length beside it
        is the pass' own (sections.simtime.SimTimeRow.contribute)."""
        freq = self.freq_ghz(None)
        if freq is None or freq <= 0:
            raise RuntimeError(
                f"Pattern frequency: '{self.freq.GetValue()}' is not a "
                "positive number (GHz)"
            )
        params["fpattern_ghz"] = freq
