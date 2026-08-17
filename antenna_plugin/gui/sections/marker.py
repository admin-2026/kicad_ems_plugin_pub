"""The Feed marker section of the simulate view (pages.simulate.SimulatePage).

FeedMarkerSection owns the marker generator UI (the always-visible Feed marker
box): the feed-width slider, the Feed layer picker, the marker button with a
picture of the marker it places beside it (ICON_FILE) and the marker status
line under it, and the marker layer picker (built
into the Advanced pane — only User.1..User.9 are offered). Generate puts the
antenna_plugin.feed_marker footprint on the cursor for the user to click onto
the feed line (clipboard + simulated paste — see on_place_marker), falling back
to dropping it at the board center, and hands the editor the marker's own layer
as it goes (``_activate_layer``, shared with the area marker); moving the slider
(or the layer pick) rewrites the placed marker's segments and feed-point dot in
place, live, no button press needed.
The status line — not the run log — carries the marker messages: the target
layer before a marker exists, the placement prompt after Generate, the placed
marker's location and layer once it lands (a short poll watches for that), and
that same location again when the button is pressed with a marker already
there, which it refuses to replace.

A placed marker is never replaced, so the button says so before it is pressed:
with one on the board it reads "Show placed feed marker" (``_sync_button``,
driven from the same board reading as the status line), and pressing it takes
the PCB editor to that marker — its layer made active, the canvas scrolled to
it and the editor window raised (``_show_already_placed`` over ``_reveal``, and
gui.reveal). Words in the plugin window are easy to miss while the user is
looking at their board; a canvas that jumps to the marker is not.

This section also holds what the two footprint-marker sections share: the
placed-marker lookup (``_markers``, keyed off the ``marker_module`` class
attribute), the Feed-width slider and Feed-layer picker builders
(``build_feed_width`` / ``build_feed_layer``), the marker-picture builder
(``build_marker_icon``), the button's two labels (``_sync_button``), the
already-placed reply and the jump to the board behind it
(``_show_already_placed`` / ``_reveal``), the marker-layer picker its page's
Advanced pane builds
(``build_layer_picker``), and the wrapped status line (from the common Section
base). All three picks are one value across the
window: each page builds its own widgets, but they are views onto the shared
FormModel (``snapshot`` / ``restore``), so the feed marker and the area marker
are drawn on the same User layer — one Marker-layer pick under one saved key
(LAYER_KEY), wherever the user changes it. The area marker
(sections.area.AreaSection) is the same idea — a footprint on a User layer,
reshaped live by sliders — so it subclasses this section and reuses those
helpers, its own ``_build`` replacing the feed-specific UI and its own
``_apply_live`` / ``refresh_status`` reshaping and describing its own marker.
"""

import wx

from ...markers import feed_marker
from .. import icons
from ..theme import PAD, ROW
from ..widgets import FIELD_W, UnitSlider, set_choice, set_slider, set_tip
from .base import Section

# Slider ranges in hundredths of a mm (wx sliders are integer-valued).
# GAP_DEFAULT stays here as the fixed feed gap the wizard's scan sizes its
# ground stub from (area.FEED_GAP_MM imports it); neither marker draws a gap.
GAP_DEFAULT = 50  # 0.50 mm, about the one cell the runner's own gap comes to
WIDTH_RANGE = (10, 500)  # 0.10 .. 5.00 mm
WIDTH_DEFAULT = 100  # 1.00 mm

MARKER_LAYERS = [f"User.{n}" for n in range(1, 10)]
MARKER_LAYER_DEFAULT = 1  # 0-based index into MARKER_LAYERS -> User.2

# The Advanced pane's marker-layer picker: its label, and the key its pick is
# saved (and shared between the pages) under. One of each, not one per marker:
# the feed marker and the area marker go on the same User layer, so whichever
# page's picker the user reaches for moves both.
LAYER_LABEL = "Marker layer"
LAYER_KEY = "marker_layer"

