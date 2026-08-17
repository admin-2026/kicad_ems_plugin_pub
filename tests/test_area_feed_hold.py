"""The feed point under a resize: it stays put (no KiCad, real wx stubbed).

The feed sits at a *fraction* of the area's edge, and the rectangle grows
about the marker's own centre -- so on its own, every nudge of the Area-width
slider slides the feed sideways across the board, off whatever the user lined
it up with (the pour's edge, a connector, the feed marker), and every nudge of
the Area-height slider pushes the feed *edge* half the change the other way.
Each side holds the feed its own way: the width slider re-aims the
feed-position slider first (AreaSection._hold_feed_point) so the area grows and
shrinks *around* the feed; the height slider reshapes with
``area_marker.update_marker``'s ``hold_feed``, which slides the whole marker
back so the area deepens *away* from the feed.

What is pinned here: the feed point's board position survives a width or height
change (at any rotation -- the fraction the width is re-aimed to is the
marker's own local one, and the height's slide is measured on the board), that
a feed the new width can't reach clamps instead of raising, and that nothing
else moves it -- the height and feed-width sliders leave the fraction alone,
and so does a width change with no (or no readable) marker.

The marker is a real one: its segments are area_marker's own, so the decode
these run through is the decode the board gets.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_area_feed_hold.py
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
area_marker = load("markers.area_marker")
feed_marker = load("markers.feed_marker")
markergeom = load("markers.markergeom")
area_section = load("gui.sections.area")

wx = wx_stub.wx

F0 = 2.45
TRI_W = 1.2  # the feed-width slider's default, near enough


# --------------------------------------------------------------------------- #
# A placed area marker, carrying nothing but its segments
# --------------------------------------------------------------------------- #
class _Marker:
    """A marker footprint the way the section reaches it: a bag of segments in
    board mm (its local shape, dropped at ``at`` and turned by ``rot_deg``),
    reshaped by update_marker and read back by decode_marker -- the three
    board-facing calls below answer those for a _Marker, since everything under
    them is pcbnew."""

    def __init__(self, w_mm, h_mm, frac, at=(100.0, 80.0), rot_deg=0.0):
        self.at, self.rot_deg = at, rot_deg
        self.reshape(w_mm, h_mm, frac, TRI_W)

    def reshape(self, w_mm, h_mm, frac, tri_w_mm):
        local = area_marker._local_segments(w_mm, h_mm, frac, tri_w_mm)
        turned = markergeom.rotate_segments(local, self.rot_deg)
        self.segments = [
            (
                (a[0] + self.at[0], a[1] + self.at[1]),
                (b[0] + self.at[0], b[1] + self.at[1]),
            )
            for (a, b) in turned
        ]

    def move_by(self, dx, dy):
        """The whole marker slid across the board, segments and all -- what
        FOOTPRINT::SetPosition does for the real one
        (area_marker._shift_to_held_feed)."""
        self.at = (self.at[0] + dx, self.at[1] + dy)
        self.segments = [
            ((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)) for (a, b) in self.segments
        ]

    def feed_point(self):
        """The feed point in *board* mm: the decode reports it in the marker's
        derotated frame, so it is turned back the way the board sees it."""
        d = area_marker.decode_marker(self)
        return markergeom.rotate_pt(d["feed"], d["rot_deg"], d["pivot"])


def _for_markers(module, name, answer):
    """Answer ``module.name`` from ``answer`` for a _Marker, and from the real
    implementation for anything else. These modules are shared with every other
    test in the run (one interpreter under pytest), so the stand-ins delegate
    rather than replace -- a fake footprint from another module's harness still
    gets the real function."""
    real = getattr(module, name)

    def dispatch(fp, *args, **kwargs):
        if isinstance(fp, _Marker):
            return answer(fp, *args, **kwargs)
        return real(fp, *args, **kwargs)

    setattr(module, name, dispatch)


def _update_marker(fp, w, h, frac, tri=None, layer=None, hold_feed=False):
    """area_marker.update_marker for a _Marker: the reshape, followed by the
    feed-holding slide the real one makes through pcbnew -- the arithmetic
    behind it (area_marker.hold_shift_mm) is the shipped one, only the
    SetPosition it ends in is stood in for (_Marker.move_by)."""
    before = list(fp.segments)
    fp.reshape(w, h, frac, tri)
    if hold_feed:
        fp.move_by(*area_marker.hold_shift_mm(before, fp.segments))


# The board-facing calls the section makes on a marker: its segments, its layer
# and the reshape -- all three pcbnew, all three trivial on a _Marker.
_for_markers(feed_marker, "_segment_points_mm", lambda fp: fp.segments)
_for_markers(feed_marker, "marker_layer_name", lambda fp: "User.2")
_for_markers(area_marker, "update_marker", _update_marker)


# --------------------------------------------------------------------------- #
# The section, off the board
# --------------------------------------------------------------------------- #
class _Host:
    def target_freq_ghz(self, default=None):
        return F0

    def marker_layer_n(self):
        return 2


class _Page:
    def __init__(self, design):
        self.design = design
        self.scroll = None
        self.host = _Host()
        self.scan = None  # built after this section

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def refresh_area_checks(self):
        pass


def _section(marker=None):
    """An Area section with ``marker`` placed on the board (None = none), its
    sliders synced to it."""
    page = _Page(registry.DESIGNS[0])
    section = area_section.AreaSection(page, wx.BoxSizer())
    section.build_layer_picker(None, wx.FlexGridSizer())
    section._markers = lambda: [marker] if marker is not None else []
    section.marker_width.set_value(TRI_W)
    if marker is not None:
        section.refresh()  # the sliders take the placed marker's shape
    return section


def _drag(slider, value, scale=10):
    """Drag ``slider`` to ``value`` in real units, as wx does it: the position
    moves under a held button, then EVT_SLIDER fires (wx_stub.adjust -- a
    change with no button behind it is a wheel notch, which widgets.Slider
    undoes)."""
    slider.slider.adjust(int(round(value * scale)))


def _drag_width(section, w_mm):
    _drag(section.w, w_mm)


def _drawn(marker):
    """The marker's geometry as the board carries it."""
    d = area_marker.decode_marker(marker)
    return {k: d[k] for k in ("w_mm", "h_mm", "tri_w_mm", "frac")}


