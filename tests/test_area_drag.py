"""The area marker on the board: placed as a group, sized by dragging it (no
KiCad, real wx stubbed, a fake pcbnew).

The wizard has no width, height or feed-position sliders. The area is the
rectangle the user drew: a board-level rectangle graphic, which is the only
kind of item KiCad's point editor will give drag handles to, grouped with the
feed arrow under the marker's name. So the plugin's job is to *read* it — and
to land the feed arrow back on whichever edge it was dropped nearest, which is
how the feed is placed.

What is pinned here: what Place actually draws (a named group of a rectangle
shape, five arrow segments and the feed dot, all on the marker layer), that a
dragged corner is taken as the area with no resistance and no rewrite of the
rectangle, that a dragged arrow is squared back onto the nearest edge — moving
the feed edge when that is where it was dropped, following an edge that was
dragged when it isn't — that the Feed-width slider redraws the triangle without
moving the feed, that the Marker-layer pick moves every shape, that the Angle
slider and its box both turn the marker to an angle KiCad's own R cannot reach,
and that the group's name and the status line both say how the marker is
edited.

The geometry under all of it is tested off the board in test_area_marker.py;
what these add is the pcbnew half — the shapes, the group and the section. A
marker an older version of the plugin drew as one footprint never reaches any of
this: it is converted on the way in, which is test_area_legacy.py.

See wx_stub.py for what "stubbed" means here, and fake_pcbnew.py for the board.

    python3 tests/test_area_drag.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_pcbnew  # noqa: E402  (a board, on the pcbnew wx_stub installs)
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
area_marker = load("markers.area_marker")
boardshapes = load("emkit.markers.boardshapes")
area_section = load("gui.sections.area")

wx = wx_stub.wx
pcbnew = sys.modules["pcbnew"]

# The fake KiCad -- points, graphics, footprints, groups and a board -- is
# shared with the other tests of the plugin's board half (fake_pcbnew.py).
_Board = fake_pcbnew.Board
_KICAD = fake_pcbnew.KICAD
_with_kicad = fake_pcbnew.with_kicad
USER_2 = fake_pcbnew.USER_2

F0 = 2.45
TRI_W = 1.2  # the feed-width slider's default, near enough


# --------------------------------------------------------------------------- #
# The section, off the board
# --------------------------------------------------------------------------- #
class _Host:
    def target_freq_ghz(self, default=None):
        return F0

    def marker_layer_n(self):
        return 2


class _Scan:
    def __init__(self):
        self.previews = 0
        self.reset = 0

    def refresh_preview(self):
        self.previews += 1

    def reset_params(self):
        self.reset += 1


class _Page:
    def __init__(self, design):
        self.design = design
        self.scroll = None
        self.host = _Host()
        self.scan = _Scan()
        self.checks = 0

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def refresh_area_checks(self):
        self.checks += 1

    def save_settings(self):
        pass


def _section(board):
    """An Area section reading ``board``, its feed width at TRI_W."""
    page = _Page(registry.DESIGNS[0])
    section = _with_kicad(board, lambda: area_section.AreaSection(page, wx.BoxSizer()))
    _with_kicad(board, lambda: section.build_layer_picker(None, wx.FlexGridSizer()))
    section.marker_layer.SetSelection(1)  # User.2
    section.marker_width.set_value(TRI_W)
    return section


def _placed(board=None):
    """A board with an area marker placed on it, and the section that placed
    it: the marker is the one the shipped code draws, through the fake pcbnew
    above."""
    board = board if board is not None else _Board()
    section = _section(board)
    _with_kicad(board, section.on_place)
    return board, section


def _group(board):
    return board.Groups()[0]


def _parts(board):
    """The marker's two members: (outline shape, arrow footprint)."""
    return _with_kicad(board, lambda: area_marker._parts(_group(board)))


def _arrow_shapes(board):
    """The arrow's own graphics: its five segments and its feed dot, which are
    the footprint's and so out of reach of a drag."""
    _outline, arrow = _parts(board)
    segments = [s for s in arrow.items if s.shape == _KICAD["SHAPE_T_SEGMENT"]]
    dots = [s for s in arrow.items if s.shape == _KICAD["SHAPE_T_CIRCLE"]]
    return segments, dots


def _decode(board):
    return _with_kicad(board, lambda: area_marker.decode_marker(_group(board)))


