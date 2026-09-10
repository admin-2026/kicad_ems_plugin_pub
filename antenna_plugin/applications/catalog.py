"""The design targets a picker offers: the built-in services and the user's own.

The kind ``userlib.SavedCatalog`` is told about here is a design target: what
its fields are (the numbers the ``Custom…`` form is typed into), how one is
built from them, and what makes one a target at all -- a pattern frequency.
Everything else about it -- the file, the naming rules, the merged choices --
is the shared machinery's, and so is the same for a saved metal.

The band is not a field: it is *derived* from the pattern frequency and the
bandwidth by ``Applications.custom``, the same call a live ``Custom…`` pick goes
through, so a saved target and a typed one can never be built by different
rules. The bandwidth stored is the one read back off those band edges
(``fields_of``), which is why ``Application.bandwidth_mhz`` rounds.
"""

from ..emkit.userlib.catalog import SavedCatalog
from .db import Applications


class Catalog(SavedCatalog):
    FILENAME = "applications.json"
    FIELDS = ("f0_ghz", "bandwidth_mhz", "impedance_ohm", "return_loss_db")
    NOUN = "design target"
    CUSTOM = Applications.CUSTOM

    def builtin_names(self):
        return Applications.names()

    def builtin(self, name):
        return Applications.get(name)

    def build(self, name, values):
        return Applications.custom(name=name, **values)

    def check(self, values):
        """Only the pattern frequency is required: a target with no frequency
        is nothing to design at, while a free band, impedance or return-loss
        target is a target that judges less (shown, not judged)."""
        f0 = values.get("f0_ghz")
        if not f0 or f0 <= 0:
            raise ValueError("enter a positive pattern frequency (GHz)")
