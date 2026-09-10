"""GuidesSection: the bundled documentation on the About page.

A titled box of buttons, one per guide worth reading on its own rather than
when something goes wrong — today the settings reference (help/settings.html),
every knob of the window in one page, and the command-line guide
(help/cli.html), the other frontend in one page. The pre-flight guides beside
it in ``help/`` are not listed: each belongs to a problem and is opened from
the banner row reporting it (sections.banner), where it means something.

Like the links and version tables above it, this section decides nothing about
*what* is worth showing: ``GUIDES`` is the list, so adding one is a line there
plus the HTML file. Opening it is the shared path every guide takes
(viewers.show_guide) — the same window a banner's Help button uses, so a guide
opened from here and one opened from a blocked run look the same.

The About page has no run log, so a guide missing from the install has to be
said on the section's own status line; at rest that line says what these
buttons open.
"""

import wx

from ..theme import PAD
from ..viewers import show_guide
from .base import Section

# The guides this box offers: (button label, help/ file, help-window title,
# button tooltip). One entry, one button, in this order.
#
# The command-line guide is not here: it sits in the box that installs the
# command line's shortcut (sections.cli), where a reader is already looking at
# the thing it explains.
GUIDES = (
    (
        "Settings reference",
        "settings.html",
        "Settings reference",
        "Every setting in this window, what it changes and its default",
    ),
)

# What a section says when a guide is not in the install. Here because both
# boxes that open one need it, and there is one sentence for it.
MISSING = "✗ {label} is missing from this install."


def open_guide(section, label, filename, title):
    """Show one guide from ``section``, or say on that section's status line
    that the install has not got it -- the About page has no run log for the
    message to land in. Returns whether it opened, so the caller can decide
    what its line goes back to saying."""
    if show_guide(section.page, filename, title):
        return True
    section._set_status(MISSING.format(label=label))
    return False


class GuidesSection(Section):
    _TITLE = "Documentation"
    _NOTE = "Opens in a help window beside this one."
    _MISSING = MISSING

    def __init__(self, page, body):
        super().__init__(page)
        self._build(body)

    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, filename, title, tip in GUIDES:
            button = self.row_button(
                row,
                label,
                lambda event, f=filename, t=title, lb=label: self._open(f, t, lb),
            )
            button.SetToolTip(tip)
        box.Add(row, 0, wx.EXPAND)
        self._status_label = self.wrap_label(p, self._NOTE, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)

    def _open(self, filename, title, label):
        """Show one guide, the shared way (``open_guide`` says it if the file
        is not in the install); this box's line goes back to what its buttons
        do once one opens."""
        if open_guide(self, label, filename, title):
            self._set_status(self._NOTE)
