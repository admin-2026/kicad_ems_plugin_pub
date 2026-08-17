#!/usr/bin/env python3
"""Regenerate every PNG the KiCad plugin ships (``make icon``, needs Pillow).

Three sets, drawn from one engine (the ``icons`` package next door):

- the toolbar button's glyph and the window's sidebar tab icons (icons/tabs.py)
- the Scan section's per-parameter illustrations (icons/scan.py)
- the picture of each marker footprint a button places (icons/markers.py)

Each is drawn at its own size in fractions of the canvas rather than in raw
pixels, supersampled and downscaled for anti-aliasing, so a resolution change
never touches the geometry.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from icons import markers, scan, tabs  # noqa: E402  (after the path fix above)

if __name__ == "__main__":
    tabs.draw_all()
    scan.draw_all()
    markers.draw_all()
