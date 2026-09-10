"""Converting the area marker an older plugin drew as one footprint (no KiCad,
real wx stubbed, a fake pcbnew).

Up to 2026-09-01 the area marker was a single ``board_only`` footprint: the
rectangle drawn as four line segments and the feed arrow as five more, all of
them the footprint's own graphics, and the area sized by sliders in the wizard.
Nothing in ``markers/`` knows that marker any more — it is converted to today's
group (a draggable rectangle plus a rigid arrow footprint) the first time the
wizard looks at the board, and only the converted one is ever read.

What is pinned here: that the conversion keeps the marker the user drew (the
same rectangle, the same feed edge and place along it, the same rotation, the
same layer, the same drawn triangle width), that the old footprint goes off the
board and is not freed while the editor may still point at it, that a v1 marker
whose drawing no longer decodes is left alone and reported rather than guessed
at, that the wizard runs the conversion by itself on the focus refresh and says
so, and that a marker converted once is not converted twice.

    python3 tests/test_area_legacy.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_pcbnew  # noqa: E402  (a board, on the pcbnew wx_stub installs)
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
area_marker = load("markers.area_marker")
feed_marker = load("emkit.markers.feed_marker")
markergeom = load("emkit.markers.markergeom")
area_marker_v1 = load("legacy.area_marker_v1")
area_section = load("gui.sections.area")

wx = wx_stub.wx
Board = fake_pcbnew.Board
KICAD = fake_pcbnew.KICAD
with_kicad = fake_pcbnew.with_kicad
USER_1 = fake_pcbnew.USER_1

TRI_W = 1.2  # the feed-width slider's default, near enough

# The v1 marker these tests convert: 30 x 20 mm centred on (40, 25), feed a
# third of the way along its bottom edge -- what the old Place drew.
V1_W, V1_H, V1_FRAC = 30.0, 20.0, 0.3
V1_CENTER = (40.0, 25.0)


# --------------------------------------------------------------------------- #
# A v1 marker on the board
# --------------------------------------------------------------------------- #
def v1_marker(board, center=V1_CENTER, turn_deg=0.0, layer=USER_1):
    """Draw the marker an older plugin would have left on ``board``: one
    footprint named MARKER_NAME holding the rectangle's four sides, the arrow's
    five segments and the feed dot, all as its own graphics.

    Built from the plugin's own local geometry (``_local_segments`` /
    ``_local_dots``, which is what that version drew with and what this one
    still draws its arrow from), moved onto the board and, for ``turn_deg``,
    rotated the way the user's own R rotated the whole footprint."""
    cx, cy = center
    segments = area_marker._local_segments(V1_W, V1_H, V1_FRAC, TRI_W)
    dots = area_marker._local_dots(V1_W, V1_H, V1_FRAC, TRI_W)
    segments = [((a[0] + cx, a[1] + cy), (b[0] + cx, b[1] + cy)) for a, b in segments]
    dots = [((x + cx, y + cy), r) for (x, y), r in dots]
    if turn_deg:
        segments = markergeom.rotate_segments(segments, turn_deg, center)
        dots = [(markergeom.rotate_pt(pt, turn_deg, center), r) for pt, r in dots]

    def build():
        fp = feed_marker._build_footprint(
            board,
            area_marker.MARKER_NAME,
            "AREA",
            layer,
            segments,
            area_marker.LINE_STROKE_MM,
            dots,
        )
        board.Add(fp)
        return fp

    return with_kicad(board, build)


def decoded(board):
    """The one marker group on ``board``, decoded."""
    group = board.Groups()[0]
    return with_kicad(board, lambda: area_marker.decode_marker(group))


def upgrade(board):
    return with_kicad(board, lambda: area_marker_v1.upgrade(board))


# --------------------------------------------------------------------------- #
# The conversion itself
# --------------------------------------------------------------------------- #
def test_a_v1_marker_becomes_todays_group():
    board = Board()
    v1_marker(board)
    converted, skipped = upgrade(board)
    assert len(converted) == 1 and skipped == []

    group = board.Groups()[0]
    assert group.GetName() == area_marker.GROUP_NAME
    outline, arrow = with_kicad(board, lambda: area_marker._parts(group))
    # The rectangle is a board graphic (the drag handles the whole conversion
    # is for) and the arrow is a footprint of its own (which cannot be pulled
    # apart) -- the two members, and nothing else.
    assert len(group.items) == 2
    assert outline.shape == KICAD["SHAPE_T_RECT"]
    assert str(arrow.GetFPID().GetLibItemName()) == area_marker.FEED_NAME
    assert len(arrow.items) == 6  # five arrow segments and the feed dot


def test_the_converted_marker_is_the_marker_the_user_drew():
    board = Board()
    fp = v1_marker(board)
    before = with_kicad(
        board, lambda: area_marker._decode_segments(feed_marker._segment_points_mm(fp))
    )
    upgrade(board)
    after = decoded(board)
    assert after["area"] == before["area"]
    assert after["edge"] == before["edge"]
    assert abs(after["frac"] - before["frac"]) < 0.001
    assert abs(after["tri_w_mm"] - before["tri_w_mm"]) < 0.001
    assert after["feed"] == before["feed"]


