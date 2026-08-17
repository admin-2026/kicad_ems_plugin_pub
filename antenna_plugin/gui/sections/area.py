"""Section 1 of the wizard: the antenna area + feed position, marked by a
footprint.

The area lives on the board as the area-marker footprint (area_marker.py) —
a rectangle outline with a feed arrow on its bottom edge (a triangle pointing
inward plus a short outward stem, with a dot on the feed point where the two
meet), the same idea as the feed marker. "Place
area marker" adds it at the board center through the pcbnew API — not the feed
marker's clipboard/paste-to-cursor flow: when KiCad's clipboard parser rejects
the footprint text it falls back to pasting it as a (slow) text string, and
unlike the feed marker the drop point doesn't matter, since the user
repositions it anyway. The sliders here reshape the placed marker live —
width, height, the feed position along its edge, and the feed triangle's
(visual-only) width — by rewriting its segments in place; the Area width,
height and feed-position readouts also accept a typed value, for a precise
size and feed location. Resizing the area leaves the feed point itself where it
is drawn — the feed is usually lined up with something on the board, and the
size is tuned around it, not the other way round. Each side holds it its own
way: the width slider re-aims the feed-position slider to the new edge
(``_hold_feed_point``), while the height slider, which moves the feed edge
itself, slides the whole marker back instead (``area_marker.update_marker``'s
``hold_feed``) so the area deepens away from the feed. The two
side sliders stop at the board itself: with an
Edge.Cuts outline drawn, width ends at the outline's span in x and height at
its span in y (``_apply_side_range``, re-measured on every refresh), since an
area larger than the board can't be placed on it; a board with no outline yet
keeps the default SIDE_RANGE. The Feed-width slider and Feed-layer picker
mirror the feed marker's (the base's ``build_feed_width`` /
``build_feed_layer``), their
values shared across both pages through the FormModel; so is the User layer
this marker is drawn on, picked in the wizard's own Advanced pane
(``build_layer_picker``, the same widget the simulate view builds) — one
Marker-layer pick for both markers, wherever it is changed. Moving and rotating
the marker (any angle — an off-grid rotation is handled by rotating the
whole board in the simulation) is done in the editor with KiCad's own tools
(M / R). The scan consumes the
decoded rectangle + feed edge + position through spec(); the feed gap that
sizes the ground stub is fixed at the runner's default (FEED_GAP_MM), not a
slider. Placing a marker starts the design over: the scan section's persisted
rows are tuned to whatever area was there before, so they go back to the
design's seeds and out of the settings file (``_forget_scan_params``).

It is the same idea as the feed marker — a footprint on a User layer, reshaped
live by sliders — so it subclasses FeedMarkerSection, reusing the placed-marker
lookup (``_markers``, keyed to area_marker here), the Feed-width / Feed-layer
builders, the button's two labels (``_sync_button``: Place with no marker on
the board, Show with one), the reply Place gives when a marker is already on
the board (``_show_already_placed`` — it takes the PCB editor to that marker
and leads with where it is) and the wrapped status line (``_set_status``); only
the rest of the UI and the reshape/decode differ — this section's
``_placed_text`` describes its own marker, and the shared reply is written from
it.
"""

import pcbnew
import wx

from ...markers import area_marker, feed_marker
from ..board import board_edge_span_mm
from ..theme import PAD, ROW
from ..widgets import UnitSlider, set_tip
from .marker import GAP_DEFAULT, MARKER_LAYERS, FeedMarkerSection

# Rectangle-side slider range in tenths of a mm (wx sliders are integer).
SIDE_RANGE = (20, 2000)  # rectangle sides: 2 .. 200 mm
# Feed position along the edge, in tenths of a percent (wx sliders are
# integer): a typed value places the feed to 0.1 % of the edge — well under a
# grid cell on any sane area — rather than the whole percent a 0..100 slider
# could express.
POS_RANGE = (0, 1000)  # 0 .. 100 %
POS_DEFAULT = 300  # feed at 30 % leaves the bend more room

