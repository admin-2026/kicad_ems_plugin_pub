"""Enough of wx and pcbnew to build a section off KiCad.

The wizard's Scan section is generic over a design -- it builds its rows,
seeds, preview and scan spec from ``design.params`` -- and that logic is worth
testing directly rather than only through the modules under it. It lives on
widgets, though, so this installs stand-in ``wx`` / ``pcbnew`` modules: real
behaviour for the handful of controls the logic actually reads back (text
boxes, sliders, radio buttons, spin controls, dropdowns, the collapsible pane
the Advanced form is built into, the bundled images the rows illustrate
themselves with, and the tooltips those pictures put their names on) and inert
stand-ins for everything else (layout flags, events, colours). A sizer is inert
too, but remembers what went into it and — for a static box — its title.

This is a harness, not a wx conformance test: it proves the section drives its
*own* state correctly (which parameter is swept, what each row holds, what
spec comes out), not that wx lays anything out. Anything wx-shaped it can't
answer, it answers with a do-nothing.
"""

import sys
import types


class _Event:
    """The event object handlers are called with: they only ever Skip() it."""

    def Skip(self, skip=True):
        pass


class _Size:
    """A wx.Size: the two fields anything here reads off one, under both the
    names wx gives them (``x``/``y`` and ``width``/``height``)."""

    def __init__(self, x=-1, y=-1):
        self.x = x
        self.y = y

    @property
    def width(self):
        return self.x

    @property
    def height(self):
        return self.y

    def __repr__(self):
        return f"Size({self.x}, {self.y})"


def _as_size(value):
    """A widget's ``size=`` argument as a _Size -- wx takes either a tuple or
    a wx.Size there, and so do the controls this stands in for."""
    return value if isinstance(value, _Size) else _Size(*value)


class _Widget:
    """The default control: swallows construction and every layout call, and
    remembers whether it is enabled, whether it has the keyboard focus, its
    tooltip, its size, and what it bound to which event -- so a test can drive
    a handler with ``fire("EVT_TEXT")`` the way wx would.

    The size is real because a control may widen itself against it
    (widgets.SpinCtrl._fit_arrows): the requested ``size=`` is what it has, and
    ``best_size`` is the theme's own -- which a stub has no business inventing,
    so it is the requested size until a test says otherwise."""

    def __init__(self, *args, **kwargs):
        self.enabled = True
        self.focused = False
        self.tooltip = ""
        self._label = kwargs.get("label", "")
        self._size = _as_size(kwargs.get("size", (-1, -1)))
        self.best_size = None  # None: no opinion, so GetBestSize is the size

    def Bind(self, event, handler=None, *args, **kwargs):
        # setdefault, not __init__: a widget whose subclass skipped super()
        # still records its bindings.
        self.__dict__.setdefault("handlers", {})[event] = handler

    def fire(self, name, event=None):
        """Call this widget's handler for ``wx.<name>`` (a no-op when nothing
        is bound to it), as wx would when the event happens."""
        handler = self.__dict__.get("handlers", {}).get(
            getattr(sys.modules["wx"], name)
        )
        if handler is not None:
            handler(event if event is not None else _Event())

    def HasFocus(self):
        return self.focused

    def SetFocus(self):
        self.focused = True

    def Enable(self, enable=True):
        self.enabled = enable

    def Show(self, show=True):
        self.shown = show

    def Hide(self):
        self.shown = False

    def SetLabel(self, text):
        self._label = text

    def GetLabel(self):
        return self._label

    # Real, not swallowed: a scan row shows a picture instead of the
    # parameter's name, so the tooltip is where that name still is.
    def SetToolTip(self, text):
        self.tooltip = text

    def UnsetToolTip(self):
        self.tooltip = ""

    def Wrap(self, width):
        pass

    def GetSize(self):
        return self._size

    def GetBestSize(self):
        return self.best_size if self.best_size is not None else self._size

    def SetInitialSize(self, size):
        self._size = _as_size(size)

    def GetClientSize(self):
        return self._size

    def GetChildren(self):
        # A stub has no widget tree, but the callers that walk one (the wheel
        # guard over a built page) must get something to iterate rather than
        # the do-nothing __getattr__ answers with.
        return []

    def __getattr__(self, name):
        # SetForegroundColour, SetToolTip, SetRange, Refresh, ... -- anything
        # this harness has no opinion about. Only wx's own names, though: a
        # leading capital is wx's convention and never this project's, and a
        # widget that answered to *every* name would break the plugin's own
        # `getattr(page, "advanced", None)` -- which asks whether a section has
        # been built yet, and would be told yes by a stand-in.
        if not name[:1].isupper():
            raise AttributeError(name)
        return lambda *args, **kwargs: None