_EPS_MM = 1e-6  # float noise, well under the decode's own 3-dp rounding


def _notch_mm(w_mm):
    """How exactly a feed can be held, in mm: the feed-position slider steps in
    0.1 % of the edge (POS_RANGE), and the marker is drawn from that slider, so
    the re-aimed fraction is rounded to a notch of it. One notch at the new
    width is the floor for all of this -- and it is what one press of an arrow
    key on that slider moves the feed anyway."""
    return w_mm / area_section.POS_RANGE[1]


def _assert_held(marker, before, w_mm):
    """The marker's feed point is still where it was (board mm), to within the
    feed slider's own resolution at the new width."""
    after = marker.feed_point()
    for got, want, axis in zip(after, before, "xy"):
        assert abs(got - want) <= _notch_mm(w_mm) + _EPS_MM, (
            f"{axis}: {before} -> {after}"
        )


# --------------------------------------------------------------------------- #
# The feed stays where it is drawn
# --------------------------------------------------------------------------- #
def test_widening_the_area_leaves_the_feed_point_alone():
    marker = _Marker(40.0, 12.0, 0.3)
    before = marker.feed_point()
    section = _section(marker)
    _drag_width(section, 60.0)
    _assert_held(marker, before, 60.0)
    # 8 mm left of a 60 mm centre is 36.67 % along the edge, and the readout
    # says so -- the fraction is what moved, not the feed.
    assert math.isclose(section.pos.value(), 36.7, abs_tol=0.05)
    assert math.isclose(section.w_mm(), 60.0)


def test_narrowing_the_area_leaves_the_feed_point_alone():
    marker = _Marker(40.0, 12.0, 0.3)
    before = marker.feed_point()
    section = _section(marker)
    _drag_width(section, 24.0)
    _assert_held(marker, before, 24.0)
    assert math.isclose(section.pos.value(), 16.7, abs_tol=0.05)


