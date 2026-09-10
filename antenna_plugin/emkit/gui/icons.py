"""The bundled PNGs the GUI shows, loaded as wx bitmaps.

Two kinds ship with the package, both drawn by ``tools/icons/`` and both flat
blue on transparency, so they read as one family:

* the **tab icons** beside the package (``page.tab_icon`` / ``design.icon``),
  one per view in the shell's sidebar;
* the **illustrations** under ``assets/icons/``: one per geometry parameter the
  Scan section can sweep (``base.Param.icon``) -- the picture of which piece of
  the antenna that row moves -- and one per marker footprint a button places
  (``sections.marker.ICON_FILE``), the picture of what that button puts on the
  board.

Everything about *where they live and how they are loaded* is here, so the
shell and the sections just ask for a file name at the size they show it --
including which of the two trees it is in (see ROOTS). The
art is square and oversized on purpose (see tools/icons/frames.py), and scaling
happens once, at load.
"""

import os

import wx

# Where a bundled PNG may be: the plugin's own tree first, the core's second.
# A drawing lives in the tree that *names* it -- a design's artwork and the
# toolbar glyph are the plugin's, the marker pictures are the core's -- and a
# caller asks for a file name without having to know which of the two it is.
CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.dirname(CORE_DIR)
ROOTS = (PKG_DIR, CORE_DIR)
ART_DIR = ("assets", "icons")


def bitmap(size, *parts, alpha=1.0):
    """A bundled PNG (``parts`` joined under the package) as a square bitmap
    of ``size`` px, optionally faded to ``alpha`` -- the "this row is not the
    one" look, which keeps the drawing's colour instead of greying it into a
    different picture.

    Returns None when the file isn't bundled, rather than letting wx pop its
    own image-load error out of a dialog build: the caller decides whether a
    missing picture is fatal (a sidebar tab) or simply nothing to show (a
    parameter a design ships no artwork for).
    """
    for root in ROOTS:
        path = os.path.join(root, *parts)
        if os.path.isfile(path):
            break
    else:
        return None
    image = wx.Image(path, wx.BITMAP_TYPE_PNG)
    if image.GetWidth() != size or image.GetHeight() != size:
        image = image.Scale(size, size, wx.IMAGE_QUALITY_HIGH)
    if alpha < 1.0:
        image = image.AdjustChannels(1.0, 1.0, 1.0, alpha)
    return wx.Bitmap(image)


def illustration(file_name, size, alpha=1.0):
    """One drawing of the bundled ``assets/icons/`` set at ``size`` px: a swept
    parameter's picture (``base.Param.icon``), a marker's picture of itself.
    Named by file rather than by subject -- each caller owns its own file
    names -- and None for a missing (or unnamed) one, as ``bitmap``."""
    if not file_name:
        return None
    return bitmap(size, *ART_DIR, file_name, alpha=alpha)