# The picture beside the Generate button: the marker as it is drawn -- triangle
# head, stem, and the dot on the feed point, on transparency (the feed track it
# is placed across is the user's copper, not part of what the button makes, so
# it is not in the drawing -- tools/icons/markers.py). It stands there so that
# pressing the button is a known quantity: the flow that follows hands the
# footprint to KiCad's paste tool and asks the user to click it onto their
# board, which is a poor moment to be finding out what the thing looks like.
# 64 px is a small drawing rather than a glyph; the bundled PNG is 128, so a
# HiDPI display has one to scale from.
ICON_FILE = "marker_feed.png"
ICON_SIZE = 64
ICON_TIP = (
    "What Generate places: an arrow whose base is the feed width, sitting "
    "across the feed line with the triangle pointing toward the antenna and "
    "the dot on the feed point itself."
)


class FeedMarkerSection(Section):
    # The board footprint this section places/decodes; AreaSection overrides it.
    marker_module = feed_marker
    _TITLE = "Feed marker"
    # The button's two labels: what it does with no marker on the board, and
    # what it does with one (_sync_button swaps them). A marker already placed
    # is never replaced, so the button stops offering to place one and offers
    # the thing the user actually wants at that point -- to be shown the marker
    # they have (_show_already_placed).
    _BTN_PLACE = "Generate feed marker"
    _BTN_SHOW = "Show placed feed marker"
    _SHOW_TIP = (
        "A feed marker is already on the board — this takes the PCB editor to "
        "it. The sliders resize it; delete it (Del) to place a new one."
    )
    # What to do with that marker, once the reply has said where it is.
    # AreaSection overrides it: its marker is reshaped, moved and rotated where
    # this one is resized.
    _ALREADY_HINT = (
        "the sliders resize it, or delete it (Del) to re-place it from the "
        "cursor."
    )

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self._build(body)

    def _build(self, body):
        """The always-visible Feed marker section: the feed-width slider and the
        generate button. The feed comes only from the placed marker (or a
        hand-drawn User-layer circle) -- there are no manual override fields."""
        scroll = self.scroll
        box = self.box(self._TITLE)
        self._build_controls(scroll, box)
        self.add_to_body(body, box)

    def _build_controls(self, pane, sizer):
        """The marker generator: the feed-width slider, the Feed layer picker,
        the Generate button and the status line under it. The Marker layer
        picker lives in the Advanced pane (see build_layer_picker). ``pane`` is
        the parent window, ``sizer`` the box to fill."""
        grid = wx.FlexGridSizer(3, ROW, PAD)
        self.build_feed_width(pane, grid, lambda: self.slider_changed(live=True))

        # Feed layer picker (the marker-layer picker is in the Advanced pane).
        layer_grid = wx.FlexGridSizer(2, ROW, PAD)
        self.build_feed_layer(pane, layer_grid)

        # The picture of the marker, then the button that places it: what you
        # get, then how to get it.
        row = wx.BoxSizer(wx.HORIZONTAL)
        icon = self.build_marker_icon(pane, ICON_FILE, ICON_TIP)
        if icon is not None:
            row.Add(icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, PAD)
        self.marker_btn = wx.Button(pane, label=self._BTN_PLACE)
        self.marker_btn.Bind(wx.EVT_BUTTON, self.on_place_marker)
        row.Add(self.marker_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        # The marker's own status line, under the buttons (marker messages
        # live here, not in the run log): the target layer before a marker
        # exists, the placement prompt after Generate, and the placed
        # marker's location + layer once it lands.
        self._status_label = self.wrap_label(pane, mute=True)

        sizer.Add(grid, 0)
        sizer.Add(layer_grid, 0, wx.EXPAND | wx.TOP, ROW)
        sizer.Add(row, 0, wx.TOP, PAD)
        sizer.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)

    def build_layer_picker(self, pane, grid):
        """Add the Marker-layer picker (a label + choice) to ``grid`` in the
        Advanced pane, defaulting to User.2. Only User.1..User.9 are offered:
        a marker is a board_only footprint on a User layer. Seed the marker
        status line once it exists (the marker box is built first, so it
        deferred that). Both marker sections build one -- the same pick behind
        both widgets, shared through the FormModel like the feed picks, so the
        feed marker and the area marker land on one layer."""
        grid.Add(wx.StaticText(pane, label=LAYER_LABEL), 0, wx.ALIGN_CENTER_VERTICAL)
        self.marker_layer = wx.Choice(pane, size=(FIELD_W, -1), choices=MARKER_LAYERS)
        self.marker_layer.SetSelection(MARKER_LAYER_DEFAULT)
        self.marker_layer.Bind(wx.EVT_CHOICE, lambda event: self._layer_changed())
        grid.Add(self.marker_layer, 0)
        self.refresh_status()  # seed: layer / already-placed marker

    def _refresh_feed_layer_choices(self):
        """Populate the feed layer dropdown from the board's copper layers."""
        from ..board import board_layer_names

        copper_names, _ = board_layer_names()
        if hasattr(self, "feed_layer"):
            current = self.feed_layer.GetStringSelection() or ""
            self.feed_layer.Clear()
            for name in copper_names:
                self.feed_layer.Append(name)
            if current and current in copper_names:
                self.feed_layer.SetStringSelection(current)
            elif len(copper_names) > 0:
                self.feed_layer.SetSelection(0)

    # --- shared marker helpers (also used by AreaSection) ---------------------
    def build_feed_width(self, pane, grid, on_change):
        """Add the Feed-width slider to ``grid`` (three cells) as
        ``self.marker_width``: the feed marker's drawn width, and the area
        marker's feed-triangle width. Both marker sections build it, and its
        value is shared across the two pages through the FormModel;
        ``on_change`` live-reshapes the owning section's placed marker."""
        self.marker_width = UnitSlider(
            grid,
            pane,
            "Feed width",
            WIDTH_RANGE,
            WIDTH_DEFAULT,
            100,
            on_change,
            fmt="{:.2f} mm".format,
            value_w=64,
        )

    def build_marker_icon(self, pane, file_name, tip, size=ICON_SIZE):
        """A picture of the marker this section's button places, as a
        StaticBitmap on ``pane`` (``file_name`` is a drawing of the bundled
        ``assets/icons/`` set, tools/icons/markers.py). Both marker sections
        can wear one beside their button -- the drawings differ, so the file
        name and the tooltip describing it come from the caller.

        Returns None when the drawing isn't bundled, which is the caller's cue
        to lay out the button without it: an installation missing a PNG still
        places markers, and the loader answering None rather than letting wx
        raise is what keeps that true (gui.icons.bitmap)."""
        bitmap = icons.illustration(file_name, size)
        if bitmap is None:
            return None
        picture = wx.StaticBitmap(pane, bitmap=bitmap)
        set_tip(picture, tip)
        return picture

    def build_feed_layer(self, pane, grid):
        """Add the Feed-layer picker (a label + copper-layer choice) to
        ``grid`` (two cells) as ``self.feed_layer``, defaulting to the top
        copper. Both marker sections build it; the pick is shared across the
        two pages through the FormModel."""
        grid.Add(wx.StaticText(pane, label="Feed layer"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.feed_layer = wx.Choice(pane, size=(FIELD_W, -1))
        self._refresh_feed_layer_choices()
        self.feed_layer.SetSelection(0)  # top copper by default
        grid.Add(self.feed_layer, 0)

    def _markers(self):
        """The placed marker footprints of this section's ``marker_module``
        (empty with no board)."""
        import pcbnew

        board = pcbnew.GetBoard()
        return self.marker_module.marker_footprints(board) if board is not None else []

    def _activate_layer(self, board, layer_id):
        """Put the PCB editor on ``layer_id`` -- the layer the marker this
        section is about to place is drawn on, so the user lands in the editor
        with the marker's layer selected (and, with high-contrast display on,
        the marker in full colour). Best effort, and never in the way of the
        placement: a KiCad that won't take the switch leaves the active layer
        alone (gui.activelayer)."""
        from ..activelayer import set_active_layer

        return set_active_layer(self.page, board, layer_id)

    # --- values ---------------------------------------------------------------
    def feed_layer_name(self):
        """The Feed layer pick (copper layer suffix); '' when the picker has no
        selection -- callers apply their own fallback."""
        return self.feed_layer.GetStringSelection()

    def marker_layer_n(self):
        """The Marker-layer pick as 1-based User.N -- where this section places
        its marker, and (the pick being shared) where the other one places its
        own. A selection-less picker (wx.NOT_FOUND) falls back to User.1
        instead of a bogus User.0."""
        return max(self.marker_layer.GetSelection(), 0) + 1

    def width_mm(self):
        return self.marker_width.value()

    # --- shared / persisted state ---------------------------------------------
    # Every pick this section owns -- the feed width, the Feed layer and the
    # Marker layer -- is one value for the whole window: both marker sections
    # build their own controls, and snapshot / restore are the seam the pages
    # sync through (the shared FormModel, gui.model) and the settings file is
    # written from (gui.settings). So the two markers share a User layer:
    # whichever Advanced pane the user picks it in, the other page's picker
    # follows on the next page switch. The Marker-layer picker is built into
    # that pane (build_layer_picker) *after* this section, hence the guards on
    # its existing yet.
    def snapshot(self):
        """This section's picks -- feed width, Feed layer, Marker layer -- as a
        flat string dict, the keys both marker sections contribute to the shared
        form. The Marker layer drops out until its picker is built."""
        data = {
            "marker_width": str(self.marker_width.slider.GetValue()),
            "feed_layer": self.feed_layer.GetStringSelection(),
        }
        if hasattr(self, "marker_layer"):
            data[LAYER_KEY] = self.marker_layer.GetStringSelection()
        return data

    def restore(self, data):
        """Set those picks from a ``snapshot`` dict (a key that isn't there
        leaves its control alone, so a settings file written before a pick
        existed just keeps the default); the caller re-derives the live marker
        shape afterwards. Nothing on the board is reshaped here -- the placed
        marker follows the restored layer the next time a slider or the picker
        moves it (_apply_live)."""
        set_slider(self.marker_width.slider, data.get("marker_width"))
        if "feed_layer" in data:
            self.feed_layer.SetStringSelection(data["feed_layer"])
        if hasattr(self, "marker_layer"):
            set_choice(self.marker_layer, data.get(LAYER_KEY))

    def feed_sync_labels(self):
        """Bring this section's slider readouts back in step with sliders that
        were just set from elsewhere (a model or settings restore) -- labels
        only, leaving the placed marker as it is. The seam every page runs at
        the end of a restore (pages.designform.DesignFormPage.rederive_form);
        the area section syncs its own sliders too."""
        self.slider_changed(layout=False)

    def slider_changed(self, layout=True, live=False):
        self.marker_width.sync_label()
        if live:
            self._apply_live()
        if layout:
            self.scroll.Layout()

    def _layer_changed(self):
        """The marker-layer pick changed: move a placed marker to the new
        layer live, or — with none placed — just show the new target layer. A
        move that failed keeps its own message (it named the layer that
        refused), so the status line is only re-derived when it worked."""
        if self._apply_live():
            self.refresh_status()

    def _apply_live(self):
        """Reshape the placed feed marker to the slider's width and the
        current layer pick, in place — the live counterpart to the area
        marker's slider reshape, so no button press is needed. With no marker
        yet there is nothing to do (Generate makes one). Segments are
        rewritten in place, never removed and re-added, so the marker's
        position, rotation and the editor's undo pointers hold. Returns False
        when it failed, having put the reason on the status line; the area
        section overrides it with its own marker's reshape."""
        import pcbnew

        board = pcbnew.GetBoard()
        if board is None:
            return True
        try:
            layer_id = feed_marker.check_layer(board, self.marker_layer_n())
            existing = feed_marker.marker_footprints(board)
            if not existing:
                return True
            feed_marker.update_marker(existing[0], layer_id, self.width_mm())
            pcbnew.Refresh()
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return False
        self._set_status(self._placed_text(existing))
        return True

    # --- status line ------------------------------------------------------------
    def refresh_status(self):
        """Reflect the board's current state: the placed marker's location
        and layer, or — before one exists — the layer Generate will use. The
        button follows the same reading (_sync_button)."""
        fps = self._markers()
        self._sync_button(fps)
        if fps:
            self._set_status(self._placed_text(fps))
        else:
            layer = MARKER_LAYERS[self.marker_layer_n() - 1]
            self._set_status(
                f"No feed marker on the board — Generate puts one on the "
                f"cursor ({layer})."
            )

    def _placed_text(self, fps):
        """The placed-marker status: location, layer and drawn gap/width of
        the first marker, plus a cleanup nudge when there are extras."""
        d = feed_marker.describe_marker(fps[0])
        text = (
            f"Feed marker on {d['layer'] or 'the board'} at "
            f"({d['x_mm']:g}, {d['y_mm']:g}) mm"
        )
        if d["width_mm"] is not None:
            text += f" — width {d['width_mm']:.2f} mm"
        if len(fps) > 1:
            text += (
                f"; {len(fps)} markers found — delete the extras (Del), "
                "the run needs exactly one"
            )
        return text + "."

    def _sync_button(self, fps):
        """Point the section's button at what it can actually do: with no
        marker on the board it places one, with one on the board it shows that
        one (_BTN_PLACE / _BTN_SHOW, and the explanation in its tooltip).

        The label is a signpost, never a gate: both handlers re-read the board
        when pressed, so a label left stale by a marker deleted in the editor
        still does the right thing on the press that follows -- and puts itself
        right. Every path that re-derives the status line comes through here
        (refresh_status), which is also where a page's focus refresh lands."""
        placed = bool(fps)
        self.marker_btn.SetLabel(self._BTN_SHOW if placed else self._BTN_PLACE)
        set_tip(self.marker_btn, self._SHOW_TIP if placed else "")

    def _placed_now(self, text):
        """Report a marker this section has just put on the board: ``text`` on
        the status line, and the button pointed at the marker that now exists
        (_sync_button). The paths that drop a marker through the API land here
        -- the feed marker's two fallbacks and the area marker's ordinary
        Place -- since each carries its own instructions and so doesn't go
        through refresh_status. The clipboard path has no marker yet when it
        returns; its watcher refreshes once the paste lands (_watch)."""
        self._sync_button(self._markers())
        self._set_status(text)

    def _reveal(self, fp):
        """Take the PCB editor to a placed marker: its own layer made active
        (_activate_layer, so it draws in full colour), the canvas scrolled to
        it and brightened, and the editor window raised (gui.reveal). True when
        the editor went there.

        This is the answer to "where is it?" that a line of text can't give: a
        marker can sit well outside the visible area, and the user is looking
        at the canvas rather than at the plugin. Best effort throughout, this
        method included: the reply it decorates says the same thing in words,
        so nothing here is ever allowed to turn a refusal into an error."""
        import pcbnew

        from ..reveal import reveal_item

        try:
            board = pcbnew.GetBoard()
            layer_id = feed_marker.marker_layer_id(fp)
            if board is not None and layer_id is not None:
                self._activate_layer(board, layer_id)
            return reveal_item(self.page, fp)
        except Exception:
            return False

    def _show_already_placed(self, fps):
        """Answer a Generate/Place press that can't place anything by taking
        the user to the marker that is already there (_reveal) and saying on
        the status line *where* that is, then what to do with it instead of a
        second one.

        Both marker sections refuse to place a second marker -- the plugin
        never removes a placed footprint itself (see on_place_marker) -- and
        the one on the board may well be off screen, or somewhere the user has
        forgotten, so a refusal that only said no left them hunting for it.
        Only the advice differs between the two markers (_ALREADY_HINT); the
        location leads either way, and the lead-in says whether the editor was
        moved or the words are all there is. A marker whose drawing no longer
        decodes (the area marker's ``_placed_text`` reads its geometry back)
        reports that instead -- it is the same "why can't I place one"
        question."""
        self._sync_button(fps)  # a label the board had moved on from
        shown = self._reveal(fps[0])
        try:
            placed = self._placed_text(fps)
        except ValueError as exc:
            placed = f"✗ {exc}"
        lead = "Shown in the PCB editor" if shown else "Already on the board"
        self._set_status(f"{placed} {lead}: {self._ALREADY_HINT}")

    # --- generate -------------------------------------------------------------
    def on_place_marker(self, event=None):
        """Place a new marker: it goes to KiCad's paste tool so it rides the
        cursor (the Python API exposes no interactive move, and the placement
        is undoable), with the editor switched to the marker's own layer on the
        way out (_activate_layer). With a marker already on the board this
        refuses, answering with where that marker is (_show_already_placed) —
        resizing it is the sliders' job, and the plugin never removes a placed
        marker itself (the editor's selection and undo stack may still point at
        a footprint KiCad's paste tool placed, and board.Remove would turn
        those into a crash). Fallbacks, in order:
        clipboard set but the keystroke can't be simulated -> tell the user to
        press Ctrl+V themselves; no clipboard at all -> drop the footprint at
        the board center."""
        import pcbnew

        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            return
        layer_n = self.marker_layer_n()
        width = self.width_mm()
        try:
            layer_id = feed_marker.check_layer(board, layer_n)

            existing = feed_marker.marker_footprints(board)
            if existing:
                self._show_already_placed(existing)
                return

            # From here the marker is going onto the board one way or another,
            # so hand the editor the layer it will be drawn on -- now, not once
            # the paste lands, so the user is already on that layer while they
            # aim the marker.
            self._activate_layer(board, layer_id)

            from ..place import to_clipboard

            if feed_marker.pasted_as_text(board) is not None:
                # The previous paste degraded to a plain-text item (a
                # clipboard manager fed KiCad stale content): don't fight
                # the clipboard again, place through the API.
                x, y = feed_marker.place_marker(board, layer_n, width)
                self._placed_now(
                    f"Feed marker dropped at the board center ({x}, {y}) "
                    f"mm, User.{layer_n} — move it onto the feed line (M); "
                    "the triangle points toward the antenna. Also delete "
                    "the pasted marker text the failed paste left behind "
                    "(Del)."
                )
                return

            if not to_clipboard(feed_marker.footprint_sexpr(layer_n, width)):
                x, y = feed_marker.place_marker(board, layer_n, width)
                self._placed_now(
                    f"Feed marker dropped at the board center ({x}, {y}) mm, "
                    f"User.{layer_n} — move it onto the feed line (M); the "
                    "triangle points toward the antenna."
                )
                return
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return

        from ..place import trigger_paste

        if trigger_paste(self.page):
            self._set_status(
                "Click the feed line to place the marker — the triangle "
                "points toward the antenna (Esc cancels)."
            )
        else:
            self._set_status(
                "Feed marker copied — press Ctrl+V in the PCB editor to put "
                "it on the cursor, then click the feed line to place it."
            )
        self._watch()

    def _watch(self):
        """Show the placed marker's location and layer once the paste lands
        (place.watch_placement does the polling). A paste KiCad degraded to
        a plain-text item — a clipboard manager fed it stale content — is
        caught here too, with the recovery on the status line."""
        import pcbnew

        from ..place import watch_placement

        def markers():
            board = pcbnew.GetBoard()
            return feed_marker.marker_footprints(board) if board is not None else []

        def text_blob():
            board = pcbnew.GetBoard()
            return feed_marker.pasted_as_text(board) if board is not None else None

        def snapshot():
            fps = markers()
            if fps:
                pos = fps[0].GetPosition()
                return ("marker", int(pos.x), int(pos.y))
            blob = text_blob()
            if blob is not None:
                pos = blob.GetPosition()
                return ("text", int(pos.x), int(pos.y))
            return None

        def settled():
            if not self.page:
                return
            fps = markers()
            if fps:
                # Through refresh_status, not _set_status: the marker that just
                # landed is also what the button now offers to show.
                self.refresh_status()
            elif text_blob() is not None:
                self._set_status(
                    "✗ KiCad pasted the marker as plain text — a clipboard "
                    "manager handed it stale content. Delete the text (Del) "
                    "and press Generate again: the retry places the marker "
                    "at the board center instead."
                )

        watch_placement(self.page, snapshot, settled)
