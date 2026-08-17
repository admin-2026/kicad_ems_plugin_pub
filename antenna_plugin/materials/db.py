"""Selectable material catalog for the antenna simulation.

Lets the user pick a metal for the copper layers (copper by default, or
aluminium, gold, ...) and a dielectric for the substrate (the board's own
stackup by default, or FR-4, PTFE, a Rogers laminate, ...). Each choice maps
to the electromagnetic constants the runner reads: a metal contributes its
bulk conductivity ``sigma`` [S/m]; a dielectric contributes its relative
permittivity ``eps`` and its loss tangent ``tan_d`` (the solver scales that
loss across the band itself).

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
    def metal_choices(cls):
        """Metal picker labels, with the Custom sentinel last."""
        return cls.metal_names() + [cls.CUSTOM]

    @classmethod
    def substrate_choices(cls):
        """Substrate picker labels, board default first and Custom last."""
        return cls.substrate_names() + [cls.CUSTOM]

    @staticmethod
    def custom_metal(sigma):
        """A one-off metal from a hand-typed conductivity [S/m]."""
        return Material(Materials.CUSTOM, sigma=float(sigma))

    @staticmethod
    def custom_substrate(eps, tan_d):
        """A one-off dielectric from a hand-typed eps_r and loss tangent."""
        return Material(Materials.CUSTOM, eps=float(eps), tan_d=float(tan_d))

    @classmethod
    def metal(cls, name):
        """The chosen metal ``Material`` (falls back to copper)."""
        return cls._by_name(cls._METALS, name) or cls._by_name(
            cls._METALS, cls.DEFAULT_METAL
        )

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