def test_a_turned_v1_marker_keeps_its_angle():
    """A v1 marker could be rotated (it was a footprint, so its properties
    dialog had an angle). That angle is the one thing a rebuilt rectangle would
    quietly lose, since a KiCad rectangle is always upright: off the grid the
    converted outline is a polygon, turned by what the old marker was turned
    by."""
    board = Board()
    v1_marker(board, turn_deg=-33.0)  # 33 degrees counter-clockwise on screen
    upgrade(board)
    d = decoded(board)
    assert abs(d["angle_deg"] - 33.0) < 0.01
    assert abs(d["rot_deg"] + 33.0) < 0.01  # the residual the scan simulates
    outline, _arrow = with_kicad(board, lambda: area_marker._parts(board.Groups()[0]))
    assert outline.shape == KICAD["SHAPE_T_POLYGON"]
    assert abs(d["w_mm"] - V1_W) < 0.01 and abs(d["h_mm"] - V1_H) < 0.01


def test_the_converted_marker_stays_on_its_own_layer():
    board = Board()
    v1_marker(board, layer=fake_pcbnew.USER_2)
    upgrade(board)
    shapes = with_kicad(board, lambda: area_marker.marker_shapes(board.Groups()[0]))
    assert len(shapes) == 7  # the rectangle, five arrow segments, the dot
    assert {s.layer for s in shapes} == {fake_pcbnew.USER_2}


def test_the_old_footprint_leaves_the_board_without_being_freed():
    """Unlinked, but never freed: the editor's view, selection and undo stack
    may still point at a footprint KiCad loaded with the board, so the C++
    object is orphaned instead (feed_marker._detach_footprint)."""
    board = Board()
    fp = v1_marker(board)
    upgrade(board)
    assert fp not in board.GetFootprints()
    assert fp.thisown is False
    # ... and the marker that is left is the new one alone.
    assert len(with_kicad(board, lambda: area_marker.placed_markers(board))) == 1


def test_a_converted_board_is_not_converted_twice():
    board = Board()
    v1_marker(board)
    upgrade(board)
    again = upgrade(board)
    assert again == ([], [])
    assert len(board.Groups()) == 1


def test_a_v1_marker_that_no_longer_decodes_is_left_alone():
    """Rebuilding it would mean guessing at an area the user drew, so it is
    reported instead -- and it is still on the board for them to delete."""
    board = Board()
    fp = v1_marker(board)
    with_kicad(board, lambda: fp.Remove(fp.items[0]))  # a side rubbed out
    converted, skipped = upgrade(board)
    assert converted == [] and board.Groups() == []
    assert len(skipped) == 1 and skipped[0][0] is fp
    assert "regenerate" in skipped[0][1]
    assert fp in board.GetFootprints()


# --------------------------------------------------------------------------- #
# The wizard doing it by itself
# --------------------------------------------------------------------------- #
class _Host:
    def target_freq_ghz(self, default=None):
        return 2.45

    def marker_layer_n(self):
        return 1


class _Scan:
    def refresh_preview(self):
        pass

    def reset_params(self):
        pass


class _Page:
    def __init__(self):
        self.design = registry.DESIGNS[0]
        self.scroll = None
        self.host = _Host()
        self.scan = _Scan()

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def refresh_area_checks(self):
        pass

    def save_settings(self):
        pass


def _section(board):
    section = with_kicad(
        board, lambda: area_section.AreaSection(_Page(), wx.BoxSizer())
    )
    with_kicad(board, lambda: section.build_layer_picker(None, wx.FlexGridSizer()))
    section.marker_width.set_value(TRI_W)
    return section


def test_the_wizard_converts_what_it_finds_and_says_so():
    """No button and no dialog: the marker is converted on the sync that runs
    when the wizard's window takes the focus, and the status line reports it --
    the board was changed, and a plugin's change is not on KiCad's undo
    stack."""
    board = Board()
    v1_marker(board)
    section = _section(board)
    with_kicad(board, section.sync_from_board)

    assert len(board.Groups()) == 1
    text = section._status_label.GetLabel()
    assert "older version" in text and "dragging its corners" in text
    # ... and it goes on to describe the marker, as any other sync does.
    assert f"{V1_W:g} × {V1_H:g} mm" in text


def test_the_note_is_said_once():
    board = Board()
    v1_marker(board)
    section = _section(board)
    with_kicad(board, section.sync_from_board)
    with_kicad(board, section.sync_from_board)
    assert "older version" not in section._status_label.GetLabel()


def test_a_marker_that_cannot_be_converted_is_reported_on_the_status_line():
    board = Board()
    fp = v1_marker(board)
    with_kicad(board, lambda: fp.Remove(fp.items[0]))
    section = _section(board)
    with_kicad(board, section.sync_from_board)
    text = section._status_label.GetLabel()
    assert "✗" in text and "delete" in text
    # The wizard sees no marker at all now, and says what Place would do.
    assert "No area marker" in text


if __name__ == "__main__":
    run_module_tests(globals())
