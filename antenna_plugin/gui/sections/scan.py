"""Section 2: the parameter scan — one row per knob of whichever design the
page carries.

Every geometry parameter the design declares (``design.params``: an L-shaped
monopole's length / width / stem, an inverted-F's length / width / height /
tap) gets a row of radio button + illustration + min / slider / max / value.
The radio picks the ONE parameter the scan sweeps: its min/max bound the sweep
and its slider previews a candidate inside them, and its value box is
read-only, being the slider's readout. The other rows grey out their min/max
and slider — a range means nothing to a parameter nobody sweeps — but their
value box stays typeable: that number is the fixed value every candidate
shares, so a fixed parameter is set by typing it rather than by selecting the
row to free its slider. Moving the active slider draws the candidate at that
value straight into the placed area marker, on the copper layer the main
dialog's Feed layer pick names (also the layer the scan splices candidates
into), so the swept shape is visible on the board before anything is
simulated. The preview is real copper on the marker, so the scan strips it
before plotting gerbers (and redraws it after), and placing the final
footprint clears it.

A row's label *is* the picture of its own knob (``Param.icon``, drawn by
tools/icons/scan.py): the design's antenna with the ends of *that* parameter's
range ghosted around it and the swept quantity dimensioned. Words can name a
parameter, but only the drawing can point at the copper it moves — so the
drawing is the whole of the row's answer to "which one is this?", and the name
that used to sit beside it is gone from the row. The name is a hover away (the
picture's tooltip and the radio's), and nothing spells out in prose what
sweeping the knob does, because the drawing already has. The picture fades with
the rest of the row when the row isn't the swept one, and clicking it selects
the row, the way its radio does. Only a knob a design ships no artwork for
falls back to wearing its name — a row has to say which one it is, one way or
the other.

A candidate that no longer fits the area is still drawn — **on the marker's own
User layer instead of on copper** (design.fit solves it in a rectangle grown
until it does hold, area_marker.marker_layer says where to put it). So the
antenna never silently vanishes off the board: it hangs out of the rectangle,
in the marker's colour, showing exactly how much too big it is and which way
to drag the area slider. Only copper the design fits inside the area is drawn
as copper, so nothing that couldn't be fabricated is ever shown as metal, and
nothing that isn't metal is ever spliced. The status line here names the layer
it went on and why, in full contrast rather than muted grey.

That is the *previewed* candidate. The **sweep's** candidates that don't fit
are skipped by the pass rather than simulated (wizard_scan.Plan), which is
invisible on the board — a sweep of five that runs three looks exactly like a
sweep of three. So ``plan_problems`` hands the area banner one warning saying
how many went and why, and unlike the overlap check it does not wait for a
pass to be started: the point of it is to be read before the scan is paid for.
It follows the rows, so the bounds, the swept row and the candidate count all
re-check it as they change.

Nothing here is topology-specific: the rows, their seeds (``design.params``'
Seed, in quarter waves so they follow the target frequency), the preview and
the spec are all built from the design object the page was constructed with. A
new design needs no edit in this file.

The rows outlive the window: bounds hand-tuned to one board's area are worth
keeping, so ``snapshot`` / ``restore`` put them in the project's settings file
under keys namespaced by design (gui.settings, the same per-section contract
the simulate view's sections use). They do not outlive the *area*, though —
placing a new area marker calls ``reset_params`` and the rows go back to the
design's seeds.

The target frequency comes from the wizard's own Pattern-frequency section (a
second view onto the shared model the simulate view uses, so a later
verification run matches); the feed layer is borrowed from the simulate view.
Both reach the scan through host.WizardHost. How long each candidate is solved
for, and whether the solver finds its own ground/source, are this section's own
knobs (sections.passknobs, built beside the buttons that spend them and reaching
the candidates through the shared run params); they ride the same model, so the
verification run matches there too. The scan spec adds the area section's
decoded marker and feed gap (AreaSection.spec()).
wizard_scan.run_scan does the work on a daemon thread; each candidate is scored
from its pcb_data.json dump, and the finished scan writes the scan_report /
scan_grid manifests (scan_views.py) naming every candidate's pcb_<kind>.js dump,
into the scan folder (simulate.scan_dir, one per design).

Two buttons start that loop, and both take the same path (``_start(grid_only)``
-> ``_prepare`` on the main thread -> ``_worker``): Start scan simulates every
candidate and scores it, while Generate grids meshes them all and solves none
-- the scan-wide twin of the simulate view's Generate grid, for checking the
meshes a sweep produces before paying for it. A grid pass writes only the
combined grid view and leaves the last scan's results (and the footprint
section's pick) alone, since it measures nothing. Either pass splices copper
into the feed layer, so either one hands the wizard's advisory overlap check
the copper it judges (``spliced_copper``) — before one is started that check
has nothing to say.

Showing the views belongs to the Results section below this one
(sections.results.ScanResultsSection): this section only says "a fresh set
landed" (``page.results.show_all``) and knows nothing about viewer windows. The
best result feeds section 3's footprint — and so, through
``current_candidate``, do the rows themselves: the shape being previewed is
offered as a row of that section's chooser, beside the scanned candidates, so
it can be placed without any pass having been run.

The results outlive the window as the views do: a finished scan writes its rows
and the spec they were measured under into the same folder
(design.scan_store), and ``load_saved`` reads them back when a wizard opens on
a board that was scanned in an earlier session. So closing the plugin no longer
costs a sweep -- the candidates are still there to place, and only what the
wizard *says* about them changes (``saved_scan``).
"""

import pcbnew
import wx

from ...design import fit, sizing
from ...markers import area_marker
from .. import icons
from ..theme import PAD, ROW
from ..widgets import (
    SPIN_W,
    Slider,
    SpinCtrl,
    emphasize,
    live_text,
    muted,
    set_tip,
    to_float,
)
from .passknobs import PassKnobs
from .solver import SolverSection

# Candidates a sweep may produce: the SpinCtrl's range, its initial value (what
# reset_params puts back) and the clamp a restored count goes through -- the
# settings file is a text file somebody may edit.
#
# One is a sweep too: a lone candidate sits in the middle of the row's range
# (sizing.ladder / sizing.sweep_values), which on the automatic length ladder is
# the lambda/4 estimate itself -- the cheap "simulate this one shape" pass, and
# the auto ladder still refines it from the single resonance it measured.
COUNT_RANGE = (1, 50)
COUNT_DEFAULT = 5

