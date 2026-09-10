"""Small wx helpers shared by the GUI modules."""

import re

import wx

# widget <-> flat string state, re-exported: a section's snapshot/restore reads
# and writes the same strings the settings file holds and `formparams` parses,
# so the conversions live with that translation and a widget module imports
# them rather than owning a second spelling of them.
from ..formparams import bool_str, parse_bool, to_float  # noqa: F401
from . import gtk_wheel, mac_enable

# Fixed control widths: fields, dropdowns and the speed slider keep these
# sizes regardless of how the dialog is resized. Sized so that at the default
# dialog width (760) the fields end just short of the right margin.
FIELD_W = 460  # form fields and dropdowns
SLIDER_W = 520  # speed/accuracy slider (and its end labels)
# A slider's height on macOS, where wx's own is too small for the knob.
# wxOSX sizes a slider from the Aqua constants it has always carried -- 18
# points across for a plain one, 24 for one with tick marks -- and the knob
# AppKit draws today is a circle wider than the plain figure, so it is cut off
# at the top and bottom of a frame three points too short. The form's one
# tick-marked slider (Speed) is also the one that looks right, which is the
# measurement: the tick-marked height is enough for the knob, and it is only a
# height -- a slider given it draws no ticks it wasn't asked for.
MAC_SLIDER_H = 24
# A spin control: room for its digits *and* its arrows. A width picked for the
# number alone leaves the arrows nowhere to go -- on GTK, where a GtkSpinButton
# draws them inside its own entry, they disappear behind the digits outright;
# elsewhere they merely crowd them. So this is a plain width for every
# platform, not a Linux workaround. It is the width to ask for; SpinCtrl widens
# anything narrower than the native control needs (see _fit_arrows), so the two
# together mean no caller can lose the arrows again.
SPIN_W = 90


# wx.Platform for the Cocoa port -- both spellings, as in gui.mac_scroll. It is
# the platform where a notch a control doesn't want reaches the page by itself,
# so nothing below binds anything (see no_scroll for what macOS does with the
# wheel and why standing in front of it is what broke the sliders), and the one
# where a slider has to be told how tall its knob is (MAC_SLIDER_H).
_MAC = ("__WXMAC__", "__WXOSX__")


def _redirect_wheel(event):
    """Scroll the enclosing ScrolledWindow by the wheel notch, instead of
    letting the control under the cursor act on it (a Choice/Slider would
    change value; a text field or button just swallows it, freezing the page).
    Bound by no_scroll / no_scroll_tree.

    Only reaching wx makes this the whole story. Where a native control eats
    the notch first -- GTK's slider and spin button do -- the value moves
    anyway and _WheelGuard below is what puts it back."""
    ctrl = event.GetEventObject()
    target = ctrl.GetParent()
    while target is not None and not isinstance(target, wx.ScrolledWindow):
        target = target.GetParent()
    if target is None:
        # No scroller above us (e.g. the wizard, which doesn't scroll): swallow
        # the wheel so it can't change the control's value; there is no page to
        # pan anyway.
        return
    delta = event.GetWheelDelta() or 120
    notches = event.GetWheelRotation() / delta
    target.ScrollLines(-round(notches * event.GetLinesPerAction()))


