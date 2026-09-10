"""The design-target form of the simulate view (pages.simulate.SimulatePage).

PatternFreqSection owns the top of the form -- the "Design target" section: the
Application picker, the fields a hand-typed target is typed into (pattern
frequency, bandwidth, input impedance, return loss), the buttons that save such
a target under a name, and the spec / resonant-length lines below them.
Everything here describes the antenna being designed; how long to solve for is
the pass' own knob and lives with the button that spends it (sections.simtime,
built by the Run and Scan sections).

A pick either *is* the target or *is not*: a named application (a built-in
service, or one the user saved) carries its own frequency, band, impedance and
return loss, so its fields are not shown -- the picker already said what they
are, and the spec line under it spells them out. ``Custom…`` shows them,
because there they are the target rather than a description of one, and
hand-editing the frequency snaps the picker back to it.
``current_application`` reads the whole thing back as an :class:`Application`
— a catalog pick, or one synthesized from the Custom fields — so the scan and
the run score against the same target.

A typed target can be named and kept (**Save as…**, **Update**, **Delete**): it
joins the picker as its own entry, on this board and every other one, and is
picked back like a built-in. None of that is this section's: the buttons and
their flows are the shared ``gui.savedpick.SavedPicks`` (the same trio a
material row wears), over ``applications.catalog.Catalog``. What is this
section's is what those buttons act on -- the four fields -- and when they are
shown: ``saved.is_typing()``, which is the ``Custom…`` pick and a saved target
being updated, the two states where the fields *are* the target. That is also
the one state in which typing a frequency mustn't snap the pick away.

The picker is rebuilt from the catalog whenever the form is restored, so a
target saved on one page (or in another session) shows up on the others without
the window being reopened.

``contribute`` adds the frequency to a run's params (parsed strictly, naming the
field), mirroring AdvancedSection.contribute. The resonant-length hint reads the
substrate's permittivity from the Advanced section's material picker
(``page.advanced``) when one is chosen, so the two stay in step.
"""

import math

import wx

from ...applications.catalog import Catalog
from ...applications.db import Applications
from ...emkit.gui.savedpick import SavedPicks
from ...emkit.gui.sections.base import Section
from ...emkit.gui.theme import PAD, ROW
from ...emkit.gui.widgets import FIELD_W, to_float


