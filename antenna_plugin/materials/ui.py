"""Optional material-selection block for the Antenna Designer dialog.

Owns a per-layer "Materials" table -- one metal picker for every copper layer
and one dielectric picker for every substrate gap -- and translates the picks
into the override params ``config.py`` already understands. Each picker also
offers **Custom…**, which reveals fields for a hand-typed conductivity (metals)
or eps_r + loss tangent (dielectrics).

The output is two ordered lists, ``metal_layers`` and ``substrate_layers``,
that ``config._apply_overrides`` lays onto the board-read stackup entry by
entry. They are the sole source of each layer's conductivity/loss -- config
invents no fallback, so any layer left without a material blocks the run.
Nothing else imports this module directly; the GUI loads it through a guarded
try/except and injects the board's layer list.

wx + materials (plus the shared ``gui.widgets`` controls and the ``gui.theme``
look) -- no pcbnew, no ``ems``.
"""

import wx

from ..gui import theme
from ..gui.widgets import no_scroll, to_float
from .db import Materials

_GREY = wx.SYS_COLOUR_GRAYTEXT
_CHOICE_W = 380  # fixed picker width; doesn't stretch on resize
_HINT_WRAP = 560  # px the note under the table wraps at (see MaterialSelector)


class _MetalRow:
    """One copper layer: a metal picker plus a conductivity field enabled only
    for the Custom pick."""

    def __init__(self, parent, grid, label, on_change):
        self.label = label
        grid.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        self.choice = no_scroll(
            wx.Choice(parent, size=(_CHOICE_W, -1), choices=Materials.metal_choices())
        )
        self.choice.SetStringSelection(Materials.DEFAULT_METAL)
        grid.Add(self.choice, 0)
        self.sigma = wx.TextCtrl(parent, size=(80, -1))
        self.sigma.SetHint("σ S/m")
        self.sigma.Enable(False)
        grid.Add(self.sigma, 0)
        self._on_change = on_change
        self.choice.Bind(wx.EVT_CHOICE, self._on_choice)

    def _on_choice(self, event):
        self._sync()
        if self._on_change:
            self._on_change(event)

    def _sync(self):
        """Enable the conductivity field only for the Custom pick."""
        self.sigma.Enable(self.choice.GetStringSelection() == Materials.CUSTOM)

    def material(self, strict=False):
        """The picked metal. ``strict`` (used when building the run config)
        raises on a Custom pick whose conductivity doesn't parse, instead of
        silently substituting copper's value."""
        if self.choice.GetStringSelection() == Materials.CUSTOM:
            sigma = to_float(self.sigma.GetValue(), None)
            if sigma is None or sigma <= 0:
                if strict:
                    raise ValueError(
                        f"{self.label}: enter a positive conductivity "
                        "(S/m) for the Custom metal"
                    )
                sigma = 5.8e7
            return Materials.custom_metal(sigma)
        return Materials.metal(self.choice.GetStringSelection())

    def get_state(self):
        return (self.choice.GetStringSelection(), self.sigma.GetValue())

    def set_state(self, choice, sigma):
        if choice:
            self.choice.SetStringSelection(choice)
        self.sigma.ChangeValue(sigma or "")
        self._sync()


class _SubstrateRow:
    """One dielectric gap: a substrate picker plus eps_r / loss-tangent fields
    enabled only for the Custom pick. Returns ``None`` for the board-default
    sentinel (keep the board's own eps)."""

    def __init__(self, parent, grid, label, on_change):
        self.label = label
        grid.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        self.choice = no_scroll(
            wx.Choice(
                parent, size=(_CHOICE_W, -1), choices=Materials.substrate_choices()
            )
        )
        self.choice.SetSelection(0)  # board-default sentinel
        grid.Add(self.choice, 0)
        self.eps = wx.TextCtrl(parent, size=(52, -1))
        self.eps.SetHint("εr")
        self.eps.Enable(False)
        grid.Add(self.eps, 0)
        self.tand = wx.TextCtrl(parent, size=(52, -1))
        self.tand.SetHint("tanδ")
        self.tand.Enable(False)
        grid.Add(self.tand, 0)
        self._on_change = on_change
        self.choice.Bind(wx.EVT_CHOICE, self._on_choice)

    def _on_choice(self, event):
        self._sync()
        if self._on_change:
            self._on_change(event)

    def _sync(self):
        """Enable the eps / loss fields only for the Custom pick."""
        custom = self.choice.GetStringSelection() == Materials.CUSTOM
        self.eps.Enable(custom)
        self.tand.Enable(custom)

    def material(self, strict=False):
        """The picked substrate (None = board default). ``strict`` (used
        when building the run config) raises on a Custom pick whose fields
        don't parse, instead of silently substituting FR-4's values."""
        name = self.choice.GetStringSelection()
        if name == Materials.CUSTOM:
            eps = to_float(self.eps.GetValue(), None)
            tand = to_float(self.tand.GetValue(), None)
            if eps is None or eps < 1 or tand is None or tand < 0:
                if strict:
                    raise ValueError(
                        f"{self.label}: enter εr (≥ 1) and a loss tangent "
                        "(≥ 0) for the Custom substrate"
                    )
                eps = 4.4 if eps is None or eps < 1 else eps
                tand = 0.02 if tand is None or tand < 0 else tand
            return Materials.custom_substrate(eps, tand)
        return Materials.substrate(name)

    def get_state(self):
        return (
            self.choice.GetStringSelection(),
            self.eps.GetValue(),
            self.tand.GetValue(),
        )

    def set_state(self, choice, eps, tand):
        if choice:
            self.choice.SetStringSelection(choice)
        self.eps.ChangeValue(eps or "")
        self.tand.ChangeValue(tand or "")
        self._sync()