def no_scroll(ctrl):
    """Redirect mouse-wheel events over a Choice/Slider to the containing
    ScrolledWindow, so hovering the control while scrolling the dialog pans the
    page instead of silently changing the control's value -- the user must click
    to pick. Simply swallowing the wheel (not skipping) would leave the page
    frozen whenever the cursor is over the control. Idempotent (a guard flag
    lets no_scroll_tree re-cover an already-wrapped control harmlessly).
    Returns the control so callers can wrap creation inline.

    Not skipping is a veto of the control's *default* wheel action, which only
    binds where wx is in front of that action: on MSW, where an unskipped
    WM_MOUSEWHEEL is never passed to the control's own window proc. It does not
    bind on GTK -- see _WheelGuard, which the Slider/SpinCtrl below carry for
    exactly that reason.

    On macOS this binds nothing at all, which is the fix and not the omission
    it looks like. A notch there is an NSEvent offered to the view under the
    pointer and passed *up* the view hierarchy by anything that doesn't want
    it, and no native control wants it: an NSSlider or an NSPopUpButton leaves
    the wheel to the scroll view above it, the way every Mac application does.
    So the rule this function exists to enforce already holds -- the notch
    cannot change a value -- and the page already scrolls, from wx's own
    handler on the ScrolledWindow, which is also the one that accumulates the
    *fractional* deltas a trackpad reports and that whole-notch arithmetic here
    would drop.

    What binding costs there is the reason the sliders went missing. Answering
    the event on the control is what stops wx from passing it on, so the page
    would then have to be scrolled from here -- from inside the native view's
    own event dispatch, moving every child of the form, the hovered slider
    included, while AppKit is still walking it. That is the trap _revert
    already defers around on GTK, and on macOS it is not ours to take at all:
    the platform was going to scroll the page correctly on its own."""
    if wx.Platform in _MAC:
        return ctrl
    if not getattr(ctrl, "_no_scroll_bound", False):
        ctrl._no_scroll_bound = True
        ctrl.Bind(wx.EVT_MOUSEWHEEL, _redirect_wheel)
    return ctrl


def enable(ctrl, flag=True):
    """Make ``ctrl`` live or grey it out -- what ``ctrl.Enable(flag)`` says,
    said in the way that leaves the page scrolling on every platform. Returns
    the control, so a sync pass can chain off it.

    Use this for anything on a form that scrolls. A wx-disabled control on
    macOS swallows the mouse wheel outright -- the notch reaches neither wx nor
    the scroll view above it, so the page freezes wherever the pointer happens
    to rest on a greyed field, slider or button -- and gui.mac_enable is the
    way round that: it greys the native control and leaves the wx window
    enabled, which is what the notch is passed up by. Off macOS, and wherever
    that can't be done, this is ``Enable`` and nothing more."""
    if not mac_enable.grey(ctrl, flag):
        ctrl.Enable(flag)
    return ctrl


def native_scroll(ctrl):
    """Exempt a control from no_scroll / no_scroll_tree: the wheel keeps
    scrolling the control itself (the run log pans its own text) instead of
    being redirected to the page. Implemented by pre-setting no_scroll's guard
    flag, so a later no_scroll_tree pass skips the control without binding.
    Returns the control so callers can wrap creation inline."""
    ctrl._no_scroll_bound = True
    return ctrl


def no_scroll_tree(container):
    """Apply no_scroll to every descendant control of ``container`` (not the
    container itself), so a wheel notch scrolls the page from anywhere in the
    subtree -- over an input box, dropdown, checkbox or button alike -- and
    never changes a control's value. Call once after the subtree is built:
    fields added later are covered by the same call, and controls already
    wrapped inline with no_scroll are skipped by its guard flag. On macOS it
    walks the tree and binds nothing, for the reason no_scroll gives."""
    for child in container.GetChildren():
        no_scroll(child)
        no_scroll_tree(child)