# ... but no wider than the board: with an Edge.Cuts outline drawn, the width
# slider stops at the outline's span in x and the height slider at its span in
# y (_apply_side_range), since an area bigger than the board it sits on can
# never be placed. Boards are re-measured on every refresh -- the outline can
# be drawn or resized while the wizard is open -- and a board with no outline
# yet leaves the full SIDE_RANGE, with these tooltips saying which of the two
# limits a slider is wearing.
_TIP_CAPPED = (
    "At most {mm:g} mm — the board outline's span in {axis} (Edge.Cuts). "
    "Draw a bigger outline for a bigger area."
)
_TIP_UNCAPPED = (
    "No Edge.Cuts outline on the board to limit the area — the full "
    f"{SIDE_RANGE[0] / 10:g} … {SIDE_RANGE[1] / 10:g} mm range is offered."
)

# The feed gap the scan sizes its ground stub from is fixed at the runner's
# default (GAP_DEFAULT, hundredths of a mm) rather than exposed as a slider —
# the runner severs its own gap on the simulation grid regardless, and the
# width of that gap is an output of the meshing, so there is nothing here to
# ask for.
FEED_GAP_MM = GAP_DEFAULT / 100.0


def _side_cap(span_mm):
    """A board span (mm) as a side slider's maximum position (tenths of a mm):
    rounded *down*, so the area never exceeds the outline it was measured
    from, and held between SIDE_RANGE's own ends -- a board smaller than the
    range's floor would otherwise invert it, and one larger than its ceiling
    caps nothing."""
    lo, hi = SIDE_RANGE
    return min(max(int(span_mm * 10), lo), hi)


