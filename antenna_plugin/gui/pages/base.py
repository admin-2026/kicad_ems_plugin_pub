"""BookPage: the shared base for AntennaShell's book pages.

Every page -- the simulate view (simulate.SimulatePage), the antenna designers
(wizard.DesignWizardPage, one per design) and the About view (info.InfoPage) --
is a vertical ScrolledWindow: a tall form that scrolls with the mouse wheel from
anywhere in it (over an input box, dropdown, slider or blank space alike --
widgets.no_scroll_tree), filling the whole page. This base owns that
scaffolding, the run-log handle and the relayout helpers they all need, so none
of them repeats it.

A page may also hand ``mount`` a *footer* (the banners, sections.banner): a
strip that sits below the scroll, outside it, so it stays put however far the
form is scrolled. Below and not above on purpose. These banners appear and clear
on their own -- a focus switch back from Board Setup, a marker moved, a fix
applied -- and above the scroll each of those shoved the whole form up and down
under the pointer. Below it nothing moves: the form is anchored to the top of
the scroll, so a footer coming and going only shrinks the viewport under it.

It is a real row of the page's sizer, *not* a widget floated over the scroll:
wx doesn't support overlapping sibling windows (no defined z-order or clipping
on GTK/MSW -- an overlaid panel comes out half-invisible, mis-sized and smeared
with the form's pixels), which is what an earlier version of this tried.

A page also *describes its own tab*: the shell reads ``tab_icon`` / ``tab_hint``
/ ``tab_at_bottom`` off it and asks nothing else about what it is (gui.shell),
so adding a view is adding a module here and one line to the shell's page list.

Each page composes its own run log as the last section of its scrolled body
(sections.LogSection); the subclass points ``self.log_ctrl`` at that section's
widget so this base's ``log`` -- and the sections' -- can write to it. A page
without a log (the About view) leaves it None and its ``log`` goes nowhere.

Subclass contract:
  * declare ``tab_icon`` (a PNG bundled beside the package), ``tab_label`` (the
    short name under it) and ``tab_hint`` (the tab's tooltip) -- as class
    attributes, or set on the instance when they depend on what the page was
    built with (a designer's design);
  * build the form into ``self.scroll`` (parent every scrolling widget on it),
    filling a vertical body sizer, and set ``self.log_ctrl`` from the log
    section it builds before anything logs;
  * call ``self.mount(body, footer=...)`` once the form is built -- it mounts
    the body on the scroll, lays the page out (any ``footer`` widget docked
    below it) and binds wheel scrolling across the whole form;
  * override the lifecycle hooks it needs (``on_shown``, ``on_activate``,
    ``shutdown``) -- a page with nothing in flight inherits the no-ops;
  * override ``settings_snapshot`` / ``settings_restore`` to take part in the
    per-project settings file (gui.settings), and call ``load_settings()`` once
    the form is built. A page with nothing to persist inherits the no-ops;
  * override ``shared_snapshot`` / ``shared_restore`` to take part in the
    shared design form (gui.model) -- designform.DesignFormPage implements
    both for the pages that carry it; the rest inherit the no-ops.
"""

import wx

from ..widgets import no_scroll_tree