class _WheelGuard:
    """Mix-in for a native control whose GTK peer moves *itself* on a mouse
    wheel notch: it undoes such a change instead of reporting it.

    no_scroll cannot prevent one. Not skipping the wheel event withholds a
    default action only where wx is in front of it, as on MSW: wx gets
    WM_MOUSEWHEEL first and hands it to the control's own window proc only if
    the event was skipped, so the value never moves. On GTK there is nothing to
    withhold -- a wx.Slider *is* a GtkScale and a wx.SpinCtrl a GtkSpinButton,
    each with its own scroll handler on its own event window, which consumes
    the notch (value and all) whether or not wx ever emits EVT_MOUSEWHEEL for
    it. Hence the difference users see: the wheel slides these controls on
    Linux and not on Windows.

    The cure is to take the notch away from the GTK widget, which is done a
    layer down (gtk_wheel.block_wheel, connected as the control is built):
    nothing then moves and there is nothing to correct. What remains here is
    the fallback for a build where that block doesn't take, since it is the
    fallback that decides what "the wheel did this" even means.

    That decision: value-change events come here first, and a change no
    deliberate input can account for -- no button held down (dragging a thumb,
    clicking a trough or a spin arrow), no keystroke in flight -- was the
    wheel's doing on GTK, so the control goes back where it was (``_revert``,
    on the next idle -- never from inside the callback that is still running)
    and the caller hears nothing. Off GTK every change is passed straight on:
    the wheel is already kept off these controls -- on MSW by no_scroll's veto,
    on macOS by the platform, which never offers a control the notch in the
    first place -- and second-guessing native input we never see is how real
    edits get eaten.

    Two things follow for callers. Bind through ``bind_change``, not
    ``Bind(EVT_SLIDER, ...)``: wx calls dynamic handlers newest-bound first, so
    a handler bound directly would run *before* this one and act on the wheel's
    value. And set values through ``SetValue``, which is deliberate by
    definition -- it is what a later notch is put back to.
    """

    # Class-level defaults: the value the user is accountable for, whether a
    # key is currently down, and the re-entry flag a revert sets.
    _committed = None
    _keying = False
    _reverting = False

    def _guard_wheel(self, events):
        """Cover the control three ways over, each picking up where the one
        before it stops: block the notch at the GTK widget (where it is the
        control's own doing), redirect it to the page with no_scroll (where wx
        is in front of that, i.e. MSW), and take over ``events`` -- the
        control's value-change events -- to undo whatever still gets through.
        Called from the concrete control's __init__, by when there is a value
        to remember."""
        self._committed = self.GetValue()
        self._handlers = []
        # Whether the notch is being stopped at the GTK widget, or only undone
        # here after the fact -- the one thing worth knowing when a build
        # behaves differently from another.
        self._wheel_blocked = gtk_wheel.block_wheel(self)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_KEY_UP, self._on_key_up)
        for event in events:
            self.Bind(event, self._on_change)
        no_scroll(self)

    def bind_change(self, handler):
        """Call ``handler(event)`` whenever the *user* changes the value. More
        than one may be registered; they run in the order they were added."""
        self._handlers.append(handler)

    def SetValue(self, value):
        super().SetValue(value)
        self._committed = self.GetValue()

    def _deliberate(self):
        """Is there a deliberate input that accounts for a value change?"""
        return self._keying or wx.GetMouseState().LeftIsDown()

    def _on_key_down(self, event):
        self._keying = True
        event.Skip()

    def _on_key_up(self, event):
        self._keying = False
        event.Skip()

    def _on_change(self, event):
        if self._reverting:
            return  # our own SetValue coming back round (GTK spin buttons do)
        if wx.Platform == "__WXGTK__" and not self._deliberate():
            if self.GetValue() != self._committed:
                self._revert()
            return
        self._committed = self.GetValue()
        for handler in self._handlers:
            handler(event)

    def _revert(self):
        """Put the control back where it was -- on the next idle, not here.

        Here is inside the native widget's own scroll handler: GTK is still
        walking the GtkScale/GtkSpinButton that sent this, and moving it from
        under itself takes KiCad down with the dialog. UnitSlider's focus-out
        commit is deferred for the same reason, and says so at more length.

        The flag holds until the move lands, so the events GTK is still about
        to send for the notch (a spin button sends two) don't each queue their
        own revert. A notch that gets this far is visible for a frame -- the
        thumb moves and springs back -- which is why this is the fallback and
        gtk_wheel.block_wheel, where nothing moves at all, is the fix."""
        self._reverting = True

        def settle():
            try:
                self.SetValue(self._committed)
            except RuntimeError:
                pass  # the control went away with the dialog
            finally:
                self._reverting = False

        wx.CallAfter(settle)


