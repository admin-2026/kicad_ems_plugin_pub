"""The Advanced pane's "Cell size" group: the two knobs as one control.

The pair is drawn as a range -- ``start at`` to ``never coarser than`` -- with
the sentence they currently mean underneath (cellsize.caption), redrawn on
every keystroke and whenever the Mesh box's re-mesh tick moves.

The host section supplies everything this box cannot know: the window to build
on, how to make a wrapping prose label at the pane's indentation, what to call
when the caption's line count changes the pane's height, and how to read the
re-mesh tick. In return it gets a sizer to add and ``fields`` -- the two
controls, by config key -- to register with the rest of the pane, which then
snapshots, restores and reads them back like any other Advanced field.

wx + the shared ``gui.theme`` look and ``gui.widgets`` controls; no pcbnew.
"""

import wx

from ..gui import theme
from ..gui.widgets import FIELD_W, live_text, muted, set_tip
from .caption import ADVICE, caption
from .knobs import FIELDS, TIPS, TITLE

# The two fields sit side by side on one field column, so each takes half of
# it -- less the "to" that joins them, which is what makes them read as one
# range rather than as two knobs that happen to be adjacent.
_HALF_W = (FIELD_W - 40) // 2


class CellSizeBox:
    """The "Cell size" box: two fields, their keys, and their live caption."""

    def __init__(self, parent, wrap, relayout, fit_cell):
        self._fit_cell = fit_cell  # () -> bool: the Mesh box's re-mesh tick
        self._relayout = relayout  # () -> None: the pane's height changed
        self.fields = {}  # config key -> wx.TextCtrl, for the host section
        self.sizer = self._build(parent, wrap)

    # --- construction ---------------------------------------------------------
    def _build(self, parent, wrap):
        box = theme.group_box(parent, TITLE)
        # Labels over fields, in three columns: the middle one is the "to", and
        # in the label row a spacer under it. A range reads left to right, so
        # the fine end (where a run starts) is the left field and the coarse
        # ceiling the right one.
        left, right = FIELDS  # the pair IS the control -- exactly two
        grid = wx.FlexGridSizer(3, theme.HAIR, theme.ROW)
        grid.Add(theme.key_label(parent, left[1], left[0]), 0)
        grid.AddSpacer(0)
        grid.Add(theme.key_label(parent, right[1], right[0]), 0)
        grid.Add(self._field(parent, left), 0)
        grid.Add(muted(wx.StaticText(parent, label="to")), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._field(parent, right), 0)
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        # Both fields start blank, which is the state with nothing to say, so
        # the box opens without a caption at all -- set here rather than
        # through refresh(), which relayouts a pane still being assembled.
        self._caption = wrap("")
        self._say(caption("", ""))
        box.Add(self._caption, 0, wx.EXPAND | wx.TOP, theme.HAIR)
        box.Add(wrap(ADVICE, mute=True), 0, wx.EXPAND | wx.TOP, theme.HAIR)
        return box

    def _field(self, parent, spec):
        """One of the two fields: live (every keystroke re-captions the box),
        its placeholder saying what a blank one resolves to and its tooltip
        what the number is for.

        The config key is NOT on the placeholder here, unlike the pane's
        one-per-row fields: this box stacks each field under its own label
        (theme.key_label), which already carries the key greyed and -- unlike a
        placeholder -- goes on carrying it once a value is typed. Saying it
        twice on one field would only make the row harder to read."""
        key, _label, hint = spec
        ctrl = live_text(parent, self.refresh, _HALF_W)
        ctrl.SetHint(hint)
        set_tip(ctrl, f"{TIPS[key]} Writes {key} in the run's config.")
        self.fields[key] = ctrl
        return ctrl

    # --- the live caption -----------------------------------------------------
    def refresh(self, event=None):
        """Re-caption from the fields as they now read. Called on every edit,
        after a restore (which sets the fields without firing events) and by the
        re-mesh tick, whose state changes what the pair means -- so it takes an
        optional event and can be bound directly."""
        if event is not None:
            event.Skip()
        values = [self.fields[key].GetValue() for key, _label, _hint in FIELDS]
        self._say(caption(*values, fit_cell=self._fit_cell()))
        self._relayout()

    def _say(self, text):
        """Put ``text`` on the caption, or take the label out of the layout
        while there is nothing to say -- an empty label would hold open the gap
        it occupies, which on an untouched box is a blank line between the
        fields and the advice under them."""
        self._caption.SetLabel(text)
        self._caption.Show(bool(text))
