"""How the plugin's window looks: the spacing scale, the type scale and the
frame every form section is built into.

One place, so the pages don't each invent their own margins. Everything visual
that is *shared* lives here; gui.widgets keeps the controls that behave
(the wheel-guarded slider, the live text field), and the sections keep what
they say.

The look is flat on purpose. wx's own group frame (``wx.StaticBoxSizer``) draws
an engraved rectangle around every group, and a form of eight of them stacked
is mostly border. A section is instead a **heading over a hairline rule** with
its controls flush under it: the same grouping, drawn with one line instead of
four, and the whitespace between sections (``GAP``) doing the rest. Nested
groups -- the boxes inside the Advanced pane -- drop the rule as well and are
told apart by their heading alone, so one page never shows two weights of the
same device.

Type is the native font at three weights/sizes: the page title (bold, a third
up), a section heading (bold, unchanged) and prose (unchanged, usually greyed
with widgets.muted). No colours and no font faces of our own -- the window has
to sit inside whatever theme KiCad is wearing, dark ones included, so the
system's text colours are left alone (see widgets.muted / emphasize).
"""

import wx

from .widgets import muted

# --- the spacing scale (px) -------------------------------------------------
# Four steps, and every margin in the window is one of them. HAIR separates a
# label from what it labels, ROW the controls of one block, PAD two blocks of
# one section, GAP two sections (and the form's own side margins).
HAIR = 4
ROW = 8
PAD = 12
GAP = 22

# px trimmed off the page width for a full-width prose label (widgets.WrapLabel
# wraps to what is left): the form's two side margins, plus PAD of slack so a
# wrapped line never runs under the scrollbar.
TEXT_MARGIN = 2 * GAP + PAD

# The page title's size, as a multiple of the window's own font.
TITLE_SCALE = 1.3


def _restyle(label, scale=1.0, bold=False):
    """Re-set ``label``'s font from the window's own -- so a title is this
    theme's *relation* to the native font (bold, a third bigger), never a face
    or a point size of our own. A control that answers no font (the test
    harness) is left as it is; returns the label, so callers can wrap creation
    inline."""
    font = label.GetFont()
    if not isinstance(font, wx.Font):
        return label
    if bold:
        font = font.Bold()
    if scale != 1.0:
        font.SetPointSize(int(round(font.GetPointSize() * scale)))
    label.SetFont(font)
    return label


def page_title(parent, text):
    """The one line naming a whole view, at the top of its form."""
    return _restyle(wx.StaticText(parent, label=text), scale=TITLE_SCALE, bold=True)


def subtitle(parent, text):
    """The greyed line under a page title: what the view is for, in a sentence."""
    return muted(wx.StaticText(parent, label=text))


def heading(parent, text):
    """A section's heading -- the native font, bold."""
    return _restyle(wx.StaticText(parent, label=text), bold=True)


# Why a knob shows its config key at all, and the three places it does it:
#
# The solver names its knobs by key and nothing else -- a warning says
# ``cell_mm``, a log line says ``mesh_nudge``, and the run's ``config.yaml`` is
# a list of those same names -- while the window names them in prose. A knob a
# message is about is only findable in the window if the widget says which key
# it is, so every control that *is* one config key carries its name
# (gui.sections.advanced).
#
# A typed field carries it inside the box, on the placeholder that already says
# what a blank one resolves to (hint_with_key): the key rides the empty box
# rather than taking a line of the form. A tick carries it after its label
# (with_key) -- the label is the whole row, so the key costs nothing anyone else
# has to line up with. A picker, which has no placeholder to put it on, carries
# it under its label (key_label): the label column of those grids sits beside a
# fixed-width control in a form that only scrolls vertically, so a wider column
# would push the control's right edge off the page instead of scrolling to it.
#
# A key is written in brackets wherever it appears -- ``[cell_mm]`` -- and never
# behind a separator. Both parts of a placeholder are one native string (GTK's
# placeholder text, MSW's cue banner) drawn in the control's own alignment, so
# the default cannot sit flush left with the key flush right; a middle dot in
# the gap instead would read as multiplication, which in these boxes it might
# actually be ("0 = 3·cell" is one of the defaults). Brackets are not a
# separator between two readings -- they are a tag around one, and they say the
# same thing next to a tick, where there is nothing to separate at all.
def key_text(key):
    """One config key, as the window writes it: ``[cell_mm]``."""
    return f"[{key}]"


def hint_with_key(hint, key):
    """A config field's placeholder: what a blank field resolves to, then the
    config key it writes -- ``0 = auto [cell_mm]``."""
    return f"{hint} {key_text(key)}"


def with_key(parent, ctrl, key):
    """``ctrl`` followed by the config key it drives, greyed:
    ``[x] Conformal metal (sub-cell trace edges)   [conformal]``. Returns a
    horizontal sizer, added where the bare control was."""
    row = wx.BoxSizer(wx.HORIZONTAL)
    row.Add(ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
    row.Add(
        muted(wx.StaticText(parent, label=key_text(key))),
        0,
        wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
        ROW,
    )
    return row


def key_label(parent, text, key):
    """A control's label over the config key it writes, greyed::

        Metal model
        [copper_model]

    For the label column of a field grid, where the control itself has no
    placeholder to carry the key (a picker, a field too narrow to show one).
    Returns a vertical sizer, added where the bare StaticText was -- stacked, so
    the column stays as wide as it was (see the note above)."""
    stack = wx.BoxSizer(wx.VERTICAL)
    stack.Add(wx.StaticText(parent, label=text), 0)
    stack.Add(muted(wx.StaticText(parent, label=key_text(key))), 0, wx.TOP, 1)
    return stack


def numbered(title, step):
    """A section title carrying its place in a guided flow ("2 · Scan"), or the
    bare title when it has none. The *page* says which step a section is (the
    designer's flow, pages.wizard), so a section reused off that flow -- the
    simulate view's copy of the same box -- shows no number."""
    return title if step is None else f"{step} · {title}"


def section_box(parent, title, step=None, rule=True):
    """The frame of one form section: a heading (numbered when the page gave it
    a step), a hairline rule under it, and room below for the caller's controls.

    Returns a plain vertical sizer, so a section fills it with ``Add`` exactly
    as it filled the wx.StaticBoxSizer this replaced -- and its controls parent
    on ``parent`` (the page's scroll) either way.

    ``rule=False`` is the nested form (theme.group_box): heading only.
    """
    box = wx.BoxSizer(wx.VERTICAL)
    box.Add(heading(parent, numbered(title, step)), 0, wx.BOTTOM, HAIR if rule else ROW)
    if rule:
        box.Add(wx.StaticLine(parent), 0, wx.EXPAND | wx.BOTTOM, ROW)
    return box


def group_box(parent, title):
    """A group *inside* a section (the Advanced pane's boxes): the heading
    alone, no rule -- the rules belong to the sections of the page, and one
    inside a section would read as another of them."""
    return section_box(parent, title, rule=False)