class Slider(_WheelGuard, wx.Slider):
    """A wx.Slider the mouse wheel cannot move, on GTK as well as MSW. Bind
    value changes with ``bind_change``, not EVT_SLIDER (_WheelGuard)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guard_wheel([wx.EVT_SLIDER])
        self._fit_knob()

    def _fit_knob(self):
        """Never be shorter than the knob macOS draws (MAC_SLIDER_H), the way
        SpinCtrl._fit_arrows is never narrower than its arrows: a caller's
        ``size=(w, -1)`` leaves the height to wx, and on macOS wx's answer for
        a plain slider is smaller than the knob, which is then cut off along
        the top. A slider that is already tall enough is left as it is -- the
        Speed slider's tick marks earn it that height from wx itself -- and off
        macOS nothing is touched at all: the native height is the right one
        there, and forcing this figure on a taller GtkScale would be the same
        mistake the other way round."""
        if wx.Platform not in _MAC or self.GetSize().y >= MAC_SLIDER_H:
            return
        # The width stands as it is: SetInitialSize takes -1 as "ask the theme"
        # and would spend the caller's fixed width on the slider's own idea of
        # one.
        self.SetInitialSize(wx.Size(self.GetSize().x, MAC_SLIDER_H))

    def SetRange(self, min_value, max_value):
        """Re-range, remembering where that left the value: a narrowed range
        clamps it, and the clamped position is the one to revert to."""
        super().SetRange(min_value, max_value)
        self._committed = self.GetValue()

    def _deliberate(self):
        """The focus counts here, on top of the shared tests. Arrow/Home/End
        move a focused scale, but wxGTK doesn't deliver those keystrokes for a
        native GtkScale, so having the focus has to stand in for them. The gap
        that leaves -- a notch over a slider the user has already clicked into
        still moves it -- is the cheaper mistake: eating keyboard input would
        break a way the slider is actually driven."""
        return super()._deliberate() or self.HasFocus()


class SpinCtrl(_WheelGuard, wx.SpinCtrl):
    """A wx.SpinCtrl the mouse wheel cannot move, on GTK as well as MSW. Bind
    value changes with ``bind_change``, not EVT_SPINCTRL/EVT_TEXT: both are
    covered, so the arrows and typing are heard once each, as before.

    Unlike Slider this does *not* let the focus stand in for a keystroke: a
    GtkSpinButton takes the focus when it scrolls, so by the time the value
    changes the control is focused either way. It doesn't need to -- a spin
    control's keystrokes go to its text field, and those wx does deliver."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guard_wheel([wx.EVT_SPINCTRL, wx.EVT_TEXT])
        self._fit_arrows()

    def _fit_arrows(self):
        """Never be narrower than the native control needs: a caller's fixed
        width becomes a floor of the theme's own best size instead of a
        promise the arrows have to fit inside.

        A wx.SpinCtrl is one control with two parts, and a width chosen by
        eyeballing the digits spends all of it on the entry -- on GTK the
        arrows are drawn *inside* that entry, so they end up behind the number
        and there is no way to click them. What "wide enough" means is the
        theme's business (font, arrow size, digits in the range), so ask the
        control rather than guess per platform: SPIN_W above is what the form
        asks for, this is what stops any width from being too little."""
        best = self.GetBestSize()
        if self.GetSize().x < best.x:
            self.SetInitialSize(wx.Size(best.x, -1))


