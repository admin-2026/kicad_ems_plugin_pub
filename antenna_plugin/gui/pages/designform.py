"""DesignFormPage: the base of the pages that carry the shared design form.

The simulate view and every designer show the same antenna inputs — the
Pattern-frequency section, the Speed / accuracy slider, the Advanced pane and
the marker section's feed-width / Feed-layer / Marker-layer picks — as separate
widgets over one datastore (gui.model.FormModel). Only *where the marker
section lives* differs: the simulate view builds it as its Feed-marker section,
a designer as its Area section (both are sections.FeedMarkerSection, so both
answer the same methods) — and because its picks are shared, the feed marker
and the area markers all sit on one Marker layer.

The pass knobs — the simulation time and Auto ground/source — are shared the
same way, though they aren't a section: the simulate view builds them into its
Run section and a designer into its Scan section, beside the button that spends
them, and the model carries the one value behind each (``pass_knobs``,
sections.passknobs.PassKnobs).

So the sync itself — which sections go into the model, which come back out, and
what has to be re-derived afterwards so the form agrees with itself — is one
implementation here rather than a copy per page. A subclass supplies the three
sections it built (``form``, ``speed``, ``advanced``) and points
``feed_section`` / ``pass_knobs`` at whichever of its sections owns the feed
picks and the knobs of the pass.

Subclass contract (on top of base.BookPage's):
  * build sections named ``form`` (PatternFreqSection), ``speed``
    (SpeedSection) and ``advanced`` (AdvancedSection);
  * override ``feed_section`` to return the section carrying the feed-width
    slider, the Feed-layer picker and this page's marker (the Marker-layer
    picker is built into the Advanced pane, and its pick is shared too);
  * override ``pass_knobs`` to return the pass knobs its solver section built;
  * call ``rederive_form()`` after restoring those sections from anywhere else
    (a page's own settings restore does exactly what the model's does).
"""

from ...emkit.gui.pages.base import BookPage


class DesignFormPage(BookPage):
    # --- the sections this base drives ----------------------------------------
    @property
    def feed_section(self):
        """The section owning the feed-width slider and Feed-layer picker (the
        simulate view's Feed-marker section, a designer's Area section)."""
        raise NotImplementedError

    @property
    def pass_knobs(self):
        """The knobs of the pass (sections.passknobs.PassKnobs) this page's
        solver section built: the simulate view's Run section, a designer's
        Scan section."""
        raise NotImplementedError

    # --- shared design form (gui.model, one model per page) -------------------
    def shared_snapshot(self):
        """The shared Pattern-frequency + Advanced fields, the marker section's
        picks (feed width, Feed layer, Marker layer) and the pass knobs as a
        flat dict."""
        return {
            **self.form.snapshot(),
            **self.advanced.snapshot(),
            **self.feed_section.snapshot(),
            **self.pass_knobs.snapshot(),
        }

    def shared_restore(self, data):
        """Set those fields from the model, then re-derive the dependent UI
        without firing edit events."""
        self.form.restore(data)
        self.advanced.restore(data)
        self.feed_section.restore(data)
        self.pass_knobs.restore(data)
        self.rederive_form()

    def rederive_form(self):
        """Bring everything the restored fields feed back in step, the way the
        manual edit handlers would: the Custom band/impedance fields, the speed
        slider and its caption, the pass knobs' own fields (the
        simulation-time ns box), the resonant-length hint and the feed readouts
        (labels only — nothing on the board is reshaped)."""
        self.form.sync_custom_fields()
        self.speed.on_override()
        self.pass_knobs.sync()
        self.form.update_hint()
        self.feed_section.feed_sync_labels()

    # --- feed picks the wizard sections read through their host ---------------
    def feed_layer_name(self):
        return self.feed_section.feed_layer_name()

    def marker_width_mm(self):
        return self.feed_section.width_mm()

    def marker_layer_n(self):
        """The Marker-layer pick — 1-based User.N — off this page's own picker.
        One pick behind them all: it rides the shared model like the feed picks,
        so the feed marker and every designer's area marker are placed on the
        same User layer."""
        return self.feed_section.marker_layer_n()
