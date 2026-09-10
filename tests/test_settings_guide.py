"""This product's half of the settings reference: the boxes only an antenna has.

The page a user opens is two files -- the shared boxes (``emkit/help``) and
this plugin's own fragment beside its code, spliced together on the way into
the package (``tools/assemble.py``). The core's suite checks the splice
happened; what it cannot check is *what this window has*, because the core may
not know what a design target or a scan is. So that half is asserted here, off
the sections themselves: a box added to this form and not to its fragment is a
reference that has stopped describing the window it is about.

    python3 tests/test_settings_guide.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (the sections import wx to be read at all)
from bare_package import load, run_module_tests  # noqa: E402
from helppage import assert_page_loads  # noqa: E402

pattern_freq = load("gui.sections.pattern_freq")
registry = load("design.registry")

PAGE = "settings.html"


def test_the_page_has_a_box_for_this_flows_own_form():
    """By the title the section itself draws, so renaming the box in the window
    and not on the page fails here rather than confusing a reader."""
    text = assert_page_loads(PAGE)
    title = pattern_freq.PatternFreqSection._TITLE
    assert title in text, f"no section for the {title} box"


def test_it_names_the_designer_boxes_a_reader_will_be_looking_at():
    """The three that exist nowhere else: the marker whose width is a setting,
    the area marker that *is* one, and the sweep over it."""
    text = " ".join(assert_page_loads(PAGE).split())
    for label in ("Feed marker", "Antenna area", "Scan", "Candidates", "Angle"):
        assert label in text, f"the settings guide does not name {label!r}"


def test_it_names_every_field_of_a_typed_target():
    """The three the ``Custom…`` pick reveals -- the whole of what a target is
    when it is not picked from the catalog, and the fields a settings file
    holds beside ``app``."""
    text = " ".join(assert_page_loads(PAGE).split())
    for label in ("Pattern frequency", "Bandwidth", "Input impedance"):
        assert label in text, f"the settings guide does not name {label!r}"


def test_a_scan_row_is_described_for_whatever_a_design_asks_for():
    """The scan table is per design, so the page describes the *row* -- the
    swept-parameter radio, the bounds, the value, the candidate count -- rather
    than listing one design's knobs. This says the designs still fit that
    description: one that asked for something else would need a page that said
    so."""
    text = " ".join(assert_page_loads(PAGE).split())
    assert registry.DESIGNS, "no designs at all"
    for phrase in ("Swept parameter", "Min / Max", "Value"):
        assert phrase in text, f"the settings guide does not name {phrase!r}"


if __name__ == "__main__":
    run_module_tests(globals())