class MaterialSelector:
    """A self-contained group (the shared ``theme.group_box``) holding the
    per-layer material table. The host adds ``sizer()`` to its layout, calls
    ``apply(params)`` when building the run config, and reads
    ``substrate_material()`` for the resonant-length hint.

    ``layers`` is ``(copper_layer_names, dielectric_gap_count)`` -- the caller
    (``gui.py``) supplies it from the board, keeping this module pcbnew-free."""

    def __init__(self, parent, layers, on_change=None):
        copper_names, gap_count = layers
        # The same frame as the Advanced pane's other groups, since this box
        # sits among them -- a heading, no rule (gui.theme).
        self._box = theme.group_box(parent, "Materials")

        self._box.Add(wx.StaticText(parent, label="Metal layers"), 0)
        mgrid = wx.FlexGridSizer(3, theme.ROW, theme.ROW)
        self.metal_rows = [
            _MetalRow(parent, mgrid, name, on_change) for name in copper_names
        ]
        self._box.Add(mgrid, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, theme.HAIR)

        self._box.Add(wx.StaticText(parent, label="Substrate layers"), 0)
        sgrid = wx.FlexGridSizer(4, theme.ROW, theme.ROW)
        labels = (
            [f"Dielectric {i + 1}" for i in range(gap_count)]
            if gap_count > 1
            else ["Substrate"]
        )
        self.substrate_rows = [
            _SubstrateRow(parent, sgrid, lbl, on_change) for lbl in labels
        ]
        self._box.Add(sgrid, 0, wx.EXPAND | wx.TOP, theme.HAIR)

        hint = wx.StaticText(
            parent,
            label="Per-layer metal σ and substrate εr / loss for the solve; "
            "pick Custom… to type values. Layers match the board as of "
            "when this dialog opened — reopen it after changing them.",
        )
        hint.SetForegroundColour(wx.SystemSettings.GetColour(_GREY))
        # Wrapped, and to a fixed width: laid out at its natural width this
        # sentence is wider than the window, and the form only scrolls
        # vertically, so it would push the pane's own controls off the right
        # edge. The page's re-wrapping label (sections.base.wrap_label) is not
        # available here -- this module knows no page -- so it wraps once, to
        # the width of the pickers above it.
        hint.Wrap(_HINT_WRAP)
        self._box.Add(hint, 0, wx.TOP, theme.ROW)

    def sizer(self):
        return self._box

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
            choice, sigma = row.get_state()
            data[f"metal{i}.choice"] = choice
            data[f"metal{i}.sigma"] = sigma
        for i, row in enumerate(self.substrate_rows):
            choice, eps, tand = row.get_state()
            data[f"sub{i}.choice"] = choice
            data[f"sub{i}.eps"] = eps
            data[f"sub{i}.tand"] = tand
        return data

    def restore(self, data):
        """Apply a ``state`` dict; rows without saved keys keep their default."""
        for i, row in enumerate(self.metal_rows):
            row.set_state(data.get(f"metal{i}.choice"), data.get(f"metal{i}.sigma"))
        for i, row in enumerate(self.substrate_rows):
            row.set_state(
                data.get(f"sub{i}.choice"),
                data.get(f"sub{i}.eps"),
                data.get(f"sub{i}.tand"),
            )
