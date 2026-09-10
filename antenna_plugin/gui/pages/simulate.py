"""SimulatePage: the settings/run view of the shell.

A pages.base.BookPage composed entirely of form sections (gui.sections): the
target form, the Feed marker box, the Speed/accuracy slider, the Run section
(what starts and ends a run), the Results box (what it left behind) and the
Advanced pane all live in the scroll, followed by the run log, with the
pre-flight banner docked under it. The page owns no widgets of its own — it
just wires the sections together, contributes its share of the per-project
settings file
(``settings_snapshot`` / ``settings_restore``; the shell writes it) and stops the
run on close; the shell owns the window and the pre-flight refresh on focus.

The one non-widget service it owns is the viewer hub (gui.viewers.ViewerHub):
the embedded HTML windows its results and guides open in, which the wizard page
borrows (both pages expose ``viewers``) so a scan's views and a run's land in
the same windows.

The Design-target, Speed and Advanced sections, the Feed-marker box's picks
(feed width, Feed layer, Marker layer) and the Run box's pass knobs (simulation
time, Auto ground/source) are two views onto one datastore (gui.model.FormModel):
the designers build their own copies (theirs live in the area and scan sections)
and the shell syncs them
through the model on page switch. That sync is designform.DesignFormPage's,
shared with the designers — this page only says which of its sections owns those
picks. The Marker layer is one of them, so
this page's feed marker and a designer's area marker are drawn on the same User
layer, whichever Advanced pane the user picks it in.
"""

import wx

from ...emkit.gui.sections import (
    AdvancedSection,
    FeedMarkerSection,
    IntroSection,
    LogSection,
    PreflightBanner,
    RunResultsSection,
    SpeedSection,
)
from ...emkit.gui.viewers import ViewerHub
from ..sections import PatternFreqSection, RunSection
from .designform import DesignFormPage


class SimulatePage(DesignFormPage):
    tab_icon = "play_icon.png"
    tab_label = "Simulate"
    tab_hint = "Simulate the board as drawn"

    def __init__(self, parent):
        super().__init__(parent)  # sets up self.scroll / log

        # The embedded HTML windows this page's results and guides open in,
        # shared with the wizard page. Built before the sections that show
        # pages in it; it logs through this page's log, which the LogSection
        # below points at before anything can write to it.
        self.viewers = ViewerHub(self, self.log)

        body = wx.BoxSizer(wx.VERTICAL)
        # Unlike a designer's sections these carry no step numbers: this view is
        # a form to be filled in in any order, not a sequence to be walked.
        self.intro = IntroSection(
            self,
            body,
            "Simulate an Antenna",
            subtitle=(
                "Solve the board as it is drawn: mark the feed, set the target, "
                "and run the bundled FDTD solver over it."
            ),
        )
        self.form = PatternFreqSection(self, body)
        self.feed = FeedMarkerSection(self, body)
        self.speed = SpeedSection(self, body)
        self.run = RunSection(self, body)
        # What the runs left behind (grid / report), re-openable without a
        # re-run; the run section hands its fresh pages to this one too.
        self.results = RunResultsSection(self, body)
        # Advanced sits below Run; it builds the Marker-layer picker (owned by
        # the Feed section) into its pane, so feed is built first.
        self.advanced = AdvancedSection(self, body)
        # Wire the speed slider to the optimization toggles (Advanced) and sync
        # the toggles to the default preset, now that both exist.
        self.speed.set_optimizations(self.advanced)
        self.speed.apply_default()
        # The run log ends the scrolled body; point log_ctrl at it before
        # anything logs (settings load, pre-flight refresh below).
        self.log_section = LogSection(self, body)
        self.log_ctrl = self.log_section.ctrl
        # The pre-flight banner isn't part of the scrolled body: its panel docks
        # below the scroll, so it stays visible however far the settings are
        # scrolled and showing/clearing it never moves the form above it
        # (BookPage.mount footer=).
        self.banner = PreflightBanner(self)
        self.mount(body, footer=self.banner.panel)

        self.load_settings()  # restore the last-used form, if any
        self.banner.refresh()

    def on_activate(self, visible):
        """The window regained the focus: re-check pre-flight, whether or not
        this page is the visible one (the usual fix -- Board Setup > Physical
        Stackup -- happens in KiCad, and the user then comes back). A run in
        flight owns the banner, so it is left alone.

        The feed marker is re-read for the same reason: it can be moved or
        deleted in the editor while this window is open, and both its status
        line and its button (Generate a marker, or show the one already there)
        are a reading of the board that would otherwise stay as it was."""
        if not self.run.running:
            self.banner.refresh()
        self.feed.refresh_status()

    def shutdown(self):
        """Stop a run in flight (the run section owns the solver process) and
        tear down the embedded viewer windows -- including the ones the wizard
        borrowed, so nothing outlives the shell."""
        self.run.shutdown()
        self.viewers.close_all()

    # --- shared design form (gui.model, one view per page) --------------------
    # The snapshot/restore pair itself is designform.DesignFormPage's; this page
    # only names the sections its feed picks and its pass knobs live in (the
    # Feed-marker box and the Run box).
    @property
    def feed_section(self):
        return self.feed

    @property
    def pass_knobs(self):
        """The pass knobs (simulation time, Auto ground/source): this view's are
        built into its Run section, beside the button that spends them (a
        designer's into its Scan section)."""
        return self.run.knobs

    # --- persisted form (emkit.settings) -----------------------------------
    # This page's share of the settings file is exactly what the shared model
    # carries (Design target, Advanced, the marker section's feed-width /
    # Feed-layer / Marker-layer picks and the pass knobs), so it is that
    # same snapshot/restore pair. It is written from here for the whole window
    # -- a designer edits the same values through its own widgets, and the shell
    # pushes the model onto this page before saving. The saving itself is the
    # shell's (one file for every page) -- BookPage.save_settings.
    def settings_snapshot(self):
        """The page's form as a flat string dict (DesignFormPage)."""
        return self.shared_snapshot()

    def settings_restore(self, data):
        """Set those fields from a ``settings_snapshot`` dict and re-derive the
        UI they feed (DesignFormPage)."""
        self.shared_restore(data)

    # _on_pane_changed / _relayout_scroll come from pages.base.BookPage, which
    # re-wraps the full-width prose labels (WrapLabel) on resize.
