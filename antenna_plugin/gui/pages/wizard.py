"""DesignWizardPage: one antenna designer, a view in the shell.

ONE page class serves every antenna topology: it is constructed with a design
(design.registry — the L-shaped monopole, the meandered inverted-F, whatever
comes next) and every section reads its knobs, labels and geometry off that
object. Adding a designer is adding a design module; nothing here changes.

A guided flow on top of its own copy of the design form -- the numbers below are
the ones on the page, and this page is where they are assigned (the sections
carry no number of their own, see the ``step=`` arguments):

    1 · Target    the target frequency / application — its own section, a second
                  view onto the shared datastore the simulate view uses
                  (gui.model.FormModel), so the two stay in step
    2 · Area      the user drops the area-marker footprint on the board — a
                  rectangle (where the antenna may live) with a feed triangle
                  on one edge (where the feed enters, pointing inward). The
                  sliders here reshape it live; KiCad's own tools move it
                  anywhere and rotate it to feed from another side
                  (sections.AreaSection + area_marker.py)
    3 · Speed     the Speed / accuracy slider (drives the Advanced toggles)
    4 · Scan      radio buttons pick which of the design's geometry parameters
                  is swept between its min/max; the wizard simulates each
                  candidate and scores S11 at the target frequency
                  (sections.ScanSection), keeping the best result — or, with
                  Generate grids, meshes every candidate without solving any,
                  to check the meshes the sweep produces first. How long each
                  candidate is solved for, and whether the solver finds its own
                  ground/source, are the knobs beside those buttons, shared
                  with the simulate view's run (sections.passknobs)
    5 · Results   the scan's combined report / grid views, every candidate
                  overlaid (sections.ScanResultsSection); opened by the scan
                  when it finishes and re-openable any time after
    6 · Footprint a chosen geometry becomes a .kicad_mod in the project's
                  wizard folder and is placed on the board at its feed point,
                  ready to wire to the feed line. Its chooser offers the scan's
                  ranked candidates *and* one row for the shape the Scan
                  section describes right now, so a geometry somebody already
                  wants can be placed unsimulated. The scan need not be this
                  session's: a finished one is saved in its folder
                  (design.scan_store) and read back when this page is shown
                  (sections.FootprintSection)
    7 · Advanced  mesh / ports / materials — the same knobs the simulate view
                  carries, grouped by function, kept in step through the shared
                  model; the Marker-layer picker among them, the User layer this
                  page's area marker and the simulate view's feed marker alike
                  are drawn on

The Design-target / Speed / Advanced sections are the simulate view's
sections' second view, as are the feed-width / Feed-layer / Marker-layer picks
(this page's live in its area section) and the pass knobs (this page's in its
scan section, the simulate view's in its Run box): the shell syncs them
through the model on page switch (gui.shell). That sync is
designform.DesignFormPage's — shared with the simulate view, since only *where*
those picks live differs — so this page just names the sections carrying them.
The Marker layer travels with them, so the area marker goes on the layer the
feed marker does; its Advanced pane builds a picker of its own for it. The only
thing still borrowed from the simulate page is the result-viewer windows. The
wizard sections read all of this through host.WizardHost, which wraps this page.

This is a page in AntennaShell's book (pages.base.BookPage), not its own window:
the shell is a frame (never modal, and free to sit behind the editor), so the
user can keep editing the PCB — moving the area marker above all — while a
wizard is open.
Board-touching steps run on the wx main thread; the solver loop runs in a worker
via wizard_scan.
"""

import wx

from ...emkit.gui.sections import (
    AdvancedSection,
    IntroSection,
    LogSection,
    SpeedSection,
)
from ..sections import (
    AreaBanner,
    AreaSection,
    FootprintSection,
    PatternFreqSection,
    ScanResultsSection,
    ScanSection,
)
from .designform import DesignFormPage
from .host import WizardHost

# The Ground-layer pick's name: the form's own key inside the Area section
# (sections/area.py), and the last part of its key in the settings file, where
# it lives in this designer's namespace (``settings_snapshot``).
_GROUND = "ground_layer"


