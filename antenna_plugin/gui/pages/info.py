"""InfoPage: the About view of the shell.

The last tab, pinned to the foot of the sidebar: what this installation is made
of, where the project lives, and what there is to read. First the project links
(sections.LinksSection over antenna_plugin.links) — the source repository and
the community chat, both still placeholder addresses, which the section says on
the rows themselves — then the bundled documentation (sections.GuidesSection:
the settings reference, every knob of the window in one page) and the version
table (sections.VersionsSection over antenna_plugin.versions): the plugin, the
bundled solver and the schema they agree on, plus the KiCad / Python / wx
underneath, the things to quote when something misbehaves.

A page with nothing running and nothing to persist, so it inherits every
lifecycle and settings no-op from base.BookPage and overrides only ``on_shown``,
where the version table starts the one probe it defers (the solver's own
version, a process spawn) and picks up the update check's answer from the
shell's strip (antenna_plugin.update). It has no run log either — nothing here
runs, and the update check is the shell's, not this page's.

It does show one HTML page, so like a designer it *borrows* the simulate view's
viewer windows (``viewers``) rather than owning a hub of its own: a guide opened
here lands in the same help window a blocked run's Help button opens.
"""

import wx

from ..sections import GuidesSection, IntroSection, LinksSection, VersionsSection
from .base import BookPage


class InfoPage(BookPage):
    tab_icon = "gear_icon.png"
    tab_label = "About"
    tab_hint = "About this installation"
    tab_at_bottom = True  # the sidebar's foot, below the working tabs

    def __init__(self, parent):
        super().__init__(parent)  # sets up self.scroll
        body = wx.BoxSizer(wx.VERTICAL)
        self.intro = IntroSection(
            self,
            body,
            "About Antenna Designer",
            subtitle=(
                "What this installation is made of — the versions to quote "
                "when something misbehaves."
            ),
        )
        self.links = LinksSection(self, body)
        self.guides = GuidesSection(self, body)
        self.versions = VersionsSection(self, body)
        self.mount(body)

    @property
    def viewers(self):
        """The viewer windows this page's guides open in: the simulate page's
        hub (gui.viewers), borrowed the way a designer borrows it, so the help
        window is shared with the pre-flight banner's guides. Every page that
        shows HTML exposes ``viewers``, so a section never has to know which
        page owns it."""
        return self.shell.simulate.viewers

    def on_shown(self):
        """The shell switched to this page: let the version table start (once)
        the probe it can't do on the wx thread, and note on it whatever the
        shell's launch-time update check has found by now (nothing, usually --
        every outcome but "a newer release exists" leaves the table alone)."""
        self.versions.refresh()
        strip = getattr(self.shell, "update_strip", None)
        self.versions.show_update(strip.outcome if strip is not None else None)
