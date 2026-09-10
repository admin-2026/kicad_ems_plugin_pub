"""Section: the shared base for the shell's form sections.

A Section is a group of controls one of the shell's book pages
(pages.base.BookPage) composes into its scrolled form. Every section is constructed
with the page it lives on and builds its widgets into a body sizer; this base
holds what they all need — the page handle, the window their widgets parent on
(the page's scroll), the relayout / log shortcuts, and the common wrapped
status line.

Subclass contract:
  * call ``super().__init__(page, step)`` first (``step`` being whatever the
    page passed it), then build the widgets into the ``body`` sizer the
    constructor is handed (parenting them on ``self.scroll``);
  * open the group with ``self.box(title)`` -- the shared heading-over-a-rule
    frame (gui.theme), numbered with this section's step when the page gave it
    one -- and fill it with ``Add`` as with any vertical sizer;
  * build any full-width prose (notes, hints, a wrapping status line) with
    ``wrap_label`` so it fills the section width and re-wraps on resize; a
    section with a status line points ``self._status_label`` at it and
    ``_set_status`` keeps it in sync (``_step`` also logs the line, for the
    steps of a long operation);
  * build rows of buttons with ``row_button`` so every section's row is spaced
    alike.

``step`` is the section's place in a *guided* flow: the designer pages number
their sections 1..7 down the page (pages.wizard), and the simulate view builds
several of the same sections with no number at all. The page owns that ordering,
never the section -- the same box is step 3 on one page and unnumbered on
another.
"""

import wx

from .. import theme
from ..widgets import WrapLabel, muted

# The gap between stacked sections (also each section's side margins), in px:
# the top of the shared spacing scale (gui.theme). Every section adds itself to
# the page body through ``add_to_body`` so both pages space their sections the
# same; loosen the whole form there, not here.
SECTION_GAP = theme.GAP


class Section:
    def __init__(self, page, step=None):
        self.page = page
        # This section's place in the page's flow ("2 · Scan"), or None where
        # the page numbers nothing -- read by ``box`` and by nothing else.
        self.step = step

    def box(self, title):
        """This section's frame: the shared heading + hairline rule
        (theme.section_box), numbered with the page's step. Returns the vertical
        sizer the section fills."""
        return theme.section_box(self.scroll, title, self.step)

    def update_hint(self, event=None):
        """Recompute whatever this section derives from the chosen materials.

        The Advanced section calls it on the page's form (``page.form``) when a
        material picker changes, because a permittivity moves what a form can
        say about the board -- the antenna's resonant-length hint is the one
        that does. A form that derives nothing does nothing, which is why this
        is a default here rather than a method every form has to write."""

    @property
    def scroll(self):
        """The window every section widget parents on (the page's scroll)."""
        return self.page.scroll

    def add_to_body(self, body, item, last=False):
        """Add a built section (its box or pane) to the page body sizer with
        the shared side margins and the inter-section gap above it. ``last``
        (the run log) also gets the gap below, so the form doesn't end flush,
        and proportion 1: when the window is taller than the form, the spare
        height goes to the log (the scroll's virtual size is max(content min,
        client), so the sizer has that height to spread)."""
        flags = wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP
        if last:
            flags |= wx.BOTTOM
        body.Add(item, 1 if last else 0, flags, SECTION_GAP)

    def row_button(self, row, label, handler):
        """A button on one of a section's button rows: created on the page's
        scroll, bound to ``handler`` and added with the shared row spacing (no
        left margin on the first one, so every row of buttons is spaced the
        same). Returns the button, for the sections that gate or relabel it."""
        button = wx.Button(self.scroll, label=label)
        button.Bind(wx.EVT_BUTTON, handler)
        row.Add(
            button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            theme.ROW if row.GetItemCount() else 0,
        )
        return button

    def _relayout(self):
        """Refresh the scrolled form after this section changed its height."""
        self.page._relayout_scroll()

    def log(self, text):
        """Append a line to this page's run log (safe from any thread)."""
        self.page.log(text)

    def wrap_label(self, parent, text="", margin=theme.TEXT_MARGIN, mute=False):
        """Build a full-width prose label (widgets.WrapLabel): it fills the
        section width and wraps to it -- on resize (the page re-wraps every
        WrapLabel) and whenever its text is set. ``margin`` is the px trimmed
        off the page width for this label's indentation, which for a section of
        the form is the form's own margins (theme.TEXT_MARGIN); a label further
        in (the Advanced pane's) passes its own."""
        label = WrapLabel(parent, label=text, margin=margin)
        if mute:
            muted(label)
        self.page.register_wrap(label)
        return label

    def _step(self, text):
        """Announce a step of a long operation: the section's status line and
        the page's run log say the same thing (the status line is overwritten
        by the next step; the log keeps the sequence)."""
        self._set_status(text)
        self.log(text)

    def _set_status(self, text):
        """Show ``text`` on the section's status line. A wrapping status line
        (a WrapLabel) can change its line count, so the form is relaid out; a
        plain single-line label just updates."""
        if not self.page:
            return
        self._status_label.SetLabel(text)
        if isinstance(self._status_label, WrapLabel):
            self.page._relayout_scroll()
