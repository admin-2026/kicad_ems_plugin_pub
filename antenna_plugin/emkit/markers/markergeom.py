"""Planar geometry shared by the plugin's markers and the feed.

Both markers (feed_marker, area_marker) decode a footprint back from the line
segments KiCad placed — recovering vertices and connected outlines from a bag
of ``((x0, y0), (x1, y1))`` mm pairs under arbitrary translation, rotation and
mirror. These pure helpers do that bag-of-segments work for both; the
marker-specific meaning of the recovered shapes stays in each module.
``explicit_feed`` is the other shared piece: the one builder for the explicit
feed dict config.write_yaml consumes, so both feed producers emit it
identically. No pcbnew/wx dependency, so they stay unit-testable off-KiCad.
"""

import math

TOL_MM = 0.01  # endpoint-matching tolerance (mm)

DOT_RADIUS_FRAC = 0.25  # feed-point dot radius, per mm of arrow half-base
DOT_MIN_MM = 0.05  # ... clamped to stay visible/discreet (mm)
DOT_MAX_MM = 0.4


def explicit_feed(x, y, dir_x, dir_y):
    """Build the feed dict config.write_yaml consumes (``params['feed']``): a
    point on the feed line plus the direction toward the antenna, in gerber
    mm. That is the whole port -- the runner infers the trace axis and width
    from the copper under the point and severs a one-cell gap on the simulation
    grid, so there is no clearance rect to pass. Both feed producers -- the
    placed feed marker (feed_marker.feed_dict) and the wizards
    (design.geometry.Geometry.feed_dict) -- funnel through here, so the two
    feeds are the same shape."""
    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "dir_x": round(dir_x, 4),
        "dir_y": round(dir_y, 4),
    }


def arrow_segments(cx, cy, half_w, tri_h, direction=(0.0, -1.0)):
    """The five segments (mm pairs) of a feed arrow in the plane: a triangle
    head of half-base ``half_w`` and height ``tri_h`` with its base centred on
    ``(cx, cy)`` and its apex ``tri_h`` along ``direction``, plus a stem
    running the other way ``half_w`` long — half the base width. The base is
    drawn as two halves meeting at the centre so the stem shares that vertex.
    Both markers build their feed from this and decode_arrow reads it back, so
    the drawn shape and its meaning have one definition. arrow_dot puts a dot
    on that base centre, the feed point the whole arrow is about.

    ``direction`` is a unit vector (it is normalised here regardless) and
    defaults to −Y, the way both markers draw an arrow in their own local
    frame. The area marker's feed rides whichever edge of the rectangle the
    user drops it on, so it passes that edge's inward normal instead
    (area_marker.pin_feed) rather than building a second arrow of its own."""
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length <= 0:
        raise ValueError("a feed arrow needs a direction to point in")
    dx, dy = dx / length, dy / length
    px, py = -dy, dx  # along the base, perpendicular to the head
    c = (cx, cy)
    base_l = (cx - px * half_w, cy - py * half_w)
    base_r = (cx + px * half_w, cy + py * half_w)
    apex = (cx + dx * tri_h, cy + dy * tri_h)
    tail = (cx - dx * half_w, cy - dy * half_w)  # stem = half the base width
    return [(c, base_l), (c, base_r), (base_l, apex), (base_r, apex), (c, tail)]


def arrow_dot(cx, cy, half_w):
    """The dot that marks the feed point of the arrow arrow_segments builds:
    ``((cx, cy), radius)`` in mm — a small filled circle on the base centre,
    the joint between the stem and the triangle, which is the port point
    itself. Drawn only: the feed point is recovered from the arrow's segments
    (decode_arrow), so the dot carries no information and both markers keep it
    out of their decode. The radius scales with the arrow and is clamped so it
    stays visible on a thin feed without swallowing a fat one."""
    return (cx, cy), min(max(DOT_RADIUS_FRAC * half_w, DOT_MIN_MM), DOT_MAX_MM)


