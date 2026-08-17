"""AntennaShell: the single window hosting the plugin's views.

A modeless frame with a hand-rolled sidebar: a white full-height column of
toggle buttons -- each the page's icon over its short name, with the longer
description on the tooltip -- beside a wx.Simplebook holding the pages. The
sidebar is a plain panel rather than a Listbook/Toolbook controller because the
native ones fought back — a Listbook sidebar leaves dead, unclickable space
between items, and a Toolbook's toolbar would not reliably paint a background
across platforms.

The names are under the icons and not only on the tooltips: a drawing of an
inverted-F says which antenna a tab designs to somebody who already knows the
shape, and nothing at all to anybody else, and a tooltip is only read by a user
who already suspects there is something to find. They are short on purpose
(``tab_label``, a design's ``short_name``) -- the column is a margin of this
window, not a pane of it.

The pages are the simulate view (settings + Run, pages.simulate.SimulatePage),
one designer per antenna in design.registry (pages.wizard.DesignWizardPage — so
shipping another topology adds a tab without an edit here) and the About view
(pages.info.InfoPage), which sits at the foot of the sidebar. Building the
sidebar is all this file knows about them: each page describes its own tab
(``tab_icon`` / ``tab_hint`` / ``tab_at_bottom``) and answers the same three
lifecycle hooks (``on_shown`` / ``on_activate`` / ``shutdown``, no-ops by
default in pages.base.BookPage), so adding a view is a page module plus a line
in ``_build_pages`` — nothing else here special-cases which page it is.

Across the top of both columns sits the update notice (update.strip.UpdateStrip)
-- normally invisible, and taking no height while it is: it appears only when
the launch-time check finds a newer release, with a link to it and a ✕. The
check runs on a daemon thread and answers a value rather than raising, so this
window neither waits for it nor is gated by it; building the strip and starting
it is all the shell knows about the feature.

A frame, not a dialog, on purpose: the wizard's board-marker steps need the PCB
editor to stay interactive, and a dialog is treated as (quasi-)modal on some
platforms and steals input from the editor.

A plain frame, *not* FRAME_FLOAT_ON_PARENT: that style is what forces a window
to stay above its parent (on MSW it makes the editor the native owner, on GTK it
sets transient-for), and it left the shell permanently on top of the PCB editor
— no way to look at the board it covers except to move or minimise it. Without
it the shell is an ordinary window in the stack: click the editor and it goes
behind, click the shell (or re-invoke the plugin, which raises it — gui.show)
and it comes forward. The editor is still passed as the parent so the shell dies
with it and the wx parent chain (dialogs, viewers) is intact.

Lifecycle is driven by gui.show's EVT_CLOSE handler, which calls save_settings
/ shutdown / Destroy — the same contract the old single dialog exposed.
"""

import wx

from .. import __version__
from ..design import registry
from ..update.strip import UpdateStrip
from . import icons, settings, theme
from .model import FormModel
from .pages import DesignWizardPage, InfoPage, SimulatePage

# The tab icon, and the air around the column of them. The drawings are bundled
# at 64 px, so this scales down from artwork with room to spare on a HiDPI
# display; it is smaller than the icons alone used to be because each now has
# its name under it, and the two together are what has to read as one tab.
_ICON_SIZE = 40
_TAB_PAD = theme.HAIR


