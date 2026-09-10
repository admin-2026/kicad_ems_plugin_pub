"""Selectable material catalog for the antenna simulation.

Lets the user pick a metal for the copper layers (copper by default, or
aluminium, gold, ...) and a dielectric for the substrate (the board's own
stackup by default, or FR-4, PTFE, a Rogers laminate, ...). Each choice maps
to the electromagnetic constants the runner reads: a metal contributes its
bulk conductivity ``sigma`` [S/m]; a dielectric contributes its relative
permittivity ``eps`` and its loss tangent ``tan_d`` (the solver scales that
loss across the band itself). The solder mask is a third list of the second
kind: the coating over the copper is a thin dielectric, and a run that includes
it (Advanced > Materials > Solder mask) meshes it with these constants or with
the board's own.

This package is the sole source of the metal conductivity, and can override a
dielectric's board-read eps / loss tangent: ``config.py`` invents no metal
sigma, so a copper foil needs a metal pick or the run is blocked; a dielectric
falls back to the board's own eps + loss tangent when left at "from board
stackup" (see ``config._apply_overrides``). The GUI hook is still guarded, but
with the package removed there is no metal-conductivity source and a run cannot
proceed until one is supplied. Stdlib only, no pcbnew and nothing from ``ems``:
kept unit-testable off KiCad. The catalog's Copper / FR-4 entries carry the
usual textbook constants, so those default picks reproduce the familiar numbers.
"""


class Material:
    """One named material. Metals carry a fixed ``sigma``; dielectrics carry
    ``eps`` (relative permittivity) and ``tan_d`` (loss tangent)."""

    def __init__(self, name, *, sigma=None, eps=None, tan_d=None):
        self.name = name
        self.sigma = sigma
        self.eps = eps
        self.tan_d = tan_d

    @property
    def spec_line(self):
        """The constants this material actually carries, in one line
        ("σ 5.8e+07 S/m", "εr 4.4 · tanδ 0.02") -- what the log says a saved
        material is, mirroring an application's ``spec_line``. A constant the
        material doesn't have is left out, not printed as a zero."""
        parts = []
        if self.sigma:
            parts.append(f"σ {self.sigma:g} S/m")
        if self.eps:
            parts.append(f"εr {self.eps:g}")
        if self.tan_d is not None:
            parts.append(f"tanδ {self.tan_d:g}")
        return " · ".join(parts)


class Materials:
    """Catalog and lookup for the selectable metals and substrates.

    ``BOARD_SUBSTRATE`` is the sentinel first substrate choice: keep the
    per-dielectric ``eps`` read from the board's Physical Stackup instead of
    forcing one material's value (this is the default, so leaving the picker
    alone preserves the board-is-source-of-truth behaviour)."""

    DEFAULT_METAL = "Copper"
    BOARD_SUBSTRATE = "From board stackup"
    CUSTOM = "Custom…"  # picker entry that reveals hand-typed fields

    # Bulk conductivities [S/m] at room temperature. Copper is the default
    # metal pick (5.8e7 S/m), so an untouched picker uses copper foil.
    _METALS = [
        Material("Copper", sigma=5.8e7),
        Material("Silver", sigma=6.3e7),
        Material("Gold", sigma=4.1e7),
        Material("Aluminium", sigma=3.77e7),
        Material("Brass", sigma=1.5e7),
        Material("Nickel", sigma=1.43e7),
    ]

    # Solder mask coatings, same two constants as a substrate: the mask is a
    # thin dielectric over the copper, and a run that includes it meshes it
    # with these. Typical published ranges rather than one house's datasheet
    # (LPI green is quoted anywhere from 3.2 to 4.0 depending on cure and
    # frequency), which is what Custom… and Save as… are for -- and why the
    # sentinel first choice is still the board's own numbers.
    _MASKS = [
        Material("LPI solder mask", eps=3.5, tan_d=0.025),
        Material("Dry-film solder mask", eps=4.0, tan_d=0.03),
        Material("Polyimide coverlay", eps=3.5, tan_d=0.008),
    ]

    # Dielectrics as (eps_r, tan_d) -- both ride straight through to the
    # solver. FR-4's eps 4.4 / tan_d 0.02 are the familiar textbook values.
    _SUBSTRATES = [
        Material("FR-4", eps=4.4, tan_d=0.02),
        Material("Rogers RO4003C", eps=3.38, tan_d=0.0027),
        Material("Rogers RO4350B", eps=3.48, tan_d=0.0037),
        Material("Rogers RT/duroid 5880", eps=2.20, tan_d=0.0009),
        Material("PTFE (Teflon)", eps=2.1, tan_d=0.0002),
        Material("Alumina 99.5%", eps=9.8, tan_d=0.0001),
        Material("Polyimide", eps=3.5, tan_d=0.008),
    ]

    @classmethod
    def metal_names(cls):
        return [m.name for m in cls._METALS]

    @classmethod
    def substrate_names(cls):
        """Substrate picker labels, board-default sentinel first."""
        return [cls.BOARD_SUBSTRATE] + [m.name for m in cls._SUBSTRATES]

    @classmethod
    def mask_names(cls):
        """Solder-mask picker labels, board-default sentinel first -- the same
        sentinel the substrates use, since it means the same thing on both: the
        layer's own eps out of the board's Physical Stackup."""
        return [cls.BOARD_SUBSTRATE] + [m.name for m in cls._MASKS]

    @classmethod
    def mask(cls, name):
        """The chosen solder mask ``Material``, or ``None`` for the
        board-default sentinel."""
        if name == cls.BOARD_SUBSTRATE:
            return None
        return cls._by_name(cls._MASKS, name)

    @classmethod
    def metal_choices(cls):
        """Metal picker labels, with the Custom sentinel last."""
        return cls.metal_names() + [cls.CUSTOM]

    @classmethod
    def substrate_choices(cls):
        """Substrate picker labels, board default first and Custom last."""
        return cls.substrate_names() + [cls.CUSTOM]

    @staticmethod
    def custom_metal(sigma, name=None):
        """A metal from a hand-typed conductivity [S/m]. ``name`` is the label
        it carries: the ``Custom…`` sentinel while it is being typed, or the
        user's own once it has been saved and picked back (materials.catalog)
        -- one construction either way."""
        return Material(name or Materials.CUSTOM, sigma=float(sigma))

    @staticmethod
    def custom_substrate(eps, tan_d, name=None):
        """A dielectric from a hand-typed eps_r and loss tangent, named as
        :meth:`custom_metal` is."""
        return Material(name or Materials.CUSTOM, eps=float(eps), tan_d=float(tan_d))

    @classmethod
    def metal(cls, name):
        """The chosen metal ``Material`` (falls back to copper)."""
        return cls.metal_named(name) or cls._by_name(cls._METALS, cls.DEFAULT_METAL)

    @classmethod
    def metal_named(cls, name):
        """The metal called ``name``, or ``None`` -- the strict lookup, for a
        caller that has to tell "not one of ours" from copper (the saved-metal
        catalog does: an unknown name there is the user's own or nobody's)."""
        return cls._by_name(cls._METALS, name)

    @classmethod
    def substrate(cls, name):
        """The chosen substrate ``Material``, or ``None`` for the board-default
        sentinel (meaning: don't override the board's eps)."""
        if name == cls.BOARD_SUBSTRATE:
            return None
        return cls._by_name(cls._SUBSTRATES, name)

    @staticmethod
    def _by_name(items, name):
        for m in items:
            if m.name == name:
                return m
        return None
