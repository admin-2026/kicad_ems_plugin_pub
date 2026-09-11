"""Unit tests for the inset-fed patch design (no KiCad, no wx).

The three things that make it a patch rather than a wire -- copper drawn at
widths of its own (the body is a rectangle, the feed is a microstrip), the
notch the line is let into, and the patch sitting centred on the feed, a feed
line's length away from the marker's edge -- plus what each knob moves and what
it leaves alone, the refusals an area or a set of values earns, and the
capacity that bounds a scan.

    python3 tests/test_patch.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

footprints = load("design.footprints")
geometry = load("design.geometry")
registry = load("design.registry")

DESIGN = registry.by_key("patch")

# A 60 x 40 mm area at the origin, KiCad mm (Y down: the feed edge is y = 40).
AREA = (0.0, 0.0, 60.0, 40.0)
BORDER = geometry.BORDER_MM  # the keep-off at the far border, and the floor
# under the feed line's own length


def _v(length=24.0, width=2.0, patch_w=30.0, inset=7.0, feed_len=2.0, inset_gap=2.0):
    return {
        "length": length,
        "width": width,
        "patch_w": patch_w,
        "inset": inset,
        "feed_len": feed_len,
        "inset_gap": inset_gap,
    }


def _solve(frac=0.5, area=AREA, edge="bottom", **kw):
    return DESIGN.solve(area, edge, frac, _v(**kw))


def _rects(geo, **kw):
    """The candidate's copper, stubs off -- the four rectangles a patch is."""
    return geo.copper_rects(_v(**kw)["width"], 0.0, include_stub=False)


def _refuses(**kw):
    """The message ``solve`` refuses these values with, or "" if it didn't."""
    try:
        _solve(**kw)
    except ValueError as exc:
        return str(exc)
    return ""


def _span(rect, axis):
    return rect[axis + 2] - rect[axis]


# --------------------------------------------------------------------------- #
# The shape
# --------------------------------------------------------------------------- #
def test_solve_lays_out_a_feed_line_a_body_and_two_shoulders():
    geo = _solve()
    assert geo.feed == (30.0, 40.0)  # centre of the bottom edge
    assert geo.inward == (0, -1)
    assert geo.total_mm == 24.0

    feed, body, right, left = geo.paths
    # The line runs from the port to the bottom of the notch: its own length
    # standing the patch off the feed edge, plus the inset.
    assert feed.stub == geometry.FEED_STUB
    assert feed.width == 2.0
    assert feed.points == ((30.0, 40.0), (30.0, 40.0 - 2.0 - 7.0))
    # The body is one rectangle the full patch width, from the notch to the
    # far edge; the shoulders are the patch either side of the notch.
    assert body.width == 30.0
    assert body.points == ((30.0, 31.0), (30.0, 40.0 - 2.0 - 24.0))
    assert body.stub == right.stub == left.stub == geometry.NO_STUB
    # notch = the line plus one gap either side (here 2 mm each, the classic
    # drawing's "gap = line width") -> 6 mm, so each shoulder is
    # (30 - 6) / 2 = 12 mm of patch.
    assert right.width == left.width == 12.0
    assert geo.metrics["shoulder_mm"] == 12.0
    assert geo.metrics["inset_gap_mm"] == 2.0


def test_the_copper_is_the_rectangle_the_reference_drawing_shows():
    geo = _solve()
    line, body, right, left = _rects(geo)
    # The feed line: its own width, from the port up to the notch's bottom.
    assert line == (29.0, 31.0, 31.0, 40.0)
    # The body: the whole patch width, from the notch to the far edge.
    assert body == (15.0, 14.0, 45.0, 31.0)
    # The shoulders: outer edges flush with the body's, inner edges one gap
    # (the line's width) off the line, and only as deep as the inset.
    assert right == (33.0, 31.0, 45.0, 38.0)
    assert left == (15.0, 31.0, 27.0, 38.0)
    # ... which is a notch exactly three line widths across, cut into a patch
    # standing one border keep-off inside the feed edge.
    assert right[0] - left[2] == 3 * 2.0
    assert body[3] == right[1] == left[1]  # the shoulders meet the body
    assert math.isclose(_span(body, 1) + _span(right, 1), 24.0)  # = the length
    # ... and the patch stands its feed line's length off the marker's edge.
    assert math.isclose(line[3] - right[3], 2.0)


