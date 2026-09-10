"""Optional material-selection block for the plugin's dialog.

Owns a per-layer "Materials" table -- one metal picker for every copper layer,
one dielectric picker for every substrate gap and one for the solder mask
coating -- and translates the picks into the override params ``config.py``
already understands. Each picker offers
**Custom…**, which brings its fields to life (a conductivity for a metal, eps_r
+ loss tangent for a dielectric), and the **Save as… / Update / Delete** trio
beside them, which turns a typed material into a picker entry of the user's own
-- on this board and every other one. That trio and the file behind it are not
this module's: they are ``gui.savedpick`` over ``materials.catalog``, the same
pair the Design-target section's application picker wears.

The two row kinds differ only in what they are made of -- their picker, their
fields, their default pick -- so :class:`_MaterialRow` is the row and the two
subclasses are little more than that list. A row's fields are live exactly when
they *are* the material: the Custom pick, and a saved material being updated
(``saved.is_typing``). Any other pick answers for itself, and fills the (dead)
fields with its own constants, so dropping to Custom… starts from what was
picked rather than from an empty box.

The output is two ordered lists, ``metal_layers`` and ``substrate_layers``,
plus the single ``mask_material``, that ``config._apply_overrides`` lays onto
the board-read stackup entry by entry. They are the sole source of each layer's
conductivity/loss -- config invents no fallback, so any layer left without a
material blocks the run.
Nothing else imports this module directly; the GUI loads it through a guarded
try/except and injects the board's layer list.

wx + materials (plus the shared ``gui.widgets`` controls, the ``gui.theme``
look and ``gui.savedpick``) -- no pcbnew, no ``ems``.
"""

from collections import namedtuple

import wx

from ..gui import theme
from ..gui.savedpick import SavedPicks
from ..gui.widgets import enable, no_scroll, to_float
from .catalog import MaskCatalog, MetalCatalog, SubstrateCatalog
from .db import Materials

_CHOICE_W = 300  # fixed picker width; doesn't stretch on resize

# One typed constant of a row: the widget and settings key it is known by here,
# the catalog field it is saved as, its placeholder, the unit it is read in and
# its width in px. The widths hold the widest value a pick fills them with --
# "5.8e+07" for a metal, "0.0002" for a loss tangent -- rather than the
# placeholder, which is shorter. ``unit`` is a static label beside the field
# (the widgets.LabeledSlider suffix, for the same reason: the field holds the
# bare number, and the unit stays on screen once a value has covered the
# placeholder). A dimensionless constant carries its symbol there instead of a
# unit, so every field in the table is named next to the number it holds; those
# rows leave ``hint`` empty rather than print the symbol twice on an empty
# field. No hint states an example value: a greyed number in an empty box reads
# as one this dialog would use, and it would use nothing (config invents no
# fallback).
_Field = namedtuple("_Field", "key field hint unit width")


