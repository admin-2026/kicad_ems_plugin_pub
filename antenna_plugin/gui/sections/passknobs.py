"""The knobs of the *pass*, built by the section that starts one.

A run (sections.run) and a scan (sections.scan) both hand the solver two
decisions that are about the pass rather than about the antenna being designed:

    Simulation time      how long to step for -- Auto (ring-down) until the
                         feed port has rung down, or a fixed number of ns
    Ground/source        Auto: whether the solver may find and attach the
                         board's ground (or source) reference itself

Both sit beside the button that spends them instead of on the design-target
form or down in the Advanced pane, because they are what somebody changes on
the way to pressing it. They are still ONE value each: the rows ride the shared
datastore (gui.model.FormModel) like every other field of the design form, so a
designer's scan and the verification run that follows it are solved the same
way, whichever section they were set in.

None of these is a :class:`~antenna_plugin.gui.sections.base.Section` -- they
have no frame of their own, they are lines inside somebody else's. A section
builds one :class:`PassKnobs`, adds ``knobs.sizer`` where it wants it, and gets
back what a shared form field owes its page: ``snapshot`` / ``restore`` (the
model and the settings file), ``contribute`` (the run params) and ``sync``
(re-derive what a restore can't fire an event for). ``PassKnobs`` answers all
four for every row it holds, so a page names its knobs once
(``pages.designform.DesignFormPage.pass_knobs``) and a third knob is added here
rather than in both sections.
"""

import wx

from ..theme import HAIR, PAD, ROW
from ..widgets import bool_str, muted, parse_bool, set_tip, to_float


class SimTimeRow:
    """How long the solver steps for: an "Auto (ring-down)" tick that greys out
    a hand-typed ns field.

    ``LABEL`` names the knob in the grid's first column and in the error a bad
    ns value raises; the tick says what *automatic* means for it, so the two
    knobs read as one pair (see PassKnobs)."""

    LABEL = "Simulation time"
    CHECK_LABEL = "Auto (ring-down)"

    def __init__(self, parent, relayout=None):
        """Build the row's controls on ``parent`` (the label is PassKnobs').
        ``relayout`` is called when the ns field appears or goes away (the row
        changes width, and on a section whose height follows it, its height
        too)."""
        self._relayout = relayout
        self.auto = wx.CheckBox(parent, label=self.CHECK_LABEL)
        self.auto.SetValue(True)
        self.auto.Bind(wx.EVT_CHECKBOX, self.sync)
        set_tip(
            self.auto,
            "Solve until the feed port has rung down, however long that "
            "takes; uncheck to stop after a fixed number of nanoseconds",
        )
        self.value = wx.TextCtrl(parent, value="", size=(70, -1))
        self.value.Enable(False)
        # "ns" suffix, shown only when Auto is unchecked (a value is typed).
        self.unit = muted(wx.StaticText(parent, label="ns"))
        self.unit.Hide()

        self.controls = wx.BoxSizer(wx.HORIZONTAL)
        self.controls.Add(self.auto, 0, wx.ALIGN_CENTER_VERTICAL)
        self.controls.Add(self.value, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, ROW)
        self.controls.Add(self.unit, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, HAIR)

    # --- form sync ------------------------------------------------------------
    def sync(self, event=None):
        """Auto ring-down checked: grey out the ns field (time_ns -> 0) and hide
        its unit; unchecked reveals the field and its 'ns' suffix."""
        active = not self.auto.GetValue()
        self.value.Enable(active)
        self.unit.Show(active)
        if self._relayout is not None:
            self._relayout()

    # --- shared-form state (model / persistence) ------------------------------
    def snapshot(self):
        """The row as a flat string dict (see gui.model / settings)."""
        return {
            "time_auto": bool_str(self.auto.GetValue()),
            "time": self.value.GetValue(),
        }

    def restore(self, data):
        """Set the row from a ``snapshot`` dict without firing edit events; the
        caller re-derives the greying (``sync``)."""
        if "time_auto" in data:
            self.auto.SetValue(parse_bool(data["time_auto"]))
        if "time" in data:
            self.value.ChangeValue(data["time"])  # ChangeValue: no EVT_TEXT

    # --- run parameters -------------------------------------------------------
    def contribute(self, params):
        """Add the run length to a run's params, parsed strictly and naming the
        field -- never silently substituted."""
        if self.auto.GetValue():
            time_ns = 0.0  # 0 = run until the port rings down
        else:
            time_ns = to_float(self.value.GetValue(), None)
            if time_ns is None or time_ns <= 0:
                raise RuntimeError(
                    f"{self.LABEL}: enter a positive number of ns, or "
                    "check Auto (ring-down)"
                )
        params["time_ns"] = time_ns


