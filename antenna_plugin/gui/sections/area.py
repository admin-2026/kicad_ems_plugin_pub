"""Section 1 of the wizard: the antenna area + feed position, drawn on the
board.

The area lives on the board as the area marker (markers/area_marker.py): a
rectangle graphic and a feed arrow (a triangle pointing inward plus a short
outward stem, with a dot on the feed point where the two meet), held together
in a group named ``AntennaAreaMarker``. "Place area marker" drops one beside
the board outline through the pcbnew API.

**The board is the interface.** The rectangle is a board graphic, so KiCad's own
point editor puts a handle on each of its corners: double-click the marker to
enter its group, drag a corner, and the area is the size you drew. The feed
moves the same way — drag the arrow (a footprint, so it moves as one thing and
can't be pulled apart) to the edge the feed enters from and the wizard lands its
base back on the nearest edge, squared to it, at the point it was dropped
(``area_marker.sync_marker``). Moving (M) and rotating (R) work as they do for
anything else on the board. The status line under this box says so whenever
there is a marker to say it about (EDIT_HINT), in the same words the marker
carries on the board — KiCad draws the group's *name* over it, and that name
ends in ``area_marker.HINT_TEXT`` — so the window and the drawing tell the user
the same thing about where the work is done.

So this section has no width, height or feed-position sliders: there is nothing
here that describes the rectangle, because the rectangle describes itself. What
is left is the Feed-width slider and the Feed-layer picker, which mirror the
feed marker's (the base's ``build_feed_width`` / ``build_feed_layer``) and whose
values are shared across both pages through the FormModel; so is the User layer
this marker is drawn on, picked in the wizard's own Advanced pane
(``build_layer_picker``). The feed width is visual only: it sizes the drawn
triangle, and a sync carries the new size onto the board.

And, under the feed width and built like it, one control that is not a reading
of the board but a lever on it: **Angle** (``_build_angle``) — a slider to sweep
the marker round and a box to type the exact figure. KiCad turns a selection by
its rotation *step*, and only a footprint carries an angle anyone can type, so a
group can never be turned to 37.5° on the board — this is where that is done, in
the same degrees KiCad means everywhere else. An off-grid angle is handled by
rotating the whole board in the simulation, as it always was.

The plugin otherwise reads the board rather than driving it: ``sync_from_board``
— run when the page is shown and whenever the window regains the focus, which is
exactly when the user comes back from dragging something — squares the outline
back up if a drag pulled it out of square, repins the arrow, re-describes the
marker on the status line and redraws the candidate preview against the area as
it now stands. It is also where a marker an older version of the plugin drew as
a single footprint is converted into today's draggable one
(``_upgrade_old_markers``, legacy/area_marker_v1.py) — nothing below this
section knows the old shape at all. The scan consumes the decoded rectangle +
feed edge + position through ``spec()``; the feed gap that sizes the ground stub
is fixed at the runner's default (FEED_GAP_MM), not a slider. Placing a marker
starts the design over: the scan section's persisted rows are tuned to whatever
area was there before, so they go back to the design's seeds and out of the
settings file (``_forget_scan_params``).

It is the same idea as the feed marker — the plugin's own drawing on a User
layer, placed once and never replaced — so it subclasses FeedMarkerSection,
reusing the placed-marker lookup (``_markers``, keyed to area_marker here), the
Feed-width / Feed-layer builders, the button's two labels (``_sync_button``:
Place with no marker on the board, Show with one), the reply Place gives when a
marker is already on the board (``_show_already_placed`` — it takes the PCB
editor to that marker and leads with where it is) and the wrapped status line
(``_set_status``); only the rest of the UI and the sync/decode differ — this
section's ``_placed_text`` describes its own marker, and the shared reply is
written from it.
"""

import pcbnew
import wx

from ...emkit.gui.board import board_edge_span_mm
from ...emkit.gui.sections.marker import GAP_DEFAULT, MARKER_LAYERS, FeedMarkerSection
from ...emkit.gui.theme import PAD, ROW
from ...emkit.gui.widgets import UnitSlider
from ...emkit.markers import feed_marker
from ...legacy import area_marker_v1
from ...markers import area_marker

