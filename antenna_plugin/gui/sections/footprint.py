"""Section 3: turning a candidate geometry into a placed footprint.

One button, **Generate + place footprint**, and one chooser behind it — with
*two* tables in it:

    Scanned candidates      every result of the last scan, ranked best-first,
                            each property marked against the desired spec --
                            this session's scan, or the one the scan folder
                            saved (design.scan_store), which is the same rows
                            read back off disk
    The Scan rows as they   one row: the geometry the Scan section's rows
    stand                   describe *right now*, the shape previewed inside
                            the area (``ScanSection.current_candidate``)

The second table is the way to get copper without a simulation: pick its row
and the previewed antenna is placed exactly as a scanned candidate would be.
Nothing was measured for it, so its property cells are em dashes rather than
verdicts (scoring shows what it has and judges only what was measured) and the
status line says outright that nothing was simulated — a footprint must never
imply a measurement that was never made. It is a *row*, not a second button,
because it is the same question the chooser already asks: which of these
geometries goes on the board?

Whichever row is picked, the geometry is re-solved from its own context (the
scan's frame for a scanned candidate, the marker as it stands for the current
shape), written as a .kicad_mod into the project's own antenna.pretty library
(beside the simulation folder, not inside it) and placed on the board at the feed
point, ready to wire to the feed line. Before placing, the copper is checked
against existing metal inside the area (markers.area_checks) and an overlap
asks the user to confirm — the same advisory warning the wizard's banner shows,
at the moment it matters most. Afterwards the placement is what the wizard's
drawn preview and the scan's recorded splice were *for*, so both are dropped
(``ScanSection.forget_preview`` / ``forget_splice``): the copper is on the
board now, and neither is a thing still waiting to be drawn or spliced onto it.
Only ``_place`` writes a footprint, and both tables' rows reach it as the same
:class:`Candidate`, so the two can never drift apart.

Design-agnostic: the chooser's geometry columns are the page's design's own
(one per ``design.params``, plus its derived ``design.columns``), and the
footprint comes from the shared emitter (design.footprints) via the design's
``solve`` / ``footprint_pads``. Adding a topology adds nothing here.
"""

from typing import NamedTuple

import pcbnew
import wx

from ...design import footprints, scoring
from ...emkit.gui.sections.base import Section
from ...emkit.gui.theme import PAD
from ...emkit.gui.widgets import set_tip
from ...emkit.markers import markergeom, preview
from ...markers import area_checks


class Candidate(NamedTuple):
    """One placeable row of the chooser, from either table.

    ``row`` is result-shaped (``values`` + ``geom``, plus whatever was
    measured): a scan result as the driver wrote it, or — for the shape the
    Scan rows describe — the same two keys and nothing else, which is exactly
    what "not simulated" looks like to the scoring (every property a NONE
    verdict, shown but not judged). ``ctx`` is the frame and target it is
    solved and placed in, which is *not* shared: a scanned candidate belongs to
    the area as it was scanned, the current shape to the marker as it is now.
    ``simulated`` is only what the status line may claim afterwards, and
    ``saved`` — when the scan behind the row finished — is set only for a row
    read back out of the scan folder (design.scan_store), which is a thing to
    *say* rather than a difference in what gets placed."""

    row: dict
    ctx: dict
    simulated: bool
    saved: str = ""

    @property
    def values(self):
        """The geometry knobs to solve and place."""
        return self.row["values"]


def _fmt(value, suffix=""):
    """A geometry field for the chooser table: numbers as ``%g``, a missing
    one as an em dash."""
    if value is None:
        return "—"
    return f"{value:g}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


# The row text colour when a candidate's overall (worst) status is warn/fail;
# PASS/NONE keep the default colour. The glyphs and property order come from
# scoring (scoring.GLYPH / scoring.PROPERTIES) -- shared with the HTML views.
_ROW_COLOUR = {
    scoring.WARN: wx.Colour(176, 120, 0),
    scoring.FAIL: wx.Colour(200, 60, 60),
}