class AntennaShell(wx.Frame):
    def __init__(self, parent):
        super().__init__(
            parent,
            title=f"Antenna Designer v{__version__}",
            size=(900, 760),
            # No FRAME_FLOAT_ON_PARENT: the shell sits in the window stack like
            # any other window, so the editor can come in front of it (see the
            # module docstring).
            style=wx.DEFAULT_FRAME_STYLE,
        )
        self.SetMinSize((760, 600))

        # The single datastore behind the design pages' Pattern-frequency /
        # Speed / Advanced sections (one model, a view per page): the shell
        # reads the visible page into it and writes it onto the incoming page
        # as pages switch. A page carrying none of it snapshots/restores
        # nothing (pages.base.BookPage's no-ops), so it takes part harmlessly.
        self.model = FormModel()

        # The sidebar column and the page book it drives.
        self.sidebar = wx.Panel(self)
        self.sidebar.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX)
        )
        self._side_sizer = wx.BoxSizer(wx.VERTICAL)
        self.sidebar.SetSizer(self._side_sizer)
        self._tabs = []
        self._bottom_spacer = False  # the stretch above the foot tabs

        self.book = wx.Simplebook(self)

        for page in self._build_pages():
            self._add_page(page)
        self._tabs[0].SetValue(True)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(self.sidebar, 0, wx.EXPAND)
        # The edge of the column: the sidebar is painted in the list background
        # and the pages in the window background, which under some themes (and
        # most dark ones) are the same colour -- then nothing but this line says
        # where the tabs end.
        body.Add(wx.StaticLine(self, style=wx.LI_VERTICAL), 0, wx.EXPAND)
        body.Add(self.book, 1, wx.EXPAND)

        # Above the sidebar and the pages, spanning both: the update notice
        # (update.strip). It is hidden -- and so takes no height -- unless a
        # newer release turns up, and the check behind it is a daemon thread
        # that answers a value rather than raising, so nothing below waits on
        # it or is gated by it. This is the shell's whole share of the feature.
        self.update_strip = UpdateStrip(self, log=self.simulate.log)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.update_strip, 0, wx.EXPAND)
        outer.Add(body, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.update_strip.start()

        # Re-check pre-flight when the window regains focus: the usual fix
        # (Board Setup > Physical Stackup) happens in KiCad, and the user then
        # comes back.
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

    # --- the views ------------------------------------------------------------
    def _build_pages(self):
        """Build every page, in tab order -- the one list of what this window
        holds. Simulate comes first: the designers borrow its feed-marker picks
        and its result viewers, so it must exist before they do. Adding a view
        is a line here (and the page module it names)."""
        self.simulate = SimulatePage(self.book)
        # Seed the model from the simulate page's just-loaded settings, so a
        # designer picks up the same values when it is first shown.
        self.model.read(self.simulate)
        # One designer page per registered antenna design, in registry order.
        self.wizards = [
            DesignWizardPage(self.book, self.simulate, design)
            for design in registry.DESIGNS
        ]
        self._pages = [self.simulate, *self.wizards, InfoPage(self.book)]
        return self._pages

    # --- view switching -------------------------------------------------------
    def _add_page(self, page):
        """Append a page to the book and its tab to the sidebar, the page saying
        which icon, name and tooltip it wants. A page asking for the sidebar's
        foot (the About view) gets the spare height pushed above it, so the tabs
        that do the work stay grouped at the top."""
        self.book.AddPage(page, "")
        if page.tab_at_bottom and not self._bottom_spacer:
            self._bottom_spacer = True
            self._side_sizer.AddStretchSpacer()
        # A wx.ToggleButton and not a wx.BitmapToggleButton: the bitmap one
        # takes its picture *as* its label and has nowhere to put a name, while
        # a plain toggle button is a wx.AnyButton like any other and wears both
        # (SetBitmap). A page whose PNG isn't bundled keeps the name alone.
        tab = wx.ToggleButton(self.sidebar, label=page.tab_label)
        icon = icons.bitmap(_ICON_SIZE, page.tab_icon)
        if icon is not None:
            tab.SetBitmap(icon)
            # The name sits *under* the drawing, so a tab is one tall block
            # rather than a wide row -- the column stays a margin.
            tab.SetBitmapPosition(wx.TOP)
        tab.SetBackgroundColour(self.sidebar.GetBackgroundColour())
        tab.SetToolTip(page.tab_hint)
        tab.Bind(wx.EVT_TOGGLEBUTTON, self._on_tab)
        self._side_sizer.Add(tab, 0, wx.EXPAND | wx.ALL, _TAB_PAD)
        self._tabs.append(tab)

    def _on_tab(self, event):
        self._select(self._tabs.index(event.GetEventObject()))

    def _select(self, index):
        """Switch pages, syncing the shared form through the model: snapshot
        the outgoing page, restore the incoming page, then let it wake (a
        designer re-seeds its scan and re-reads the board; the About view
        probes its versions). A page that carries no shared form contributes
        and takes nothing, so this needs no case for it."""
        for i, tab in enumerate(self._tabs):
            tab.SetValue(i == index)
        if index == self.book.GetSelection():
            return
        self.model.read(self.book.GetCurrentPage())
        self.book.ChangeSelection(index)
        page = self.book.GetPage(index)
        self.model.write(page)
        page.on_shown()

    def _page_at(self, index):
        return self.book.GetPage(index) if index != wx.NOT_FOUND else None

    # --- lifecycle ------------------------------------------------------------
    def _on_activate(self, event):
        """The window regained the focus: tell every page, saying which one is
        on screen. What to re-check is the page's business -- the simulate
        view's pre-flight banner, a designer's area banner."""
        event.Skip()
        if not event.GetActive():
            return
        current = self._page_at(self.book.GetSelection())
        for page in self._pages:
            page.on_activate(page is current)

    def pages(self):
        """Every page of the book, in tab order -- the simulate view first."""
        return list(self._pages)

    def save_settings(self):
        """Persist the form for the next launch. One file holds the whole
        window, so every page contributes (gui.settings.save_pages): the
        simulate view's form and each designer's scan rows. The visible page is
        flushed into the model and pushed onto the simulate page first, so a
        shared field last edited on a wizard is captured on the page that owns
        its keys."""
        active = self._page_at(self.book.GetSelection())
        if active is not None:
            self.model.read(active)
        self.model.write(self.simulate)
        settings.save_pages(self.pages())

    def shutdown(self):
        """Stop any run/scan in flight and tear down the embedded viewers --
        every page in tab order, the simulate view (which owns the viewer
        windows the others borrow) first."""
        for page in self._pages:
            page.shutdown()