def test_a_feed_on_the_centre_line_is_a_fixed_point():
    """The one feed a plain fraction would already hold: the middle."""
    marker = _Marker(40.0, 12.0, 0.5)
    before = marker.feed_point()
    section = _section(marker)
    _drag_width(section, 55.0)
    assert marker.feed_point() == before  # exactly: the centre needs no notch
    assert math.isclose(section.pos.value(), 50.0, abs_tol=0.05)


def test_a_typed_width_holds_the_feed_too():
    """The readout is the same path a drag takes (UnitSlider commits it), so
    the precise size the box is there for doesn't cost the feed its place."""
    marker = _Marker(40.0, 12.0, 0.2)
    before = marker.feed_point()
    section = _section(marker)
    section.w._readout.type("31.5")
    assert math.isclose(section.w_mm(), 31.5)
    _assert_held(marker, before, 31.5)


def test_a_rotated_marker_holds_its_feed_point_too():
    """Rotation is the user's (R, any angle): the fraction being re-aimed is
    the marker's own local one, so it holds there as well."""
    for rot_deg in (30.0, 90.0, -127.5):
        marker = _Marker(40.0, 12.0, 0.25, rot_deg=rot_deg)
        before = marker.feed_point()
        section = _section(marker)
        _drag_width(section, 52.0)
        _assert_held(marker, before, 52.0)


def test_a_slow_drag_lands_where_one_step_would():
    """A drag arrives as dozens of small changes, each re-reading the offset
    off a marker drawn at the *rounded* fraction (the feed slider's step is
    0.1 % of the edge), so the held point can drift by a fraction of a step per
    change. What is pinned is that the drift stays inside the feed slider's own
    resolution end to end -- i.e. below what one notch of that slider moves the
    feed anyway -- rather than accumulating into a visible slide."""
    stepped = _Marker(40.0, 12.0, 0.35)
    section = _section(stepped)
    for w in range(400, 601, 5):  # 40 -> 60 mm, 0.5 mm at a time
        _drag_width(section, w / 10.0)
    straight = _Marker(40.0, 12.0, 0.35)
    _drag_width(_section(straight), 60.0)
    drift = abs(stepped.feed_point()[0] - straight.feed_point()[0])
    assert drift <= _notch_mm(60.0) + _EPS_MM, drift


def test_a_feed_the_new_width_cannot_reach_clamps_to_the_edge():
    """Shrunk far enough, the feed's offset falls outside the rectangle
    altogether: the slider clamps to its own end (and the marker keeps the
    triangle off the corner) rather than raising."""
    marker = _Marker(60.0, 12.0, 0.95)  # 27 mm right of the centre
    section = _section(marker)
    _drag_width(section, 10.0)
    assert section.pos.value() == area_section.POS_RANGE[1] / 10  # 100 %
    d = area_marker.decode_marker(marker)
    assert d["w_mm"] == 10.0 and d["frac"] < 1.0  # on the edge, off the corner


# --------------------------------------------------------------------------- #
# ... and when the area deepens, the feed edge is what stays
# --------------------------------------------------------------------------- #
# The height's hold is measured on the board rather than re-aimed through a
# slider, so it costs nothing but the decode's own rounding (3 dp on the feed,
# 4 on the pivot a rotated marker is turned back about).
_HOLD_TOL_MM = 2e-3


def _assert_feed_unmoved(marker, before):
    """The marker's feed point is still where it was, in board mm."""
    after = marker.feed_point()
    for got, want, axis in zip(after, before, "xy"):
        assert abs(got - want) <= _HOLD_TOL_MM, f"{axis}: {before} -> {after}"


def test_deepening_the_area_leaves_the_feed_point_alone():
    marker = _Marker(40.0, 12.0, 0.3)
    before = marker.feed_point()
    section = _section(marker)
    _drag(section.h, 25.0)
    _assert_feed_unmoved(marker, before)
    assert _drawn(marker)["h_mm"] == 25.0


def test_shallowing_the_area_leaves_the_feed_point_alone():
    marker = _Marker(40.0, 20.0, 0.3)
    before = marker.feed_point()
    section = _section(marker)
    _drag(section.h, 6.0)
    _assert_feed_unmoved(marker, before)
    assert _drawn(marker)["h_mm"] == 6.0