# A fresh marker's rectangle: the design says how much room its antennas want
# (design.area_hint_mm), held between these ends so that a starter is always
# something the user can see and grab a corner of. Everything after the drop is
# the drag's business -- these bound the plugin's opening guess, not the area.
MIN_SIDE_MM = area_marker.MIN_SIDE_MM
MAX_SIDE_MM = 200.0
# The feed of a fresh marker sits at 30 % of its bottom edge: it leaves the
# bend of an L or an F more room than the middle does. Where it goes after
# that is wherever the arrow is dragged.
START_FRAC = 0.3

# The feed gap the scan sizes its ground stub from is fixed at the runner's
# default (GAP_DEFAULT, hundredths of a mm) rather than exposed as a slider —
# the runner severs its own gap on the simulation grid regardless, and the
# width of that gap is an output of the meshing, so there is nothing here to
# ask for.
FEED_GAP_MM = GAP_DEFAULT / 100.0

# The Angle slider's positions are tenths of a degree over a whole turn, so the
# slider reaches every angle the field can be typed: a marker is turned to face
# the ground pour, and a tenth of a degree is finer than that ask ever is. 360
# and 0 are the same marker -- a sweep that ends there reads back as 0.
ANGLE_SCALE = 10
ANGLE_RANGE = (0, 360 * ANGLE_SCALE)

# How the area is edited, said on the status line under this box whenever it
# describes a placed marker. The marker itself says the same thing on the
# canvas -- KiCad draws its group's name over it, and that name ends in these
# words (area_marker.HINT_TEXT) -- so the window and the board agree.
EDIT_HINT = f"{area_marker.HINT_TEXT.capitalize()} in the PCB editor."


def _v1_markers(n):
    """``n`` area markers from an older version of the plugin, as the subject
    of a status line (``_upgrade_old_markers``). The case that happens is one,
    and it reads like one; more than one is a board with extras on it, which the
    placed-marker line has its own word about."""
    return "An area marker" if n == 1 else f"{n} area markers"


