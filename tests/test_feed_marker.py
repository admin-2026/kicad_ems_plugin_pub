"""Unit tests for antenna_plugin.markers.feed_marker's pure helpers (no KiCad).

Covers the local marker geometry, decoding placed segments back into a feed
(round-trip, translated/rotated placements, broken markers) and the synthetic
one-circle gerber. The package is assembled by hand around the real modules
(skipping antenna_plugin/__init__, which imports pcbnew) so feed_marker's
relative import of markergeom works:  python3 tests/test_feed_marker.py
"""

import math
import pathlib

from bare_package import load

_ROOT = pathlib.Path(__file__).resolve().parents[1]

feed_marker = load("emkit.markers.feed_marker")


def _place(segments, dx=0.0, dy=0.0, angle_deg=0.0):
    """Rotate then translate every segment endpoint, like dropping the
    footprint on a board."""
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))

    def xf(p):
        return (p[0] * c - p[1] * s + dx, p[0] * s + p[1] * c + dy)

    return [(xf(a), xf(b)) for a, b in segments]


def test_local_segments_shape():
    segs = feed_marker._local_segments(1.0)
    assert len(segs) == 5
    # The base is drawn as two halves meeting at the centre (the origin, which
    # is the feed point), each running out to a base corner at y=0.
    assert segs[0][0] == (0.0, 0.0) and segs[1][0] == (0.0, 0.0)
    assert {segs[0][1], segs[1][1]} == {(-0.5, 0.0), (0.5, 0.0)}
    # The two slopes rise from those base corners to a single apex above
    # (negative Y, toward the antenna).
    apex = segs[2][1]
    assert segs[3][1] == apex
    assert apex[0] == 0.0 and apex[1] < 0.0
    # The stem runs back from the centre, half the width long, opposite the
    # apex (positive Y, away from the antenna).
    (sc, tail) = segs[4]
    assert sc == (0.0, 0.0)
    assert tail == (0.0, 0.5)


def test_decode_round_trip():
    segs = feed_marker._local_segments(1.2)
    x, y, width, dx, dy = feed_marker._decode_segments(segs)
    assert math.isclose(width, 1.2, abs_tol=1e-9)
    # Feed point: the base centre, at the origin.
    assert math.isclose(x, 0.0, abs_tol=1e-9)
    assert math.isclose(y, 0.0, abs_tol=1e-9)
    # Direction: base centre -> apex, the local 'up' (-Y) toward the antenna.
    assert math.isclose(dx, 0.0, abs_tol=1e-9)
    assert math.isclose(dy, -1.0, abs_tol=1e-9)


def test_decode_translated_and_rotated():
    for angle in (0, 90, 180, 270, 37.5):
        segs = _place(
            feed_marker._local_segments(1.0), dx=120.0, dy=80.0, angle_deg=angle
        )
        x, y, width, dx, dy = feed_marker._decode_segments(segs)
        assert math.isclose(width, 1.0, abs_tol=1e-6)
        # The feed point is the marker origin (the base centre) itself.
        assert math.isclose(x, 120.0, abs_tol=1e-6)
        assert math.isclose(y, 80.0, abs_tol=1e-6)
        assert math.isclose(dx, math.sin(math.radians(angle)), abs_tol=1e-6)
        assert math.isclose(dy, -math.cos(math.radians(angle)), abs_tol=1e-6)


def test_decode_rejects_wrong_segment_count():
    segs = feed_marker._local_segments(1.0)[:3]
    try:
        feed_marker._decode_segments(segs)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "expected 5" in str(exc)


def test_decode_rejects_broken_arrow():
    segs = feed_marker._local_segments(1.0)
    # Break the head apart: shift one slope far off its apex/corner.
    (a, b) = segs[2]
    segs[2] = ((a[0] + 5, a[1] + 5), (b[0] + 5, b[1] + 5))
    try:
        feed_marker._decode_segments(segs)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "arrow" in str(exc)


