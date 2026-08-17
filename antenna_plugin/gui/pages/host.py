"""WizardHost: the wizard sections' facade onto their own page (and, for the
few things it borrows, the simulate view).

The wizard sections (area / scan / footprint) need a handful of inputs — the
target frequency, the design application, the run params, the feed/marker layer
picks — but nothing about *how* the page stores them.
WizardHost is the one place that knows: it wraps the
:class:`~antenna_plugin.gui.pages.wizard.DesignWizardPage` and exposes just those.

Every input comes from the wizard's *own* sections (a second view onto the
shared FormModel), so the wizard stays in step with a later verification run
without duplicating state: the Pattern-frequency / Advanced fields, the
feed-width / Feed-layer picks, and the User layer the markers are drawn on
(its area section owns all of those — the marker layer through the picker its
Advanced pane builds, one shared pick with the simulate view's feed marker, see
DesignFormPage.marker_layer_n).

The viewer windows are borrowed too, but not through here: both pages expose
``viewers`` (the wizard's delegating to the simulate page's hub, gui.viewers),
so a section that shows a page reaches its own page for it, as the banners do.

This is the seam a future settings-model refactor plugs into: swap what backs
these methods and the sections don't change. It is also what a second wizard
would reuse.
"""

from ..sections.run import collect_run_params


class WizardHost:
    def __init__(self, page):
        self._page = page

    # --- design inputs --------------------------------------------------------
    def target_freq_ghz(self, default=None):
        """The wizard's target frequency (GHz) as a float, or ``default`` when
        the field is blank/unparseable."""
        return self._page.form.freq_ghz(default)

    def feed_layer_name(self):
        """The Feed layer pick (copper layer suffix); '' when the picker has no
        selection -- callers apply their own fallback."""
        return self._page.feed_layer_name()

    def marker_width_mm(self):
        """The Feed marker width (mm) -- the area marker's feed-triangle width."""
        return self._page.marker_width_mm()

    def marker_layer_n(self):
        """The Marker-layer pick as 1-based User.N (both markers share it)."""
        return self._page.marker_layer_n()

    def current_application(self):
        """The design target the form describes (catalog pick or synthesized
        Custom), for scoring scan candidates."""
        return self._page.form.current_application()

    def run_params(self, run_dir):
        """The run config params (frequency, speed/quality toggles, materials,
        advanced, and the Scan section's pass knobs) built from the wizard's own
        sections, for ``run_dir`` (shared collect_run_params)."""
        return collect_run_params(self._page, run_dir)