def _corners(board):
    outline, _arrow = _parts(board)
    return _with_kicad(board, lambda: area_marker.outline_corners_mm(outline))


def _drag_rect(board, area):
    """A corner drag on an upright marker: KiCad rewrites the rectangle
    graphic's two corners, and nothing else moves."""
    outline, _arrow = _parts(board)
    x0, y0, x1, y1 = area
    outline.drag_to(((x0, y0), (x1, y1)))


def _drag_vertex(board, index, dx, dy):
    """A corner drag on a *turned* marker, whose outline is a polygon: KiCad
    moves the one vertex and leaves the other three where they are, which is
    what pulls the rectangle out of square (square_outline puts it back)."""
    outline, _arrow = _parts(board)
    corners = list(_corners(board))
    (x, y) = corners[index]
    corners[index] = (x + dx, y + dy)
    outline.set_poly_mm(corners)


def _type_angle(board, section, text):
    """Type into the Angle box, as wx does it: every keystroke fires EVT_TEXT,
    the slider follows what parses, and the handler reads the board."""
    return _with_kicad(board, lambda: section.angle._readout.type(text))


def _drag_angle(board, section, degrees):
    """Work the Angle slider by hand — the other half of the same control."""
    position = int(round(degrees * area_section.ANGLE_SCALE))
    return _with_kicad(board, lambda: section.angle.slider.adjust(position))


def _drag_arrow(board, dx, dy):
    """The feed arrow dragged by (dx, dy) mm — the whole footprint, which is
    all KiCad will let the user move."""
    _outline, arrow = _parts(board)
    arrow.drag_by(dx, dy)


# --------------------------------------------------------------------------- #
# What Place draws
# --------------------------------------------------------------------------- #
def test_place_draws_a_named_group_of_a_rectangle_and_an_arrow():
    board, _section = _placed()
    group = _group(board)
    assert group.GetName() == area_marker.GROUP_NAME
    outline, arrow = _parts(board)
    # The rectangle is a *rectangle shape* -- that is what carries the corner
    # handles the whole marker exists to offer -- not four line segments.
    assert outline.shape == _KICAD["SHAPE_T_RECT"]
    segments, dots = _arrow_shapes(board)
    assert len(segments) == 5 and len(dots) == 1
    assert {s.layer for s in [outline, *segments, *dots]} == {USER_2}


def test_the_arrow_is_one_item_and_cannot_be_taken_apart():
    """The group holds two things: the rectangle and the arrow. The arrow's
    five segments and its dot are a *footprint's* graphics, not group members
    — which is the whole point, because KiCad lets a group's members be
    selected one at a time and a footprint's graphics never."""
    board, _section = _placed()
    assert len(_group(board).items) == 2
    outline, arrow = _parts(board)
    assert str(arrow.GetFPID().GetLibItemName()) == area_marker.FEED_NAME
    assert len(arrow.items) == 6  # the five segments and the dot, all its own
    assert outline not in arrow.items


def test_place_draws_the_designs_starter_area_and_it_decodes():
    board, section = _placed()
    want_w, want_h = _with_kicad(board, section._starter_size)
    d = _decode(board)
    assert abs(d["w_mm"] - want_w) < 0.01 and abs(d["h_mm"] - want_h) < 0.01
    assert d["edge"] == "bottom"
    assert abs(d["frac"] - section.page.design.feed_frac) < 0.01


def test_the_starter_area_is_capped_by_the_board_outline():
    """The design's hint is only an opening guess: an area bigger than the
    board it has to sit on can never be placed, so a small board gets a small
    starter. (After that the user drags; nothing is capped again.)"""
    board = _Board(outline=(0.0, 0.0, 18.0, 9.0))
    _board, section = _placed(board)
    d = _decode(board)
    assert d["w_mm"] <= 18.0 and d["h_mm"] <= 9.0


def test_place_says_what_to_do_with_it():
    board, section = _placed()
    text = section._status_label.GetLabel()
    assert "drag a corner" in text and "×" in text
    assert section.page.scan.reset == 1  # a fresh area drops the scan rows