def test_footprint_sexpr_layout():
    text = feed_marker.footprint_sexpr(3, 1.0)
    assert text.count("(") == text.count(")")  # well-formed
    assert text.startswith('(footprint "AntennaFeedMarker" (version 20211014) ')
    assert text.count("(fp_line ") == 5  # base halves + slopes + stem
    assert text.count("(fp_circle ") == 1  # the feed-point dot
    assert text.count('(layer "User.3")') == 6  # all on the picked layer
    assert "(attr board_only exclude_from_pos_files exclude_from_bom)" in text
    # The base halves run from the centre out to each corner at y=0.
    assert "(fp_line (start 0 0) (end -0.5 0) " in text
    assert "(start 0 0) (end 0.5 0)" in text
    # A slope climbs from a base corner to the apex above (Y-down).
    assert "(start -0.5 0) (end 0 -0.75)" in text
    # The stem runs back from the centre, half the width long.
    assert "(start 0 0) (end 0 0.5)" in text
    # The dot sits on the feed point (the origin), solid-filled and unstroked
    # so its drawn size is its radius.
    assert "(fp_circle (center 0 0) (end 0.125 0) " in text
    assert "(width 0) (fill solid))" in text


def test_dot_marks_the_feed_point():
    # One dot, on the joint between the stem and the triangle -- the base
    # centre the decode recovers as the feed point -- scaled to the width.
    for width in (0.4, 1.0, 4.0):
        dots = feed_marker._local_dots(width)
        assert len(dots) == 1
        (center, radius) = dots[0]
        assert center == (0.0, 0.0) == feed_marker._local_segments(width)[0][0]
        assert 0.05 <= radius <= 0.4
        assert radius < width / 2  # never swallows the arrow


def test_footprint_sexpr_round_trips_through_decode():
    # The emitted fp_line coordinates decode back to the slider value.
    import re

    text = feed_marker.footprint_sexpr(1, 1.4)
    segs = [
        ((float(a), float(b)), (float(c), float(d)))
        for a, b, c, d in re.findall(
            r"\(fp_line \(start ([-\d.]+) ([-\d.]+)\) "
            r"\(end ([-\d.]+) ([-\d.]+)\)",
            text,
        )
    ]
    x, y, width, dx, dy = feed_marker._decode_segments(segs)
    assert math.isclose(width, 1.4, abs_tol=1e-6)
    assert math.isclose(x, 0.0, abs_tol=1e-6)
    assert math.isclose(y, 0.0, abs_tol=1e-6)
    assert math.isclose(dx, 0.0, abs_tol=1e-6)
    assert math.isclose(dy, -1.0, abs_tol=1e-6)


def test_feed_dict_point_plus_direction():
    # Schema 5.x: the feed is the point + direction, nothing else -- the
    # drawn width stays on the marker for display only.
    marker = {"x_mm": 30.0, "y_mm": -38.0, "width_mm": 1.0, "dir_x": 0.0, "dir_y": 1.0}
    feed = feed_marker.feed_dict(marker)
    assert feed == {"x": 30.0, "y": -38.0, "dir_x": 0.0, "dir_y": 1.0}


def test_align_rotation_for_rotated_marker():
    # A marker rotated off-grid decodes to a diagonal direction; the aligning
    # board rotation is the residual back to the nearest axis.
    markergeom = load("emkit.markers.markergeom")
    segs = _place(feed_marker._local_segments(1.0), dx=120.0, dy=80.0, angle_deg=30.0)
    _x, _y, _width, dx, dy = feed_marker._decode_segments(segs)
    # KiCad -> gerber flips Y (as find_markers does): the marker's 30° in
    # Y-down coordinates is -30° in the gerber frame, so +30° CCW re-aligns.
    rot = markergeom.align_rotation_deg(dx, -dy)
    assert math.isclose(rot, 30.0, abs_tol=1e-6)
    # Axis-aligned directions need no rotation, at every quarter turn.
    for gdx, gdy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        assert markergeom.align_rotation_deg(gdx, gdy) == 0.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
