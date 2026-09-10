"""What a generated antenna footprint says about itself, on F.Fab.

Copper is the one thing the wizard cannot re-derive. A placed antenna is a bag
of polygons like any other footprint's, and the numbers behind it -- which
topology, which target frequency, which knob settings -- live in a scan folder
that outlives nothing. So the footprint carries them itself, as plain
``key=value`` text on F.Fab, the layer for what the drawing has to say rather
than what the board is made of::

    design=lmonopole
    plugin_version=0.1.0
    f0_ghz=2.45
    length_mm=30.591067
    width_mm=1
    stem_mm=12.236427

``record`` builds those lines, ``fab_text`` turns them into the footprint's
text items, and ``read`` parses them back off a .kicad_mod.

What goes in: the design (registry.by_key resolves it), the plugin that laid
the copper out, the target frequency, and every parameter of *that design's*
table in table order -- so a topology added or a knob added is in the record
with no edit here. What stays out: derived numbers (an L-monopole's stem/arm
split, a meander's fold count) are what ``solve`` makes of these values, and a
second copy of them beside the copper could only ever go stale.

**Self-contained on purpose.** Nothing else in the plugin reads or writes the
record, and design/footprints.py touches it in one line of ``sexpr``. Delete
this module and that line and the wizard still places exactly the same copper:
this is an annotation, never an input.

Pure: no wx, no pcbnew (tests/test_annotation.py runs it off KiCad).
"""

import re
from typing import NamedTuple

from ..emkit import versions
from ..emkit.kicad import modtext

# The layer the record is written on, and the pitch of the stacked lines for
# modtext's 1 mm font.
LAYER = "F.Fab"
LINE_MM = 1.2

# One F.Fab user text of a .kicad_mod: the payload of an ``fp_text user``
# whose layer is on the same line, which is how modtext.fp_text emits them
# (only the effects wrap). What makes a payload part of the record is its
# ``key=value`` shape, and what makes the record ours is the ``design`` key in
# it; a fab note of somebody's own reads as neither.
_FAB_TEXT = re.compile(r'\(fp_text user "([^"]*)"[^\n]*\(layer "F\.Fab"\)')


class FabParams(NamedTuple):
    """A generated footprint's parameter record, as read back off its F.Fab
    text: the ``design`` key, the ``plugin_version`` that generated it, the
    target ``f0_ghz`` it was generated for, and ``values`` -- the design's
    geometry knobs in mm, keyed exactly as ``design.solve`` takes them."""

    design: str
    plugin_version: str
    f0_ghz: float
    values: dict


def record(design, values, f0_ghz):
    """The record as ``key=value`` strings, one per line (see the module
    docstring for what is in it and what is not).

    The **plugin version** is there because the copper is only as reproducible
    as the code that laid it out: a topology's layout can change between
    releases (a meander's fold rule, a keepout), so a board whose antenna is
    two years old needs to say which plugin's idea of these values it is --
    the numbers alone would re-solve into a subtly different shape and nothing
    would say so. It is ``versions.plugin_version()``, the same answer the
    About page gives, and an installation that cannot establish it records
    that rather than a guess.

    Raises ValueError naming any knob ``values`` is missing, rather than
    writing a record that is a partial answer nobody can tell from a whole
    one."""
    missing = [p.key for p in design.params if values.get(p.key) is None]
    if missing:
        raise ValueError(
            f"cannot record the {design.name} parameters on {LAYER}: no value "
            f"for {', '.join(missing)}"
        )
    pairs = [
        ("design", design.key),
        ("plugin_version", versions.plugin_version()),
        ("f0_ghz", modtext.num(f0_ghz)),
    ]
    pairs += [(f"{p.key}_mm", modtext.num(values[p.key])) for p in design.params]
    return [f"{key}={value}" for key, value in pairs]


def fab_text(design, values, f0_ghz, below_mm):
    """The record as .kicad_mod text items, stacked one line below ``below_mm``
    (the y of the last text the footprint has already emitted, in local mm).

    Visible, unlike a footprint's value field: hidden text is drawn by neither
    the board editor (bar its Hidden Text toggle) nor a plot, and a record
    nobody sees on the board is one nobody knows to look for. A user who wants
    the canvas back hides or moves the lines on their own copy."""
    return [
        modtext.fp_text("user", line, (0.0, below_mm + (i + 1) * LINE_MM), LAYER)
        for i, line in enumerate(record(design, values, f0_ghz))
    ]


def read(text):
    """The record in .kicad_mod ``text`` as a :class:`FabParams`, or None when
    it carries none (any footprint that isn't one of ours -- a fab note of
    somebody's own is not a ``design=`` line). Raises ValueError on a record
    too damaged to use: an edited text is worth a complaint, since acting on
    half of one would re-solve a different antenna than the copper on the
    board."""
    fields = {}
    for payload in _FAB_TEXT.findall(text):
        key, sep, value = payload.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    if "design" not in fields:
        return None
    try:
        values = {
            key[: -len("_mm")]: float(v)
            for key, v in fields.items()
            if key.endswith("_mm")
        }
        return FabParams(
            fields["design"],
            fields["plugin_version"],
            float(fields["f0_ghz"]),
            values,
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"damaged antenna parameter record on {LAYER}: {exc}") from exc
