"""Shell: the single window hosting a plugin's views.

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

*Which* pages is the plugin's answer, and the only one it owes this class:
``build_pages`` returns them in tab order, the first being the one that owns
the window's log, its viewers and its settings. Building the sidebar is all
this file knows about them: each page describes its own tab (``tab_icon`` /
``tab_hint`` / ``tab_at_bottom``) and answers the same three lifecycle hooks
(``on_shown`` / ``on_activate`` / ``shutdown``, no-ops by default in
pages.base.BookPage), so adding a view is a page module plus a line in the
plugin's ``build_pages`` — nothing here special-cases which page it is.

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
with it and the wx parent chain (dialogs, viewers) is intact — which is why the
parent is *found* (gui.editor.editor_frame) rather than asked of
wx.GetActiveWindow, an answer only MSW and GTK have.

Lifecycle is driven by gui.show's EVT_CLOSE handler, which calls save_settings
/ shutdown / Destroy — the same contract the old single dialog exposed. Closing
the PCB editor goes through the same handler rather than around it
(gui.editor.close_with_editor): a window destroyed with its parent is deleted
and not closed, so nothing below would be saved or stopped.
"""

import wx

from ... import product
from .. import settings
from ..update.strip import UpdateStrip
from . import icons, theme
from .editor import close_with_editor, editor_frame, stop_watching
from .model import FormModel

# The tab icon, and the air around the column of them. The drawings are bundled
# at 64 px, so this scales down from artwork with room to spare on a HiDPI
# display; it is smaller than the icons alone used to be because each now has
# its name under it, and the two together are what has to read as one tab.
_ICON_SIZE = 40
_TAB_PAD = theme.HAIR


def _version():
    """The plugin's own version, for the title bar. Read late and defensively:
    a package assembled without its ``__init__`` (the tests' bare one) still
    opens a window."""
    from .. import versions

    return versions.plugin_version()


class Shell(wx.Frame):
    def __init__(self, parent):
        super().__init__(
            parent,
            title=f"{product.NAME} v{_version()}",
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
        self.update_strip = UpdateStrip(self, log=self.primary.log)
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
    def build_pages(self, book):
        """Every page this window holds, in tab order -- the plugin's answer.

        The first one is the *primary*: it owns the run log, the viewer
        windows and the settings file, and the others borrow them, so it must
        be built before they are.
        """
        raise NotImplementedError

    def _build_pages(self):
        self._pages = list(self.build_pages(self.book))
        self.primary = self._pages[0]
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
        window, so every page contributes (settings.save_pages). The
        visible page is flushed into the model and pushed onto the primary page
        first, so a shared field last edited on another page is captured on the
        one that owns its keys."""
        active = self._page_at(self.book.GetSelection())
        if active is not None:
            self.model.read(active)
        self.model.write(self.primary)
        settings.save_pages(self.pages())

    def shutdown(self):
        """Stop any run in flight and tear down the embedded viewers -- every
        page in tab order, the primary one (which owns the viewer windows the
        others borrow) first."""
        for page in self._pages:
            page.shutdown()


# The one window a plugin has open at a time. Module-level and not per-plugin
# because the core is nested inside each package: two installed plugins are
# two module trees, so this list is theirs separately, which is exactly right
# -- one Antenna Designer window and one Signal Integrity window, each raised
# rather than doubled.
_windows = []


def show(shell_class, parent=None):
    """Show *shell_class* modelessly, or raise the one already open.

    One instance per plugin: re-invoking it raises the existing window instead
    of opening a second one, whose run would race the first on the board's
    simulation folder.
    """
    if _windows:
        window = _windows[-1]
        bring_to_front(window)
        return window
    if parent is None:
        # The PCB editor frame, found rather than asked for: wx.GetActiveWindow
        # is implemented on MSW and GTK only, and the None it answers on macOS
        # is a shell that outlives the editor it belongs to (gui.editor).
        parent = editor_frame() or wx.GetActiveWindow()
    window = shell_class(parent)
    _windows.append(window)
    window.Bind(wx.EVT_CLOSE, _on_close)
    # ...and the editor closing closes this window, through that same handler.
    close_with_editor(window)
    window.Centre()
    window.Show()
    bring_to_front(window)
    return window


def bring_to_front(window):
    """Put *window* in front of the editor it was invoked from. Raise() alone
    leaves a minimised window minimised and the keyboard on the editor, so
    un-minimise first and take the focus after."""
    if window.IsIconized():
        window.Iconize(False)
    window.Raise()
    window.SetFocus()


def _on_close(event):
    window = event.GetEventObject()
    if window in _windows:
        _windows.remove(window)
    stop_watching(window)  # the editor outlives this window: drop its binding
    window.save_settings()  # persist the form for the next launch
    window.shutdown()  # stop a run in flight + tear down the viewers
    window.Destroy()
