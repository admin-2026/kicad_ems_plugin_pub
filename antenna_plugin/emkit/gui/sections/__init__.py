"""The form sections that are not about one kind of simulation.

Each section is a self-contained class that builds its own group of controls
into a page's scrolled body sizer and owns the widgets and event handlers for
that group, over the ``base.Section`` base (the page handle, the window their
widgets parent on, the shared section frame -- a heading over a rule, see
gui.theme -- the relayout / log shortcuts and the wrapped status line). A
section's number in a guided flow ("2 · Scan") is the *page's*: it passes
``step=`` when it builds one, and the pages that are forms rather than
sequences pass nothing.

A plugin's own sections live in its own ``gui.sections`` package and are built
on the same base; a page imports each from wherever it comes from, which is
what keeps the seam visible at the point of use.

Modules:
    base     — Section, the shared base for every form section
    intro    — IntroSection, the page title (+ its one-line summary)
    solver   — SolverSection, the solver-driver base a run or a sweep is built
               on: the button, the live process, the log and the stop
    run      — RunSection, one solve of the open board: the buttons, the two
               phases, the worker and the archiving, with three methods a flow
               fills in
    passknobs — PassKnobs, the knobs of the pass itself (simulation time, Auto
               ground/source), built by the section that starts one
    results  — the Results box: ResultsSection base + RunResultsSection, a
               run's newest grid / report
    speed    — SpeedSection, the Speed / accuracy slider
    marker   — FeedMarkerSection, the feed/port marker generator box
    advanced — AdvancedSection, the collapsible Advanced pane
    banner   — BannerSection base + PreflightBanner, the pre-flight banner
               docked under a form
    guides   — GuidesSection, the About page's bundled documentation
    cli      — CliSection, the About page's shortcut to the command line
    docker   — DockerSection, the About page's container box: the tick, the
               image, and what stands in the way of one
    links    — LinksSection, the About page's project links
    feedback — FeedbackSection, the About page's ask for bug reports and
               feature requests
    versions — VersionsSection, the About page's version table
    log      — LogSection, the terminal run log at the bottom of a page
"""

from .advanced import AdvancedSection
from .banner import PreflightBanner
from .cli import CliSection
from .docker import DockerSection
from .feedback import FeedbackSection
from .guides import GuidesSection
from .intro import IntroSection
from .links import LinksSection
from .log import LogSection
from .marker import FeedMarkerSection
from .passknobs import PassKnobs
from .results import RunResultsSection
from .run import RunSection
from .speed import SpeedSection
from .versions import VersionsSection

__all__ = [
    "AdvancedSection",
    "CliSection",
    "DockerSection",
    "FeedbackSection",
    "FeedMarkerSection",
    "GuidesSection",
    "IntroSection",
    "LinksSection",
    "LogSection",
    "PassKnobs",
    "PreflightBanner",
    "RunResultsSection",
    "RunSection",
    "SpeedSection",
    "VersionsSection",
]
