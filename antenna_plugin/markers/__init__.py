"""The drawings this plugin puts on the board that are about an antenna: the
wizard's area marker (area_marker, a group of board shapes so KiCad's point
editor will let the user drag its rectangle into shape) and the advisory
checks it is judged by (area_checks).

The pieces under them -- the placed-geometry decoding, the board-shape and
group mechanics, the feed marker and the candidate preview -- are the core's
(``emkit.markers``), because a drawing that says "the port is here" is not an
antenna idea.

A board carrying a marker an older version of the plugin made is brought up to
the current shape before either of these sees it, which is the ../legacy
package; nothing here imports it.
"""