# --------------------------------------------------------------------------- #
# Reading a drag
# --------------------------------------------------------------------------- #
def test_a_dragged_corner_is_the_area():
    board, section = _placed()
    _drag_rect(board, (10.0, 10.0, 50.0, 28.0))
    _with_kicad(board, section.sync_from_board)
    d = _decode(board)
    assert (d["w_mm"], d["h_mm"]) == (40.0, 18.0)
    assert d["area"] == (10.0, 10.0, 50.0, 28.0)
    # ... and the section reports it, rather than reshaping it back.
    assert "40 × 18 mm" in section._status_label.GetLabel()


def test_a_repin_never_rewrites_the_rectangle():
    """The rectangle is the user's drawing: a repin only ever writes the
    arrow, so a drag is never fought."""
    board, section = _placed()
    outline, _arrow = _parts(board)
    _drag_rect(board, (10.0, 10.0, 50.0, 28.0))
    writes = outline.writes
    _with_kicad(board, section.sync_from_board)
    _with_kicad(board, section.sync_from_board)
    assert outline.writes == writes


def test_the_arrow_follows_an_edge_that_was_dragged():
    board, section = _placed()
    before = _decode(board)
    x0, y0, x1, y1 = before["area"]
    _drag_rect(board, (x0, y0, x1, y1 - 6.0))  # bottom edge pulled up 6 mm
    _with_kicad(board, section.sync_from_board)
    after = _decode(board)
    assert after["edge"] == "bottom"
    assert abs(after["feed"][1] - (y1 - 6.0)) < 0.01  # on the edge's new place
    assert abs(after["feed"][0] - before["feed"][0]) < 0.01  # same place along it


def test_a_dragged_arrow_moves_the_feed_to_the_edge_it_was_dropped_on():
    board, section = _placed()
    d = _decode(board)
    x0, _y0, _x1, y1 = d["area"]
    # Drag the arrow over to the left edge, halfway up.
    _drag_arrow(board, x0 - d["feed"][0], (d["area"][1] - y1) / 2)
    _with_kicad(board, section.sync_from_board)
    after = _decode(board)
    assert after["edge"] == "left"
    assert abs(after["feed"][0] - x0) < 0.01  # squared back onto the edge
    assert "left edge" in section._status_label.GetLabel()


def test_a_dragged_arrow_keeps_its_place_along_the_edge():
    board, section = _placed()
    before = _decode(board)
    _drag_arrow(board, 5.0, -2.0)  # along the edge a bit, and off it
    _with_kicad(board, section.sync_from_board)
    after = _decode(board)
    assert after["edge"] == "bottom"
    assert abs(after["feed"][0] - (before["feed"][0] + 5.0)) < 0.01
    assert abs(after["feed"][1] - before["feed"][1]) < 0.01  # back on the edge


def test_a_marker_nobody_touched_is_not_written_at_all():
    """The wizard repins every time its window takes the focus, and all but one
    of those finds a marker nobody moved: it must write nothing rather than
    push the same six shapes back onto the user's board."""
    board, section = _placed()
    outline, _arrow = _parts(board)
    segments, dots = _arrow_shapes(board)
    writes = [s.writes for s in (outline, *segments, *dots)]
    for _ in range(3):
        _with_kicad(board, section.sync_from_board)
    assert [s.writes for s in (outline, *segments, *dots)] == writes


def test_the_dot_rides_with_the_repinned_arrow_and_is_never_replaced():
    """The feed-point dot is drawn on the joint the arrow is pinned at. It is
    rewritten in place: a shape KiCad loaded with the board is KiCad's, and
    unlinking one from a plugin is a use-after-free."""
    board, section = _placed()
    dot = _arrow_shapes(board)[1][0]
    _drag_arrow(board, 5.0, -2.0)
    _with_kicad(board, section.sync_from_board)
    after = _arrow_shapes(board)[1]
    assert [id(d) for d in after] == [id(dot)]  # the same C++ object
    feed = _decode(board)["feed"]  # the decode rounds to 3 dp; the dot doesn't
    for got, want in zip(dot.points_mm()[0], feed):
        assert abs(got - want) < 0.001  # on the feed point the repin chose


def test_a_broken_marker_is_reported_not_repaired():
    board, section = _placed()
    _outline, arrow = _parts(board)
    board.Groups()[0].items.remove(arrow)  # someone deleted the feed arrow
    _with_kicad(board, section.sync_from_board)
    assert "✗" in section._status_label.GetLabel()


