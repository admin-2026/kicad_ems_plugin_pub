"""The drawings a plugin puts on the board, and the geometry under them.

Shared placed-geometry decoding (markergeom), the board-shape and group
mechanics beneath it (boardshapes), the marker that says where the port is and
which way it faces (feed_marker, a footprint) and the sketch of a candidate a
wizard previews (preview, a footprint again) -- each its own item, so the user
selects and deletes them one at a time.

Each of these knows exactly one shape for the thing it draws. A board carrying
a drawing an older version of a plugin made is brought up to that shape before
these ever see it, which is the plugin's own ``legacy`` package; nothing here
imports one.
"""