def test_the_patch_is_centred_on_the_feed_wherever_the_feed_is():
    # The inset feed belongs on the patch's centre line, so the patch follows
    # the marker's arrow along the edge rather than sitting in the middle of
    # the rectangle.
    for frac, feed_x in ((0.3, 18.0), (0.5, 30.0), (0.7, 42.0)):
        geo = _solve(frac=frac, patch_w=20.0)
        line, body, right, left = _rects(geo, patch_w=20.0)
        assert geo.feed[0] == feed_x, frac
        assert math.isclose((body[0] + body[2]) / 2, feed_x), frac
        assert math.isclose(feed_x - left[0], right[2] - feed_x), frac


def test_every_edge_puts_the_patch_inside_the_area():
    # The marker can be rotated to feed from any side; the patch grows away
    # from that edge and stays inside the rectangle (bar the port's own stub,
    # which is dropped here).
    square = (0.0, 0.0, 50.0, 50.0)
    for edge in geometry.EDGES:
        geo = _solve(area=square, edge=edge, length=20.0, patch_w=20.0)
        for rect in _rects(geo, patch_w=20.0):
            assert square[0] <= rect[0] and rect[2] <= square[2], edge
            assert square[1] <= rect[1] and rect[3] <= square[3], edge


# --------------------------------------------------------------------------- #
# What each knob moves
# --------------------------------------------------------------------------- #
def test_the_length_moves_the_far_edge_and_nothing_else():
    # The resonant knob: a length sweep must redraw one edge, or the scan reads
    # the rest of the change as frequency too.
    base = _rects(_solve(length=20.0))
    for length in (22.0, 26.0, 30.0):
        line, body, right, left = _rects(_solve(length=length))
        assert (line, right, left) == (base[0], base[2], base[3]), length
        assert body[0::2] == base[1][0::2] and body[3] == base[1][3], length
        assert math.isclose(base[1][1] - body[1], length - 20.0), length


def test_the_inset_moves_the_notch_and_leaves_the_patch_where_it_was():
    # The match, not the resonator: the patch's own edges stay put while the
    # line reaches further in (an inverted-F's tap is the same idea).
    outer = None
    for inset in (3.0, 7.0, 11.0):
        line, body, right, left = _rects(_solve(inset=inset))
        edges = (left[0], right[2], body[1], right[3])
        assert outer is None or edges == outer, inset
        outer = edges
        assert math.isclose(right[3] - right[1], inset)  # shoulder = the inset
        assert math.isclose(line[1], body[1] + (body[3] - body[1]))
        assert _solve(inset=inset).total_mm == 24.0


def test_the_feed_line_walks_the_whole_patch_away_from_the_edge():
    # The patch keeps its shape and its length; only where it sits moves, so a
    # feed-line sweep asks "how far off the edge?" and nothing else. (The port
    # stays on the marker's edge -- that is where the user's own line meets
    # it -- so it is the line that grows.)
    base = _rects(_solve(feed_len=2.0))
    for feed_len in (0.5, 4.0, 9.0):
        line, body, right, left = _rects(_solve(feed_len=feed_len))
        shift = feed_len - 2.0
        assert line[3] == base[0][3] == 40.0, feed_len  # the port has not moved
        assert math.isclose(line[1], base[0][1] - shift), feed_len
        for rect, was in ((body, base[1]), (right, base[2]), (left, base[3])):
            assert rect[0::2] == was[0::2], feed_len  # nothing moves sideways
            assert math.isclose(rect[1], was[1] - shift), feed_len
            assert math.isclose(rect[3], was[3] - shift), feed_len
        geo = _solve(feed_len=feed_len)
        assert geo.total_mm == 24.0
        assert geo.metrics["feed_len_mm"] == feed_len


def test_the_patch_width_widens_the_patch_symmetrically():
    for patch_w in (16.0, 24.0, 34.0):
        geo = _solve(patch_w=patch_w)
        line, body, right, left = _rects(geo, patch_w=patch_w)
        assert math.isclose(body[2] - body[0], patch_w), patch_w
        assert math.isclose(30.0 - body[0], body[2] - 30.0), patch_w
        # The notch does not move with it: the shoulders take the difference.
        assert (line, right[0], left[2]) == (
            _rects(_solve())[0],
            _rects(_solve())[2][0],
            _rects(_solve())[3][2],
        ), patch_w


