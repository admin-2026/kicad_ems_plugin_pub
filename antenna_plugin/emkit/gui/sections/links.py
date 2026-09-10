"""LinksSection: the project links on the About page.

A titled box of label / link rows built straight from the link facts
(emkit.links) — the source repository and the community chat, and
whatever else is added there later. Like the version table below it, this
section decides nothing about *what* is worth showing: it renders the list that
module hands it, so adding a link is a line there, not here.

What to *use* the two of them for is the box below (sections.feedback): this
one only says where the project is.

All of today's addresses are published, so all are offered plainly, the URL
on the tooltip. Should a link be added before its destination exists
(links.is_placeholder), the section says so rather than letting the user
discover it by following one: the row's tooltip names the destination as a
placeholder and a greyed line under the table repeats it once for the box.
Nothing is hidden and nothing is disabled — such a link is the announcement
that the thing is coming.
"""

import wx

from ... import links
from ..theme import ROW
from ..widgets import hyperlink, muted
from .base import Section


class LinksSection(Section):
    _TITLE = "Project links"
    _PLACEHOLDER_NOTE = (
        "Addresses marked as placeholders are not published yet — following "
        "one lands nowhere."
    )
    _PLACEHOLDER_TIP = "{url} (placeholder — not published yet)"

    def __init__(self, page, body):
        super().__init__(page)
        self._entries = links.entries()
        self._build(body)

    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)
        grid = wx.FlexGridSizer(2, ROW, 2 * ROW)  # 2 columns; vgap, hgap
        for entry in self._entries:
            name = wx.StaticText(p, label=entry.label)
            muted(name)
            grid.Add(name, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self._link(p, entry), 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(grid, 0, wx.EXPAND)
        if any(links.is_placeholder(entry.url) for entry in self._entries):
            note = self.wrap_label(p, self._PLACEHOLDER_NOTE, mute=True)
            box.Add(note, 0, wx.EXPAND | wx.TOP, ROW)
        self.add_to_body(body, box)

    def _link(self, parent, entry):
        """One row's link (widgets.hyperlink), the URL on its tooltip — said to
        be a placeholder where it is one, since that is the one thing a link
        nobody can follow yet has to tell the user up front."""
        tip = entry.url
        if links.is_placeholder(entry.url):
            tip = self._PLACEHOLDER_TIP.format(url=entry.url)
        return hyperlink(parent, entry.name, entry.url, tip=tip)
