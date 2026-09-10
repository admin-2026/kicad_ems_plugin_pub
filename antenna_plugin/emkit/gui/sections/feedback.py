"""FeedbackSection: the About page's one ask of the user.

Under the project links (sections.links), which say where the project is, this
box says what to use them for — report a bug, ask for a feature, or say how it
went — and which address each belongs at: the issue tracker for anything that
wants an answer on the record, the chat above for the rest. It asks for the
versions the table below it lists too, since a report without them is a round
trip.

Only the tracker is offered here, as the one thing the sentence asks for; the
chat is a link in the box above and is not repeated. The address comes from
emkit.links, like every other outward link the page shows, so this section
decides nothing about where it points.
"""

import wx

from ... import links
from ..theme import PAD
from ..widgets import hyperlink
from .base import Section


class FeedbackSection(Section):
    _TITLE = "Feedback"
    _NOTE = (
        "Feedback is welcome. Open an issue to report a bug or ask for a "
        "feature — quote the versions listed below, they are the first thing "
        "a report is asked for — or come to the Discord chat above for "
        "anything that isn't one."
    )
    _LINK = "Report a bug or request a feature"

    def __init__(self, page, body):
        super().__init__(page)
        self._build(body)

    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)
        box.Add(self.wrap_label(p, self._NOTE, mute=True), 0, wx.EXPAND)
        box.Add(
            hyperlink(p, self._LINK, links.ISSUES_URL),
            0,
            wx.ALIGN_LEFT | wx.TOP,
            PAD,
        )
        self.add_to_body(body, box)