class BookPage(wx.Panel):
    # --- the page's tab in the shell's sidebar (read by gui.shell) ------------
    tab_icon = ""  # bundled PNG beside the package
    tab_label = ""  # the name under that drawing -- short: it sets the
    # sidebar's width
    tab_hint = ""  # the tab's tooltip, where the longer name goes
    tab_at_bottom = False  # sit at the foot of the sidebar, not in order

    def __init__(self, parent):
        super().__init__(parent)
        self.log_ctrl = None  # set from the page's LogSection widget
        # The strip docked below the scroll (a banner), set by mount(); None on
        # a page that has none (the About view).
        self._footer = None
        # Prose labels that fill the width and wrap to it (widgets.WrapLabel);
        # a resize re-wraps them all (register_wrap / _on_page_size).
        self._wrap_labels = []
        # The form lives in a vertical ScrolledWindow so it never clips when it
        # overflows the window; fields keep fixed widths so resizing the window
        # doesn't stretch them.
        self.scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.scroll.SetScrollRate(0, 12)
        # Re-wrap the full-width prose labels to the new width on every resize.
        self.Bind(wx.EVT_SIZE, self._on_page_size)

    # --- layout ---------------------------------------------------------------
    def mount(self, body, footer=None):
        """Mount the built ``body`` sizer on the scroll and lay the page out.
        The scroll takes the page's height, and a wheel notch scrolls it from
        anywhere in the form -- never changing a control's value.

        ``footer`` is a widget docked below the scroll (a banner, which comes
        and goes as the board changes -- see the module docstring). It must be a
        child of this page; it is shown/hidden by its own owner, and
        ``relayout_footer`` re-fits the page around it whenever that happens."""
        self.scroll.SetSizer(body)
        self._footer = footer
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.scroll, 1, wx.EXPAND)
        if footer is not None:
            outer.Add(footer, 0, wx.EXPAND)
        self.SetSizer(outer)
        no_scroll_tree(self.scroll)
        self._rewrap_labels()  # wrap once to the initial width

    def relayout_footer(self):
        """The footer changed height or visibility (a banner rebuilt its rows):
        re-lay the page so the scroll gives up exactly the height the strip now
        needs. The page sizer caches the footer's best size, so drop that first
        -- its sizer's contents are what just changed. A page with no footer
        does nothing."""
        if self._footer is None:
            return
        self._footer.InvalidateBestSize()
        self.Layout()
        # The viewport just changed height; re-read the scroll range against it
        # (the scrollbar may now be needed, or no longer be).
        self._relayout_scroll()

    def _relayout_scroll(self):
        """Refresh the scroll after its content height changed outside a window
        resize (a collapsible pane toggled, a wrapped label regrew, a gauge
        shown/hidden). The bookkeeping is wx's own: a ScrolledWindow with a
        sizer keeps its virtual size at max(content min, client) and lays the
        sizer over that area, so the scrollbar appears only once the content
        overflows and the view is clamped when it shrinks. FitInside re-reads
        the content min; Layout re-spreads the sizer. Window resizes take the
        same path via the scroll's own size handler."""
        self.scroll.FitInside()
        self.scroll.Layout()

    def _on_pane_changed(self, event=None):
        """A collapsible pane opened/closed: relayout the scrolled form so its
        virtual size (and scrollbar) tracks the new content height."""
        self._relayout_scroll()

    # --- full-width prose labels ----------------------------------------------
    def register_wrap(self, label):
        """Register a widgets.WrapLabel so page resizes re-wrap it to the width
        (sections build these through base.Section.wrap_label)."""
        self._wrap_labels.append(label)

    def _on_page_size(self, event):
        """The page resized: re-wrap every full-width label to the new width
        (their wrapped line counts change, so this can regrow the form)."""
        event.Skip()
        self._rewrap_labels()

    def _rewrap_labels(self):
        width = self.GetClientSize().width
        changed = False
        for label in self._wrap_labels:
            if label:  # skip any destroyed mid-teardown
                changed = label.rewrap(width) or changed
        if changed:
            self._relayout_scroll()

    # --- run log --------------------------------------------------------------
    def log(self, text):
        """Append a line to this page's run log; safe from any thread. A page
        that builds no log section (the About view) silently drops the line,
        so anything shared -- a section, the settings loader -- can log
        without asking which page it is on."""
        if self.log_ctrl is not None:
            self.log_ctrl.log(text)

    # --- shared design form (gui.model) ---------------------------------------
    # The pages that carry the Pattern-frequency / Speed / Advanced sections are
    # two views onto one datastore; the shell syncs them through the model as it
    # switches pages. The defaults keep a page that carries none of it (the
    # About view) out of that sync without the shell having to ask.
    def shared_snapshot(self):
        """This page's share of the shared form as a flat string dict."""
        return {}

    def shared_restore(self, data):
        """Set those widgets from the model, without firing edit events."""

    # --- persisted form (gui.settings) ----------------------------------------
    @property
    def shell(self):
        """The AntennaShell hosting this page -- the parent of the book the
        pages sit in. It owns the settings file, since one file holds them
        all."""
        return self.GetParent().GetParent()

    def settings_snapshot(self):
        """This page's persisted widgets as a flat string dict. The default is
        empty: a page takes part by overriding this and ``settings_restore``."""
        return {}

    def settings_restore(self, data):
        """Set those widgets from a ``settings_snapshot`` dict (and re-derive
        whatever depends on them), without firing edit events."""

    def load_settings(self):
        """Restore this page from the saved file -- called once, at the end of
        the subclass' construction."""
        from .. import settings

        settings.load_into(self)

    def save_settings(self):
        """Persist the window's form. Every page's keys go in one file, so this
        saves them all through the shell rather than this page alone."""
        self.shell.save_settings()

    # --- lifecycle ------------------------------------------------------------
    # The shell drives these three; each defaults to nothing to do, so a page
    # only writes the ones it needs.
    def on_shown(self):
        """The shell switched to this page (after writing the shared model
        onto it): re-read whatever the page shows off the board or the form.
        Must be idempotent -- every switch back calls it again."""

    def on_activate(self, visible):
        """The shell's window regained the focus, ``visible`` telling this page
        whether it is the one on screen. The usual fixes (Board Setup, moving a
        marker) happen in KiCad, so this is where an advisory banner re-checks
        the board."""

    def shutdown(self):
        """Stop anything in flight (and, for the page that owns them, tear down
        the embedded viewer windows) as the window closes."""