def decode_arrow(segments):
    """Recover ``(cx, cy, width, dir_x, dir_y)`` from a feed arrow's five
    segments (mm pairs, any position/rotation/mirror — the shape
    arrow_segments builds). The base centre ``(cx, cy)`` is the feed point,
    ``dir`` the unit centre→apex direction (toward the antenna) and ``width``
    the base spacing. Raises ValueError on anything that is not that arrow.

    The arrow has five vertices: the base centre, where the two base halves
    meet the stem, touches three segments; the stem's free tail touches one;
    the two base corners and the apex each touch two. The base corners are the
    two-segment vertices adjacent to the centre, the apex the remaining one;
    the stem must run opposite the head (a valid arrow is one straight axis)."""
    if len(segments) != 5:
        raise ValueError(
            f"feed arrow has {len(segments)} segment(s), expected 5 (a "
            "triangle head plus a stem); regenerate the marker"
        )
    pts = unique_vertices(segments)
    if len(pts) != 5:
        raise ValueError(
            "feed arrow segments do not form a triangle + stem arrow; "
            "regenerate the marker"
        )

    def touches(v):
        return sum(1 for seg in segments for p in seg if near(p, v))

    center = [v for v in pts if touches(v) == 3]  # base centre / stem join
    tail = [v for v in pts if touches(v) == 1]  # the stem's free end
    two = [v for v in pts if touches(v) == 2]  # base corners + the apex
    if len(center) != 1 or len(tail) != 1 or len(two) != 3:
        raise ValueError(
            "feed arrow segments do not form a triangle + stem arrow; "
            "regenerate the marker"
        )
    cx, cy = center[0]

    def neighbours(v):
        out = []
        for a, b in segments:
            if near(a, v):
                out.append(b)
            elif near(b, v):
                out.append(a)
        return out

    def adjacent(v):  # shares a segment with the base centre
        return any(near(n, (cx, cy)) for n in neighbours(v))

    corners = [v for v in two if adjacent(v)]  # base corners touch the centre
    apex = [v for v in two if not adjacent(v)]  # the apex does not
    if len(corners) != 2 or len(apex) != 1:
        raise ValueError("feed arrow head is broken; regenerate the marker")

    dx, dy = apex[0][0] - cx, apex[0][1] - cy  # centre -> apex
    dlen = math.hypot(dx, dy)
    tvx, tvy = tail[0][0] - cx, tail[0][1] - cy  # centre -> tail
    tlen = math.hypot(tvx, tvy)
    if dlen <= TOL_MM or tlen <= TOL_MM:
        raise ValueError("feed arrow is degenerate; regenerate the marker")
    dx, dy = dx / dlen, dy / dlen
    if (tvx * dx + tvy * dy) / tlen > -0.9:  # stem must oppose the head
        raise ValueError(
            "feed arrow head and stem are not aligned; regenerate the marker"
        )
    width = math.hypot(corners[0][0] - corners[1][0], corners[0][1] - corners[1][1])
    if width <= TOL_MM:
        raise ValueError("feed arrow head is degenerate; regenerate the marker")
    return cx, cy, width, dx, dy


def align_rotation_deg(dir_x, dir_y):
    """The whole-board rotation (degrees CCW, in the direction's own frame)
    that brings the feed direction onto its nearest grid axis -- what the
    runner's ``rotation_deg`` needs so a marker the user rotated off-grid
    still drives an axis-aligned trace exactly. In (-45, 45]; 0.0 for an
    already-aligned direction. Pass the direction in gerber frame to get the
    gerber-frame (CCW) angle the config wants."""
    theta = math.degrees(math.atan2(dir_y, dir_x))
    rot = 90.0 * round(theta / 90.0) - theta
    return 0.0 if abs(rot) < 1e-6 else round(rot, 4)


def rotate_pt(p, deg, pivot=(0.0, 0.0)):
    """Point ``p`` rotated by ``deg`` (mathematically CCW in the frame the
    coordinates are given in) about ``pivot``."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    dx, dy = p[0] - pivot[0], p[1] - pivot[1]
    return (pivot[0] + c * dx - s * dy, pivot[1] + s * dx + c * dy)


def rotate_segments(segments, deg, pivot=(0.0, 0.0)):
    """``segments`` (mm pairs) rigidly rotated by ``deg`` about ``pivot``
    (see rotate_pt)."""
    return [(rotate_pt(a, deg, pivot), rotate_pt(b, deg, pivot)) for (a, b) in segments]


def near(a, b, tol=TOL_MM):
    """True when points ``a`` and ``b`` coincide within ``tol`` mm."""
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def unique_vertices(segments, tol=TOL_MM):
    """The distinct endpoints of ``segments`` (mm pairs), de-duplicated within
    ``tol``."""
    verts = []
    for seg in segments:
        for p in seg:
            if not any(near(p, v, tol) for v in verts):
                verts.append(p)
    return verts


def components(segments, tol=TOL_MM):
    """Segment indices grouped into connected outlines by shared endpoints
    (union-find): two segments join when any endpoint of one lands within
    ``tol`` of an endpoint of the other. Each group is a list of indices into
    ``segments``."""
    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            if any(near(p, q, tol) for p in segments[i] for q in segments[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i in range(len(segments)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())