def test_the_area_deepens_away_from_the_feed_edge():
    """Where the depth goes: the feed edge (max Y on an unrotated marker) is
    pinned and the opposite edge moves the whole change, so the antenna gets
    its room on the inside of the board -- not by dragging the feed off the
    pour it was lined up with."""
    marker = _Marker(40.0, 12.0, 0.3)
    (_x0, y0, _x1, y1) = area_marker.decode_marker(marker)["area"]
    _drag(_section(marker).h, 20.0)
    (_x0b, y0b, _x1b, y1b) = area_marker.decode_marker(marker)["area"]
    assert math.isclose(y1b, y1, abs_tol=_HOLD_TOL_MM)  # the feed edge, held
    assert math.isclose(y0b, y0 - 8.0, abs_tol=_HOLD_TOL_MM)  # the far one moved


def test_a_rotated_marker_holds_its_feed_point_when_it_deepens():
    """Rotation is the user's (R, any angle): the slide is measured on the
    board, so it follows the marker's own feed edge whichever way it faces."""
    for rot_deg in (30.0, 90.0, -127.5):
        marker = _Marker(40.0, 12.0, 0.25, rot_deg=rot_deg)
        before = marker.feed_point()
        section = _section(marker)
        _drag(section.h, 22.0)
        _assert_feed_unmoved(marker, before)


def test_a_typed_height_holds_the_feed_too():
    marker = _Marker(40.0, 12.0, 0.2)
    before = marker.feed_point()
    section = _section(marker)
    section.h._readout.type("17.5")
    assert math.isclose(section.h_mm(), 17.5)
    _assert_feed_unmoved(marker, before)


def test_a_slow_height_drag_lands_where_one_step_would():
    """A drag arrives as dozens of small changes; each holds the feed against
    the marker as it stands, so nothing accumulates -- unlike the width's
    re-aimed fraction, this hold has no slider resolution to round to."""
    stepped = _Marker(40.0, 12.0, 0.35)
    section = _section(stepped)
    for h in range(120, 301, 5):  # 12 -> 30 mm, 0.5 mm at a time
        _drag(section.h, h / 10.0)
    straight = _Marker(40.0, 12.0, 0.35)
    _drag(_section(straight).h, 30.0)
    for got, want in zip(stepped.feed_point(), straight.feed_point()):
        assert abs(got - want) <= _HOLD_TOL_MM


def test_the_width_and_height_together_leave_the_feed_where_it_is():
    """Both sliders on the same marker, each holding the feed its own way."""
    marker = _Marker(40.0, 12.0, 0.15, rot_deg=15.0)
    before = marker.feed_point()
    section = _section(marker)
    _drag_width(section, 55.0)
    _drag(section.h, 24.0)
    _assert_held(marker, before, 55.0)


# --------------------------------------------------------------------------- #
# A slider drives its own knob, and only its own
# --------------------------------------------------------------------------- #
def _out_of_step_launch():
    """The wizard as it comes up on a board whose marker the sliders don't
    match: the Feed-width slider is the *feed marker's* width, restored from
    the settings file and shared with the simulate view, so it arrives holding
    something else entirely; the height slider is held under the marker's own
    depth by the board-outline cap (_apply_side_range). Returns the marker and
    its section, both as they stand the moment the user reaches for a slider.
    """
    marker = _Marker(20.0, 12.0, 0.05, at=(100.0, 80.0))  # feed near a corner
    marker.reshape(20.0, 12.0, 0.05, 1.0)  # ... drawn with a 1 mm triangle
    section = _section(marker)
    section.marker_width.set_value(4.0)  # the feed marker's width, restored
    section.h.set_value(8.0)  # a cap the marker is deeper than
    return marker, section


def test_the_first_width_change_after_launch_changes_only_the_width():
    """The bug this pins: every reshape has to pass all four numbers, so at the
    first touch of any slider the ones that were never in step with the board
    -- the shared feed width, a capped height -- used to land on the marker
    too, dragging the feed with them. Only the width the user dragged applies
    now; the rest of the marker is left as drawn."""
    marker, section = _out_of_step_launch()
    before, drawn = marker.feed_point(), _drawn(marker)
    _drag_width(section, 21.0)
    _assert_held(marker, before, 21.0)
    after = _drawn(marker)
    assert after["w_mm"] == 21.0  # the one thing asked for
    assert after["h_mm"] == drawn["h_mm"]  # not the capped slider's 8 mm
    assert after["tri_w_mm"] == drawn["tri_w_mm"]  # not the feed marker's 4 mm