# The row illustrations (Param.icon). Shown at the size the artwork was drawn
# to read at: a whole antenna with a ghosted sweep and a dimension mark on it
# is a drawing, not a glyph, and it is the row's *label* rather than a bullet
# beside one -- at icon size the difference between two of them was a squint.
# 96 px is what those parts read at; the bundled PNGs are 192 (tools/icons/
# scan.py), so a HiDPI display has one to scale from. The rows are as tall as
# this, so the section grows with it -- the form scrolls (pages.base).
#
# A fixed row's picture is faded rather than greyed: same drawing, quieter,
# beside the greyed-out controls it belongs to.
ICON_SIZE = 96
ICON_FADED_ALPHA = 0.35

# The status line at rest -- before any pass, and again after a scan that
# finished: what it measured is on the results page that opened with it, so
# nothing about the winner is repeated here.
READY = "Ready."


class ScanSection(SolverSection):
    _TITLE = "Scan"

    # Why Generate grids is unavailable while a pass is on (SolverSection).
    _BUSY_TIP = "Available when no scan or grid pass is in flight"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)  # _session / _running / _cancelled
        self.design = page.design  # the topology this page designs
        self._results = []  # every result of the last scan, best-first
        self._ctx = None  # geometry inputs the result belongs to
        # The saved scan those results were read back from (design.scan_store),
        # None while they are this session's own (see load_saved).
        self._saved = None
        self._total = 0  # candidates the running pass will produce
        self._done = 0  # candidates it has finished (gauge)
        self._grid_only = False  # this pass meshes candidates, solves none
        # What the last started pass splices into the feed layer, and the spec
        # it was solved in: (frame, rects), None until a pass is started and
        # None again once a placement has consumed it (forget_splice). The
        # advisory overlap check reads it -- see spliced_copper.
        self._spliced = None
        # A preview is *wanted* on the marker. Sticky, because a redraw that
        # can't be made at all wipes the drawn shape (_preview_failed):
        # without this the board alone would say "no preview", and fixing the
        # inputs would never bring the antenna back (see refresh_preview).
        self._preview_on = False
        # Row values (mm) that came back from the settings file and haven't met
        # the frequency seeding yet, which would otherwise overwrite them --
        # see restore / seed_from_freq.
        self._restored = {}
        self._build_scan(body)

    @property
    def busy_label(self):
        """How another section names this one's pass when it warns about
        starting a second (SolverSection.confirm_concurrent) -- named by its
        design, since that is the tab to go to. Only read while this pass is in
        flight, so ``_grid_only`` is its own."""
        kind = "grid pass" if self._grid_only else "scan"
        return f"the {self.design.name} {kind}"

    # --- construction ---------------------------------------------------------
    def _build_scan(self, body):
        p = self.scroll
        box = self.box(self._TITLE)

        # One row per geometry parameter of the design: the radio picks the
        # swept one, whose min/max bound the sweep and whose slider previews a
        # candidate inside them; the other rows grey out all but their value
        # box, which is typed with the fixed value every candidate shares. The
        # feed gap is fixed at the runner's default (section 1,
        # AreaSection.FEED_GAP_MM).
        #
        # Six columns, (vgap, hgap) = (ROW, PAD): the rows are as tall as an
        # illustration (ICON_SIZE), so they need air between the pictures and
        # clear of the boxes beside them, and their controls sit centred in
        # that height (one line, so the columns stay scannable top to bottom).
        grid = wx.FlexGridSizer(6, ROW, PAD)
        self._radio, self._lo, self._hi = {}, {}, {}
        self._sl, self._val = {}, {}
        self._icon = {}  # key -> (StaticBitmap, lit, faded)
        grid.Add((0, 0))  # the radio column
        grid.Add((0, 0))  # the illustration column (the row's label)
        for text in ("min (mm)", "", "max (mm)", "value (mm)"):
            grid.Add(muted(wx.StaticText(p, label=text)), 0, wx.ALIGN_CENTER_HORIZONTAL)
        for i, param in enumerate(self.design.params):
            self._param_row(grid, param, rb_group=(i == 0))
        box.Add(grid, 0)
        self._radio[self.design.LENGTH_KEY].SetValue(True)
        self._seed_absolute()

        # Scan knobs. The copper layer the preview is drawn on and the scan
        # splices candidates into is the main dialog's Feed layer pick, not a
        # field here (see _feed_layer_name).
        knobs = wx.BoxSizer(wx.HORIZONTAL)
        knobs.Add(wx.StaticText(p, label="Candidates"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.count = SpinCtrl(
            p,
            min=COUNT_RANGE[0],
            max=COUNT_RANGE[1],
            initial=COUNT_DEFAULT,
            size=(SPIN_W, -1),
        )
        set_tip(
            self.count,
            "How many values of the swept parameter are simulated "
            f"({COUNT_RANGE[0]}–{COUNT_RANGE[1]}). "
            "1 runs a single candidate, in the middle of the row's range — "
            "the λ/4 estimate on the automatic length ladder",
        )
        # How many candidates are asked for is half of "the area holds only 2
        # of the 5 you asked for", so the banner re-reads the plan when it
        # changes (the preview shape doesn't move with it). Arrows and typing
        # both land here (widgets.SpinCtrl covers EVT_SPINCTRL and EVT_TEXT),
        # and a re-check is idempotent (the banner skips an unchanged rebuild).
        self.count.bind_change(lambda evt: self.page.refresh_area_checks())
        knobs.Add(self.count, 0, wx.LEFT, ROW)
        box.Add(knobs, 0, wx.TOP, PAD)
        # How long each candidate is solved for, and whether the solver finds
        # its own ground/source -- a sweep pays for both once per candidate, so
        # they sit with the buttons that spend them. One value each with the
        # simulate view's run (sections.passknobs).
        self.knobs = PassKnobs(p, self._relayout)
        box.Add(self.knobs.sizer, 0, wx.TOP, ROW)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.scan_btn = self.row_button(row, "Start scan", self.on_scan)
        # The meshing pass over the whole sweep: every candidate's grid, no
        # solve (the scan-wide twin of the simulate view's Generate grid).
        self.grids_btn = self.row_button(row, "Generate grids", self.on_grids)
        box.Add(row, 0, wx.EXPAND | wx.TOP, PAD)
        # The status line under the buttons, full width: a long line (the one
        # that explains why the preview went away) wraps into the section
        # instead of being cut off by the buttons beside it.
        self._status_label = self.wrap_label(p, READY, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        # Per-candidate progress while a scan runs (hidden at rest); its range
        # is the planned candidate count and it advances on each on_result.
        self._gauge = wx.Gauge(p, range=1, size=(-1, ROW))
        self._gauge.Hide()
        box.Add(self._gauge, 0, wx.EXPAND | wx.TOP, ROW)
        self.add_to_body(body, box)
        self._on_scan_param()  # grey out the fixed rows
        self._sync_scan_buttons()  # the at-rest labels and tooltips

    def _param_row(self, grid, param, rb_group):
        """A parameter row: the radio (picks it as the swept one), the
        illustration that labels it, min box, preview/value slider, max box,
        and the value box (mm) — the slider's readout while the row is swept,
        and the typed fixed value while it isn't.

        The radio wears no text: the picture beside it is the label, and the
        name is on the tooltip of both — which is where somebody looks up the
        word for a drawing (and the vocabulary the result table then uses). A
        parameter with no artwork keeps the words, or its row would be a
        nameless bullet."""
        p = self.scroll
        bmp = self._make_icon(param)
        radio = wx.RadioButton(
            p, label="" if bmp else param.label, style=wx.RB_GROUP if rb_group else 0
        )
        set_tip(radio, param.label)
        radio.Bind(wx.EVT_RADIOBUTTON, self._on_scan_param)
        # The bounds take effect as they are typed (widgets.live_text).
        lo = live_text(p, self._on_range_edit, 56)
        sl = Slider(p, value=50, minValue=0, maxValue=100, size=(170, -1))
        sl.bind_change(self.on_preview)
        hi = live_text(p, self._on_range_edit, 56)
        val = live_text(p, self._on_value_edit, 64)
        set_tip(val, param.label)
        grid.Add(radio, 0, wx.ALIGN_CENTER_VERTICAL)
        if bmp:
            grid.Add(bmp, 0, wx.ALIGN_CENTER_VERTICAL)
        else:
            grid.Add((0, 0))  # no artwork: the radio carries the name
        grid.Add(lo, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(sl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(hi, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(val, 0, wx.ALIGN_CENTER_VERTICAL)
        self._radio[param.key], self._lo[param.key] = radio, lo
        self._hi[param.key] = hi
        self._sl[param.key], self._val[param.key] = sl, val

    # --- the row illustrations ------------------------------------------------
    def _make_icon(self, param):
        """The row's label: the picture of the knob it turns
        (design.base.Param.icon), the design's own antenna with this
        parameter's sweep drawn on it. Both states are loaded once — lit for
        the swept row, faded for a fixed one — so switching rows is a SetBitmap
        rather than a decode.

        Clicking it selects the row, so the pictures are a way to *pick* the
        sweep and not only to read it (the radio beside it still does the same
        thing). Returns None when the design ships no artwork for the parameter,
        which is the caller's cue to let the radio wear the name instead."""
        lit = icons.illustration(param.icon, ICON_SIZE)
        if lit is None:
            return None
        faded = icons.illustration(param.icon, ICON_SIZE, alpha=ICON_FADED_ALPHA)
        bmp = wx.StaticBitmap(self.scroll, bitmap=lit)
        set_tip(bmp, param.label)
        bmp.Bind(
            wx.EVT_LEFT_DOWN, lambda evt, key=param.key: self._pick_param(key, evt)
        )
        self._icon[param.key] = (bmp, lit, faded)
        return bmp

    def _sync_icons(self, swept):
        """Light the swept row's illustration and fade the rest, in step with
        the controls those rows just enabled or greyed."""
        for key, (bmp, lit, faded) in self._icon.items():
            bmp.SetBitmap(lit if key == swept else faded)

    def _pick_param(self, key, event):
        """Make ``key`` the swept parameter because its illustration was
        clicked — the same move as clicking the row's radio, event and all, so
        the preview follows it the way it follows the radio."""
        if self._radio[key].GetValue():
            return
        self._radio[self._swept_param()].SetValue(False)
        self._radio[key].SetValue(True)
        self._on_scan_param(event)

    # --- scan-parameter selection ---------------------------------------------
    def _swept_param(self):
        return next(p.key for p in self.design.params if self._radio[p.key].GetValue())

    def _on_scan_param(self, event=None):
        """The swept parameter changed: only its row's min/max and slider
        stay live, and its value box goes read-only (the slider writes it); the
        other rows grey those out and take their value box the other way, since
        typing into it is how the fixed value every candidate shares is set.
        The newly swept row starts from the value that box was holding, so
        picking a row doesn't move the candidate under the user. ``event`` is
        None when the rows were set rather than clicked (construction, restore,
        reset_params) -- don't touch a drawn preview then: at construction the
        ranges are still blank, so redrawing would fail and clear it
        (area.refresh redraws it right after), and the other two have no
        preview to move."""
        param = self._swept_param()
        for p in self.design.params:
            active = p.key == param
            for ctrl in (self._lo[p.key], self._sl[p.key], self._hi[p.key]):
                ctrl.Enable(active)
            self._val[p.key].Enable(not active)
        held = to_float(self._val[param].GetValue(), None)
        if held is not None:
            self._set_value(param, held)  # into the row's range
        self._sync_icons(param)
        self._sync_swept_value()
        if event is not None and not self.refresh_preview():
            self.page.refresh_area_checks()  # a different sweep to warn about
        self._relayout()

    # --- row values -----------------------------------------------------------
    def _range(self, key):
        """The row's min/max bounds (mm). Blank bounds on the resonant length
        fall back to the automatic ladder's λ/4 band around the target
        frequency; anything else unusable raises with guidance."""
        lo = to_float(self._lo[key].GetValue(), None)
        hi = to_float(self._hi[key].GetValue(), None)
        if key == self.design.LENGTH_KEY and lo is None and hi is None:
            f0 = self.page.host.target_freq_ghz()
            if f0 and f0 > 0:
                est = sizing.quarter_wave_mm(f0)
                lo, hi = est * sizing.LADDER_LO, est * sizing.LADDER_HI
        if lo is None or hi is None or lo <= 0 or hi <= 0:
            raise RuntimeError(
                f"set the {self.design.param_label(key).lower()} min/max (mm)"
            )
        return (lo, hi) if hi >= lo else (hi, lo)

    def _value(self, key):
        """The row's value in mm: the previewed candidate for the swept row
        (its slider position mapped into its min/max), and the number typed in
        the value box for a greyed one -- a fixed parameter has no sweep to be
        a fraction of, so it is simply the value the box says. A blank or
        unusable fixed value is an error rather than a guess: nothing here
        invents a track width."""
        if key != self._swept_param():
            mm = to_float(self._val[key].GetValue(), None)
            if mm is None or mm <= 0:
                raise RuntimeError(
                    f"set the {self.design.param_label(key).lower()} value (mm)"
                )
            return mm
        lo, hi = self._range(key)
        t = self._sl[key].GetValue() / 100.0
        return round(lo + t * (hi - lo), 3)

    def _values(self):
        """Every parameter's current value (mm), keyed as the design names
        them -- the geometry a preview solves and the fixed half of a spec."""
        return {p.key: self._value(p.key) for p in self.design.params}

    def _set_value(self, key, mm):
        """Put ``mm`` in the row's value box and position its slider to match
        (clamped into the row's min/max -- the box keeps the exact number, a
        fixed value being free to sit outside a sweep it isn't part of). A row
        without a usable range still gets the box; only its slider is left
        alone."""
        self._val[key].ChangeValue(f"{mm:g}")
        try:
            lo, hi = self._range(key)
        except RuntimeError:
            return
        t = 0.5 if hi <= lo else (mm - lo) / (hi - lo)
        self._sl[key].SetValue(int(round(100 * min(max(t, 0.0), 1.0))))

    def _sync_swept_value(self):
        """Write the swept row's slider position into its value box (a range
        may have changed under it); blank while its range isn't usable. Only
        that row: the fixed rows' boxes are the user's own text, and this runs
        while they are being typed into."""
        key = self._swept_param()
        try:
            self._val[key].ChangeValue(f"{self._value(key):g}")
        except Exception:
            self._val[key].ChangeValue("")

    def _on_range_edit(self):
        """A min/max bound was typed into: the row values, the drawn preview
        and the banner's view of the sweep follow it keystroke by keystroke.
        The bounds are the sweep, so a bound that puts candidates outside the
        area must reach the banner even on a board with no preview drawn --
        which is why the check runs here when the redraw didn't do it."""
        self._sync_swept_value()
        if not self.refresh_preview():
            self.page.refresh_area_checks()

    def _on_value_edit(self):
        """A fixed row's value was typed into: every candidate carries it, so
        the drawn preview and the banner's view of the sweep follow it
        keystroke by keystroke, exactly as a bound does. The box isn't
        rewritten here -- it is what is being typed."""
        if not self.refresh_preview():
            self.page.refresh_area_checks()

    # --- seeding --------------------------------------------------------------
    def _seed_absolute(self):
        """Seed the rows whose Seed is plain mm (the track width). They don't
        depend on the target frequency, so they are filled as the rows are
        built; the frequency-relative ones wait for seed_from_freq."""
        for param in self.design.params:
            if param.seed.relative:
                continue
            lo, hi, value = param.seed.at(0.0)
            self._lo[param.key].ChangeValue(f"{lo:g}")
            self._hi[param.key].ChangeValue(f"{hi:g}")
            self._set_value(param.key, value)

    def seed_from_freq(self):
        """Seed every frequency-relative row from the free-space quarter wave
        for the target frequency (these are quarter-wave antennas, ~30 mm at
        2.45 GHz): the design's own Seed gives each row its min/max and the
        slider position inside them. Leaves any bounds the user already
        typed."""
        f0 = self.page.host.target_freq_ghz()
        if not f0 or f0 <= 0:
            return
        for key, (lo, hi, value) in self.design.seed_values(f0).items():
            if not self.design.param(key).seed.relative:
                continue  # absolute rows are seeded once
            if self._lo[key].GetValue().strip() or self._hi[key].GetValue().strip():
                continue
            self._lo[key].ChangeValue(f"{lo:.1f}")
            self._hi[key].ChangeValue(f"{hi:.1f}")
            # A restored row keeps its saved value: restore ran before the
            # frequency was known, so a row saved with blank bounds gets its
            # band seeded here and would otherwise lose the value with it. Once
            # handed over the saved value is spent -- from here the row is the
            # user's to move, and a later re-seed uses the design's own.
            self._set_value(key, self._restored.pop(key, value))
        self._sync_swept_value()  # ChangeValue fires no EVT_TEXT

    # --- persisted rows (gui.settings) ----------------------------------------
    # The sweep is worth keeping across launches: the bounds and fixed values
    # are hand-tuned to one board's area. Keys are namespaced by design -- every
    # designer page has its own rows and they all share one settings file.
    def _key(self, *parts):
        return ".".join(("scan", self.design.key) + parts)

    def snapshot(self):
        """This section's rows as a flat string dict: every parameter's min/max
        bounds and its current value (mm), plus which row is swept and the
        candidate count. Values rather than slider positions -- a position only
        means something against the bounds it is read with, and those may be
        re-seeded before it is restored. A row with nothing usable to read (a
        blank fixed value, a swept row whose range isn't usable yet) has no
        value to save, and stores a blank."""
        data = {
            self._key("param"): self._swept_param(),
            self._key("count"): str(self.count.GetValue()),
        }
        for param in self.design.params:
            data[self._key(param.key, "min")] = self._lo[param.key].GetValue()
            data[self._key(param.key, "max")] = self._hi[param.key].GetValue()
            try:
                data[self._key(param.key)] = f"{self._value(param.key):g}"
            except RuntimeError:
                data[self._key(param.key)] = ""
        return data

    def restore(self, data):
        """Set the rows from a ``snapshot`` dict without firing edit events.
        Keys the file doesn't carry leave their row on its seed, so a file
        written before this design shipped (or by an older version) just
        doesn't move it."""
        for param in self.design.params:
            key = param.key
            for box, part in ((self._lo[key], "min"), (self._hi[key], "max")):
                if self._key(key, part) in data:
                    box.ChangeValue(data[self._key(key, part)])
            value = to_float(data.get(self._key(key), ""), None)
            if value is not None:
                self._restored[key] = value  # survives the frequency seeding
                self._set_value(key, value)
        swept = data.get(self._key("param"))
        if swept in self._radio:
            self._radio[self._swept_param()].SetValue(False)
            self._radio[swept].SetValue(True)
        count = to_float(data.get(self._key("count"), ""), None)
        if count is not None:
            self.count.SetValue(int(min(max(count, COUNT_RANGE[0]), COUNT_RANGE[1])))
        self._on_scan_param()  # grey the fixed rows, retitle the note

    def reset_params(self):
        """Forget the sweep and go back to the design's own seeds: bounds
        cleared (and re-seeded), the resonant length swept again, the candidate
        count back to its default. The area section calls this when a fresh
        marker is placed — the rows describe an area that is gone, and a saved
        sweep tuned for it would be worse than no sweep at all."""
        self._restored.clear()
        for param in self.design.params:
            self._lo[param.key].ChangeValue("")
            self._hi[param.key].ChangeValue("")
        self._seed_absolute()
        self._radio[self._swept_param()].SetValue(False)
        self._radio[self.design.LENGTH_KEY].SetValue(True)
        self.count.SetValue(COUNT_DEFAULT)
        self.seed_from_freq()  # refills the frequency-relative rows
        self._on_scan_param()  # grey the fixed rows, retitle the note

    # --- candidate preview ------------------------------------------------------
    def _feed_layer_name(self):
        """The main dialog's Feed layer pick — the copper the preview is
        drawn on and the scan splices candidates into."""
        return self.page.host.feed_layer_name() or "F_Cu"

    def _feed_layer_id(self, board):
        """The pcbnew layer id of the Feed layer pick, validated against the
        board's enabled copper layers."""
        from ...sim import simulate

        name = self._feed_layer_name()
        for suffix, layer_id in simulate.copper_layers(board):
            if suffix == name:
                return layer_id
        raise RuntimeError(f"copper layer {name} is not enabled on this board")

    def _target_freq(self):
        """The target frequency (GHz) every candidate is sized and scored for,
        or a raise saying where to set it. Shared by the scan spec and the
        direct placement (current_candidate), so the one input both need is
        refused in one wording — and never guessed at."""
        f0 = self.page.host.target_freq_ghz()
        if f0 is None or f0 <= 0:
            raise RuntimeError(
                "target frequency must be a positive number "
                "(GHz) — set it in the main window"
            )
        return f0

    def on_preview(self, event=None):
        """The active slider moved: redraw the candidate in the placed area
        marker — on copper when it fits, on the marker's layer when it doesn't
        (_draw_preview). The user asked for a preview, so one stays wanted even
        if this candidate can't be drawn at all (_preview_on)."""
        self._preview_on = True
        try:
            text, fits = self._draw_preview()
        except Exception as exc:
            self._preview_failed(exc)
        else:
            self._set_status(text, alert=not fits)
        # A preview that fits is copper on the feed layer, so the board the
        # advisory checks read just changed. (The overlap check itself doesn't
        # move with the sliders -- it judges the last started pass' copper,
        # spliced_copper.)
        self.page.refresh_area_checks()

    def plan_problems(self):
        """The advisory warnings about the sweep the rows currently describe --
        the candidates the area marker can't hold, which a pass skips
        (wizard_scan.plan_problems). The area banner shows them.

        Unlike ``spliced_copper`` this does not wait for a pass to be started:
        it is about the plan, not the splice, and the whole point of saying it
        is to say it *before* the scan is paid for. It needs no board either --
        the sweep either fits the marker's rectangle or it doesn't -- so a form
        too incomplete to build a spec from (no marker yet, a blank bound) is
        simply nothing to warn about: the Start scan button tells that story on
        the section's own status line."""
        from ...design import wizard_scan

        try:
            spec = self._spec()
        except Exception:
            return []
        return wizard_scan.plan_problems(spec)

    def spliced_copper(self):
        """The copper the last started pass splices into the feed layer, with
        the spec it was solved in: ``(frame, rects)`` -- what the advisory
        overlap check judges (the banner is the caller). None until Start scan
        or Generate grids has been pressed: that check is about the splice, so
        before a pass there is nothing to warn about, and warning anyway meant
        greeting the user with an overlap they had not asked for yet.

        It stays put afterwards (the frame with it, so a marker moved since is
        no bother): it describes the pass that ran, the way the results below
        do, until the next pass replaces it -- or a placement consumes it
        (``forget_splice``)."""
        return self._spliced

    def _candidate(self):
        """The candidate at the current rows — the swept parameter's slider
        picks a value between its min/max, the greyed rows' value boxes hold
        the others — put to design.fit in the placed marker's derotated frame:
        ``(fit.Fit, spec)``. Raises with guidance when the marker is missing
        or broken; a geometry that doesn't fit is not an error here, it is what
        the Fit reports (and what gets drawn on the marker layer)."""
        spec = self.page.area.spec()  # raises without exactly one marker
        return fit.check(
            self.design, spec["area"], spec["edge"], spec["frac"], self._values()
        ), spec

    def current_candidate(self):
        """The shape the rows describe *right now* — the previewed candidate —
        as ``(values, ctx, geo)``: every parameter's current value (the swept
        row's slider position, the fixed rows' typed numbers), the context a
        placement re-solves it in (the decoded area marker, the target
        frequency and desired spec, the feed layer), and the geometry already
        solved from the two, whose derived metrics fill the chooser's row.

        This is what section 3 offers beside the scan's results: the same kind
        of row, in a table of its own, so a geometry somebody already knows
        they want — or one they are still eyeballing on the board — can be
        placed without paying for a sweep first. Nothing here was simulated,
        and the ctx carries the desired spec precisely so the chooser can show
        that it has nothing to judge (scoring's NONE verdicts) rather than
        inventing one.

        Raises with guidance when there is nothing placeable: no area marker,
        an unusable row, or a candidate the area doesn't hold. That last one is
        drawn on the marker's own layer rather than as copper (_draw_preview),
        and placing it would fabricate metal outside the rectangle the user
        drew — so it is refused here, in the words the status line already
        uses."""
        state, spec = self._candidate()
        if not state.ok:
            raise RuntimeError(state.detail or "the shape doesn't fit the area")
        ctx = dict(spec)
        ctx.update(
            {
                "design": self.design,
                "f0_ghz": self._target_freq(),
                "feed_layer": self._feed_layer_name(),
            }
        )
        ctx.update(self._target_fields())
        return dict(state.values), ctx, state.geo

    def _draw_preview(self):
        """Draw the candidate at the current sliders (_candidate) into the
        placed area marker, stroked at the track width: on the picked copper
        layer while it fits the area, and on the marker's own User layer while
        it doesn't — the antenna spilling out of the rectangle, in the marker's
        colour, rather than nothing at all. Returns ``(status text, fits)``;
        raises with guidance when the marker is missing or the values yield no
        geometry to draw at any size."""
        board = pcbnew.GetBoard()
        if board is None:
            raise RuntimeError("no board is open")
        self._sync_swept_value()
        state, spec = self._candidate()
        geo = state.preview
        if geo is None:
            raise ValueError(state.detail)
        marker = self.page.area._markers()[0]
        trace_w = state.values[self.design.WIDTH_KEY]
        if state.ok:
            layer = self._feed_layer_name()
            layer_id = self._feed_layer_id(board)
        else:
            layer, layer_id = area_marker.marker_layer(marker)
        rot = spec.get("rot_deg") or 0.0
        pivot = spec.get("pivot") or (0, 0)
        area_marker.draw_antenna(
            marker, geo.centerline_segments(rot, pivot), layer_id, trace_w
        )
        pcbnew.Refresh()
        self._preview_on = True
        shape = (
            f"{geo.total_mm:g} mm ({self.design.describe(geo)}), width {trace_w:g} mm"
        )
        if state.ok:
            return f"Preview: {shape} — drawn on {layer}.", True
        # Not copper: it doesn't fit, so it is drawn on the marker instead,
        # hanging out of the rectangle by however much is missing.
        return (
            f"Doesn't fit the area — {shape} drawn on {layer} (the marker "
            f"layer), not on copper: {state.detail}.",
            False,
        )

    def _preview_failed(self, exc):
        """A preview redraw could not be made at all (a bound is blank, the
        marker is missing or broken, the values yield no geometry at any size):
        clear the drawn antenna so a stale shape isn't left posing as the
        candidate, and say why — in full contrast, since this line is why the
        board just went empty. _preview_on keeps the preview wanted, so it
        comes back by itself once the inputs make a shape again. A candidate
        that merely doesn't fit does not come here: it is drawn on the marker
        layer (_draw_preview)."""
        try:
            fps = self.page.area._markers()
            if fps and area_marker.clear_antenna(fps[0]):
                pcbnew.Refresh()
        except Exception:
            pass
        self._set_status(f"✗ {exc}", alert=True)

    def refresh_preview(self):
        """Redraw the preview after its inputs changed (the area marker
        reshaped or moved, a range edited, the swept parameter switched).
        Redraws whenever one is wanted — either because the marker carries one
        (this wizard was reopened on a board that already has it) or because
        this session drew one and an undrawable candidate wiped it; a marker
        that never had a preview is left alone. This is also what moves a
        preview between the copper and the marker layer as the candidate starts
        or stops fitting the area (_draw_preview picks the layer every time).

        Returns whether it redrew — which is also whether it re-ran the
        advisory checks, so a caller that changed the *sweep* rather than the
        drawn candidate knows whether the banner still needs telling."""
        fps = self.page.area._markers()
        if not fps or not (self._preview_on or area_marker.antenna_items(fps[0])):
            return False
        self.on_preview()
        return True

    def forget_preview(self):
        """The drawn preview was removed for good (the footprint section just
        placed the real copper): stop wanting one, so a later area tweak
        doesn't redraw the candidate on top of the placed footprint."""
        self._preview_on = False

    def forget_splice(self):
        """The last pass' copper became a footprint (the footprint section just
        placed one of its candidates): stop offering it to the advisory overlap
        check.

        That check asks whether the copper a pass *would* splice lands on metal
        already there, and a placement answers it -- the winner is now real
        copper inside the area, so the recorded sweep, which by construction
        covers it, warned about the antenna colliding with itself the moment it
        was placed. Nothing is silenced for good: pressing Start scan or
        Generate grids records the next pass' copper (``_prepare``), and then
        the placed footprint *is* metal a splice would merge with -- the
        warning comes back saying so, at the point where it is worth acting
        on."""
        self._spliced = None

    # --- helpers --------------------------------------------------------------
    def _set_status(self, text, alert=False):
        """This section's status line. ``alert`` shows it in full contrast
        instead of the running commentary's muted grey -- for the line that
        explains why the antenna drawn on the board just went away, which is
        exactly the line an eye skips when it is grey."""
        (emphasize if alert else muted)(self._status_label)
        super()._set_status(text)
        self._status_label.Refresh()

    def results(self):
        """Every result of the last finished scan (best-first, the same order
        ``picked`` draws its winner from) with the geometry context they were
        scanned under: ``(results, ctx)``. ``results`` is empty before a scan
        has finished; individual entries may carry an ``error`` (no numbers).

        "The last scan" outlives the window: these may be the rows this session
        measured, or the ones ``load_saved`` read back out of the scan folder.
        Both are the same shape, measured under the frame their own ctx
        carries, so a consumer never has to tell them apart -- ``saved_scan``
        is there for the one thing that does differ, which is what the wizard
        should *say* about them."""
        return self._results, self._ctx

    def saved_scan(self):
        """The saved scan the current results were read back from
        (design.scan_store.Saved), or None when this session's own scan
        measured them. Only the wording depends on it: a restored candidate is
        placed exactly as a fresh one is."""
        return self._saved

    def load_saved(self):
        """Take the last finished scan's results back off disk when this
        session hasn't run one (design.scan_store, written by run_scan into
        this design's scan folder). Returns whether any were restored.

        The wizard's page calls this when it is shown, so reopening the plugin
        on a board that was scanned yesterday offers those candidates for
        placement instead of asking for the sweep to be paid for again. Never
        over live results: a scan that has run here is the newer truth, and a
        pass in flight is about to replace them. It re-reads whenever there are
        none, so a scan that failed or was cancelled falls back to the last one
        that did finish rather than leaving the section with nothing placeable.

        A file that can't be trusted (another version, another design, no
        results) is refused by the store; that reason goes to the run log and
        the section carries on as though nothing had been saved -- reopening a
        wizard must not fail because of what an old folder holds."""
        if self._results or self._running:
            return False
        board = pcbnew.GetBoard()
        if board is None:
            return False
        from ...design import scan_store
        from ...sim import simulate

        folder = simulate.scan_dir(board, self.design.key)
        try:
            saved = scan_store.load(folder, self.design.key)
        except Exception as exc:
            self.log(f"could not read the last scan's results: {exc}")
            return False
        if saved is None:
            return False
        self._results, self._ctx, self._saved = saved.results, saved.spec, saved
        # The footprint section is what these are for: it says so on its own
        # status line, which is where "what can I place right now?" is
        # answered.
        self.page.footprint.note_saved_scan(saved)
        return True

    # --- scan flow ------------------------------------------------------------
    def on_scan(self, event=None):
        """Start scan button: simulate every candidate and score it -- or,
        while a scan or grid pass is in flight (the button reads Cancel scan),
        cancel it. A scan cancel is deliberately the hard stop: the solver's
        "stop early but still write the outputs" would hand the scan a partial
        record to score as if it were complete."""
        if self._running:
            self._request_cancel()
            self._set_status("Cancelling…")
            return
        self._start(grid_only=False)

    def on_grids(self, event=None):
        """Generate grids button: the meshing pass over the whole sweep. Every
        candidate is planned, spliced, configured and meshed exactly as a scan
        would -- only the solve is skipped -- so the combined grid view previews
        the meshes the scan would solve, in the time one candidate's mesh takes.
        Disabled while anything is in flight (_sync_scan_buttons), so it never
        races a scan."""
        self._start(grid_only=True)

    def _start(self, grid_only):
        """Prepare and launch a pass over the sweep: the plan, the board (saved
        stackup and gerbers) and the run params on the main thread (pcbnew
        objects aren't thread-safe), then the candidates on a worker.
        ``grid_only`` meshes them instead of solving them."""
        # A run, or another designer's scan, may already be in flight. That is
        # allowed, but it is the user's call to make
        # (SolverSection.confirm_concurrent) -- and it is asked before
        # _prepare, so a declined pass plots no gerbers and never disturbs the
        # marker's drawn preview.
        if not self.confirm_concurrent():
            return
        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            self._report_failure("No board is open.")
            return
        try:
            spec, planned, total, work, launch = self._prepare(board, grid_only)
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            self.log(f"ERROR: {exc}")
            self._report_failure(f"The scan did not start.\n\n{exc}")
            return

        # This pass is going ahead, so its copper is now the copper the
        # advisory overlap check judges (spliced_copper); a pass that failed
        # to prepare splices nothing and leaves the last one's standing.
        from ...design import wizard_scan

        self._spliced = (spec, wizard_scan.spliced_rects(spec, planned))
        self._claim()  # _running, and the shell now counts this pass
        self._cancelled = False
        self._grid_only = grid_only
        # A grid pass measures nothing, so it leaves the last scan's results
        # (and the footprint section's pick) standing: what it overwrote in
        # the candidate folders is their data, not the geometry the placer
        # re-solves from.
        if not grid_only:
            self._results = []
            self._ctx = spec
            # Whatever this pass measures is this session's own; the saved
            # scan it may have been showing until now is about to be replaced
            # (run_scan rewrites the folder's record when it finishes).
            self._saved = None
        self._total = max(total, 1)
        self._done = 0
        self._gauge.SetRange(self._total)
        self._gauge.SetValue(0)
        self._gauge.Show()
        self._sync_scan_buttons()
        # The banner's overlap check has copper to judge now (spliced_copper).
        self.page.refresh_area_checks()
        self.page.log_ctrl.Clear()
        self.log(f"Scan folder: {work}")
        if grid_only:
            self.log("Grids only — no candidate will be solved.")
        self._relayout()  # the gauge just appeared
        self._begin_session()  # the candidates' solver processes attach to it
        self._start_worker(*launch, spec, work, grid_only)

    def _prepare(self, board, grid_only):
        """Everything a pass needs off the board and the form, gathered on the
        main thread: ``(spec, planned candidates, candidate count for the
        gauge, scan folder, (exe, gerbers, stack, base_params) for the
        worker)``. Raises with one readable message when any of it can't be had
        (an infeasible sweep, a missing binary, an unsaved board)."""
        from ...design import wizard_scan
        from ...sim import simulate

        spec = self._spec()
        planned = wizard_scan.plan(spec)  # raises on an infeasible sweep
        # Gauge range: one step per planned candidate, plus one for the
        # auto-length refine run the driver may append to a real scan (skipped
        # when the fit lands on an already-scanned length -- the gauge is
        # snapped to full on finish either way). A grid pass never refines.
        total = len(planned)
        if (
            not grid_only
            and spec["scan_param"] == self.design.LENGTH_KEY
            and spec.get("sweep_lo") is None
        ):
            total += 1
        exe, _root = simulate.locate()
        self._ensure_board_saved(board)
        stack = simulate.collect_stackup(board)
        work = simulate.scan_dir(board, self.design.key)
        # A drawn preview that fits is real copper on the feed layer, so it
        # would be plotted under every spliced candidate: strip it for the
        # plot, then put it back (one that doesn't fit sits on the marker
        # layer and plots nothing, but it costs nothing to treat both alike).
        fps = self.page.area._markers()
        stripped = bool(fps) and area_marker.clear_antenna(fps[0]) > 0
        try:
            gerbers = simulate.plot_gerbers(board, work / "gerbers")
        finally:
            if stripped:
                try:
                    self._draw_preview()
                except Exception:
                    pcbnew.Refresh()  # show the marker without it
        base_params = self.page.host.run_params(str(work))
        return spec, planned, total, work, (exe, gerbers, stack, base_params)

    def _sync_scan_buttons(self):
        """Put the section's two buttons in step with the run state -- the
        single place that decides what they mean right now:

            at rest      Start scan + Generate grids
            scanning     Cancel scan  + Generate grids disabled
            meshing      Cancel grids + Generate grids disabled

        One pass at a time, whichever kind: the first button cancels the live
        one (naming it, so it is clear what stops), and the second can't start
        a second pass over the same folder.
        """
        if self._running:
            label = "Cancel grids" if self._grid_only else "Cancel scan"
            tip = "Stop the pass; the candidates it finished stay in the scan folder"
        else:
            label = "Start scan"
            tip = "Simulate every candidate of the sweep and score it"
        self.scan_btn.SetLabel(label)
        set_tip(self.scan_btn, tip)
        self.grids_btn.Enable(not self._running)
        set_tip(
            self.grids_btn,
            self._start_tip(
                "Mesh every candidate and show the combined grid view, without "
                "solving any of them"
            ),
        )

    def _spec(self):
        """The scan spec: the design, the area section's decoded marker and
        this section's rows — the swept row's min/max become the sweep bounds
        (blank bounds on the resonant length = automatic λ/4 ladder) and the
        greyed rows' value boxes the fixed values. The target frequency comes
        from the parent dialog (the run length is this section's own row, and
        travels with the run params rather than the spec). The geometry is
        dry-solved
        so an unusable area or length fails here, in one readable message,
        instead of on every candidate."""
        param = self._swept_param()
        label = self.design.param_label(param).lower()
        n = int(self.count.GetValue())
        f0 = self._target_freq()

        # The swept row's min/max (blank bounds on the resonant length mean
        # the automatic λ/4 ladder).
        lo = to_float(self._lo[param].GetValue(), None)
        hi = to_float(self._hi[param].GetValue(), None)
        sweep_lo = sweep_hi = None
        auto = param == self.design.LENGTH_KEY and lo is None and hi is None
        if auto:
            pass  # automatic λ/4 ladder
        elif lo is None or hi is None or lo <= 0 or hi <= 0:
            raise RuntimeError(f"the {label} min/max must be two positive numbers (mm)")
        elif abs(hi - lo) < 1e-6 and n > 1:
            # Equal bounds are a sweep of one value: several candidates would
            # dedup down to that one (sizing.sweep_values), which is not the
            # scan that was asked for. At one candidate it *is* the scan --
            # the way to pin the single run to an exact value rather than to
            # the middle of a range.
            raise RuntimeError(
                "the sweep range is a single value — set min and max apart, "
                "or ask for a single candidate"
            )
        else:
            sweep_lo, sweep_hi = lo, hi

        # The held rows read their value boxes; the swept one gets the sweep's
        # low end as the placeholder the driver overrides per candidate.
        values = self._values()
        if not auto:
            values[param] = sweep_lo
            length = values[self.design.LENGTH_KEY]
            if length < sizing.MIN_TOTAL_MM:
                raise RuntimeError(
                    f"{self.design.param_label(self.design.LENGTH_KEY).lower()}"
                    f" must be at least {sizing.MIN_TOTAL_MM:g} mm"
                )

        spec = dict(self.page.area.spec())
        spec.update(
            {
                "design": self.design,
                "scan_param": param,
                "values": values,
                "sweep_lo": sweep_lo,
                "sweep_hi": sweep_hi,
                "f0_ghz": f0,
                "n": n,
                # The main dialog's Feed layer pick: the copper the candidates
                # are spliced into (and the preview is drawn on).
                "feed_layer": self._feed_layer_name(),
            }
        )
        spec.update(self._target_fields())
        return spec

    def _target_fields(self):
        """The desired-spec fields the result table scores each candidate
        against (design.scoring): the current application's operating band,
        input impedance and return-loss target. 'Custom…' is synthesized into
        an application from the dialog's hand-typed fields
        (``host.current_application`` -> PatternFreqSection), so every pick is handled
        the same way here; absent fields stay None -- shown but not judged,
        never defaulted."""
        app = self.page.host.current_application()
        return {
            "band_ghz": list(app.band) if app.band else None,
            "impedance_ohm": app.impedance_ohm,
            "return_loss_db": app.return_loss_db,
        }

    def _worker(self, exe, gerbers, stack, base_params, spec, work, grid_only):
        from ...design import wizard_scan

        try:
            results = wizard_scan.run_scan(
                exe,
                gerbers,
                stack,
                base_params,
                spec,
                work,
                on_line=self.log,
                on_status=lambda t: wx.CallAfter(self._set_status, t),
                on_result=lambda r: wx.CallAfter(self._on_result, r),
                should_stop=lambda: self._cancelled,
                # One session for the whole scan: each candidate's solver
                # process attaches to it, so Cancel always reaches the live
                # one. A scan cancel is deliberately the hard stop -- the
                # solver's "stop early but still write the outputs" would hand
                # the scan a partial record to score as if it were complete.
                on_proc=self._session.attach,
                grid_only=grid_only,
            )
            wx.CallAfter(self._scan_done, results, None)
        except wizard_scan.ScanCancelled:
            wx.CallAfter(
                self._scan_done,
                None,
                "grids cancelled" if grid_only else "scan cancelled",
            )
        except Exception as exc:
            wx.CallAfter(self._scan_done, None, str(exc))

    def _on_result(self, result):
        """One candidate finished (marshalled from the worker): advance the
        progress gauge. The results themselves arrive together in _scan_done."""
        if not self.page or not self._running:
            return
        self._done += 1
        self._gauge.SetValue(min(self._done, self._total))

    def _scan_done(self, results, error):
        if not self.page:
            return
        self._release()  # _running, and the pass leaves the shell's live list
        self._end_session()
        self._sync_scan_buttons()
        # Snap the gauge full (a skipped refine leaves it one short) and put
        # it away now the run is over.
        self._gauge.SetValue(self._total)
        self._gauge.Hide()
        self._relayout()  # the gauge just went away
        if error:
            self._set_status(f"✗ {error}")
            self.log(f"ERROR: {error}")
            self._report_failure(
                "The scan did not complete.\n\n"
                "See the run log below for what went wrong."
            )
            return
        # A fresh set of combined views is on disk: let the Results section
        # below open whichever ones the pass managed to write, so it lands on
        # its results without a click (a grid pass wrote the grid view alone).
        self.page.results.show_all()
        if self._grid_only:
            # Nothing was solved, and the grid view alone doesn't say so --
            # this is the one pass whose status has news, since "Ready." would
            # let it pass for a scan.
            failed = sum(1 for r in results if r["error"] is not None)
            text = f"Grids ready for {len(results) - failed} candidate(s)"
            if failed:
                text += f" ({failed} failed — see the log)"
            self._set_status(f"{text} — no candidate was solved.")
            return
        self._results = results  # every candidate, for the footprint chooser
        best = results[0]  # results come back sorted best-first
        if best["error"] is not None:
            self._set_status("✗ every candidate failed — see the log")
            self._report_failure(
                "Every candidate in the sweep failed.\n\n"
                "See the run log below for each candidate's error."
            )
            return
        # Nothing to announce: the results page just opened with every
        # candidate on it, the winner's length and match included, so the
        # status line goes back to rest instead of reading them out again.
        self._set_status(READY)
