"""This plugin's own form sections: the ones that know what an antenna is.

They are built on the core's ``emkit.gui.sections.base.Section`` like every
other section, and appear beside the shared ones (Advanced, Speed, the feed
marker, the pre-flight banner, the log) on the pages that compose both.

Modules:
    pattern_freq — PatternFreqSection, the application / frequency target form
    run          — RunSection, the core's run flow with this flow's target,
                   its feed port and its scoring filled in
    results      — ScanResultsSection, the scan's combined views (a run's own
                   grid / report box is the core's)
    area         — AreaSection, a wizard's antenna-area + feed marker
    area_banner  — AreaBanner, the wizard's advisory area-marker banner
    scan         — ScanSection, a wizard's parameter scan: one row per
                   parameter of the page's design, whatever the topology
    footprint    — FootprintSection, a wizard's footprint placer
"""

from .area import AreaSection
from .area_banner import AreaBanner
from .footprint import FootprintSection
from .pattern_freq import PatternFreqSection
from .results import ScanResultsSection
from .run import RunSection
from .scan import ScanSection

__all__ = [
    "AreaBanner",
    "AreaSection",
    "FootprintSection",
    "PatternFreqSection",
    "RunSection",
    "ScanResultsSection",
    "ScanSection",
]