def test_the_untouched_sliders_come_back_into_step():
    """A slider left out of step with the board is put right by the reshape it
    didn't drive, so the mismatch shows up in the readout rather than waiting
    to be applied to the copper. The Feed-width slider is not among them: it is
    the feed marker's, shared across the pages, and this box only reads it."""
    marker, section = _out_of_step_launch()
    _drag_width(section, 21.0)
    assert math.isclose(section.h_mm(), _drawn(marker)["h_mm"])
    assert math.isclose(section.w_mm(), 21.0)
    assert math.isclose(section.tri_w_mm(), 4.0)


def test_the_height_slider_applies_the_height_and_nothing_else():
    marker, section = _out_of_step_launch()
    drawn = _drawn(marker)
    _drag(section.h, 15.0)
    after = _drawn(marker)
    assert after["h_mm"] == 15.0
    assert after["w_mm"] == drawn["w_mm"]
    assert after["tri_w_mm"] == drawn["tri_w_mm"]
    assert math.isclose(after["frac"], drawn["frac"], abs_tol=1e-3)


def test_the_feed_width_slider_applies_the_triangle_and_nothing_else():
    """The knob it does drive: moving it is the one thing that resizes the
    marker's feed triangle."""
    marker, section = _out_of_step_launch()
    drawn = _drawn(marker)
    _drag(section.marker_width, 3.0, scale=100)
    after = _drawn(marker)
    assert after["tri_w_mm"] == 3.0
    assert (after["w_mm"], after["h_mm"]) == (drawn["w_mm"], drawn["h_mm"])


def test_the_layer_pick_reshapes_nothing():
    """The Advanced pane's Marker-layer picker goes through the same reshape
    (it is how a placed marker moves layer) but drives no knob at all, so the
    geometry it writes back is the geometry already there."""
    marker, section = _out_of_step_launch()
    drawn, before = _drawn(marker), marker.feed_point()
    section._apply_live()
    assert _drawn(marker) == drawn
    assert marker.feed_point() == before


def test_the_height_slider_leaves_the_fraction_alone():
    """Height moves the feed edge itself; the feed's place *along* it is not
    the depth's business."""
    marker = _Marker(40.0, 12.0, 0.3)
    section = _section(marker)
    _drag(section.h, 25.0)
    assert math.isclose(section.pos.value(), 30.0, abs_tol=0.05)
    assert math.isclose(_drawn(marker)["frac"], 0.3, abs_tol=1e-3)


def test_the_feed_width_slider_leaves_the_fraction_alone():
    marker = _Marker(40.0, 12.0, 0.3)
    section = _section(marker)
    _drag(section.marker_width, 3.0, scale=100)
    assert math.isclose(section.pos.value(), 30.0, abs_tol=0.05)
    assert math.isclose(_drawn(marker)["frac"], 0.3, abs_tol=1e-3)


def test_no_marker_leaves_the_slider_where_it_is():
    """Nothing placed: the fraction is just a setting for the next Place, and
    the width slider has no business moving it."""
    section = _section(None)
    section.pos.set_value(20.0)
    _drag_width(section, 60.0)
    assert math.isclose(section.pos.value(), 20.0)


def test_an_unreadable_marker_leaves_the_slider_where_it_is():
    """An edited marker decodes to no local fraction (or not at all): there is
    nothing trustworthy to hold, so the slider is left alone -- the reshape
    that follows is what reports the breakage."""
    marker = _Marker(40.0, 12.0, 0.3)
    section = _section(marker)
    section.pos.set_value(30.0)
    marker.segments = marker.segments[:3]  # not a rectangle + arrow any more
    _drag_width(section, 60.0)
    assert math.isclose(section.pos.value(), 30.0)


if __name__ == "__main__":
    run_module_tests(globals())