class AutoGroundRow:
    """Whether the solver may find the board's ground (or source) reference and
    attach the port's return side to it, rather than being told where it is.

    "Ground" is the monopole reading of it -- the pour the quarter wave works
    against -- but the same search feeds a bipolar antenna's *source* arm, which
    is why the label names both ("Ground/source", read with the tick beside it:
    "Ground/source — Auto"). Off leaves the port's return side exactly as
    drawn (and the Ground check in the Advanced pane says whether that is a DC
    path at all). How far from the feed the search may reach is the Advanced
    pane's Auto ground/source radius, beside that check: the bound belongs with
    the numbers, the switch with the button that runs it.

    Independent of the Speed/accuracy slider -- it changes what is simulated,
    not how finely -- so it is not bound to ``speed.on_override`` and never
    snaps the slider to "Custom"."""

    LABEL = "Ground/source"
    CHECK_LABEL = "Auto (solver detects the reference)"

    def __init__(self, parent):
        self.check = wx.CheckBox(parent, label=self.CHECK_LABEL)
        self.check.SetValue(True)
        set_tip(
            self.check,
            "Let the solver find the ground (or source) reference the port "
            "returns through and strap the port to it; uncheck to drive the "
            "board exactly as drawn",
        )
        self.controls = wx.BoxSizer(wx.HORIZONTAL)
        self.controls.Add(self.check, 0, wx.ALIGN_CENTER_VERTICAL)

    # --- form sync ------------------------------------------------------------
    def sync(self, event=None):
        """Nothing to re-derive: the tick is the whole state (the contract's
        no-op arm, so PassKnobs can sync every row alike)."""

    # --- shared-form state (model / persistence) ------------------------------
    def snapshot(self):
        return {"auto_ground": bool_str(self.check.GetValue())}

    def restore(self, data):
        if "auto_ground" in data:
            self.check.SetValue(parse_bool(data["auto_ground"]))

    # --- run parameters -------------------------------------------------------
    def contribute(self, params):
        params["auto_ground"] = self.check.GetValue()


class PassKnobs:
    """Every knob of the pass, stacked, with one of each contract method over
    the lot: what a section builds and what a page hands round (see the module
    docstring). The rows are reachable by name (``knobs.time``,
    ``knobs.auto_ground``) for anything that needs one of them alone.

    Two columns -- each row's ``LABEL``, then its controls -- so the ticks line
    up under each other however long the labels are, and every row reads the
    same way: the knob is named on the left and its box says what leaving it
    ticked does ("Auto (ring-down)", "Auto (solver detects the reference)").
    A knob is described once, in one column, rather than in a sentence whose
    length decides where the next box starts."""

    def __init__(self, parent, relayout=None):
        self.time = SimTimeRow(parent, relayout)
        self.auto_ground = AutoGroundRow(parent)
        self.rows = (self.time, self.auto_ground)
        self.sizer = wx.FlexGridSizer(2, HAIR, PAD)
        for row in self.rows:
            self.sizer.Add(
                wx.StaticText(parent, label=row.LABEL), 0, wx.ALIGN_CENTER_VERTICAL
            )
            self.sizer.Add(row.controls, 0, wx.ALIGN_CENTER_VERTICAL)

    def sync(self):
        for row in self.rows:
            row.sync()

    def snapshot(self):
        data = {}
        for row in self.rows:
            data.update(row.snapshot())
        return data

    def restore(self, data):
        for row in self.rows:
            row.restore(data)

    def contribute(self, params):
        for row in self.rows:
            row.contribute(params)