class AreaSection(FeedMarkerSection):
    marker_module = area_marker  # _markers() looks up area markers
    _TITLE = "Antenna area and feed"
    # The button's two labels and what to do with the marker already on the
    # board when it is pressed with one there (the base's _sync_button /
    # _show_already_placed, which takes the editor to it and leads with where
    # it is). This marker is dragged into shape where the feed marker is only
    # resized.
    _BTN_PLACE = "Place area marker"
    _BTN_SHOW = "Show placed area marker"
    _SHOW_TIP = (
        "An area marker is already on the board — this takes the PCB editor to "
        "it. Double-click it to enter the group, then drag a corner of the "
        "rectangle to resize the area or drag the arrow to move the feed; "
        "delete it (Del) to place a new one."
    )
    _ALREADY_HINT = (
        "double-click it to enter the group and drag a corner to resize the "
        "area or the arrow to move the feed, move (M) / rotate (R) it in the "
        "editor, or delete it (Del) and Place again."
    )
    # A one-shot line waiting to go in front of whatever this section says next
    # (_upgrade_old_markers / _set_status). A class attribute, so it is there
    # before the first status line is written.
    _note = ""

    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)

        # The Feed-width slider and Feed-layer picker mirror the feed marker's
        # (shared across both pages through the FormModel); the width also
        # draws this marker's feed triangle, so moving it repins the arrow at
        # the new size (build_feed_width / build_feed_layer live on the base).
        grid = wx.FlexGridSizer(3, ROW, PAD)
        self.build_feed_width(p, grid, self._on_feed_width)
        self._build_angle(p, grid)  # under the width, the section's other knob
        box.Add(grid, 0)

        layer_grid = wx.FlexGridSizer(2, ROW, PAD)
        self.build_feed_layer(p, layer_grid)
        box.Add(layer_grid, 0, wx.EXPAND | wx.TOP, ROW)

        # The button comes after the settings it places the marker with, as the
        # feed marker's does (sections.marker._build_controls): the picks are
        # made above, then the button that puts the marker on the board, then
        # the status line reporting what landed — and, from then on, what the
        # board says the area is.
        self.marker_btn = wx.Button(p, label=self._BTN_PLACE)
        self.marker_btn.Bind(wx.EVT_BUTTON, self.on_place)
        box.Add(self.marker_btn, 0, wx.TOP, PAD)

        self._status_label = self.wrap_label(p, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)

    def _build_angle(self, pane, grid):
        """The Angle row (three cells of ``grid``, under the Feed width it is
        the twin of): the marker's rotation on the board, in the degrees KiCad
        means everywhere else — counter-clockwise on screen, 0 for a marker as
        it is placed. A slider to sweep it round and see where the antenna
        wants to face, and a box to type the angle you actually want; both are
        also the readout, so a marker turned in the editor shows up here.

        This is the one thing about the marker the board cannot say. KiCad
        rotates a selection by its rotation *step* (Preferences → PCB Editor →
        Editing Options), and only a footprint carries an angle anyone can
        type; the marker is a group, so R alone can never reach 37.5°. The
        size, the feed's place and everything else stay on the board where the
        user drags them."""
        self.angle = UnitSlider(
            grid,
            pane,
            "Angle",
            ANGLE_RANGE,
            0,
            ANGLE_SCALE,
            self._on_angle,
            fmt="{:.1f}".format,
            editable=True,
            suffix="°",
            value_w=56,
        )
        self.angle.set_tip(
            "Turn the placed marker, in degrees counter-clockwise (0 = as "
            "placed, feed along the bottom edge). KiCad's own R turns it in "
            "whole rotation steps; this is how it reaches an angle between "
            "them — type one in the box for an exact figure. Everything else "
            "about the marker is dragged on the board."
        )

    # --- values ---------------------------------------------------------------
    def gap_mm(self):
        return FEED_GAP_MM  # fixed; the runner cuts its own gap

    def tri_w_mm(self):
        """The feed triangle's (visual-only) width: this section's own
        Feed-width slider (``width_mm``, from the base), whose value is shared
        with the feed marker across both pages."""
        return self.width_mm()

    def _starter_size(self):
        """The rectangle a fresh marker is drawn with, in mm: the page's design
        says how much room its antennas want at the main dialog's frequency
        (``design.area_hint_mm`` -- an L-monopole lies down over a quarter
        wave, an inverted-F folds into a fraction of one), clamped to the
        board's own outline where there is one, since an area bigger than the
        board can never be placed on it. It is only a starting point: the user
        drags the rectangle to the size they mean."""
        freq = self.page.host.target_freq_ghz(2.45)
        want = self.page.design.area_hint_mm(max(freq, 0.1))
        span = board_edge_span_mm() or (None, None)
        return tuple(
            min(max(side, MIN_SIDE_MM), MAX_SIDE_MM if extent is None else extent)
            for side, extent in zip(want, span)
        )

    # --- events ---------------------------------------------------------------
    def _on_feed_width(self):
        """The Feed-width slider moved: redraw the marker's triangle at the new
        width (the repin writes the whole arrow anyway) and re-describe it. A
        repin that failed keeps its own message on the status line."""
        self.marker_width.sync_label()
        if self._apply_live():
            self.refresh_status()

    def _on_angle(self):
        """The Angle slider moved, or a figure was typed into its box: turn the
        placed marker to it (``area_marker.rotate_marker``). With no marker on
        the board there is nothing to turn — the control sits at 0 and the
        status line already says to Place one. A box holding something that
        isn't a number yet ("-", "3e") never reaches here: UnitSlider commits
        only what parses, and only when it moves the slider. A turn that failed
        keeps its own message on the status line."""
        markers = self._markers()
        if not markers:
            return
        try:
            area_marker.rotate_marker(markers[0], self.angle.value(), self.tri_w_mm())
            pcbnew.Refresh()
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return
        self._follow_preview()
        self.angle.sync_label()
        # The control keeps the value it was just moved to (keep_angle): the
        # marker's own reading of it comes back rounded, and writing that back
        # into a slider under the thumb -- or a box under the caret -- is how a
        # control starts fighting its own input.
        self.refresh_status(keep_angle=True)

    def sync_from_board(self):
        """Take the board's word for the area: convert an area marker an older
        version of the plugin left there, square the outline back up if a drag
        left it out of square, repin the feed arrow onto it as the user left the
        two, re-describe the marker on the status line and redraw the candidate
        preview against it.

        This is the whole board→plugin direction, and it runs when the page is
        shown and when the window regains the focus — the moment the user comes
        back from dragging a corner in the PCB editor. There is no polling: the
        drag is KiCad's, with KiCad's own undo, and nothing here needs to see it
        happen."""
        self._upgrade_old_markers()
        if self._apply_live():
            self.refresh_status()

    def _upgrade_old_markers(self):
        """Convert any area marker an older version of the plugin drew as a
        single footprint into the group this wizard drags
        (legacy.area_marker_v1), and leave a note about it for the status line.

        Silent when there is nothing to convert, which is every board but the
        first look at an old one. Not asked about first: a marker of the old
        kind has no drag handles, and dragging is the whole interface here, so
        leaving one would leave the user with a marker none of this section's
        instructions fit. It is said afterwards rather than asked beforehand
        because the board is changed by it — and a plugin's change is not on
        KiCad's undo stack.

        A marker whose drawing no longer decodes is left alone and reported
        instead: rebuilding it would mean guessing at an area the user drew."""
        board = pcbnew.GetBoard()
        if board is None:
            return
        try:
            converted, skipped = area_marker_v1.upgrade(board)
        except Exception as exc:  # a KiCad too old for groups, say
            self._note = f"✗ {exc}"
            return
        notes = []
        if converted:
            pcbnew.Refresh()
            n = len(converted)
            notes.append(
                f"{_v1_markers(n)} from an older version of the plugin "
                f"{'has' if n == 1 else 'have'} been converted — the rectangle "
                "is a board graphic now, so you size the area by dragging its "
                "corners in the editor."
            )
        if skipped:
            n = len(skipped)
            notes.append(
                f"✗ {_v1_markers(n)} from an older version of the plugin can no "
                f"longer be read, and {'was' if n == 1 else 'were'} left on the "
                f"board — delete (Del) and Place a new one. ({skipped[0][1]})"
            )
        self._note = " ".join(notes)

    def _set_status(self, text):
        """This section's status line, with any pending one-shot note put in
        front of it (``_upgrade_old_markers``).

        Here rather than at the one call site because the note reports a change
        made to the user's board, and it has to survive whichever line comes
        next — the marker described, or the error a sync ran into straight
        after."""
        if self._note:
            text, self._note = f"{self._note} {text}", ""
        super()._set_status(text)

    def _apply_live(self):
        """Bring the placed marker in line with this box and with itself: onto
        the Marker-layer pick (Advanced), its outline squared back into a
        rectangle if a drag pulled it out of one, and its feed arrow squared
        back onto whichever edge the arrow now sits nearest, at the drawn
        triangle's current width (``area_marker.sync_marker``). The rectangle's
        *size* is never touched — whatever the user dragged is the area.

        Overrides the feed section's, which reshapes the other marker; both are
        called by the Feed-width slider and by the Advanced pane's layer picker.
        With no marker placed there is nothing to do — the caller still
        refreshes the status line, which then names the layer Place will use.
        Returns False when the sync failed, its reason already on the status
        line.

        Shapes are rewritten in place, never removed and re-added: a shape
        KiCad loaded with the board is KiCad's, and unlinking one from a plugin
        is a use-after-free (feed_marker._detach_item)."""
        markers = self._markers()
        if not markers:
            return True
        board = pcbnew.GetBoard()
        try:
            # None keeps every shape on the layer it is drawn on: with no board
            # there is no layer id to check the pick against.
            layer_id = (
                None
                if board is None
                else feed_marker.check_layer(board, self.marker_layer_n())
            )
            area_marker.sync_marker(markers[0], self.tri_w_mm(), layer_id)
            pcbnew.Refresh()
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return False
        # The drawn candidate is its own footprint (markers/preview.py) and so
        # follows nothing by itself: it is redrawn against the area as it now
        # stands, on the layer that solve then calls for (scan._draw_preview
        # picks it every time -- the marker's own whenever the candidate
        # doesn't fit).
        self._follow_preview()
        return True

    def on_place(self, event=None):
        """Drop a new area marker just clear of the board outline (see
        area_marker._drop_spot — easy to spot rather than buried among existing
        copper on a dense board), at the design's starter size, and switch the
        editor to the marker's own layer (the base's ``_activate_layer``) so
        the user arrives there with it selected. With one already on the board
        this refuses and takes the editor to that marker instead, saying where
        it is and how big it is (``_show_already_placed``) — the board is where
        it gets resized, and the plugin never removes a placed drawing itself.
        The button says as much before it is pressed (``_sync_button``); it is
        re-read here all the same, since the marker can be deleted in the editor
        while the wizard is open."""
        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            return
        if self._markers():
            self._show_already_placed(self._markers())
            return
        try:
            layer_n, layer_id = self._pick_layer(board)
            # The editor goes to the marker's layer as the marker itself does,
            # so the user arrives in the editor with it selected.
            self._activate_layer(board, layer_id)
            w_mm, h_mm = self._starter_size()
            x, y = area_marker.place_marker(
                board, layer_n, w_mm, h_mm, START_FRAC, self.tri_w_mm()
            )
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return
        self._forget_scan_params()
        self._show_angle(0.0)  # a fresh marker is drawn upright
        self._placed_now(
            f"Area marker dropped beside the board ({x:g}, {y:g}) mm on "
            f"User.{layer_n} at {w_mm:g} × {h_mm:g} mm — move it (M) over the "
            "copper-free zone the antenna may use (at the board edge, next to "
            "the ground pour), then double-click it and drag a corner to the "
            "size you have room for. The triangle is where the feed enters: "
            "drag it to another edge to feed from there. The scan rows are "
            "back on their seeds."
        )
        self.page.refresh_area_checks()

    def _forget_scan_params(self):
        """A fresh area invalidates the sweep the last one was tuned for: put
        the scan rows back on the design's seeds and drop the saved copy from
        the settings file straight away, rather than leaving stale bounds to be
        rediscovered on the next launch."""
        self.page.scan.reset_params()
        self.page.save_settings()

    def _pick_layer(self, board):
        """The User layer for a new marker as ``(user_n, layer_id)``: this
        section's own Area-marker-layer pick, from the Advanced pane. If that
        layer isn't enabled on this board, fall back to whatever is."""
        chosen = self.page.host.marker_layer_n()
        last_exc = None
        for n in (chosen, 1, 2, 3, 4, 5, 6, 7, 8, 9):
            try:
                return n, feed_marker.check_layer(board, n)
            except Exception as exc:
                last_exc = exc
        raise last_exc

    # --- decode ---------------------------------------------------------------
    def refresh(self):
        """Read the placed marker off the board (``sync_from_board``). Called
        at wizard startup and on every page switch, to pick up a marker already
        on the board — and whatever was dragged since the page was last
        looked at."""
        self.sync_from_board()

    def refresh_status(self, keep_angle=False):
        """Describe the board's area marker on the status line and put the
        Angle field back in step with it: the decoded rectangle, or — with none
        placed — what Place will do and the layer it will use. Overrides the
        feed section's (whose text and decode are the other marker's); the
        Advanced pane's layer picker calls it, which is what makes a fresh pick
        visible before any marker exists. The button follows the same reading of
        the board (the base's ``_sync_button``).

        ``keep_angle`` leaves the Angle field alone — what the Angle field's own
        handler wants, so the marker's rounded reading isn't written back over
        what the user is still typing."""
        markers = self._markers()
        self._sync_button(markers)
        if not markers:
            self._show_angle(None)
            self._set_status(
                "No area marker on the board — Place puts one beside the board "
                f"on {MARKER_LAYERS[self.marker_layer_n() - 1]}: a rectangle "
                "marking the copper-free zone the antenna may use (near the "
                "ground pour's edge), with an arrow marking the feed. You size "
                "it by dragging its corners in the editor."
            )
            return
        try:
            d = area_marker.decode_marker(markers[0])
        except ValueError as exc:
            self._set_status(f"✗ {exc}")
            return
        if not keep_angle:
            self._show_angle(d["angle_deg"])
        # The line ends with how the marker is edited, every time it describes
        # one: this box has no width, height or feed-position field, so the
        # answer to "where do I change this?" belongs where the marker is
        # described rather than in the title over an unrelated slider.
        self._set_status(f"{self._placed_text(markers, d)} {EDIT_HINT}")

    def _show_angle(self, degrees):
        """Put the Angle control on the marker's own angle (0 with no marker on
        the board — there is nothing turned, and the status line says so).

        ``UnitSlider.set_value`` fires no event, so a readout can never
        re-enter the handler that turns the marker; and it leaves the box alone
        while the user is typing in it (sync_label), which is what keeps a
        half-typed figure from being normalised under the caret."""
        self.angle.set_value(0.0 if degrees is None else degrees)

    def _follow_preview(self):
        """The area changed (a drag picked up on focus, the feed width, or
        startup finding a marker already placed): the scan section's drawn
        antenna preview solves against it, so redraw one that exists, and
        re-run the advisory area-marker checks (the banner) against the new
        geometry. The redraw is what makes the preview follow the area at all —
        it is a footprint of its own, so nothing about it moves with the
        marker. Guarded — the scan section and the banner are built after this
        one."""
        scan = getattr(self.page, "scan", None)
        if scan is not None:
            scan.refresh_preview()
        self.page.refresh_area_checks()

    def _placed_text(self, markers, d=None):
        """The placed area marker described: the decoded rectangle, where it
        sits, its layer and which edge the feed enters from, plus a note when
        it is bigger than the board and a cleanup nudge when there are extras.
        This section's answer to the feed marker's placed-marker
        line (the base's ``_placed_text``), so the status line and the base's
        already-placed reply describe this marker through one text.

        ``d`` is a decode the caller has already made; without it the marker is
        decoded here, which raises ValueError when its drawing no longer decodes
        — the base's reply catches that, and ``refresh_status`` reports it in
        its own words."""
        if d is None:
            d = area_marker.decode_marker(markers[0])
        (x0, y0, _x1, _y1) = d["area"]
        text = (
            f"Area {d['w_mm']:g} × {d['h_mm']:g} mm at ({x0:g}, {y0:g})"
            f" on {d['layer'] or 'the board'} — feed enters from the "
            f"{d['edge']} edge at {d['frac'] * 100:.1f} %."
        )
        oversize = self._oversize_note(d)
        if oversize:
            text += f" {oversize}"
        if len(markers) > 1:
            text += (
                f" {len(markers)} area markers found — delete the extras "
                "(Del), the scan needs exactly one."
            )
        return text

    def _oversize_note(self, d):
        """A word about an area dragged bigger than the board it has to fit on,
        or "" when it fits (or there is no Edge.Cuts outline to measure against
        — the pre-flight has its own say about a board with no outline).

        Said, not enforced: the drag is the user's, and a marker that is
        momentarily too big while the other corner is still to be moved is not
        an error. The rectangle is compared to the outline's span both ways
        round, since a marker turned on its side (R) fits what its unturned
        self would not."""
        span = board_edge_span_mm()
        if span is None:
            return ""
        sx, sy = span
        w, h = d["w_mm"], d["h_mm"]
        if (w <= sx and h <= sy) or (w <= sy and h <= sx):
            return ""
        return (
            f"Bigger than the board outline ({sx:g} × {sy:g} mm) — the antenna "
            "has to fit on the board."
        )

    def spec(self):
        """The scan's feed inputs: the placed marker's ``area``/``edge``/
        ``frac`` (in the marker's derotated frame) with its off-grid
        ``rot_deg``/``pivot``, plus the fixed feed ``gap_mm`` (FEED_GAP_MM).
        Raises with guidance when the marker is missing, duplicated or
        broken."""
        markers = self._markers()
        if not markers:
            raise RuntimeError(
                "place the area marker first (section 1) — it marks where "
                "the antenna may go and where the feed enters"
            )
        if len(markers) > 1:
            raise RuntimeError("multiple area markers on the board; keep exactly one")
        d = area_marker.decode_marker(markers[0])
        return {
            "area": d["area"],
            "edge": d["edge"],
            "frac": d["frac"],
            "rot_deg": d["rot_deg"],
            "pivot": d["pivot"],
            "gap_mm": self.gap_mm(),
        }
