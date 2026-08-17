"""Composable form sections for the shell's book pages.

Each section is a self-contained class that builds its own group of controls
into a page's scrolled body sizer and owns the widgets and event handlers for
that group. The simulate view (pages.simulate.SimulatePage) and the L-shape
designers (pages.wizard.DesignWizardPage) all compose their forms from these, instead of
building the widgets inline, so a section can be read, tested and reused on its
own.

All form sections share the ``base.Section`` base (the page handle, the window
their widgets parent on, the shared section frame -- a heading over a rule,
gui.theme -- the relayout / log shortcuts and the wrapped status line). A
section's number in a guided flow ("2 · Scan") is the *page's*: it passes
``step=`` when it builds one, and the pages that are forms rather than
sequences pass nothing.

Modules:
    base         — Section, the shared base for the form sections
    intro        — IntroSection, the page title (+ its one-line summary)
    solver       — SolverSection, the solver-driver base shared by run + scan
    pattern_freq — PatternFreqSection, the application / frequency target form
    passknobs    — PassKnobs, the knobs of the pass itself (simulation time,
                   Auto ground/source) that the run and the scan sections each
                   build beside the button that spends them
    speed        — SpeedSection, the Speed / accuracy slider
    marker       — FeedMarkerSection, the Feed marker generator box
    advanced     — AdvancedSection, the collapsible Advanced pane
    banner       — BannerSection base + PreflightBanner, the simulate view's
                   pre-flight banner docked under the form
    area_banner  — AreaBanner, the wizard's advisory area-marker banner
    run          — RunSection, the Run button row + the run flow
    results      — the Results box: ResultsSection base + RunResultsSection
                   (a run's grid / report) and ScanResultsSection (the scan's
                   combined views)
    area         — AreaSection, a wizard's antenna-area + feed marker
    scan         — ScanSection, a wizard's parameter scan: one row per
                   parameter of the page's design, whatever the topology
    footprint    — FootprintSection, a wizard's footprint placer
    guides       — GuidesSection, the About page's bundled documentation
    links        — LinksSection, the About page's project links
    versions     — VersionsSection, the About page's version table
    log          — LogSection, the terminal run log at the bottom of a page
"""

from .advanced import AdvancedSection
from .area import AreaSection
from .area_banner import AreaBanner
from .banner import PreflightBanner
from .footprint import FootprintSection
from .guides import GuidesSection
from .intro import IntroSection
from .links import LinksSection
from .log import LogSection
from .marker import FeedMarkerSection
from .pattern_freq import PatternFreqSection
from .results import RunResultsSection, ScanResultsSection
from .run import RunSection
from .scan import ScanSection
from .speed import SpeedSection
from .versions import VersionsSection

__all__ = [
    "AdvancedSection",
    "AreaBanner",
    "AreaSection",
    "FeedMarkerSection",
    "FootprintSection",
    "GuidesSection",
    "IntroSection",
    "LinksSection",
    "LogSection",
    "PatternFreqSection",
    "PreflightBanner",
    "RunResultsSection",
    "RunSection",
    "ScanResultsSection",
    "ScanSection",
    "SpeedSection",
    "VersionsSection",
]