class _TextCtrl(_Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = kwargs.get("value", "")
        # Real, not swallowed: an Advanced field's placeholder is where its
        # default AND the config key it writes are said (gui.theme.hint_with_key),
        # so a test can read what the empty box tells the user.
        self._hint = ""

    def SetHint(self, text):
        self._hint = text

    def GetHint(self):
        return self._hint

    def GetValue(self):
        return self._value

    def SetValue(self, text):  # fires EVT_TEXT in wx
        self._value = text

    def ChangeValue(self, text):  # sets without firing EVT_TEXT
        self._value = text

    # The multiline half: a log control appends to itself, empties itself and
    # is read back to see what a run said (gui.sections.log). Real, because
    # ``Clear`` is *overridden* there -- a swallowed one would leave the
    # override's ``super().Clear()`` with nothing to call, which is not
    # something a stand-in may quietly answer for.
    def AppendText(self, text):
        self._value += text

    def Clear(self):
        self._value = ""

    def type(self, text):
        """A keystroke: the field takes the focus, now holds ``text``, and
        fires EVT_TEXT -- what wx does for typing (and not for ChangeValue)."""
        self.focused = True
        self._value = text
        self.fire("EVT_TEXT")


class _CheckBox(_Widget):
    """A checkbox that really holds its tick: the simulation-time row
    (gui.sections.simtime) reads one back to decide whether the run length is
    the ring-down or the number in the box beside it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = False

    def GetValue(self):
        return self._value

    def SetValue(self, value):  # fires no event in wx either
        self._value = bool(value)

    def click(self, value):
        """A click: the box takes the new state and fires EVT_CHECKBOX."""
        self._value = bool(value)
        self.fire("EVT_CHECKBOX")


class _ActivityIndicator(_Widget):
    """wx.ActivityIndicator: the spinner the About page's command-line box
    shows in the checkbox's place while it writes (gui.sections.cli). It holds
    whether it is running, so a test can tell a spinner that was started from
    one that was only made."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = False

    def Start(self):
        self.running = True

    def Stop(self):
        self.running = False


class _MouseState:
    """wx.GetMouseState(): only the left button is asked about (the wheel guard
    in gui/widgets.py reads it to tell a drag from a wheel notch). ``adjust``
    below is what holds it down."""

    left_down = False

    def LeftIsDown(self):
        return _MouseState.left_down


class _Slider(_Widget):
    """A slider with a real range: the area section re-ranges its side sliders
    off the board outline, so the ends are state a test reads back (and wx
    clamps a value to them, which the caller relies on).

    Its two ways of being moved are kept apart, because the plugin's slider
    (widgets.Slider) keeps them apart: ``adjust`` is the user, ``wheel`` is a
    notch the native GTK widget acted on by itself."""

    _change_event = "EVT_SLIDER"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._min = kwargs.get("minValue", 0)
        self._max = kwargs.get("maxValue", 100)
        self._value = kwargs.get("value", 0)

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = min(max(value, self._min), self._max)

    def SetRange(self, min_value, max_value):
        self._min, self._max = min_value, max_value
        self.SetValue(self._value)

    def GetMin(self):
        return self._min

    def GetMax(self):
        return self._max

    def _move(self, value):
        """Move the native widget behind wx's back, as both a drag and a GTK
        wheel notch do -- not through SetValue, which the guard reads as a
        deliberate change made from code."""
        if value is not None:
            _Slider.SetValue(self, value)

    def adjust(self, value=None):
        """The user works the control by hand (dragging the thumb, clicking the
        trough or a spin arrow): the left button is down while the change event
        fires, which is what marks the change deliberate."""
        self._move(value)
        _MouseState.left_down = True
        try:
            self.fire(self._change_event)
        finally:
            _MouseState.left_down = False

    def wheel(self, value):
        """A wheel notch over the control on GTK: the native widget moves
        itself and the change event arrives with no button down and no
        keystroke behind it."""
        self._move(value)
        self.fire(self._change_event)


class _RadioButton(_Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = False

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = bool(value)


class _SpinCtrl(_Slider):
    """Same value/range behaviour as the slider, but wx spells its ends
    ``min`` / ``max`` and its start ``initial``, and its arrows fire their own
    event."""

    _change_event = "EVT_SPINCTRL"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._min = kwargs.get("min", 0)
        self._max = kwargs.get("max", 2**31 - 1)
        self._value = kwargs.get("initial", 0)


class _Image(_Widget):
    """A bundled PNG, for the icon loader (gui/icons.py): it reports the size
    it was last scaled to and returns itself from the transforms, so the loader
    runs end to end on a real file without decoding one. ``size`` / ``alpha``
    are what a test asserts the loader asked for."""

    def __init__(self, path=None, *args, **kwargs):
        super().__init__()
        self.path = path
        self.size = (0, 0)
        self.alpha = 1.0

    def GetWidth(self):
        return self.size[0]

    def GetHeight(self):
        return self.size[1]

    def Scale(self, width, height, *args):
        self.size = (width, height)
        return self

    def AdjustChannels(self, _r, _g, _b, alpha=1.0):
        self.alpha = alpha
        return self


class _Bitmap(_Widget):
    """wx.Bitmap(image): keeps the image, so a test can see which one a
    control was given."""

    def __init__(self, image=None, *args, **kwargs):
        super().__init__()
        self.image = image


class _StaticBitmap(_Widget):
    """A control showing one of those images -- it remembers which, so a test
    can read back the picture a row is currently wearing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bitmap = kwargs.get("bitmap")

    def SetBitmap(self, bitmap):
        self.bitmap = bitmap

    def GetBitmap(self):
        return self.bitmap


class _Sizer(_Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = []
        # A StaticBoxSizer's title (its third positional argument, and the only
        # string any sizer takes). The plugin's own sections are headed by a
        # label inside the sizer instead (gui.theme), so a test asking which
        # boxes a pane built reads that label off ``items[0]``; this is here for
        # a caller that still builds wx's own titled box.
        self.title = next((a for a in args if isinstance(a, str)), "")

    def Add(self, item, *args, **kwargs):
        self.items.append(item)

    def GetItemCount(self):
        return len(self.items)


class _Choice(_Widget):
    """A dropdown that remembers its items and its pick, so the pane's pickers
    (marker layer, ground check, metal model) can be read back and set the way
    a snapshot/restore does. wx.NOT_FOUND (-1) is "nothing picked", which is
    what an empty choice answers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = list(kwargs.get("choices", []))
        self.selection = -1

    def Append(self, item):
        self.items.append(item)

    def Clear(self):
        self.items = []
        self.selection = -1

    def GetCount(self):
        return len(self.items)

    def SetSelection(self, index):
        self.selection = index

    def GetSelection(self):
        return self.selection

    def FindString(self, text):
        return self.items.index(text) if text in self.items else -1

    def GetStrings(self):
        """What the dropdown offers, in order -- how a test reads a picker
        built from a table (emkit.choices) without knowing this stub keeps
        them in ``items``."""
        return list(self.items)

    def GetStringSelection(self):
        if 0 <= self.selection < len(self.items):
            return self.items[self.selection]
        return ""

    def SetStringSelection(self, text):
        if text in self.items:
            self.selection = self.items.index(text)


class _Pane(_Widget):
    """The window inside a collapsible pane. It keeps the sizer set on it, so
    a test can walk what was built in there (the base swallows SetSizer like
    every other layout call)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sizer = None

    def SetSizer(self, sizer):
        self.sizer = sizer


class _CollapsiblePane(_Widget):
    """A collapsible pane that really has a child window: the Advanced pane
    builds its whole form into ``GetPane()``, so this has to answer a window
    rather than the base's do-nothing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pane = _Pane()

    def GetPane(self):
        return self.pane


class _SystemSettings:
    @staticmethod
    def GetColour(_which):
        return None


def _install():
    """Put the stand-in ``wx`` and ``pcbnew`` in sys.modules (once)."""
    if "wx" in sys.modules and getattr(sys.modules["wx"], "_is_stub", False):
        return sys.modules["wx"]

    wx = types.ModuleType("wx")
    wx._is_stub = True
    wx.StaticText = _Widget
    wx.TextCtrl = _TextCtrl
    wx.CheckBox = _CheckBox
    wx.Slider = _Slider
    wx.RadioButton = _RadioButton
    wx.SpinCtrl = _SpinCtrl
    wx.Button = _Widget
    wx.Gauge = _Widget
    wx.ActivityIndicator = _ActivityIndicator
    wx.Image = _Image
    wx.Bitmap = _Bitmap
    wx.StaticBitmap = _StaticBitmap
    wx.Choice = _Choice
    wx.CollapsiblePane = _CollapsiblePane
    wx.Size = _Size
    wx.BoxSizer = _Sizer
    wx.StaticBoxSizer = _Sizer
    wx.FlexGridSizer = _Sizer
    wx.NOT_FOUND = -1
    wx.SystemSettings = _SystemSettings
    wx.CallAfter = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    # GTK is the platform the wheel guard (gui/widgets.py) is live on, so it is
    # the one the harness plays: a test that fires a value-change event has to
    # go through ``adjust`` / ``wheel``, the way the real controls make the
    # dialog. A test that wants the other side sets wx.Platform itself.
    wx.Platform = "__WXGTK__"
    wx.GetMouseState = _MouseState

    # Unknown wx names are made up on demand and cached, so each one keeps its
    # identity: a widget class for a CamelCase name, and a distinct bit for a
    # SHOUTING one -- the layout flags and event ids, which callers OR together
    # (wx.EXPAND | wx.TOP) and hand straight back to a stub that ignores them.
    made = {}
    bit = [0]

    def _missing(name):
        if name not in made:
            if name.isupper():
                made[name] = 1 << bit[0]
                bit[0] += 1
            else:
                made[name] = type(name, (_Widget,), {})
        return made[name]

    wx.__getattr__ = _missing

    pcbnew = types.ModuleType("pcbnew")
    pcbnew._is_stub = True
    pcbnew.GetBoard = lambda: None
    pcbnew.Refresh = lambda: None
    # The base class KiCad hands the toolbar button. It lives here rather than
    # in a test because the module that subclasses it is imported once for the
    # whole run: a second stand-in installed later would leave the class
    # subclassing the first one, and `issubclass` false against the second.
    pcbnew.ActionPlugin = type("ActionPlugin", (), {})

    sys.modules["wx"] = wx
    sys.modules["pcbnew"] = pcbnew
    return wx


wx = _install()
