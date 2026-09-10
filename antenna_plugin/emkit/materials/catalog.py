"""The materials a layer picker offers: the built-in table and the user's own.

Three kinds of ``userlib.SavedCatalog``, since the pickers hold different
things: a metal is a conductivity, a substrate an eps_r and a loss tangent, and
they are saved in files of their own. The solder mask holds a substrate's two
constants and subclasses it for exactly that reason -- the difference is the
file and the noun, not the rule. Everything else -- where the files live,
what a name may be, how a record becomes a material -- is the shared
machinery's (``userlib.catalog``), the same as for every kind a product keeps
a picker of its own for.

``check`` is where each kind says what its numbers must be, and it is the only
place that says it: the same rule refuses a save, refuses a hand-typed
``Custom…`` pick when the run config is built, and drops a nonsense record from
the file. The substrate kind's built-in list leads with the "From board
stackup" sentinel, so ``get`` answers ``None`` for it -- which is that
sentinel's meaning (keep the board's own eps) -- and no saved material may take
its name.
"""

from ..userlib.catalog import SavedCatalog
from .db import Materials


class MetalCatalog(SavedCatalog):
    FILENAME = "metals.json"
    FIELDS = ("sigma",)
    NOUN = "metal"
    CUSTOM = Materials.CUSTOM

    def builtin_names(self):
        return Materials.metal_names()

    def builtin(self, name):
        return Materials.metal_named(name)  # strict: no falling back to copper

    def build(self, name, values):
        return Materials.custom_metal(values["sigma"], name=name)

    def check(self, values):
        sigma = values.get("sigma")
        if not sigma or sigma <= 0:
            raise ValueError("enter a positive conductivity (S/m)")


class SubstrateCatalog(SavedCatalog):
    FILENAME = "substrates.json"
    FIELDS = ("eps", "tan_d")
    NOUN = "substrate"
    CUSTOM = Materials.CUSTOM

    def builtin_names(self):
        return Materials.substrate_names()  # board-default sentinel first

    def builtin(self, name):
        return Materials.substrate(name)  # None for the sentinel

    def build(self, name, values):
        return Materials.custom_substrate(values["eps"], values["tan_d"], name=name)

    def check(self, values):
        eps, tan_d = values.get("eps"), values.get("tan_d")
        if eps is None or eps < 1 or tan_d is None or tan_d < 0:
            raise ValueError("enter εr (≥ 1) and a loss tangent (≥ 0)")


class MaskCatalog(SubstrateCatalog):
    """The solder mask's own list. A coating is the same two constants as a
    laminate and holds them to the same rule, so only what it is *called*, what
    it offers and where the user's own are kept differ -- a mask saved under a
    name of your own has no business turning up in the substrate picker."""

    FILENAME = "masks.json"
    NOUN = "solder mask"

    def builtin_names(self):
        return Materials.mask_names()  # board-default sentinel first

    def builtin(self, name):
        return Materials.mask(name)  # None for the sentinel
