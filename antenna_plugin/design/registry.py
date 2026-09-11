"""Which antenna designs the plugin ships, and how everything finds them.

The one list. The shell builds a wizard page per entry (and its sidebar tab
from ``design.icon``), the scan spec carries either a design or its ``key``,
and the combined views label themselves from it. Adding a topology is: write
the module against :class:`~.base.AntennaDesign`, add one line here.

Designs are stateless, so one shared instance each is all anyone needs.
"""

from .ifa import MeanderedIFADesign
from .lmonopole import LMonopoleDesign
from .meander import MeanderedMonopoleDesign
from .patch import PatchDesign

# In sidebar / menu order.
DESIGNS = (
    LMonopoleDesign(),
    MeanderedIFADesign(),
    MeanderedMonopoleDesign(),
    PatchDesign(),
)

_BY_KEY = {d.key: d for d in DESIGNS}


def by_key(key):
    """The design registered under ``key``; raises KeyError naming what is
    available (a scan spec or a saved setting may name a design that has
    since been renamed)."""
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise KeyError(
            f"unknown antenna design '{key}' (have: " + ", ".join(sorted(_BY_KEY)) + ")"
        ) from exc


def resolve(design):
    """A design from either a design object or its key -- what every caller
    that accepts ``spec['design']`` uses, so a spec stays readable in a test
    (``design="ifa"``) and cheap in the GUI (the instance itself)."""
    return by_key(design) if isinstance(design, str) else design