def _cell(verdict):
    """A property cell: its pass/warn/fail glyph before the value text."""
    glyph = scoring.GLYPH[verdict.status]
    return f"{glyph} {verdict.text}" if glyph else verdict.text


def row_cells(design, candidate):
    """One chooser row, left to right, as ``(cells, overall status)``: the
    overall verdict glyph, then the design's geometry columns (a parameter per
    ``design.params``, the derived ones per ``design.columns``), then a cell
    per scored property.

    The same cells for both tables — which is the point of building them here
    rather than inside the ListCtrl loop. An unsimulated row has nothing
    measured, so every property comes back a NONE verdict ("—") and its overall
    glyph is blank: it is shown beside the scanned ones without being scored
    against them, and without a verdict being invented for it."""
    verdicts = scoring.evaluate(candidate.row, scoring.target_from_spec(candidate.ctx))
    geom = candidate.row.get("geom") or {}
    cells = [scoring.GLYPH[verdicts["overall"]]]
    cells += [_fmt(candidate.values.get(p.key), " mm") for p in design.params]
    cells += [_fmt(geom.get(c.key), c.suffix) for c in design.columns]
    cells += [_cell(verdicts[key]) for key, _label, _fn in scoring.PROPERTIES]
    return cells, verdicts["overall"]