class PatternFreqSection(Section):
    _TITLE = "Design target"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self._syncing_app = False  # guard against app<->freq feedback loop
        # Built-ins + the user's saved targets, behind one lookup. Every read
        # goes to the file, so a target saved on another page is offered here
        # as soon as this picker is rebuilt (saved.refresh_choices).
        self.catalog = Catalog()
        self._build(body)

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        """Application pick, the spec fields a typed target is typed into and
        the Save / Update / Delete buttons that make one a picker entry."""
        p = self.scroll
        box = self.box(self._TITLE)
        form = wx.FlexGridSizer(2, ROW, PAD)

        def row(label, ctrl):
            text = wx.StaticText(p, label=label)
            form.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(ctrl, 0)
            return text

        self.app = wx.Choice(p, size=(FIELD_W, -1), choices=self.catalog.choices())
        self.app.SetSelection(0)
        self.app.Bind(wx.EVT_CHOICE, self._on_app)
        row("Application", self.app)

        # The typed target: a named application answers all four itself (and
        # hides them -- see sync_custom_fields), 'Custom…' asks for them. The
        # band is the pattern frequency ± bandwidth/2, the impedance is what
        # the port is driven through and what each match is scored against
        # (runjob._port_resistance), and the return loss is both the depth the
        # match must reach and the depth the bandwidth is measured at
        # (design.measure.match_db); the 100 MHz / 50 Ω / 10 dB sitting in them
        # are the starting point of a target nobody has typed yet, replaced by
        # the pick's own numbers as soon as one is chosen (_on_app).
        self.freq = wx.TextCtrl(p, value="2.45", size=(FIELD_W, -1))
        self._freq_lbl = row("Pattern frequency (GHz)", self.freq)
        self.bandwidth = wx.TextCtrl(p, value="100", size=(FIELD_W, -1))
        self._bandwidth_lbl = row("Bandwidth (MHz)", self.bandwidth)
        self.impedance = wx.TextCtrl(p, value="50", size=(FIELD_W, -1))
        self._impedance_lbl = row("Input impedance (Ω)", self.impedance)
        self.return_loss = wx.TextCtrl(p, value="10", size=(FIELD_W, -1))
        self._return_loss_lbl = row("Return loss (dB)", self.return_loss)

        # The Save as… / Update / Delete trio (gui.savedpick), built on this
        # section's own button row so it is spaced like every other one.
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.saved = SavedPicks(
            p,
            self.app,
            self.catalog,
            read=self._typed,
            on_change=self.sync_custom_fields,
            button=lambda label, handler: self.row_button(buttons, label, handler),
            on_edit=self.freq.SetFocus,  # the fields just appeared, to be typed in
            log=self.log,
        )
        form.Add((0, 0))  # the buttons sit under the fields, not beside a label
        form.Add(buttons, 0)
        box.Add(form, 0, wx.EXPAND)

        # What a named pick answers instead of showing fields, and the
        # resonant-length hint off the frequency behind it; both wrap to width.
        self._spec = self.wrap_label(p, mute=True)
        box.Add(self._spec, 0, wx.EXPAND | wx.TOP, PAD)
        self._hint = self.wrap_label(p, mute=True)
        box.Add(self._hint, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)
        self.freq.Bind(wx.EVT_TEXT, self._on_freq_edit)
        self._on_app()  # seed the fields from the default pick

    # --- form sync ------------------------------------------------------------
    def _on_app(self, event=None):
        """A named application fills the typed fields from its own spec, so the
        target behind the pick is there in full if the user drops back to
        'Custom…' to bend it. 'Custom…' itself (an unknown label) leaves what is
        there for hand editing.

        Picking anything abandons an edit in flight: the fields are about to
        hold the new pick's numbers, so there is nothing left of the old one to
        write back."""
        self.saved.on_pick()
        app = self.saved.entry()
        if app is not None:
            self._syncing_app = True  # ChangeValue: no EVT_TEXT, no snap back
            self.freq.ChangeValue(f"{app.f0_ghz:g}")
            if app.bandwidth_mhz:
                self.bandwidth.ChangeValue(f"{app.bandwidth_mhz:g}")
            if app.impedance_ohm:
                self.impedance.ChangeValue(f"{app.impedance_ohm:g}")
            if app.return_loss_db:
                self.return_loss.ChangeValue(f"{app.return_loss_db:g}")
            self._syncing_app = False
        self.sync_custom_fields()
        self.update_hint()

    def _on_freq_edit(self, event=None):
        """Hand-editing the frequency snaps the picker to 'Custom…' -- unless
        the edit came from selecting an application, or the pick is a saved
        target open for editing, which is exactly the case where a typed
        frequency belongs to the pick instead of replacing it."""
        if not self._syncing_app and not self.saved.is_editing():
            self.app.SetStringSelection(Applications.CUSTOM)
            self.sync_custom_fields()
        self.update_hint()

    def sync_custom_fields(self):
        """Show what the current pick leaves to the user and say what it answers
        itself: the frequency / bandwidth / impedance / return-loss fields
        belong to the picks
        whose target *is* those fields -- 'Custom…', and a saved target being
        updated (``saved.is_typing``) -- while any other named application shows
        its spec as a line of text instead. The buttons beside them are the
        shared trio's own business (``sync_buttons``)."""
        typed = self.saved.is_typing()
        for w in (
            self._freq_lbl,
            self.freq,
            self._bandwidth_lbl,
            self.bandwidth,
            self._impedance_lbl,
            self.impedance,
            self._return_loss_lbl,
            self.return_loss,
        ):
            w.Show(typed)
        self.saved.sync_buttons()
        app = None if typed else self.saved.entry()
        self._spec.SetLabel("" if app is None else app.spec_line)
        self._relayout()

    def _typed(self):
        """The hand-typed target, as the catalog takes it -- what Save as… and
        Save changes write (gui.savedpick reads it through this)."""
        return {
            "f0_ghz": to_float(self.freq.GetValue(), None),
            "bandwidth_mhz": to_float(self.bandwidth.GetValue(), None),
            "impedance_ohm": to_float(self.impedance.GetValue(), None),
            "return_loss_db": to_float(self.return_loss.GetValue(), None),
        }

    # --- shared-form state (model / persistence) ------------------------------
    def snapshot(self):
        """This section's fields as a flat string dict (see gui.model /
        emkit.settings): the application pick, the frequency, and the Custom
        band / impedance / return loss."""
        return {
            "app": self.app.GetStringSelection(),
            "freq": self.freq.GetValue(),
            "bandwidth": self.bandwidth.GetValue(),
            "impedance": self.impedance.GetValue(),
            "return_loss": self.return_loss.GetValue(),
        }

    def restore(self, data):
        """Set the fields from a ``snapshot`` dict without firing edit events
        (ChangeValue/SetValue); the caller re-derives the dependent UI
        (sync_custom_fields / update_hint).

        The pick is restored by the shared trio (``restore_pick``), which
        rebuilds the picker first and drops a target that no longer exists to
        'Custom…' -- where the four fields restored below are the numbers that
        target was."""
        self.saved.restore_pick(data.get("app"))
        if "freq" in data:
            self.freq.ChangeValue(data["freq"])  # ChangeValue: no EVT_TEXT
        if "bandwidth" in data:
            self.bandwidth.ChangeValue(data["bandwidth"])
        if "impedance" in data:
            self.impedance.ChangeValue(data["impedance"])
        if "return_loss" in data:
            self.return_loss.ChangeValue(data["return_loss"])

    # --- values ---------------------------------------------------------------
    def freq_ghz(self, default=None):
        """The pattern frequency (GHz) as a float, or ``default`` when the field
        is blank/unparseable."""
        return to_float(self.freq.GetValue(), default)

    def current_application(self):
        """The design target the form describes, as an :class:`Application`: the
        picked one (a built-in service or one the user saved), or -- on
        'Custom…' -- one synthesized from the hand-typed pattern-frequency /
        bandwidth / impedance / return-loss fields (persisted with the rest of
        the form). A
        Custom target is thus carried and scored exactly like a catalog one, so
        the scan needs no special-casing."""
        app = self.saved.entry()
        return app if app is not None else Applications.custom(**self._typed())

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
        is the pass' own (sections.passknobs).

        Through this product's half of the shared translation
        (``runjob.form_params``), over the *page's* whole form rather than just
        this section's: the same call the command line makes on a settings
        file, and it has the whole file. A target may leave its impedance free
        and be answered by Advanced > Feed port instead
        (``runjob._port_resistance``), which is a field of another section --
        handed this section's snapshot alone, the window would refuse a form
        the command line runs.

        This section's own values still win over the page's copy of them, and a
        page that keeps no shared snapshot behaves exactly as it did."""
        from ... import runjob

        page_form = getattr(self.page, "shared_snapshot", dict)()
        runjob.form_params({**page_form, **self.snapshot()}, params)