def live_text(parent, on_edit, width, value="", style=0):
    """A text field whose edits take effect as they are typed: every keystroke
    calls ``on_edit`` (with no arguments -- no caller wants the event).

    The form's typed inputs are all live, none of them waiting for an Enter or
    a focus-out that may never come: the plugin's window is a frame beside the
    PCB editor, so "clicking away" from a field usually lands somewhere that
    never takes the focus off it -- dead space in the form, or KiCad's canvas
    in another window. This is the one place that wiring lives: the scan's
    min/max bounds, the cells-across-copper override and UnitSlider's editable
    readout are all this field.

    A programmatic refresh of such a field must use ``ChangeValue``, not
    ``SetValue``: it fires no EVT_TEXT, so writing the value back can't
    re-enter ``on_edit``.
    """
    ctrl = no_scroll(wx.TextCtrl(parent, value=value, size=(width, -1), style=style))

    def edited(event):
        event.Skip()
        on_edit()

    ctrl.Bind(wx.EVT_TEXT, edited)
    return ctrl


def set_tip(ctrl, text):
    """Set (or clear) a control's tooltip -- an empty string would otherwise
    leave an empty tooltip hanging on it. Used by the sections whose buttons
    change meaning (Run / Generate grid(s) / Start scan), which re-explain
    themselves on every state change."""
    if text:
        ctrl.SetToolTip(text)
    else:
        ctrl.UnsetToolTip()


def hyperlink(parent, label, url, tip=None):
    """A clickable link to ``url``: a real hyperlink where the host's wx has
    one (it opens the browser itself), else a button that does the same through
    wx. The URL goes on the tooltip either way -- unless ``tip`` says otherwise
    -- so it can be copied out of a window whose browser launch goes nowhere.

    Shared by the About page's links (sections.links) and the update strip's
    Download (update.strip): wx.adv is optional in a KiCad build, and one
    fallback is enough."""
    try:
        # ``from wx import adv``, never ``import wx.adv``: the latter binds the
        # name *wx* in this scope, so a host without wx.adv would fall into the
        # branch below with the module's own ``wx`` shadowed by an unbound
        # local.
        from wx import adv

        link = adv.HyperlinkCtrl(parent, label=label, url=url)
    except Exception:
        link = wx.Button(parent, label=label, style=wx.BU_EXACTFIT)
        link.Bind(
            wx.EVT_BUTTON,
            lambda event, target=url: wx.LaunchDefaultBrowser(target),
        )
    set_tip(link, url if tip is None else tip)
    return link


def muted(ctrl):
    """Grey a label out (system 'graytext' colour); returns the control so
    callers can wrap creation inline."""
    ctrl.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
    return ctrl


def emphasize(ctrl):
    """The opposite of ``muted``: put a label back to full-contrast window
    text -- for a line the user must not skip (a status line reporting a
    failure). The system colour, not a red of our own, so it stays readable
    under a dark theme. Returns the control, like ``muted``."""
    ctrl.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
    return ctrl


class WrapLabel(wx.StaticText):
    """A StaticText that fills its section's width and wraps long text to it.

    A plain StaticText lays out at its natural single-line width, so a long
    sentence runs off the page (the form only scrolls vertically). WrapLabel
    instead wraps to the page width: its page registers it
    (pages.base.BookPage.register_wrap) and re-wraps every WrapLabel on resize, and
    ``SetLabel`` re-wraps the new text to the last known width -- so a label
    whose text changes at runtime (a status line, a hint) stays wrapped too.

    ``Wrap`` is destructive -- it inserts line breaks into the label -- so the
    unwrapped text is kept in ``_raw`` and restored before each re-wrap.
    ``margin`` is the px trimmed off the page width for this label's own
    indentation (its nesting inside boxes / panes).
    """

    def __init__(self, parent, label="", margin=0):
        super().__init__(parent, label=label)
        self._raw = label
        self._margin = margin
        self._wrap_w = None  # width the label was last wrapped to

    def SetLabel(self, text):
        """Set the text and re-wrap it to the last known width."""
        self._raw = text
        super().SetLabel(text)
        if self._wrap_w is not None:
            self.Wrap(self._wrap_w)

    def rewrap(self, page_width):
        """Wrap to ``page_width`` minus this label's margin. Returns True when
        the wrap width changed (so the page can relayout once); guarded on
        width so the resize this can trigger doesn't re-enter endlessly."""
        w = max(page_width - self._margin, 120)
        if w == self._wrap_w:
            return False
        self._wrap_w = w
        super().SetLabel(self._raw)  # reset before re-wrapping
        self.Wrap(w)
        return True