def test_the_feed_width_opens_the_notch_and_leaves_the_gap_alone():
    # The line widens into its own clearance rather than pushing it: the gap
    # is the other knob's, so a width sweep is the microstrip getting thicker
    # and nothing else about the notch.
    for width in (1.0, 2.0, 3.0):
        line, _body, right, left = _rects(_solve(width=width), width=width)
        assert math.isclose(line[2] - line[0], width), width
        assert math.isclose(right[0] - line[2], 2.0), width
        assert math.isclose(line[0] - left[2], 2.0), width
        # ... so the notch is still the line plus its two gaps.
        assert math.isclose(right[0] - left[2], width + 4.0), width


def test_the_inset_gap_steps_the_patch_back_from_a_line_that_stays_put():
    # The other half of the split: the copper either side moves, the line does
    # not, and neither do the patch's own outer edges.
    base = _rects(_solve())
    for gap in (0.5, 2.0, 4.0):
        line, body, right, left = _rects(_solve(inset_gap=gap))
        assert line == base[0], gap  # the microstrip is untouched
        assert (body, right[2], left[0]) == (base[1], base[2][2], base[3][0]), gap
        assert math.isclose(right[0] - line[2], gap), gap
        assert math.isclose(line[0] - left[2], gap), gap
        # The shoulders pay for it, which is the number the results table shows.
        geo = _solve(inset_gap=gap)
        assert math.isclose(geo.metrics["shoulder_mm"], (30.0 - 2.0 - 2 * gap) / 2)
        assert geo.metrics["inset_gap_mm"] == gap
        assert geo.total_mm == 24.0  # and the resonance does not move with it


def test_a_gap_below_the_track_clearance_is_refused():
    # A notch that closes up on the fab is a patch that comes back shorted to
    # its own feed line -- refused, not quietly widened (there are no silent
    # defaults here).
    message = _refuses(inset_gap=geometry.TRACK_GAP_MM / 2)
    assert "clearance" in message and f"{geometry.TRACK_GAP_MM:g} mm" in message
    assert _refuses(inset_gap=geometry.TRACK_GAP_MM) == ""  # on the floor is fine


# --------------------------------------------------------------------------- #
# What it refuses, and what it says
# --------------------------------------------------------------------------- #
def test_a_patch_deeper_than_the_area_says_so():
    assert "does not fit" in _refuses(length=39.0)
    assert "deep" in _refuses(length=39.0)


def test_a_patch_wider_than_the_room_beside_the_feed_says_which_way_to_drag():
    # Centred on the feed, so an arrow near a corner is the thing to move --
    # and the message says that before it says "widen the area".
    message = _refuses(frac=0.1, patch_w=30.0)
    assert "either side" in message and "feed arrow toward" in message
    # The same patch fits once the feed is in the middle of the same area.
    assert _refuses(frac=0.5, patch_w=30.0) == ""


def test_a_patch_too_narrow_for_its_own_notch_is_refused():
    # Three line widths of notch out of a 5 mm patch leaves no shoulder at all
    # -- the "patch" would come back as two pieces of copper.
    assert "too narrow for the notch" in _refuses(patch_w=5.0, width=2.0)
    # ... and the gap is one of the three ways out, so the message says so.
    assert "close the gap" in _refuses(patch_w=5.0, width=2.0)
    assert _refuses(patch_w=5.0, width=0.5, inset_gap=geometry.TRACK_GAP_MM) == ""


def test_an_inset_that_eats_the_patch_is_refused():
    assert "beyond the notch" in _refuses(length=8.0, inset=7.0)


def test_a_feed_line_shorter_than_the_border_keep_off_is_refused():
    # The patch would sit on the marker's own border, which no design here
    # draws copper on.
    message = _refuses(feed_len=BORDER / 2)
    assert "own border" in message and f"{BORDER:g} mm" in message
    assert _refuses(feed_len=BORDER) == ""  # exactly on the floor is fine


