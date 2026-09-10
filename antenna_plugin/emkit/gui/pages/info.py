"""InfoPage: the About view of the shell.

The last tab, pinned to the foot of the sidebar: what this installation is made
of, where the project lives, and what there is to read. First the project links
(sections.LinksSection over emkit.links) — the source repository and the
community chat — then the one thing the page asks *of* the reader
(sections.FeedbackSection: report a bug, request a feature, and quote the
versions below when doing it), then the bundled documentation
(sections.GuidesSection: the settings reference, every knob of the window in
one page, and the command-line guide, the other frontend in one), then the one
thing on this page that writes anything (sections.CliSection: the tick that
installs the command line's short name, which is a fact about this machine and
not about the board), and the version table
(sections.VersionsSection over emkit.versions): the plugin, the bundled solver
and the schema they agree on, plus the KiCad / Python / wx underneath, the
things to quote when something misbehaves.

A page with nothing to persist, so it inherits every settings no-op from
base.BookPage and overrides only ``on_shown``, where the version table picks up
the update check's answer from the shell's strip (emkit.update) and the
command-line box re-reads its shortcut off disk.

One thing here *does* run, though, and it is the longest-running thing the
window does: building the container image, which installs KiCad and takes
minutes. So this page ends with the same terminal every other page has
(sections.LogSection, titled for what it holds), and the engine's own output
goes there line by line -- a build that is doing something and a build that is
stuck look identical on a one-line status, and the reason a build failed is
always in its output rather than in its exit status.

It does show one HTML page, so it *borrows* the primary page's viewer windows
(``viewers``) rather than owning a hub of its own: a guide opened here lands in
the same help window a blocked run's Help button opens.
"""

import wx

from .... import product
from ..sections import (
    CliSection,
    DockerSection,
    FeedbackSection,
    GuidesSection,
    IntroSection,
    LinksSection,
    LogSection,
    VersionsSection,
)
from .base import BookPage


class InfoPage(BookPage):
    tab_icon = "gear_icon.png"
    tab_label = "About"
    tab_hint = "About this installation"
    tab_at_bottom = True  # the sidebar's foot, below the working tabs
    LOG_TITLE = "Image build log"

    def __init__(self, parent):
        super().__init__(parent)  # sets up self.scroll
        body = wx.BoxSizer(wx.VERTICAL)
        self.intro = IntroSection(
            self,
            body,
            f"About {product.NAME}",
            subtitle=(
                "What this installation is made of — the versions to quote "
                "when something misbehaves."
            ),
        )
        self.links = LinksSection(self, body)
        self.feedback = FeedbackSection(self, body)
        self.guides = GuidesSection(self, body)
        self.cli = CliSection(self, body)
        self.docker = DockerSection(self, body)
        self.versions = VersionsSection(self, body)
        # The terminal the image build prints into -- the same section every
        # other page ends with. Built last so it takes the page's spare height,
        # and pointed at before anything can log: the Docker box above writes
        # here through the page (Section.log), exactly as a run section writes
        # into the page it is on.
        self.log_section = LogSection(self, body, title=self.LOG_TITLE)
        self.log_ctrl = self.log_section.ctrl
        self.mount(body)

    @property
    def viewers(self):
        """The viewer windows this page's guides open in: the primary page's
        hub (gui.viewers), borrowed rather than owned, so the help window is
        shared with the pre-flight banner's guides. Every page that shows HTML
        exposes ``viewers``, so a section never has to know which page owns
        it."""
        return self.shell.primary.viewers

    def on_shown(self):
        """The shell switched to this page: note on the version table whatever
        the shell's launch-time update check has found by now (nothing, usually
        -- every outcome but "a newer release exists" leaves the table alone),
        and let the command-line box re-read whether its shortcut is still
        installed, which another window may have changed."""
        self.versions.refresh()
        self.cli.refresh()
        self.docker.refresh()
        strip = getattr(self.shell, "update_strip", None)
        self.versions.show_update(strip.outcome if strip is not None else None)