_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def parse_leading_number(text):
    """The first number in ``text``, ignoring any unit suffix (so an editable
    UnitSlider readout like ``"12.5 mm"`` parses back to ``12.5``); ``None``
    when there is no number."""
    match = _NUMBER_RE.search(str(text))
    return float(match.group()) if match else None


def set_choice(choice, text):
    """Select entry ``text`` on a wx.Choice by label; an unknown/blank label
    keeps the current pick (so reordering the option lists can't silently
    restore another entry)."""
    if text and choice.FindString(text) != wx.NOT_FOUND:
        choice.SetStringSelection(text)


def set_slider(slider, text):
    """Move a wx.Slider to the integer position in ``text`` (wx clamps to the
    slider's range); a blank/non-numeric value leaves it alone."""
    if text is None:
        return
    try:
        slider.SetValue(int(text))
    except (TypeError, ValueError):
        pass


class UnitSlider:
    """A wx.Slider whose integer position is a fixed-point value in real
    units: ``value = position / scale`` (scale 100 -> hundredths of a mm,
    10 -> tenths, 1 -> the position itself, e.g. a percentage). It lays
    itself out as three cells of ``grid`` -- label, slider, value readout --
    owns the readout and keeps it in sync, and calls ``on_change`` when the
    user drags it. Consolidates the near-identical slider rows the feed-marker
    and area-marker dialogs each built by hand (both live-reshape a footprint
    off the slider). The scan's sliders are deliberately not built from this:
    their position maps into a *runtime* min/max, not a fixed scale.

    With ``editable=True`` the readout is a text field the user can type a
    precise value into: the typed number is parsed (unit suffix and all),
    clamped into range, moved to on the slider and pushed through
    ``on_change`` -- the same path a drag takes.

    The field is a ``live_text``, so that commit happens keystroke by
    keystroke -- like the scan's min/max bounds, and for the reason given
    there: a focus-out to commit on may never come. Two things follow from
    committing mid-edit. The readout is not written back while the field has
    the focus (``sync_label``), or normalising the value would fight the
    caret; the text is instead normalised to what the slider could take
    ("12.34" -> "12.3", a blank or unparsable entry back to the current value)
    on focus-out, deferred to the next idle so the focus has settled. And a
    commit that doesn't move the slider fires no ``on_change``, so half-typed
    numbers and the focus-out repeat don't each redraw what the caller draws.

    ``suffix`` puts the unit in a static label beside the field instead of
    inside it (so an editable field holds the bare number ``fmt`` produces,
    not "12.5 mm").
    """

    def __init__(
        self,
        grid,
        parent,
        label,
        rng,
        default,
        scale,
        on_change,
        fmt="{:g}".format,
        slider_w=220,
        value_w=72,
        editable=False,
        suffix="",
    ):
        self.scale = scale
        self.rng = rng
        self.fmt = fmt
        self._on_change = on_change
        self._editable = editable
        grid.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        self.slider = Slider(
            parent,
            value=default,
            minValue=rng[0],
            maxValue=rng[1],
            size=(slider_w, -1),
        )
        grid.Add(self.slider, 0, wx.ALIGN_CENTER_VERTICAL)
        if editable:
            # TE_PROCESS_ENTER with nothing bound to it: the value is already
            # committed by the time Enter is pressed, and the style keeps the
            # keystroke in the field instead of letting it reach the frame's
            # default button.
            self._readout = live_text(
                parent, self._commit, value_w, style=wx.TE_PROCESS_ENTER
            )
            self._readout.Bind(wx.EVT_KILL_FOCUS, self._on_kill_focus)
        else:
            self._readout = wx.StaticText(parent, label="", size=(value_w, -1))
        # The readout is the grid's third cell; a suffix rides alongside it in
        # that one cell (a static unit label after the field) so the grid stays
        # three columns wide.
        if suffix:
            cell = wx.BoxSizer(wx.HORIZONTAL)
            cell.Add(self._readout, 0, wx.ALIGN_CENTER_VERTICAL)
            cell.Add(
                wx.StaticText(parent, label=suffix),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                4,
            )
            grid.Add(cell, 0, wx.ALIGN_CENTER_VERTICAL)
        else:
            grid.Add(self._readout, 0, wx.ALIGN_CENTER_VERTICAL)
        self.slider.bind_change(lambda event: on_change())
        self.sync_label()

    def value(self):
        """The slider's position in real units."""
        return self.slider.GetValue() / self.scale

    def set_tip(self, text):
        """Explain the control: the tooltip goes on both halves of it. The
        slider and its readout are one knob, and a user who reaches for the
        box rather than the thumb wants the same sentence."""
        set_tip(self.slider, text)
        set_tip(self._readout, text)
        return self

    def set_value(self, v):
        """Move the slider to real-unit value ``v`` (clamped into range)
        without firing EVT_SLIDER, and refresh the readout."""
        self.slider.SetValue(self._position(v))
        self.sync_label()

    def _position(self, v):
        """Real-unit value ``v`` as a slider position, clamped into range."""
        return min(max(int(round(v * self.scale)), self.rng[0]), self.rng[1])

    def set_range(self, rng):
        """Re-range the slider (positions, like the constructor's ``rng``) --
        for an end that isn't fixed but read off the board, the way the area
        section caps its sides at the board outline's span. The current value
        is clamped into the new range and the readout refreshed, but
        ``on_change`` is *not* fired: the caller knows whether a clamp needs
        redrawing (it returns True when one happened) and would otherwise get
        one redraw per re-range. A range that hasn't changed does nothing."""
        rng = (rng[0], rng[1])
        if rng == tuple(self.rng):
            return False
        self.rng = rng
        before = self.slider.GetValue()
        self.slider.SetRange(rng[0], rng[1])
        self.slider.SetValue(min(max(before, rng[0]), rng[1]))
        self.sync_label()
        return self.slider.GetValue() != before

    def sync_label(self):
        """Refresh the value readout from the slider's current position (an
        editable readout is set without firing its own text event). A field
        the user is typing in is left alone: rewriting it would fight the
        caret, and _commit normalises it once the focus leaves."""
        text = self.fmt(self.value())
        if not self._editable:
            self._readout.SetLabel(text)
        elif not self._readout.HasFocus():
            self._readout.ChangeValue(text)

    def _commit(self):
        """Apply what the editable readout holds: parse it (unit suffix and
        all), move the slider to it (clamped) and fire ``on_change`` so the
        caller redraws live -- but only when that actually moved the slider,
        so a keystroke that doesn't change the value costs nothing. An entry
        with no number in it (blank, "-", a half-typed unit) leaves the slider
        where it is; sync_label puts it right when the focus leaves."""
        v = parse_leading_number(self._readout.GetValue())
        if v is None:
            return
        before = self.slider.GetValue()
        self.set_value(v)
        if self.slider.GetValue() != before:
            self._on_change()

    def _on_kill_focus(self, event):
        """The user left the field: commit a last time (the keystroke that
        typed this may have been swallowed by whatever took the focus) and
        normalise the text to what the slider actually holds.

        Deferred to the next idle for two reasons: the focus transition is
        still in flight here -- the field can still report itself focused, and
        sync_label would leave it alone -- and moving a slider or reshaping a
        board footprint from inside a focus handler is unreliable. By then the
        dialog may be gone, and a destroyed field raises rather than
        answering."""
        event.Skip()

        def settle():
            try:
                self._commit()
                self.sync_label()
            except RuntimeError:
                pass  # the field went away with the dialog

        wx.CallAfter(settle)