class DesignWizardPage(DesignFormPage):
    def __init__(self, parent, simulate, design):
        super().__init__(parent)  # sets up self.scroll / log
        # The antenna this page designs. Every section below reads its
        # parameters, labels and geometry through this one object. It also
        # names this page's tab: one page class, one tab per design.
        self.design = design
        self.tab_icon = design.icon
        self.tab_label = design.short_name
        self.tab_hint = f"{design.name} designer"
        # The wizard shares the marker picks with the simulate view (through
        # the model) and borrows its result viewers; the sections read
        # everything through this facade rather than reaching into a page's
        # widgets (see host.WizardHost).
        self.simulate = simulate
        self.host = WizardHost(self)

        # The sections in flow order, each carrying its step number: this page
        # is a guided sequence, so its sections are numbered 1..7 down the form
        # (theme.numbered). The numbers live here and not in the sections
        # themselves -- the simulate view builds several of the same sections
        # and numbers none of them.
        body = wx.BoxSizer(wx.VERTICAL)
        self.intro = IntroSection(self, body, design.title, subtitle=design.summary)
        self.form = PatternFreqSection(self, body, step=1)
        self.area = AreaSection(self, body, step=2)
        self.speed = SpeedSection(self, body, step=3)
        self.scan = ScanSection(self, body, step=4)
        # The scan's combined views, between the scan that writes them and the
        # footprint step they justify; the scan section only tells it when a
        # fresh set landed (results.show_all).
        self.results = ScanResultsSection(self, body, step=5)
        self.footprint = FootprintSection(self, body, step=6)
        # Advanced is last (mesh / ports / materials); it reads form + speed, so
        # they are built first. It also builds the Marker-layer picker into its
        # Markers box -- the widget belongs to the area section, which is built
        # above (the pick itself is shared with the simulate view's feed
        # marker).
        self.advanced = AdvancedSection(self, body, step=7)
        self.speed.set_optimizations(self.advanced)
        self.speed.apply_default()
        # The run log ends the scrolled body; point log_ctrl at it before the
        # sections read the board (on_shown -> area.refresh) and can log.
        self.log_section = LogSection(self, body)
        self.log_ctrl = self.log_section.ctrl
        # The advisory area-marker banner isn't part of the scrolled body: like
        # the simulate view's pre-flight banner its panel docks below the
        # scroll, so it stays visible however far the form is scrolled and its
        # warnings coming and going never move the form under the pointer.
        self.banner = AreaBanner(self)
        # Mount the sections on the scroll and bind wheel scrolling across the
        # whole form (base class), so a tall wizard scrolls from anywhere.
        self.mount(body, footer=self.banner.panel)
        self.load_settings()  # restore this design's scan rows, if any

    def on_shown(self):
        """The shell switched to this page (after writing the shared model):
        seed the scan's sweep bounds from the now-current target frequency,
        take back the last scan this board saved (so its candidates can be
        placed without re-running it) and read the board. Idempotent —
        seed_from_freq leaves bounds already set, load_saved stands off live
        results and area.refresh just re-reads the marker."""
        self.scan.seed_from_freq()
        self.scan.load_saved()
        self.area.refresh()
        self.banner.refresh()

    def on_activate(self, visible):
        """The window regained the focus -- which is exactly when the user
        comes back from the PCB editor, where the area marker is dragged into
        shape. So re-read it (``area.sync_from_board``: the feed arrow is
        repinned onto the rectangle as they left the two, the status line and
        the Place/Show button re-derived, the drawn candidate redrawn against
        the new area) and re-check the advisory banner over it. Only while this
        designer is the page on screen and no scan of its own is mid-flight (a
        scan owns the banner).

        This is the whole board→plugin direction: a drag is KiCad's own
        interaction, with KiCad's own undo, and nothing here polls for it."""
        if visible and not self.scan.running:
            self.area.sync_from_board()
            self.banner.refresh()

    def refresh_area_checks(self):
        """Re-run the advisory area-marker checks (the banner). Called after the
        area marker is placed or reshaped; the shell also refreshes it on focus.
        Guarded so a section built before the banner can call it freely."""
        if getattr(self, "banner", None) is not None:
            self.banner.refresh()

    def shutdown(self):
        """Stop a scan in flight (never leave the solver detached). The viewer
        windows are the simulate page's; it tears them down."""
        self.scan.shutdown()

    # --- persisted form (emkit.settings) -----------------------------------
    # This page's share of the per-project settings file: its scan rows -- the
    # sweep bounds and fixed values are hand-tuned to one board's area, so they
    # come back on the next launch (the section namespaces its keys by design,
    # so the designers don't collide) -- plus the Ground-layer pick. Everything
    # else the page shows is either shared (the simulate page writes those keys,
    # the model having carried them over -- the Marker-layer pick included) or
    # read off the board.
    def settings_snapshot(self):
        """The scan rows, and the Ground-layer pick for a design that has one.

        That pick rides the shared form like the feed picks do, but the page
        that *persists* the shared form is the simulate view, whose marker
        section has no such picker -- so a key nobody claims here is dropped on
        the way to the file and the pick comes back as the default next launch.
        It is saved in this designer's own namespace
        (``ScanSection.settings_key`` -- ``scan.<design>.ground_layer``, beside
        its rows) rather than as a form-wide key: the layer a design radiates
        against is part of that design's setup, so a second one that wanted a
        plane could name a different layer without overwriting this."""
        data = self.scan.snapshot()
        ground = self.area.ground_layer_name()
        if ground:
            data[self.scan.settings_key(_GROUND)] = ground
        return data

    def settings_restore(self, data):
        """The rows, then the area picks -- the Ground layer among them, read
        out of this design's namespace and handed to the section under the
        form's own name (the section ignores it when this design has no
        picker). The feed readouts are re-derived after, as they are after any
        restore of that section; nothing on the board is reshaped."""
        self.scan.restore(data)
        ground = data.get(self.scan.settings_key(_GROUND))
        self.area.restore(dict(data, ground_layer=ground) if ground else data)
        self.area.feed_sync_labels()

    @property
    def viewers(self):
        """The embedded HTML viewer windows this page's scan views and guides
        open in: the simulate page's hub (gui.viewers), borrowed so a scan's
        views and a run's land in the same windows. Every page exposes
        ``viewers``, so a section never has to know which page owns it."""
        return self.simulate.viewers

    # --- shared design form (gui.model, one view per page) --------------------
    # The snapshot/restore pair itself is designform.DesignFormPage's; this page
    # only names the sections its feed picks live in (the Area box, where the
    # feed-width slider also sizes the marker's feed triangle) and its pass
    # knobs (the Scan box, beside the buttons that spend them).
    @property
    def feed_section(self):
        return self.area

    def ground_layer_name(self):
        """The Ground-layer pick (copper suffix) for a design that radiates
        against a plane, "" for one that doesn't (sections/area.py). The
        banner asks the page, as it does for the feed layer."""
        return self.area.ground_layer_name()

    @property
    def pass_knobs(self):
        """The pass knobs (simulation time, Auto ground/source): a designer's are
        built into its Scan section, beside the buttons that spend them (the
        simulate view's into its Run section)."""
        return self.scan.knobs