class AreaSection(FeedMarkerSection):
    marker_module = area_marker  # _markers() looks up area markers
    _TITLE = "Antenna area and feed"
    # The button's two labels and what to do with the marker already on the
    # board when it is pressed with one there (the base's _sync_button /
    # _show_already_placed, which takes the editor to it and leads with where
    # it is). This marker is reshaped, moved and rotated where the feed marker
    # is only resized.
    _BTN_PLACE = "Place area marker"
    _BTN_SHOW = "Show placed area marker"
    _SHOW_TIP = (
        "An area marker is already on the board — this takes the PCB editor to "
        "it. The sliders reshape it; delete it (Del) to place a new one."
    )
    _ALREADY_HINT = (
        "the sliders reshape it, move (M) / rotate (R) it in the editor, or "
        "delete it (Del) and Place again."
    )

    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)

        grid = wx.FlexGridSizer(3, ROW, PAD)
        one_dp = "{:.1f}".format  # bare number; the unit rides alongside
        w0, h0 = self._starter_size()
        # width/height are tenths of a mm, the feed position tenths of a
        # percent of its edge. All three are editable: type a precise value
        # into the box, with the unit in a label beside it. Each reshapes the
        # placed marker live -- naming the one knob it drives, so a slider
        # that is out of step with the board (_reshape_args) doesn't ride
        # along with it.
        self.w = UnitSlider(
            grid,
            p,
            "Area width",
            SIDE_RANGE,
            w0,
            10,
            self._on_width,
            fmt=one_dp,
            editable=True,
            suffix="mm",
        )
        self.h = UnitSlider(
            grid,
            p,
            "Area height (depth)",
            SIDE_RANGE,
            h0,
            10,
            lambda: self._on_slider("h"),
            fmt=one_dp,
            editable=True,
            suffix="mm",
        )
        self.pos = UnitSlider(
            grid,
            p,
            "Feed position along its edge",
            POS_RANGE,
            POS_DEFAULT,
            10,
            lambda: self._on_slider("frac"),
            fmt=one_dp,
            editable=True,
            suffix="%",
        )
        # The Feed-width slider and Feed-layer picker mirror the feed marker's
        # (shared across both pages through the FormModel); the width also
        # drives this marker's feed triangle, so it live-reshapes like the area
        # sliders (build_feed_width / build_feed_layer live on the base).
        self.build_feed_width(p, grid, lambda: self._on_slider("tri"))
        # The two side sliders end at the board outline, not at SIDE_RANGE,
        # whenever the board has one -- which also clamps the starter size.
        self._apply_side_range()
        box.Add(grid, 0)

        layer_grid = wx.FlexGridSizer(2, ROW, PAD)
        self.build_feed_layer(p, layer_grid)
        box.Add(layer_grid, 0, wx.EXPAND | wx.TOP, ROW)

        # The button comes after the settings it places the marker with, as the
        # feed marker's does (sections.marker._build_controls): the shape is
        # dialled in above, then the button that puts it on the board, then the
        # status line reporting what landed. It carries the same two labels as
        # the feed marker's (_sync_button): Place with none on the board, Show
        # with one on it.
        self.marker_btn = wx.Button(p, label=self._BTN_PLACE)
        self.marker_btn.Bind(wx.EVT_BUTTON, self.on_place)
        box.Add(self.marker_btn, 0, wx.TOP, PAD)

        self._status_label = self.wrap_label(p, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)

    # --- values ---------------------------------------------------------------
    def w_mm(self):
        return self.w.value()

    def h_mm(self):
        return self.h.value()

    def frac(self):
        return self.pos.value() / 100.0

    def gap_mm(self):
        return FEED_GAP_MM  # fixed; the runner cuts its own gap

    def tri_w_mm(self):
        """The feed triangle's (visual-only) width: this section's own
        Feed-width slider (``width_mm``, from the base), whose value is shared
        with the feed marker across both pages."""
        return self.width_mm()

    def _starter_size(self):
        """Starter rectangle in slider units: the page's design says how much
        room its antennas want at the main dialog's frequency
        (``design.area_hint_mm`` -- an L-monopole lies down over a quarter
        wave, an inverted-F folds into a fraction of one)."""
        freq = self.page.host.target_freq_ghz(2.45)
        w_mm, h_mm = self.page.design.area_hint_mm(max(freq, 0.1))

        def clamp(v):
            return min(max(int(round(v * 10)), SIDE_RANGE[0]), SIDE_RANGE[1])

        return clamp(w_mm), clamp(h_mm)

    def _apply_side_range(self):
        """Cap the Area width / height sliders at the board's own outline: the
        widest sensible area is the board's span in x, the deepest its span in
        y (a rectangle bigger than the board can't be placed on it). With no
        Edge.Cuts outline drawn -- or no board -- there is nothing to measure
        against and the sliders keep their default SIDE_RANGE.

        Run at build time and on every refresh, since the outline can be drawn
        or resized while the wizard is open. A cap that drops below the current
        slider value moves the *slider* only; the placed marker is left alone
        (the plugin doesn't resize the user's marker behind their back, and
        ``refresh``'s decode is what puts the two back in step)."""
        span = board_edge_span_mm() or (None, None)
        for sl, extent, axis in zip((self.w, self.h), span, "xy"):
            if extent is None:
                sl.set_range(SIDE_RANGE)
                set_tip(sl.slider, _TIP_UNCAPPED)
            else:
                cap = _side_cap(extent)
                sl.set_range((SIDE_RANGE[0], cap))
                set_tip(sl.slider, _TIP_CAPPED.format(mm=cap / 10, axis=axis))

    def feed_sync_labels(self):
        """Every slider readout of this box -- the area sliders as well as the
        inherited feed width -- back in step with its slider, reshaping
        nothing. Overrides the base's (which knows only the feed width) so a
        restore of the shared form refreshes the whole box."""
        for sl in (self.w, self.h, self.pos, self.marker_width):
            sl.sync_label()

    # --- events ---------------------------------------------------------------
    def _on_width(self):
        """The Area-width slider moved. The rectangle is centred on the
        marker's own origin, so both side edges move and a feed held at a fixed
        *fraction* of the edge would slide across the board with every nudge of
        this slider — off whatever the user lined the feed up with. So the
        feed-position slider is re-aimed first (_hold_feed_point), leaving the
        feed where it is drawn and the area growing (or shrinking) around it;
        then the marker is reshaped as any other slider does it — driving the
        feed position as well as the width, since the re-aimed fraction is this
        slider's own doing."""
        self._hold_feed_point()
        self._on_slider("w", "frac")

    def _hold_feed_point(self):
        """Re-aim the feed-position slider so the feed point stays where it is
        on the board under the width the width slider now holds: the feed's
        offset from the marker's centre is read off the placed marker — which
        still carries the *previous* width at this point, the reshape comes
        after — and turned back into a fraction of the new edge.

        The marker is asked rather than a remembered slider value because it is
        what the user sees: whatever they moved, rotated or typed their way to
        is the position being held. A feed the new width can no longer reach
        clamps to the slider's own range (and the marker keeps the triangle
        clear of the corners regardless — area_marker._local_arrow). Silent
        when no marker is placed, or when its segments no longer decode: there
        is then nothing on the board to hold still, and the reshape that
        follows reports the breakage."""
        w_new = self.w_mm()
        fps = self._markers()
        if not fps or w_new <= 0:
            return
        try:
            d = area_marker.decode_marker(fps[0])
        except ValueError:
            return
        if d["frac_local"] is None:
            return  # an edited marker: the slider's own fraction is a guess
        offset_mm = (d["frac_local"] - 0.5) * d["w_mm"]  # feed, off the centre
        self.pos.set_value((0.5 + offset_mm / w_new) * 100)  # no EVT_SLIDER

    def _on_slider(self, *knobs):
        """A slider moved, naming the ``knobs`` (_reshape_args) it drives:
        reshape the placed marker live and re-describe it, syncing the sliders
        it did *not* drive back to what is on the board. A reshape that failed
        keeps its own message on the status line."""
        self.feed_sync_labels()
        if self._apply_live(*knobs):
            self.refresh_status(sync=True, driven=knobs)

    def _apply_live(self, *knobs):
        """Reshape the placed area marker in place (its segments are rewritten,
        so position, rotation and the editor's undo pointers hold) to the
        current Area-marker-layer pick and to _reshape_args: the sliders named
        in ``knobs``, and the marker's own drawn geometry for everything else.
        Overrides the feed section's, which draws the other marker; both are
        called by the sliders and by the Advanced pane's layer picker — which
        names no knob at all, so it moves the marker's layer and nothing else.
        With no marker placed there is nothing to reshape — the caller still
        refreshes the status line, which then names the layer Place will use.
        Returns False when the reshape failed, its reason already on the status
        line."""
        fps = self._markers()
        if not fps:
            return True
        board = pcbnew.GetBoard()
        try:
            # None keeps every shape where it is: with no board there is no
            # layer id to check the pick against, and the reshape is the same.
            layer_id = (
                None
                if board is None
                else feed_marker.check_layer(board, self.marker_layer_n())
            )
            w_mm, h_mm, frac, tri_w_mm = self._reshape_args(fps[0], knobs)
            # The height slider moves the feed *edge*: the rectangle is drawn
            # about the marker's own origin, so a deeper area would push the
            # feed half the change across the board, off whatever it was lined
            # up with. Reshaping with hold_feed slides the marker instead,
            # leaving the feed point where it is drawn and growing the area away
            # from it -- the depth's answer to what _hold_feed_point does for
            # the width.
            area_marker.update_marker(
                fps[0], w_mm, h_mm, frac, tri_w_mm, layer_id, hold_feed="h" in knobs
            )
            pcbnew.Refresh()
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return False
        # The drawn candidate follows the marker: it lives on the marker's own
        # layer whenever it doesn't fit the area, so a layer move has to redraw
        # it there (scan._draw_preview picks the layer every time).
        self._follow_preview()
        return True

    def _reshape_args(self, fp, knobs):
        """What a live reshape writes: ``(w_mm, h_mm, frac, tri_w_mm)`` taken
        from this box's sliders for the ``knobs`` the user just moved ("w",
        "h", "frac", "tri") and from the marker *as drawn* for the rest.

        A reshape has to pass all four, but only one of them was asked for, and
        a slider that is out of step with the board would otherwise be applied
        along with it — the whole mismatch landing on the marker at the first
        touch of any slider. And they do go out of step: the Feed-width slider
        is shared with the simulate view's feed marker and restored from the
        settings file, so it arrives holding whatever that marker wants, and
        the side sliders can be held off the marker's size by the board-outline
        cap (_apply_side_range). Reading the untouched knobs back off the
        marker keeps a slider's reach to its own knob — the width slider
        changes the width, and the feed keeps the size and place it is drawn
        with. The sliders are then re-synced to the board (_on_slider), so what
        is left of a mismatch shows up in the readouts rather than in the
        copper.

        A marker whose segments don't decode has nothing to read back, and
        falls back to the sliders throughout (the reshape that follows names
        the breakage)."""
        vals = {
            "w": self.w_mm(),
            "h": self.h_mm(),
            "frac": self.frac(),
            "tri": self.tri_w_mm(),
        }
        drawn = self._drawn_shape(fp)
        for key, value in drawn.items():
            if key not in knobs:
                vals[key] = value
        return vals["w"], vals["h"], vals["frac"], vals["tri"]

    def _drawn_shape(self, fp):
        """The placed marker's own geometry in this box's terms — ``w``, ``h``,
        ``tri`` and (when it is recoverable) ``frac`` — or an empty dict when
        its segments no longer decode. ``frac`` is the *local* fraction, the
        one the feed-position slider means, so it survives however the marker
        was moved or rotated."""
        try:
            d = area_marker.decode_marker(fp)
        except ValueError:
            return {}
        shape = {"w": d["w_mm"], "h": d["h_mm"], "tri": d["tri_w_mm"]}
        if d["frac_local"] is not None:
            shape["frac"] = d["frac_local"]
        return shape

    def on_place(self, event=None):
        """Drop a new area marker just clear of the board outline (see
        area_marker._drop_beside_board — easy to spot rather than buried among
        existing copper on a dense board), and switch the editor to the
        marker's own layer (the base's ``_activate_layer``) so the user
        arrives there with it selected. With one already on the board this
        refuses and takes the editor to that marker instead, saying where it is
        and how big it is (``_show_already_placed``) — the sliders reshape it,
        and the plugin never removes a placed footprint itself. The button says
        as much before it is pressed (``_sync_button``); it is re-read here all
        the same, since the marker can be deleted in the editor while the
        wizard is open."""
        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            return
        fps = self._markers()
        if fps:
            self._show_already_placed(fps)
            return
        try:
            layer_n, layer_id = self._pick_layer(board)
            # The editor goes to the marker's layer as the marker itself does,
            # so the user arrives in the editor with it selected.
            self._activate_layer(board, layer_id)
            x, y = area_marker.place_marker(
                board, layer_n, self.w_mm(), self.h_mm(), self.frac(), self.tri_w_mm()
            )
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return
        self._forget_scan_params()
        self._placed_now(
            f"Area marker dropped beside the board ({x:g}, {y:g}) mm on "
            f"User.{layer_n} — move it (M) over the copper-free zone the "
            "antenna may use (at the board edge, next to the ground pour); "
            "rotate it (R) to feed from another side; the triangle is "
            "where the feed enters. The scan rows are back on their seeds."
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
        """Read the placed marker off the board: sync the sliders to it and
        describe the decoded area on the status line. Called at wizard startup
        (and on every page switch), to pick up a marker already on the
        board. The sliders' upper ends are re-measured off the board outline
        first -- this is where a board opened (or an outline drawn) after the
        wizard was built lands."""
        self._apply_side_range()
        self.refresh_status(sync=True)
        if self._markers():
            self._follow_preview()

    def refresh_status(self, sync=False, driven=()):
        """Describe the board's area marker on the status line: the decoded
        rectangle, or — with none placed — what Place will do and the layer it
        will use. Overrides the feed section's (whose text and decode are the
        other marker's); the Advanced pane's layer picker calls it, which is
        what makes a fresh pick visible before any marker exists. The button
        follows the same reading of the board (the base's ``_sync_button``).

        With ``sync`` the sliders are set from the decoded marker as well —
        what ``refresh`` wants, and what every reshape wants for the knobs it
        didn't drive, so a slider left out of step with the board comes back
        into step instead of waiting to be applied. ``driven`` names the knobs
        (_reshape_args) that were just dragged or typed into: those keep the
        value the user is entering, rather than having the decode's rounding
        written back under the caret."""
        fps = self._markers()
        self._sync_button(fps)
        if not fps:
            self._set_status(
                "No area marker on the board — Place puts one at the board "
                f"center on {MARKER_LAYERS[self.marker_layer_n() - 1]}: the "
                "rectangle marks the copper-free zone the antenna may use "
                "(near the ground pour's edge), the triangle marks the feed."
            )
            return
        self._show(fps, sync=sync, driven=driven)

    def _follow_preview(self):
        """The area changed (a slider here, or startup's refresh picking up
        an already-placed marker): the scan section's drawn antenna preview
        solves against it, so redraw one that exists, and re-run the advisory
        area-marker checks (the banner) against the new geometry. Guarded — the
        scan section and the banner are built after this one."""
        scan = getattr(self.page, "scan", None)
        if scan is not None:
            scan.refresh_preview()
        self.page.refresh_area_checks()

    def _placed_text(self, fps, d=None):
        """The placed area marker described: the decoded rectangle, where it
        sits, its layer and which edge the feed enters from, plus a cleanup
        nudge when there are extras. This section's answer to the feed
        marker's placed-marker line (the base's ``_placed_text``), so the
        status line and the base's already-placed reply describe this marker
        through one text.

        ``d`` is a decode the caller has already made (``_show`` syncs its
        sliders from one); without it the marker is decoded here, which raises
        ValueError when its drawing no longer decodes — the base's reply
        catches that, and ``_show`` reports it in its own words."""
        if d is None:
            d = area_marker.decode_marker(fps[0])
        (x0, y0, _x1, _y1) = d["area"]
        text = (
            f"Area {d['w_mm']:g} × {d['h_mm']:g} mm at ({x0:g}, {y0:g})"
            f" on {d['layer'] or 'the board'} — feed enters from the "
            f"{d['edge']} edge at {d['frac'] * 100:.1f} %."
        )
        if len(fps) > 1:
            text += (
                f" {len(fps)} area markers found — delete the extras "
                "(Del), the scan needs exactly one."
            )
        return text

    def _show(self, fps, sync, driven=()):
        try:
            d = area_marker.decode_marker(fps[0])
        except ValueError as exc:
            self._set_status(f"✗ {exc}")
            return
        if sync:
            # set_value: no EVT_SLIDER. The knob the user is working stays as
            # they left it (``driven``); the rest take the marker's shape.
            # The Feed-width slider is deliberately not among them: it is the
            # feed *marker's* width, shared across both pages, and the area
            # marker's triangle only follows it when the user moves it.
            if "w" not in driven:
                self.w.set_value(d["w_mm"])
            if "h" not in driven:
                self.h.set_value(d["h_mm"])
            if "frac" not in driven and d["frac_local"] is not None:
                self.pos.set_value(d["frac_local"] * 100)
        self._set_status(self._placed_text(fps, d))

    def spec(self):
        """The scan's feed inputs: the placed marker's ``area``/``edge``/
        ``frac`` (in the marker's derotated frame) with its off-grid
        ``rot_deg``/``pivot``, plus the fixed feed ``gap_mm`` (FEED_GAP_MM).
        Raises with guidance when the marker is missing, duplicated or
        broken."""
        fps = self._markers()
        if not fps:
            raise RuntimeError(
                "place the area marker first (section 1) — it marks where "
                "the antenna may go and where the feed enters"
            )
        if len(fps) > 1:
            raise RuntimeError("multiple area markers on the board; keep exactly one")
        d = area_marker.decode_marker(fps[0])
        return {
            "area": d["area"],
            "edge": d["edge"],
            "frac": d["frac"],
            "rot_deg": d["rot_deg"],
            "pivot": d["pivot"],
            "gap_mm": self.gap_mm(),
        }
