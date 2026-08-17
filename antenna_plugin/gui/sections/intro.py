"""IntroSection: the title at the top of a page's form.

The first section of each page's scrolled body: the view's name in the page
title face (gui.theme), over an optional greyed line saying what the view is
for -- "Simulate an Antenna", "Design an L-Shaped Monopole Antenna" and the
design's own one-line summary under it. No box: it labels the form that
follows, spaced like every other section (base.Section.add_to_body).
"""

import wx

from .. import theme
from .base import Section


class IntroSection(Section):
    def __init__(self, page, body, text, subtitle=""):
        super().__init__(page)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(theme.page_title(self.scroll, text), 0)
        if subtitle:
            # Full width and wrapping: a summary is a sentence, and the window
            # can be narrowed to where it no longer fits on one line.
            line = self.wrap_label(self.scroll, subtitle, mute=True)
            box.Add(line, 0, wx.EXPAND | wx.TOP, theme.HAIR)
        self.add_to_body(body, box)
