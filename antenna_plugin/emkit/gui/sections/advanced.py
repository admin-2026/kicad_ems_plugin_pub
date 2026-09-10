"""The Advanced section of a design form page (pages.designform.DesignFormPage
— the simulate view and every designer build one).

The collapsible Advanced pane, collapsed by default: every runner knob that
isn't on the main form, in one titled box per *function* rather than in the
order the schema grew them (the boxes and their fields are options.ADV_GROUPS;
this module builds one method per box and decides their order):

    Materials            the per-layer metal/substrate/mask pickers, the metal
                         model, and the tick that says whether the mask is
                         simulated at all
    Optimizations        the toggles the Speed/accuracy slider drives
    Cell size            the base cell's range -- where a run starts and how
                         coarse it may end up (the emkit.cellsize
                         package builds this one, caption and all)
    Mesh                 the rest of the lattice: substrate cell, grading, air
                         margin, PML, the memory ceiling and what an
                         over-budget lattice does, nudge
    Feature refinement   what refine_xy subdivides, and how far
    Frequencies and run  the excited band, the steps, the threads, and whether
                         the data is written as bare JSON as well
    Feed port            the port impedance and the centerline snap
    Ground               the ground check, the auto ground/source radius and
                         the raster they read the copper on
    Markers              the User layer the plugin's markers live on

The numeric fields are blank = the config.py default, shown greyed as a
placeholder.

Every widget in the pane is exactly one runner knob, so each carries the config
key it writes, in brackets: inside the box for a typed field, on the placeholder
that already says what a blank one resolves to (``0 = auto [cell_mm]``,
theme.hint_with_key);
after the label for a tick (theme.with_key); under the label for a picker, which
has no placeholder, and for the Cell size pair, which is stacked under labels of
its own and so says its keys there instead of in the boxes (theme.key_label).
The solver's warnings, its log and the run's ``config.yaml`` all name a knob by
that key and never by the label, so this is what ties a message about one to the
widget that set it. The one exception is the Materials box's solder-mask tick,
which writes no key at all: it decides whether the mask entries are in the
emitted stackup, and there is no line in ``pcb.yaml`` for it to name.

A pane's *closed lists* -- the metal model and the ground
check -- carry that further: what a pick saves is the value the config takes
and not the caption drawn beside it (emkit.choices, ``_picker`` / ``picked``),
so the saved form, the run parameters and pcb.yaml all say
``copper_model: sibc``.

Two collaborators reach in here:
  * the Speed/accuracy slider (SpeedSection) drives the six optimization
    toggles, so this section is the *optimizations provider* it talks to:
    ``apply_preset`` sets the toggles from a preset and ``preset_index``
    reports which preset they currently match (None for a hand-made "Custom");
  * the run flow (sections.run.RunSection) collects every Advanced-owned run
    parameter through ``contribute``.
"""

import wx

from ... import formparams
from ...cellsize.ui import CellSizeBox
from ...choices import COPPER_MODEL, GROUND_CHECK, SHARED
from ...options import ADV_GROUPS
from .. import theme
from ..board import make_material_selector
from ..widgets import FIELD_W, bool_str, live_text, parse_bool, set_tip
from .base import Section

# px trimmed off the page width for prose *inside* the pane: the form's own
# margins (theme.TEXT_MARGIN) plus the indent a CollapsiblePane gives its
# content.
_PANE_MARGIN = theme.TEXT_MARGIN + theme.GAP


def _field_grid():
    """An empty label/field column for one Advanced box: two columns, the
    pane's own spacing. Every group builds the same one."""
    return wx.FlexGridSizer(2, theme.ROW, theme.PAD)