# --------------------------------------------------------------------------- #
# Turning it: the one thing the board can't say
# --------------------------------------------------------------------------- #
def test_the_angle_box_turns_the_marker_to_any_angle():
    """KiCad turns a group by its rotation *step*, and only a footprint has an
    angle anyone can type — so the wizard keeps this one control."""
    board, section = _placed()
    before = _decode(board)
    _type_angle(board, section, "37.5")
    after = _decode(board)
    assert abs(after["angle_deg"] - 37.5) < 0.01
    # A turn, not a reshape: same rectangle, same feed edge, same place on it.
    assert abs(after["w_mm"] - before["w_mm"]) < 0.01
    assert abs(after["h_mm"] - before["h_mm"]) < 0.01
    assert after["edge"] == before["edge"]
    assert abs(after["frac"] - before["frac"]) < 0.01


def test_a_turned_marker_is_drawn_as_a_polygon_and_still_decodes():
    """A KiCad rectangle is two opposite corners, so it can only ever be
    upright: off the cardinal angles the outline becomes a four-point polygon,
    which is what the runner's own off-grid rotation is read from."""
    board, section = _placed()
    _type_angle(board, section, "20")
    outline, _arrow = _parts(board)
    assert outline.shape == _KICAD["SHAPE_T_POLYGON"]
    d = _decode(board)
    # rot_deg is the residual the scan simulates, and counts the other way
    # round: mathematically CCW in KiCad's Y-down frame is clockwise on screen.
    assert abs(d["rot_deg"] + 20.0) < 0.01
    assert len(_corners(board)) == 4


def test_turning_back_onto_the_grid_restores_the_rectangle():
    """... and back: on the grid the marker is a KiCad rectangle again, which
    is the shape whose handles cannot be dragged out of square."""
    board, section = _placed()
    _type_angle(board, section, "20")
    _type_angle(board, section, "90")
    outline, _arrow = _parts(board)
    assert outline.shape == _KICAD["SHAPE_T_RECT"]
    d = _decode(board)
    assert d["rot_deg"] == 0.0
    assert abs(d["angle_deg"] - 90.0) < 0.01
    # A quarter turn counter-clockwise on screen carries the bottom edge round
    # to the right-hand side, and the arrow with it.
    assert d["edge"] == "right"


def test_the_angle_slider_turns_the_marker_too():
    """The slider is the other half of the same control: it sweeps the marker
    round to see where the antenna wants to face, and the box says exactly
    where it got to."""
    board, section = _placed()
    _drag_angle(board, section, 120.0)
    assert abs(_decode(board)["angle_deg"] - 120.0) < 0.01
    assert section.angle.value() == 120.0
    assert section.angle._readout.GetValue() == "120.0"


def test_the_angle_control_shows_the_marker_it_finds():
    board, section = _placed()
    assert section.angle.value() == 0.0
    _type_angle(board, section, "30")
    section.angle.set_value(0.0)  # as if the control had never been touched
    _with_kicad(board, section.sync_from_board)
    assert abs(section.angle.value() - 30.0) < 0.05


def test_half_typed_angles_turn_nothing():
    """A box with no number in it yet leaves the marker alone. ("1e" is not one
    of those: it holds a 1, and every editable slider in the plugin reads the
    number a box leads with -- parse_leading_number.)"""
    board, section = _placed()
    for text in ("", "-", "eleven"):
        _type_angle(board, section, text)
        assert abs(_decode(board)["angle_deg"]) < 0.01


def test_a_vertex_dragged_out_of_square_is_squared_back():
    """A turned marker's outline is a polygon, and a polygon *can* be dragged
    out of square one vertex at a time. The wizard reads that drag the way
    KiCad reads a rectangle's — the corner opposite the one that moved is the
    anchor — so the area is still a rectangle, and still the one the user drew
    a corner of."""
    board, section = _placed()
    _type_angle(board, section, "25")
    was = _corners(board)
    dragged = (was[0][0] + 3.0, was[0][1] + 2.0)
    _drag_vertex(board, 0, 3.0, 2.0)
    _with_kicad(board, section.sync_from_board)

    assert abs(_decode(board)["rot_deg"] + 25.0) < 0.01  # still turned by 25
    corners = _corners(board)
    for i in range(4):  # ... and square again: every corner a right angle
        a, b, c = corners[i - 1], corners[i], corners[(i + 1) % 4]
        u = (a[0] - b[0], a[1] - b[1])
        v = (c[0] - b[0], c[1] - b[1])
        assert abs(u[0] * v[0] + u[1] * v[1]) < 0.01, i
    # Exactly a rectangle drag: the dragged corner is where it was dropped, the
    # corner opposite it hasn't moved, and the two beside it followed.
    assert all(abs(a - b) < 0.01 for a, b in zip(corners[0], dragged))
    assert all(abs(a - b) < 0.01 for a, b in zip(corners[2], was[2]))
    assert corners[1] != was[1] and corners[3] != was[3]