class CandidateDialog(wx.Dialog):
    """Pick which geometry to place, from two tables sharing one set of
    columns and one selection.

    The **scanned candidates** table lists every placeable result best-first;
    each property (resonance, return loss, VSWR, bandwidth, input impedance) is
    marked ✓/⚠/✗ against the application's desired spec, a warn/fail cell shows
    the desired value beside the simulated one, and the lead column carries the
    candidate's overall (worst) verdict. The **current rows** table below it
    holds a single row: the shape the Scan section describes right now, with
    dashes where the numbers would be, because nothing simulated it.

    They are two controls, so selecting in one clears the other (``_on_select``
    — wx has no cross-list single selection): whatever is selected anywhere is
    the one candidate that gets placed. The scan's ranked winner is
    pre-selected, or the current row when there is no scan to rank. Returns the
    chosen :class:`Candidate` from ``choice`` after ShowModal() == wx.ID_OK.

    Either table can be absent — no scan has run, or the rows describe nothing
    placeable — and then a line of prose says so in its place, since an empty
    table is a worse explanation than a sentence."""

    # The property columns (resonance, return loss, VSWR, bandwidth, input Z)
    # are appended from scoring.PROPERTIES with these widths, so their
    # order/labels track the scoring module (and the views). The geometry
    # columns before them are the design's own.
    _PROP_W = {
        "resonance": 120,
        "return_loss": 118,
        "vswr": 108,
        "bandwidth": 120,
        "impedance": 132,
    }
    _GEOM_W = 70
    # Table heights: the scan's table grows with the window, the current-shape
    # table is one row and stays that tall (header + row + a little).
    _SCAN_H = 240
    _CURRENT_H = 76

    def __init__(self, parent, design, scanned, suggested, current, reason=""):
        super().__init__(
            parent,
            title="Choose what to place",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.design = design
        self.choice = None
        self._tables = []  # (ListCtrl, [Candidate]) -- the selection lives here
        outer = wx.BoxSizer(wx.VERTICAL)
        self._prose(
            outer,
            f"{design.name} — each property is ✓ pass / ⚠ warn / ✗ fail "
            "against the target (desired shown for a warn or fail). Select a "
            "row and double-click or OK to place it.",
        )

        if scanned:
            f0 = scanned[0].ctx["f0_ghz"]
            when = scanned[0].saved
            # A restored scan says so here: the numbers are as real as any
            # other, but they were measured in an area marker that may have
            # been moved since -- and the candidate is placed in the area it
            # was scanned in, not the one on screen.
            whose = (
                f"Scanned candidates, best first for {f0:g} GHz:"
                if not when
                else f"Scanned candidates of the saved scan of {when} — best "
                f"first for {f0:g} GHz, each placed in the area it was "
                "scanned in:"
            )
            self._prose(outer, whose)
            lst = self._table(outer, scanned, self._SCAN_H, grow=True)
            best = next((i for i, c in enumerate(scanned) if c.row is suggested), 0)
        else:
            self._prose(
                outer,
                "No scan results — Start scan to fill this in with simulated "
                "candidates. (A finished scan is kept in its folder, so this "
                "table also comes back on a board scanned in an earlier "
                "session.)",
            )
            lst = best = None

        self._prose(
            outer,
            "The Scan rows as they stand — the shape previewed inside the "
            "area marker. Nothing simulated it, so it has no numbers to show:",
        )
        if current is not None:
            current_lst = self._table(outer, [current], self._CURRENT_H)
        else:
            self._prose(outer, f"Not placeable right now: {reason}")
            current_lst = None

        # Preselect the scan's winner, or the current shape when there is no
        # scan to have a winner.
        if lst is not None:
            lst.Select(best)
            lst.Focus(best)
        elif current_lst is not None:
            current_lst.Select(0)
            current_lst.Focus(0)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("Place selected")
        outer.Add(btns, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _prose(self, outer, text):
        """A line of explanation between the tables."""
        outer.Add(wx.StaticText(self, label=text), 0, wx.ALL, 10)

    def _table(self, outer, candidates, height, grow=False):
        """One table of candidates: the shared columns, one row per candidate
        (``row_cells``), and the bindings that keep a single selection across
        every table in the dialog. ``grow`` gives the spare height to the
        scan's table, since that is the one with rows to spare."""
        lst = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(880, height)
        )
        # ("", overall verdict) + one column per design parameter + the
        # design's derived columns + the scored properties.
        cols = (
            [("", 30)]
            + [(p.label, self._GEOM_W) for p in self.design.params]
            + [(c.label, self._GEOM_W) for c in self.design.columns]
            + [(label, self._PROP_W[key]) for key, label, _fn in scoring.PROPERTIES]
        )
        for i, (label, width) in enumerate(cols):
            lst.InsertColumn(i, label, width=width)
        for row, candidate in enumerate(candidates):
            cells, overall = row_cells(self.design, candidate)
            lst.InsertItem(row, cells[0])
            for col, text in enumerate(cells[1:], start=1):
                lst.SetItem(row, col, text)
            colour = _ROW_COLOUR.get(overall)
            if colour is not None:
                lst.SetItemTextColour(row, colour)
        lst.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        lst.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self._tables.append((lst, list(candidates)))
        outer.Add(lst, 1 if grow else 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        return lst

    def _on_select(self, event):
        """A row was selected: clear every other table's selection, so the two
        lists behave as one (wx keeps a selection per control, which would
        otherwise leave two rows looking equally chosen)."""
        picked = event.GetEventObject()
        for lst, _candidates in self._tables:
            index = -1 if lst is picked else lst.GetFirstSelected()
            if index >= 0:  # LC_SINGLE_SEL: at most one per table
                lst.Select(index, 0)
        event.Skip()

    def _selected(self):
        """The one selected candidate across both tables, or None."""
        for lst, candidates in self._tables:
            index = lst.GetFirstSelected()
            if index >= 0:
                return candidates[index]
        return None

    def _on_ok(self, event):
        self.choice = self._selected()
        event.Skip()

    def _on_activate(self, event):
        """A double-click places that row, wherever it lives."""
        for lst, candidates in self._tables:
            if lst is event.GetEventObject():
                self.choice = candidates[event.GetIndex()]
        self.EndModal(wx.ID_OK)


class FootprintSection(Section):
    _TITLE = "Footprint"

    def __init__(self, page, body, step=None):
        super().__init__(page, step)
        self.design = page.design
        p = self.scroll
        box = self.box(self._TITLE)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.place_btn = self.row_button(
            row, "Generate + place footprint", self.on_place
        )
        set_tip(
            self.place_btn,
            "Choose a geometry and place it: a scanned candidate (the best is "
            "suggested), or the shape the Scan rows describe right now",
        )
        box.Add(row, 0, wx.EXPAND)
        # The status line under the button, full width: what it says about a
        # placement (or why one can't be made) wraps into the section instead
        # of being cut off by the button beside it.
        self._status_label = self.wrap_label(
            p,
            "Place a scanned result — or, unsimulated, the shape the Scan "
            "rows describe right now.",
            mute=True,
        )
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self.add_to_body(body, box)

    def on_place(self, event=None):
        """Choose a geometry and place it: the chooser offers the scan's
        candidates (the best suggested) *and* the shape the Scan rows describe
        right now, and whichever row is picked is written as a .kicad_mod and
        placed on the board at its own feed point.

        Both tables are gathered here so the dialog is handed candidates and
        nothing else — including the reason there is no current shape, which it
        shows in that table's place."""
        board = pcbnew.GetBoard()
        if board is None:
            self._set_status("No board is open.")
            return
        if self.page.scan.running:
            self._set_status("Wait for the scan to finish.")
            return
        scanned, suggested = self._scanned()
        current, reason = self._current()
        if not scanned and current is None:
            self._set_status(
                f"✗ nothing to place — no scan result, and the Scan rows "
                f"describe no placeable shape ({reason})."
            )
            return
        # The one shortcut: a lone scanned candidate places straight away, as
        # it always has. An unsimulated shape is never placed without being
        # picked -- that choice is the whole point of showing it as a row.
        if current is None and len(scanned) == 1:
            chosen = scanned[0]
        else:
            dlg = CandidateDialog(
                self.page, self.design, scanned, suggested, current, reason
            )
            try:
                if dlg.ShowModal() != wx.ID_OK or dlg.choice is None:
                    return
                chosen = dlg.choice
            finally:
                dlg.Destroy()
        self._place(board, chosen)

    def note_saved_scan(self, saved):
        """The scan section restored a scan an earlier session ran (its
        ``scan_store.Saved``): say on this section's status line that those
        candidates are here to be placed. Said as the wizard opens on a board
        that has been scanned before — which is exactly when nothing else on
        screen would suggest that the expensive part is already done."""
        placeable = sum(1 for r in saved.results if r.get("error") is None)
        self._set_status(
            f"{placeable} candidate(s) from the saved scan of {saved.when} — "
            "Generate + place footprint offers them, no re-run needed."
        )

    def _scanned(self):
        """The last scan's placeable candidates (best-first) and the result
        the chooser suggests among them: ``(candidates, suggested)``, empty
        before a scan has finished. Only candidates that actually solved and
        scored can be placed; best_result names the winner (the same one
        scan_report stars).

        "The last scan" may be one an earlier session ran, read back off disk
        by the scan section (design.scan_store): the rows are the same, so they
        are offered and placed the same way, and all that travels with them is
        when that scan finished — for the chooser and the status line to say
        so."""
        from ...design import wizard_scan

        results, ctx = self.page.scan.results()
        if ctx is None:
            return [], None
        saved = self.page.scan.saved_scan()
        when = saved.when if saved else ""
        # Every parameter can differ per candidate (whichever one was swept),
        # so each row carries its own values -- and the scan's context, which
        # is the area as it was scanned rather than as it stands now.
        candidates = [
            Candidate(r, ctx, True, when) for r in results if r.get("error") is None
        ]
        return candidates, wizard_scan.best_result(results)

    def _current(self):
        """The Scan rows as they stand, as a chooser row — and, when there
        isn't one, why not: ``(candidate or None, reason)``. The reason is the
        scan section's own wording (no area marker, a blank row, a shape the
        area can't hold), shown in the table's place rather than swallowed, so
        the answer to "why isn't my shape offered?" is where the row would be.

        The row is result-shaped with nothing measured in it, which is what
        makes it show dashes instead of verdicts (see :class:`Candidate`)."""
        try:
            values, ctx, geo = self.page.scan.current_candidate()
        except Exception as exc:
            return None, str(exc)
        row = {"values": values, "geom": dict(geo.metrics)}
        return Candidate(row, ctx, False), ""

    def _place(self, board, candidate):
        """Solve the chosen candidate's geometry in its own context, write the
        footprint and place it — the one path onto the board, whether the row
        came from the scan or from the Scan section's sliders. What differs
        afterwards is only what the status line may claim
        (``Candidate.simulated``): the copper is identical either way, so an
        unsimulated placement has to say so itself."""
        from ...emkit.sim import simulate

        design = self.design
        values, ctx = candidate.values, candidate.ctx
        trace_w = values[design.WIDTH_KEY]
        try:
            geo = design.solve(ctx["area"], ctx["edge"], ctx["frac"], values)
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return
        if not self._confirm_overlap(board, geo, trace_w, ctx):
            self._set_status(
                "Not placed — the antenna overlaps existing "
                "copper inside the area (see the warning)."
            )
            return
        try:
            text = footprints.sexpr(design, geo, values, ctx["f0_ghz"])
            name = footprints.item_name(design, ctx["f0_ghz"], geo.total_mm)
            # The geometry solved in the area marker's derotated frame; an
            # off-grid marker places the footprint at the rotated feed point
            # with the matching orientation.
            rot = ctx.get("rot_deg") or 0.0
            pivot = ctx.get("pivot") or (0, 0)
            path = footprints.place(
                board,
                text,
                name,
                markergeom.rotate_pt(geo.feed, rot, pivot),
                simulate.library_dir(board),
                rot_deg=rot,
            )
            # The scan section's antenna preview is the same copper this
            # footprint now carries — clear it so the board doesn't hold it
            # twice, and tell the scan section to stop wanting one, or its next
            # redraw would put the candidate back on top of the footprint just
            # placed.
            if preview.clear(board):
                pcbnew.Refresh()
            self.page.scan.forget_preview()
            # The pass whose copper the overlap check judges has just produced
            # a footprint, so that copper is on the board rather than waiting
            # to be spliced onto it: drop it, or the refresh below would greet
            # the placement with the antenna overlapping itself.
            self.page.scan.forget_splice()
        except Exception as exc:
            self._set_status(f"✗ {exc}")
            return
        placed = f"{name} placed at the feed point (library: {path}). "
        if candidate.saved:
            # Placed from a scan this session didn't run: the geometry is the
            # one that was measured then, in the area marker as it stood then,
            # which is worth saying on a board that may have moved since.
            placed += (
                f"It comes from the saved scan of {candidate.saved}, "
                "in the area that scan was run in. "
            )
        if not candidate.simulated:
            # The copper is the same shape a scanned candidate's would be, so
            # nothing on the board says which of the two it is. This line is
            # the only thing that does -- and the run that would settle it is
            # already the next sentence.
            placed += (
                "Nothing was simulated — this is the shape the Scan rows describe. "
            )
        self._set_status(
            f"{placed}{design.wiring} Then put a feed marker on the feed "
            "line and Run simulation to verify."
        )
        self.log(f"Footprint written: {path}")
        # The board just changed (footprint added, preview cleared): re-run
        # the advisory area checks so the banner reflects it.
        self.page.refresh_area_checks()

    def _confirm_overlap(self, board, geo, trace_w, ctx):
        """The pre-place advisory check: warn when the chosen candidate's
        copper lands on existing metal inside the area it was scanned in
        (markers.area_checks.antenna_problems — the same warning the wizard's
        banner shows) and let the user decide. Returns True to place; a
        failing check never blocks a place, it only can't warn (the checks
        are advisory end to end)."""
        try:
            problems = area_checks.antenna_problems(
                board,
                ctx["feed_layer"],
                ctx,
                geo.copper_rects(trace_w, 0.0, include_stub=False),
            )
        except Exception as exc:
            self.log(f"area check failed: {exc}")
            return True
        if not problems:
            return True
        lines = "\n\n".join(f"⚠ {p.message}" for p in problems)
        return (
            wx.MessageBox(
                f"{lines}\n\nPlace the footprint anyway?",
                "Antenna overlaps existing copper",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                self.page,
            )
            == wx.YES
        )