class AdvancedSection(Section):
    _TITLE = "Advanced"
    # What is inside, on the pane's tooltip rather than in its label: the label
    # is a line of the form even while the pane is shut, and the list of groups
    # is the answer to "should I open this?", not something to read every time.
    _TIP = "Materials · mesh · run · ports · ground · markers"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self._build(body)

    def _build(self, body):
        self.adv_pane = wx.CollapsiblePane(
            self.scroll,
            label=theme.numbered(self._TITLE, self.step),
            style=wx.CP_NO_TLW_RESIZE,
        )
        self.adv_pane.SetToolTip(self._TIP)
        pane = self.adv_pane.GetPane()
        ps = wx.BoxSizer(wx.VERTICAL)

        # The numeric fields of every group, by config key; each box builder
        # fills in its own through _add_fields.
        self.adv = {}
        # The closed lists (choices.SHARED), by the same kind of key, filled in
        # by whichever box draws one through _picker. Two dicts keyed the same
        # way is what lets saving, restoring and contributing be a loop rather
        # than a line per widget.
        self.picks = {}
        # One box per functional group, in this order (options.ADV_GROUPS
        # titles them). A builder may return None when its group has nothing to
        # show on this page.
        for build_box in (
            self._materials_box,
            self._optimizations_box,
            self._cell_box,
            self._mesh_box,
            self._refinement_box,
            self._run_box,
            self._feed_box,
            self._ground_box,
            self._markers_box,
        ):
            box = build_box(pane)
            if box is not None:
                ps.Add(box, 0, wx.EXPAND | wx.BOTTOM, theme.GAP)

        note = self.wrap_label(
            pane,
            "Blank = default (shown greyed in the box). The name in [brackets] "
            "beside it is the config key that knob writes -- what the solver's "
            "messages and the run's config.yaml call it; it is on the field's "
            "tooltip too, once a value hides the placeholder. Stackup "
            "thickness and copper count are read from the board.",
            margin=_PANE_MARGIN,
            mute=True,
        )
        ps.Add(note, 0, wx.EXPAND | wx.TOP, theme.HAIR)

        pane.SetSizer(ps)
        self.adv_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.page._on_pane_changed)
        self.add_to_body(body, self.adv_pane)

    # --- the functional groups (one box each, options.ADV_GROUPS) -------------
    def _group_box(self, pane, key):
        """The titled group ``key`` of the Advanced pane -- a heading, no rule
        (theme.group_box: the rules belong to the sections of the page itself).
        What goes in it -- a label/field column (``_field_grid`` +
        ``_add_fields``), the group's own pickers, its checkboxes -- and in what
        order is the caller's, so each group reads the way it should."""
        return theme.group_box(pane, ADV_GROUPS[key].title)

    def _add_fields(self, pane, grid, key):
        """Add group ``key``'s numeric fields to ``grid`` as label + text
        control (the hint shows what a blank one resolves to), registering each
        control in ``self.adv`` under its config key -- which is what
        ``contribute`` reads back.

        The hint carries the key as well as the default (theme.hint_with_key):
        ``0 = auto [cell_mm]``. A placeholder goes away the moment a value is
        typed, so the key also rides the field's tooltip, which does not."""
        for field_key, label, hint in ADV_GROUPS[key].fields:
            grid.Add(wx.StaticText(pane, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            ctrl = wx.TextCtrl(pane, size=(FIELD_W, -1))
            ctrl.SetHint(theme.hint_with_key(hint, field_key))
            set_tip(ctrl, f"Writes {field_key} in the run's config")
            self.adv[field_key] = ctrl
            grid.Add(ctrl, 0)

    def _picker(self, pane, grid, picker):
        """Add one closed list (emkit.choices.Choices) to ``grid``: its label
        over the config key it writes -- a picker has no placeholder to carry
        one -- then the values, each captioned with what it does.

        Registered in ``self.picks`` under that key, the way a typed field is
        registered in ``self.adv``, so nothing below this line spells a value:
        the pane draws the list, and the table says what is in it."""
        grid.Add(
            theme.key_label(pane, picker.label, picker.key),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        ctrl = wx.Choice(pane, size=(FIELD_W, -1), choices=picker.labels())
        ctrl.SetSelection(picker.index(picker.default))
        self.picks[picker.key] = ctrl
        grid.Add(ctrl, 0)
        return ctrl

    def _materials_box(self, pane):
        """Materials: the optional per-layer metal/substrate/solder-mask
        pickers, the model the metal is meshed with, and the tick that says
        whether the mask is simulated at all. The pickers come from a guarded
        import so the plugin still runs if the materials package is removed --
        the box then holds the metal model and that tick alone (and config's
        own per-layer sources block the run, see contribute).

        The mask's switch sits in this box and not among the Optimizations
        because what it costs is a *material*: including the coating is only
        half an answer until the board or a pick says what the coating is, and
        the row that says so is right above it."""
        self.materials = make_material_selector(pane, self._on_material_change)
        box = (
            self.materials.sizer()
            if self.materials is not None
            else theme.group_box(pane, ADV_GROUPS["materials"].title)
        )
        grid = _field_grid()
        self._picker(pane, grid, COPPER_MODEL)
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        # The coating: off unless it is asked for, because it is the dearest
        # tick on the pane -- the mask is meshed at its own thickness, so a
        # 20 um layer becomes the finest cell the run has and the time step
        # follows it down, often ten times the wall clock.
        #
        # Deliberately NOT an optimization toggle: it is bound to the pre-flight
        # and not to the speed slider's override handler, so it never makes the
        # slider read "Custom". What it does change is whether the board has to
        # state its mask material, which is a pre-flight blocker -- so it
        # re-runs that check instead.
        self.include_mask = wx.CheckBox(
            pane,
            label="Simulate the solder mask coating "
            "(meshed at its own thickness — a much longer run)",
        )
        self.include_mask.Bind(wx.EVT_CHECKBOX, self._recheck)
        # The one widget on this pane with no config key beside it: including
        # the coating is not a knob of the emitted pcb.yaml but a decision about
        # what the stackup holds -- it writes the mask entries into the file, or
        # leaves them out (config._apply_overrides). There is no `include_mask:`
        # line for a message to name, so there is nothing to print here.
        box.Add(self.include_mask, 0, wx.BOTTOM, theme.HAIR)
        return box

    def _on_material_change(self, event=None):
        """A material pick changed: re-caption the resonant-length hint (the
        substrate's εr moves it) and re-run pre-flight (the mask row is one of
        the two sources its εr may come from)."""
        self.page.form.update_hint(event)
        self._recheck()

    def _recheck(self, event=None):
        """Re-run the page's banner, if it has one -- on the simulate view that
        is the pre-flight, which reads these picks (banner.PreflightBanner).
        A designer's is its advisory area banner, which does not; re-running it
        is a re-read of the marker and nothing else, which is cheaper than
        teaching this pane which banner it is talking to."""
        banner = getattr(self.page, "banner", None)
        if banner is not None:
            banner.refresh()

    def _optimizations_box(self, pane):
        """Optimizations: the five toggles and the cells-across-driven-copper
        divisor the Speed/accuracy slider drives. Editing any of them by hand
        snaps the slider to "Custom" (speed.on_override), which is what binding
        every widget here to it is for."""
        box = self._group_box(pane, "optimizations")
        self.coarse_air = wx.CheckBox(
            pane, label="Coarse air mesh (fewer cells in the air margin + PML)"
        )
        self.no_refine_xy = wx.CheckBox(
            pane, label="Skip in-plane feature refinement (staircases thin traces)"
        )
        self.mur = wx.CheckBox(
            pane, label="Mur boundary instead of CPML (leaner, reflects ~1e-2 vs 1e-4)"
        )
        self.conformal = wx.CheckBox(
            pane, label="Conformal metal (sub-cell trace edges)"
        )
        self.adaptive = wx.CheckBox(
            pane,
            label="Adaptive mesh (coarsen copper far from the feed; "
            "faster on large boards)",
        )
        override = self.page.speed.on_override
        # Each tick with the key it drives (theme.with_key). Two of them are not
        # the key spelled out: "Skip in-plane feature refinement" is refine_xy
        # *off* and "Mur boundary" is boundary: mur -- the key is still the name
        # the solver's messages use, which is what it is here for, and the label
        # beside it says which way round the tick runs.
        for cb, key in (
            (self.coarse_air, "coarse_air"),
            (self.no_refine_xy, "refine_xy"),
            (self.mur, "boundary"),
            (self.conformal, "conformal"),
            (self.adaptive, "adaptive"),
        ):
            cb.Bind(wx.EVT_CHECKBOX, override)
            box.Add(theme.with_key(pane, cb, key), 0, wx.BOTTOM, theme.HAIR)
        copper_row = wx.BoxSizer(wx.HORIZONTAL)
        copper_row.Add(
            theme.key_label(pane, "Cells across driven copper", "copper_cells"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.copper_cells = live_text(pane, override, 40)
        copper_row.Add(self.copper_cells, 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(copper_row, 0, wx.BOTTOM, theme.HAIR)
        return box

    def _cell_box(self, pane):
        """Cell size: where the base cell starts and how coarse it may end up.

        Built by the self-contained ``cellsize`` package, which owns the pair --
        its two fields, the rules that make them a range at all and the live
        sentence they add up to. This section supplies only what the box cannot
        know (the pane's prose width, its relayout, and the re-mesh tick that
        decides what an over-budget lattice does) and registers the two controls
        in ``self.adv``, after which they are ordinary Advanced fields:
        snapshotted, restored and read back by key with all the others."""
        self.cell = CellSizeBox(
            pane,
            wrap=lambda text, mute=False: self.wrap_label(
                pane, text, margin=_PANE_MARGIN, mute=mute
            ),
            relayout=self._relayout,
            fit_cell=lambda: self.mesh_fit_cell.GetValue(),
        )
        self.adv.update(self.cell.fields)
        return self.cell.sizer

    def _mesh_box(self, pane):
        """Mesh: the lattice itself -- its cell sizes, the air margin and PML
        around the board, the memory it may cost and what happens when it costs
        too much, and the post-mesh nudge."""
        box = self._group_box(pane, "mesh")
        grid = _field_grid()
        self._add_fields(pane, grid, "mesh")
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        # What a lattice over the memory budget above does (on by default, the
        # runner's own default): the whole preparation runs again with the cell
        # forced to the finest one that fits -- everything derived from it, the
        # substrate cell and the feature floor and the feed gap, follows -- and
        # the run proceeds instead of stopping. It is never quiet: MESH-028 says
        # which cell was asked for, which was used, and what the used one costs
        # in cells per wavelength and across the driven copper, so the report
        # carries the trade. Off is the plain refusal, which names the same cell
        # and lets the user decide -- for a run whose mesh has to be the one
        # asked for or nothing (a reference run, a sweep whose points must be
        # comparable to each other). Deliberately NOT an optimization toggle:
        # a run inside its budget never reaches this, so there is nothing here
        # for the Speed/accuracy slider to drive.
        self.mesh_fit_cell = wx.CheckBox(
            pane,
            label="Re-mesh at the finest cell that fits the memory budget "
            "(instead of stopping)",
        )
        self.mesh_fit_cell.SetValue(True)
        # It also decides what the Cell size box above means -- with an explicit
        # cell and this off there is nothing left for a ceiling to bound -- so
        # the tick re-captions that box as well.
        self.mesh_fit_cell.Bind(wx.EVT_CHECKBOX, self.cell.refresh)
        box.Add(
            theme.with_key(pane, self.mesh_fit_cell, "mesh_fit_cell"),
            0,
            wx.BOTTOM,
            theme.HAIR,
        )
        # Post-mesh node nudging (on by default): the built lattice's node lines
        # slide onto nearby axis-aligned material edges -- copper and the board
        # outline -- so a trace is meshed at its drawn width and the board at
        # its drawn size, rather than at whatever the cell centres sampled.
        # Deliberately NOT an optimization toggle: it creates and deletes no
        # node, so the mesh it builds is the same size either way and there is
        # nothing for the Speed/accuracy slider to drive. A move may still cost
        # up to 5% of the time step, hence "same cell count" and not "same run
        # time" on the label; the driven cell moves with the rest, so the feed
        # gap the run reports is the one that got built. Off reproduces the
        # un-nudged lattice, and its gap, exactly -- for an A/B, or bisecting a
        # regression.
        self.mesh_nudge = wx.CheckBox(
            pane,
            label="Nudge the mesh onto the copper and board edges (same cell count)",
        )
        self.mesh_nudge.SetValue(True)
        box.Add(
            theme.with_key(pane, self.mesh_nudge, "mesh_nudge"),
            0,
            wx.BOTTOM,
            theme.HAIR,
        )
        return box

    def _refinement_box(self, pane):
        """Feature refinement: which features are subdivided and how finely.
        The master switch is the Optimizations box's "Skip in-plane feature
        refinement" (refine_xy); the two graded knobs here (refine_n and the
        checkbox) are rejected by the runner with it off, so config.write_yaml
        emits them only when it is on -- the size floors are written either
        way."""
        box = self._group_box(pane, "refinement")
        grid = _field_grid()
        self._add_fields(pane, grid, "refinement")
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        # Graded feature refinement: grades the coarser
        # adaptive bands to width/(N-1) and width/(N-2) instead of pinning
        # them, so far low-current copper doesn't throttle the Courant step.
        # Independent of the Speed/accuracy slider (like Auto ground/source);
        # only takes effect with feature refinement and the adaptive mesh both
        # on -- see config.write_yaml.
        self.refine_adaptive = wx.CheckBox(
            pane, label="Grade adaptive bands during feature refinement"
        )
        self.refine_adaptive.SetValue(True)
        box.Add(
            theme.with_key(pane, self.refine_adaptive, "refine_adaptive"),
            0,
            wx.BOTTOM,
            theme.HAIR,
        )
        return box

    def _run_box(self, pane):
        """Frequencies and run: the band the port is excited over, how long the
        stepping goes on for (the simulation time itself is on the section that
        starts the pass -- Run, or a designer's Scan -- so these are the
        fixed-step and thread overrides beside it), and what the run leaves
        behind."""
        box = self._group_box(pane, "run")
        grid = _field_grid()
        self._add_fields(pane, grid, "run")
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        # The only output knob there is: both dumps are written by every run,
        # and this asks for the data one a second time as bare JSON. The .js
        # the report page loads is an assignment with an unquoted key -- not
        # JSON, and no parser will take it -- so this tick is what makes a run
        # readable by anything that is not that page: a script, a notebook, the
        # command line's reader. Off by default because it is a second copy of
        # a file that runs to hundreds of kilobytes.
        #
        # Deliberately NOT an optimization toggle: it changes nothing about the
        # mesh, the pass or the numbers, only how many files they land in.
        self.output_json = wx.CheckBox(
            pane, label="Also write the data as bare JSON (readable off the page)"
        )
        box.Add(
            theme.with_key(pane, self.output_json, "output_json"),
            0,
            wx.BOTTOM,
            theme.HAIR,
        )
        return box

    def _feed_box(self, pane):
        """Feed port: the impedance the port is driven through, and where the
        driven edge sits across the copper. The feed POINT is the marker's
        (there is no coordinate field here) and its gap is the runner's to
        sever."""
        box = self._group_box(pane, "feed")
        grid = _field_grid()
        self._add_fields(pane, grid, "feed")
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        # Centerline snap: the runner puts the feed point on the
        # centerline of the copper its driven edge bridges, which is what a
        # marker dropped on a feed line means -- it names the line to drive,
        # not the spot across it to stand on -- and makes the impedance
        # independent of how precisely that marker landed. Off places the
        # driven edge by hand (an asymmetric launch, a port on one edge of a
        # wide section); it moves the port and nothing else. Like Auto
        # ground/source, independent of the Speed/accuracy slider.
        self.feed_snap_to_center = wx.CheckBox(
            pane, label="Snap the feed to the centerline of the copper it drives"
        )
        self.feed_snap_to_center.SetValue(True)
        box.Add(
            theme.with_key(pane, self.feed_snap_to_center, "feed_snap_to_center"),
            0,
            wx.BOTTOM,
            theme.HAIR,
        )
        return box

    def _ground_box(self, pane):
        """Ground: whether the port's source side is checked for a DC path to
        ground, how far an automatic ground/source tie may be looked for, and
        the raster the two of them read the copper on (a bitmap of its own --
        never the mesh). Whether that search happens at all is the pass' own
        knob, on the section that starts it (sections.passknobs.AutoGroundRow)
        -- the bound belongs with the numbers, the switch with the button."""
        box = self._group_box(pane, "ground")
        grid = _field_grid()
        self._picker(pane, grid, GROUND_CHECK)
        self._add_fields(pane, grid, "ground")
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        return box

    def _markers_box(self, pane):
        """Markers: the User layer the plugin's markers are drawn on -- one
        pick for the feed marker's footprint and the area marker's group alike,
        shared across the pages like the feed picks. The marker section owns the
        widget -- it is the one that places and writes the marker, and it seeds
        its own status line once the picker exists -- and every page carrying
        this pane has one: the simulate view's feed marker, a designer's area
        marker (both are sections.marker.FeedMarkerSection). A page without one
        simply has no Markers box."""
        marker = getattr(self.page, "feed_section", None)
        if marker is None:
            return None
        box = self._group_box(pane, "markers")
        grid = _field_grid()
        marker.build_layer_picker(pane, grid)
        box.Add(grid, 0, wx.BOTTOM, theme.HAIR)
        return box

    # --- shared-form state (model / persistence) ------------------------------
    # The bool toggles this section owns, snapshotted/restored as flat strings.
    _TOGGLES = (
        "include_mask",
        "output_json",
        "coarse_air",
        "no_refine_xy",
        "mur",
        "conformal",
        "adaptive",
        "refine_adaptive",
        "feed_snap_to_center",
        "mesh_fit_cell",
        "mesh_nudge",
    )

    # What the metal model was saved under before it was saved as a value
    # (formparams.WAS, shared with the command line's reader): Choices.index
    # takes the caption an older window saved, so the pick survives the rename.
    _WAS = formparams.WAS

    def picked(self):
        """Every closed list's *value* -- never the caption the picker drew --
        under the config key it writes. One dict, and both the saved form
        (``snapshot``) and the run parameters (``contribute``) are it, so the
        settings file and pcb.yaml cannot spell a pick differently."""
        return {
            picker.key: picker.value(self.picks[picker.key].GetSelection())
            for picker in SHARED
        }

    def mask_params(self):
        """What the pre-flight needs to judge the mask (simulate.preflight):
        whether it is included, and the material the picker supplies for it --
        the same two run parameters ``contribute`` writes, read without
        building the whole set (which parses every typed field and raises)."""
        return formparams.mask_params(self.snapshot())

    def snapshot(self):
        """This section's fields as a flat string dict (see gui.model /
        emkit.settings): the optimization toggles, cells-across-driven-copper, the
        closed lists (``picked``), the numeric ``adv.*`` knobs and the
        ``materials.*`` picks. The Marker layer pick is the Feed section's,
        snapshotted there."""
        data = {
            name: bool_str(getattr(self, name).GetValue()) for name in self._TOGGLES
        }
        data["copper_cells"] = self.copper_cells.GetValue()
        data.update(self.picked())
        for key, ctrl in self.adv.items():
            data["adv." + key] = ctrl.GetValue()
        if self.materials is not None:
            for key, val in self.materials.state().items():
                data["materials." + key] = val
        return data

    def restore(self, data):
        """Set the fields from a ``snapshot`` dict without firing edit events;
        the caller re-derives the speed slider (speed.on_override) afterwards."""
        for name in self._TOGGLES:
            if name in data:
                getattr(self, name).SetValue(parse_bool(data[name]))
        if "copper_cells" in data:
            self.copper_cells.ChangeValue(data["copper_cells"])  # no EVT_TEXT
        for picker in SHARED:
            saved = data.get(picker.key) or data.get(self._WAS.get(picker.key, ""))
            if saved:
                # index() takes a value or the caption an older window saved,
                # and an unknown one restores the default rather than whatever
                # sits next to where it used to be.
                self.picks[picker.key].SetSelection(picker.index(saved))
        for key, ctrl in self.adv.items():
            val = data.get("adv." + key)
            if val is not None:
                ctrl.ChangeValue(val)
        # ChangeValue fires no EVT_TEXT, so the Cell size caption would still
        # read the fields as they were before the restore.
        self.cell.refresh()
        if self.materials is not None:
            self.materials.restore(
                {
                    k[len("materials.") :]: v
                    for k, v in data.items()
                    if k.startswith("materials.")
                }
            )

    # --- optimizations provider (for SpeedSection) ----------------------------
    def apply_preset(self, preset):
        """Set the six optimization toggles from ``preset`` (a SpeedPreset)."""
        self.coarse_air.SetValue(preset.coarse_air)  # SetValue: no EVT_CHECKBOX
        self.no_refine_xy.SetValue(not preset.refine_xy)
        self.mur.SetValue(preset.boundary == "mur")
        self.conformal.SetValue(preset.conformal)
        self.adaptive.SetValue(preset.adaptive)
        self.copper_cells.ChangeValue(str(preset.copper_cells))  # no EVT_TEXT

    def preset_index(self):
        """The preset index matching the current toggles, or None (custom --
        also the outcome for an unparseable Cells-across-driven-copper value,
        since no preset can match it)."""
        return formparams.preset_index(self.snapshot())

    # --- run parameters -------------------------------------------------------
    def contribute(self, params):
        """Fill in every Advanced-owned run parameter: the copper model, the
        six speed/quality toggles, the per-layer materials and the numeric
        fields the user filled in (blank fields fall through to
        config.DEFAULTS). Parsed strictly, naming the field -- never silently
        substituted.

        Through this pane's own ``snapshot`` and the shared translation
        (formparams.advanced), which is the same call the command line makes on
        a settings file: this pane decides what the form *says*, and never what
        a form means."""
        formparams.advanced(self.snapshot(), params)
