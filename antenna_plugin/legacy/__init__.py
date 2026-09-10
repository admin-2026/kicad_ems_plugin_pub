"""One-way upgrades of drawings older versions of the plugin left on a board.

The plugin reads what it finds on the board, and what it finds may have been
drawn by a version that drew it differently. Rather than teach the live code two
shapes for one thing -- a fork that never closes, and that every later change
has to be made twice -- the old drawing is converted to the current one the
first time the wizard looks at the board, and everything after that sees only
the current one.

That conversion is all this package is, one module per thing that changed:

    area_marker_v1.py   the area marker as a single footprint (the plugin up to
                        2026-09-01), converted to the group of a draggable
                        rectangle plus a rigid feed-arrow footprint

The arrow points one way: the marker modules know nothing about this package,
the wizard's board sync calls into it, and a module here can be deleted outright
once no board in the wild carries what it converts.
"""