# --------------------------------------------------------------------------- #
# Saying how the marker is edited
# --------------------------------------------------------------------------- #
def test_the_group_name_says_how_the_marker_is_edited():
    """KiCad draws a group's name over the group, so the name is where the
    marker says what to do with it — and nothing of the plugin's own is drawn
    for it, which would be one more item on the user's board to select and
    delete. The identity is the start of the name, so the caption can be
    reworded without orphaning a marker already placed."""
    board, _section = _placed()
    name = _group(board).GetName()
    assert name.startswith(area_marker.MARKER_NAME)
    assert name.endswith(area_marker.HINT_TEXT)
    assert "double-click to drag the area rectangle" in name


def test_a_reworded_caption_still_finds_the_marker():
    board, _section = _placed()
    _group(board).SetName(f"{area_marker.MARKER_NAME}: some older wording")
    assert len(_with_kicad(board, lambda: area_marker.placed_markers(board))) == 1


def test_the_status_line_says_how_the_marker_is_edited():
    """The bottom line of the box, wherever it describes a placed marker: this
    box has no width or height field, so that is the answer to "where do I
    change this?". It gets a bold row of its own under the description, shown
    only while there is a marker to double-click."""
    board, section = _placed()
    _with_kicad(board, section.refresh_status)
    hint = section._hint_label
    assert area_marker.HINT_TEXT in hint.GetLabel()
    assert hint.shown
    # ... after the description, not instead of it, and not crammed into the
    # title over the sliders.
    assert "Area" in section._status_label.GetLabel()
    assert area_marker.HINT_TEXT not in area_section.AreaSection._TITLE


def test_the_hint_row_is_hidden_with_no_marker_to_edit():
    board, section = _placed()
    for group in list(board.Groups()):
        board.Remove(group)
    _with_kicad(board, section.refresh_status)
    assert not section._hint_label.shown
    assert not section._hint_label.GetLabel()


# --------------------------------------------------------------------------- #
# The two picks that are left
# --------------------------------------------------------------------------- #
def test_feed_width_redraws_the_triangle_without_moving_the_feed():
    board, section = _placed()
    before = _decode(board)
    section.marker_width.set_value(3.0)
    _with_kicad(board, section._on_feed_width)
    after = _decode(board)
    assert after["tri_w_mm"] > before["tri_w_mm"]
    assert after["feed"] == before["feed"]
    assert after["area"] == before["area"]


def test_the_marker_layer_pick_moves_every_shape():
    """Every shape -- the rectangle and the ones inside the arrow footprint,
    which a walk of the group's members alone would miss."""
    board, section = _placed()
    section.marker_layer.SetSelection(4)  # User.5
    _with_kicad(board, section._layer_changed)
    shapes = _with_kicad(board, lambda: area_marker.marker_shapes(_group(board)))
    assert len(shapes) == 7  # the rectangle, five arrow segments, the dot
    assert {s.layer for s in shapes} == {55}


# --------------------------------------------------------------------------- #
# What the status line says about the area
# --------------------------------------------------------------------------- #
def test_an_area_dragged_bigger_than_the_board_is_said_so():
    board, section = _placed()
    _drag_rect(board, (0.0, 0.0, 120.0, 90.0))  # the board is 60 x 40
    _with_kicad(board, section.sync_from_board)
    text = section._status_label.GetLabel()
    assert "Bigger than the board outline" in text
    # Said, not enforced: the marker is left exactly as it was dragged.
    assert _decode(board)["w_mm"] == 120.0


def test_no_marker_says_what_place_will_do():
    board = _Board()
    section = _section(board)
    _with_kicad(board, section.refresh_status)
    text = section._status_label.GetLabel()
    assert "No area marker" in text and "User.2" in text and "dragging" in text


if __name__ == "__main__":
    run_module_tests(globals())