class _MaterialRow:
    """One layer of the table: a picker, the fields a typed material is typed
    into, and the buttons that keep one.

    Subclasses supply ``FIELDS`` (left to right) and ``DEFAULT`` (the pick a
    fresh row opens on); everything else is the same for both."""

    FIELDS = ()
    DEFAULT = None

    def __init__(self, parent, grid, label, catalog, on_change, on_catalog=None):
        self.label = label
        self.catalog = catalog
        self._on_change = on_change  # the pane's "a pick changed" callback
        self._on_catalog = on_catalog  # the saved-materials file changed
        grid.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        self.choice = no_scroll(
            wx.Choice(parent, size=(_CHOICE_W, -1), choices=catalog.choices())
        )
        self.choice.SetStringSelection(self.DEFAULT)
        grid.Add(self.choice, 0)

        self.fields = {}
        for f in self.FIELDS:
            ctrl = wx.TextCtrl(parent, size=(f.width, -1))
            ctrl.SetHint(f.hint)
            enable(ctrl, False)
            # A unit rides in the field's own grid cell, so the table keeps one
            # column per constant however many of them carry a unit.
            if f.unit:
                cell = wx.BoxSizer(wx.HORIZONTAL)
                cell.Add(ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
                cell.Add(
                    wx.StaticText(parent, label=f.unit),
                    0,
                    wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
                    theme.HAIR,
                )
                grid.Add(cell, 0, wx.ALIGN_CENTER_VERTICAL)
            else:
                grid.Add(ctrl, 0)
            self.fields[f.key] = ctrl

        # The buttons ride in a column of their own, so a row that has none
        # showing (a built-in pick, which is most of them) costs no width.
        buttons = wx.BoxSizer(wx.HORIZONTAL)

        def button(label, handler):
            btn = wx.Button(parent, label=label, style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(btn, 0, wx.LEFT, theme.HAIR)
            return btn

        self.saved = SavedPicks(
            parent,
            self.choice,
            catalog,
            read=self._typed,
            on_change=self._changed,
            button=button,
            on_edit=self._focus_first,
        )
        grid.Add(buttons, 0, wx.ALIGN_CENTER_VERTICAL)

        self.choice.Bind(wx.EVT_CHOICE, self._on_choice)
        self._sync()

    @classmethod
    def columns(cls):
        """The grid columns one of these rows fills: label, picker, its fields
        and the button column."""
        return 3 + len(cls.FIELDS)

    # --- form sync ------------------------------------------------------------
    def _on_choice(self, event):
        self.saved.on_pick()  # a new pick ends any edit of the old one
        self._fill()
        self._sync()
        if self._on_change:
            self._on_change(event)

    def _changed(self):
        """The buttons changed something -- an edit opened, a material saved or
        deleted. Re-derive this row, let the pane re-read the file into the
        other rows' pickers (a saved material belongs to every layer, not to
        the row it was typed on), and tell the pane its picks may have moved."""
        self._sync()
        if self._on_catalog:
            self._on_catalog(self)
        if self._on_change:
            self._on_change(None)

    def _sync(self):
        """The fields are live where they are the material (Custom…, or a saved
        material being updated) and dead where the pick answers for itself."""
        live = self.saved.is_typing()
        for ctrl in self.fields.values():
            enable(ctrl, live)
        self.saved.sync_buttons()

    def _fill(self):
        """Put the picked material's constants in the fields, so dropping to
        Custom… (or pressing Update) starts from what was picked. A pick with
        nothing to show -- Custom… itself, or "From board stackup" -- leaves
        what is typed alone."""
        material = self.saved.entry()
        if material is None:
            return
        for f in self.FIELDS:
            value = getattr(material, f.field, None)
            if value is not None:
                self.fields[f.key].ChangeValue(f"{value:g}")

    def _focus_first(self):
        self.fields[self.FIELDS[0].key].SetFocus()

    def reread(self):
        """Rebuild the picker from the file -- what another row (or another
        page) saving a material asks of this one."""
        self.saved.refresh_choices()
        self._sync()

    # --- values ---------------------------------------------------------------
    def _typed(self):
        """The hand-typed material, as the catalog takes it: what Save as… and
        Save changes write, and what a Custom pick is judged as."""
        return {
            f.field: to_float(self.fields[f.key].GetValue(), None) for f in self.FIELDS
        }

    def material(self, strict=False):
        """The picked ``Material``: a built-in, one of the user's saved ones, or
        -- on Custom… -- one built from the typed fields. ``None`` where the
        pick means "leave the board's own value" (the substrate sentinel) and
        where a Custom pick's fields don't make a material: nothing here
        substitutes a value the user didn't type, so the caller shows its own
        default instead of judging by an invented one.

        ``strict`` (building the run config) raises on those unusable fields
        instead, naming the layer -- a run must not silently solve something
        other than what is on screen.

        A saved material being *updated* is still that material until the edit
        is saved: the pick is what the run uses, not the half-typed fields.

        What a pick stands for is the catalog's (``SavedCatalog.pick``), shared
        with the command line, which resolves the same pick out of a saved form
        -- so a row and a settings file cannot disagree about a name."""
        try:
            return self.catalog.pick(self.saved.name(), self._typed(), self.label)
        except ValueError:
            # Not a material: a Custom pick whose fields aren't one yet, or a
            # saved material deleted (in another window) while it was picked
            # here. Nothing here substitutes a value the user didn't type, so a
            # run says so and a caption shows its own default instead.
            if strict:
                raise
            return None

    # --- settings -------------------------------------------------------------
    def state(self, prefix):
        """This row's pick and typed fields as flat string keys under
        ``prefix`` (``metal0.choice``, ``metal0.sigma``, ...)."""
        data = {f"{prefix}.choice": self.choice.GetStringSelection()}
        for f in self.FIELDS:
            data[f"{prefix}.{f.key}"] = self.fields[f.key].GetValue()
        return data

    def restore(self, prefix, data):
        """Set the row from a ``state`` dict (no edit events). The pick is the
        shared trio's ``restore_pick``: the picker is rebuilt first (a material
        saved since this row was built is offered), and a material that no
        longer exists restores as Custom… with the fields saved beside it."""
        self.saved.restore_pick(data.get(f"{prefix}.choice"))
        for f in self.FIELDS:
            key = f"{prefix}.{f.key}"
            if key in data:
                self.fields[f.key].ChangeValue(data[key] or "")
        self._sync()


class _MetalRow(_MaterialRow):
    """One copper layer: which metal its foil is."""

    FIELDS = (_Field("sigma", "sigma", "σ", "S/m", 110),)
    DEFAULT = Materials.DEFAULT_METAL


class _SubstrateRow(_MaterialRow):
    """One dielectric gap: which laminate fills it, or the board's own."""

    # εr and the loss tangent are ratios: the label beside each field is the
    # symbol, since there is no unit to put there.
    FIELDS = (
        _Field("eps", "eps", "", "εr", 72),
        _Field("tand", "tan_d", "", "tanδ", 72),
    )
    DEFAULT = Materials.BOARD_SUBSTRATE


class MaterialSelector:
    """A self-contained group (the shared ``theme.group_box``) holding the
    per-layer material table. The host adds ``sizer()`` to its layout, calls
    ``apply(params)`` when building the run config, and reads
    ``substrate_material()`` for the resonant-length hint.

    ``layers`` is ``(copper_layer_names, dielectric_gap_count)`` -- the caller
    (``gui.py``) supplies it from the board, keeping this module pcbnew-free.

    One metal catalog and one substrate catalog serve all the rows of their
    kind: a saved material is the user's, not a layer's, so saving one on any
    row offers it on all of them (``_catalog_changed``)."""

    def __init__(self, parent, layers, on_change=None):
        copper_names, gap_count = layers
        self._metals = MetalCatalog()
        self._substrates = SubstrateCatalog()
        self._masks = MaskCatalog()
        # The same frame as the Advanced pane's other groups, since this box
        # sits among them -- a heading, no rule (gui.theme).
        self._box = theme.group_box(parent, "Materials")

        self._box.Add(wx.StaticText(parent, label="Metal layers"), 0)
        mgrid = wx.FlexGridSizer(_MetalRow.columns(), theme.ROW, theme.ROW)
        self.metal_rows = [
            _MetalRow(
                parent, mgrid, name, self._metals, on_change, self._catalog_changed
            )
            for name in copper_names
        ]
        self._box.Add(mgrid, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, theme.HAIR)

        self._box.Add(wx.StaticText(parent, label="Substrate layers"), 0)
        sgrid = wx.FlexGridSizer(_SubstrateRow.columns(), theme.ROW, theme.ROW)
        labels = (
            [f"Dielectric {i + 1}" for i in range(gap_count)]
            if gap_count > 1
            else ["Substrate"]
        )
        self.substrate_rows = [
            _SubstrateRow(
                parent, sgrid, lbl, self._substrates, on_change, self._catalog_changed
            )
            for lbl in labels
        ]
        self._box.Add(sgrid, 0, wx.EXPAND | wx.TOP, theme.HAIR)

        # One row for the coating, not one per side: a board is masked with the
        # same stuff top and bottom, and the thickness -- which does differ, and
        # which no material can supply -- is read per layer off the board's own
        # stackup. The row is a substrate row in every way but its catalog: same
        # two constants, same rule, its own saved file (materials.catalog).
        self._box.Add(wx.StaticText(parent, label="Solder mask"), 0, wx.TOP, theme.ROW)
        kgrid = wx.FlexGridSizer(_SubstrateRow.columns(), theme.ROW, theme.ROW)
        self.mask_row = _SubstrateRow(
            parent, kgrid, "Solder mask", self._masks, on_change, self._catalog_changed
        )
        self._box.Add(kgrid, 0, wx.EXPAND | wx.TOP, theme.HAIR)

    def sizer(self):
        return self._box

    def _rows(self):
        return self.metal_rows + self.substrate_rows + [self.mask_row]

    def _catalog_changed(self, origin):
        """A row saved or deleted a material: every other row picking from the
        same catalog re-reads the file, so the new entry is offered on all of
        them (and a deleted one is gone from all of them) without the window
        being reopened."""
        for row in self._rows():
            if row is not origin and row.catalog is origin.catalog:
                row.reread()

    def apply(self, params):
        """Fold the per-layer picks into ``params`` as the ordered
        ``metal_layers`` (each ``{"sigma": …}``) and ``substrate_layers`` (each
        ``{"eps": …, "loss_tangent": …}`` or ``None`` for the board default).
        The substrate loss rides through as a loss tangent -- the solver scales
        it across the band itself -- so nothing here depends on the pattern
        frequency. Custom picks are parsed strictly (bad fields raise, naming
        the layer)."""
        params["metal_layers"] = [
            {"sigma": row.material(strict=True).sigma} for row in self.metal_rows
        ]
        subs = []
        for row in self.substrate_rows:
            mat = row.material(strict=True)
            subs.append(
                None if mat is None else {"eps": mat.eps, "loss_tangent": mat.tan_d}
            )
        params["substrate_layers"] = subs
        self.apply_mask(params)

    def apply_mask(self, params):
        """Fold the solder-mask pick into ``params`` as ``mask_material``: the
        same ``{"eps", "loss_tangent"}`` a substrate emits, or ``None`` for the
        board's own numbers. Reachable on its own because the pre-flight asks
        for this one alone -- whether the mask can be simulated at all is a
        question about this row, and asking it must not mean parsing every
        other row on the pane (AdvancedSection.mask_params)."""
        mat = self.mask_row.material(strict=True)
        params["mask_material"] = (
            None if mat is None else {"eps": mat.eps, "loss_tangent": mat.tan_d}
        )

    def substrate_material(self):
        """The first substrate row's ``Material`` (or ``None``), for the
        resonant-length hint."""
        return self.substrate_rows[0].material() if self.substrate_rows else None

    def state(self):
        """The per-row picks as a flat string dict, for the settings file. Keys
        are indexed by row so a different board (row count) restores the rows it
        still has and ignores the rest."""
        data = {}
        for i, row in enumerate(self.metal_rows):
            data.update(row.state(f"metal{i}"))
        for i, row in enumerate(self.substrate_rows):
            data.update(row.state(f"sub{i}"))
        data.update(self.mask_row.state("mask"))
        return data

    def restore(self, data):
        """Apply a ``state`` dict; rows without saved keys keep their default."""
        for i, row in enumerate(self.metal_rows):
            row.restore(f"metal{i}", data)
        for i, row in enumerate(self.substrate_rows):
            row.restore(f"sub{i}", data)
        self.mask_row.restore("mask", data)
