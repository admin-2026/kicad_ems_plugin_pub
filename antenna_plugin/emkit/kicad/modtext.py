"""The .kicad_mod text every footprint generator here shares.

The plugin writes footprint files in three places -- the feed and area markers
(markers/feed_marker.py), the generated antenna (design/footprints.py) and the
parameter record on it (design/annotation.py) -- all in KiCad 6 syntax
(version 20211014), the oldest format every supported KiCad still parses. What
they have in common is how a number is written and how a text item is, which
is here rather than copied into each.

Pure text: the rest of this package shims the pcbnew API, this module is the
file format and imports nothing, so every generator using it stays
unit-testable off KiCad.
"""

# The font the plugin's generated texts use -- KiCad's own default, so a
# generated footprint reads like a drawn one.
FONT = "(effects (font (size 1 1) (thickness 0.15)))"


def num(v):
    """A KiCad-style number: fixed decimals, trailing zeros trimmed."""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def fp_text(kind, text, at=(0.0, 0.0), layer="F.Fab", hide=False):
    """One ``fp_text`` item of a footprint -- ``kind`` is KiCad's own
    ``reference`` / ``value`` / ``user`` -- at ``at`` in footprint-local mm,
    as the two indented lines KiCad writes it on."""
    return (
        f'  (fp_text {kind} "{text}" (at {num(at[0])} {num(at[1])}) '
        f'(layer "{layer}"){" hide" if hide else ""}\n'
        f"    {FONT})"
    )