def test_a_feed_line_that_spends_the_whole_area_is_refused():
    message = _refuses(feed_len=39.0)
    assert "nothing left for the patch" in message
    # ... and the length is not what went wrong, so no capacity is quoted at
    # the user (design/fit.py only quotes one when the length overflowed).
    assert "does not fit" not in message


def test_a_blank_or_negative_knob_names_itself():
    for key, label in (
        ("length", "patch length"),
        ("width", "feed line width"),
        ("patch_w", "patch width"),
        ("inset", "inset depth"),
        ("inset_gap", "inset gap"),
    ):
        values = _v()
        values[key] = 0.0
        try:
            DESIGN.solve(AREA, "bottom", 0.5, values)
            assert False, f"expected ValueError for {key}"
        except ValueError as exc:
            assert label in str(exc), key


# --------------------------------------------------------------------------- #
# Capacity
# --------------------------------------------------------------------------- #
def test_capacity_is_the_depth_left_once_the_feed_line_has_had_its_share():
    cap = DESIGN.capacity_mm(AREA, "bottom", 0.5, _v())
    # The depth, less the feed line standing the patch off the marker's edge,
    # the half track the frame keeps and the keep-off at the far border.
    assert math.isclose(cap, 40.0 - 2.0 - BORDER - _v()["width"] / 2)
    DESIGN.solve(AREA, "bottom", 0.5, _v(length=cap))  # exactly fits
    assert "does not fit" in _refuses(length=cap + 0.05)
    # A longer line is depth the patch does not get, millimetre for millimetre.
    assert math.isclose(
        DESIGN.capacity_mm(AREA, "bottom", 0.5, _v(feed_len=6.0)), cap - 4.0
    )


def test_capacity_does_not_move_with_the_inset_or_the_patch_width():
    # The ceiling a scan clips its ladder to is about the area and what the
    # feed line spends of it, not about the rows that only reshape the patch:
    # a knob that changed it would silently rescale the sweep.
    base = DESIGN.capacity_mm(AREA, "bottom", 0.5, _v())
    for values in (_v(inset=2.0), _v(inset=12.0), _v(patch_w=20.0), _v(inset_gap=4.0)):
        assert DESIGN.capacity_mm(AREA, "bottom", 0.5, values) == base


def test_an_area_that_holds_no_patch_at_all_raises_from_capacity_too():
    # fit.py leans on this: a capacity that raises is "the area holds nothing",
    # which is a different message from "this length is too long".
    try:
        DESIGN.capacity_mm((0.0, 0.0, 60.0, 0.4), "bottom", 0.5, _v())
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "too" in str(exc)


# --------------------------------------------------------------------------- #
# The footprint
# --------------------------------------------------------------------------- #
def test_the_footprint_is_one_pad_carrying_four_pieces_of_copper():
    geo = _solve()
    assert DESIGN.footprint_pads(geo) == (("1", geo.feed),)
    text = footprints.sexpr(DESIGN, geo, _v(), 2.45)
    assert text.count("gr_poly") == 4  # line + body + two shoulders
    # The whole feed line is on the footprint, so what is placed is what was
    # simulated: the pad sits at the port and the copper runs from there.
    assert "feed_len_mm=2" in text
    assert '(pad "1" smd custom (at 0 0)' in text
    assert "net_tie_pad_groups" not in text  # one pad shorts nothing
    assert "(size 2 2)" in text  # the pad is the feed line's width


def test_the_shoulders_reach_the_body_so_the_pad_is_one_piece():
    # A custom pad's primitives have to hang together; the shoulders touch
    # nothing but the body, which is what carries them to the feed.
    for width in (0.4, 2.0, 3.5):
        line, body, right, left = _rects(_solve(width=width), width=width)
        for shoulder in (right, left):
            assert shoulder[1] == body[3]  # abutting the body's near edge
            # (to a float's tolerance: the shoulder is the patch width less
            # the notch, halved, so its outer edge is arithmetic away from the
            # body's rather than the same number twice)
            assert shoulder[0] >= body[0] - 1e-9 and shoulder[2] <= body[2] + 1e-9
        assert line[1] == body[3]  # and the line's far end meets it too


if __name__ == "__main__":
    run_module_tests(globals())
