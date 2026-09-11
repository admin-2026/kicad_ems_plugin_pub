"""The wizard's Footprint section: the two rows copper can come from.

Section 3 has one button and one chooser, and the chooser has two tables — the
scan's ranked candidates, and a single row for the shape the Scan section's
rows describe right now (previewed on the area marker, simulated by nothing).
Picking either places the same kind of footprint, so what these check is what
differs: which rows are offered, what the unsimulated one is allowed to show,
and what the status line claims afterwards.

The scan behind the first table need not be this session's — one read back out
of the scan folder (design.scan_store) fills it the same way — so the same
questions are asked of a restored scan: same rows, same placement, and a status
line that says which scan the copper came from.

The Scan section under it is the real one, driven by a design, so the current
row really is the previewed candidate rather than a stand-in. The board, the
.kicad_mod write, the overlap check and the chooser dialog are stubbed for the
duration of one test (``_bench``) — see wx_stub.py for what "stubbed" means
here.

    python3 tests/test_footprint_section.py
"""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx / pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
scan_store = load("design.scan_store")
scoring = load("design.scoring")
wizard_scan = load("design.wizard_scan")
scan_section = load("gui.sections.scan")
footprint_section = load("gui.sections.footprint")
simulate = load("emkit.sim.simulate")

wx = wx_stub.wx
F0 = 2.45


class _Application:
    band = (2.4, 2.4835)
    impedance_ohm = 50.0
    return_loss_db = 10.0


class _Host:
    """The wizard sections' facade (pages.host.WizardHost), stubbed."""

    def target_freq_ghz(self, default=None):
        return F0

    def feed_layer_name(self):
        return "F_Cu"

    def current_application(self):
        return _Application()


class _Area:
    """The Area section's contribution: a decoded marker sized to the design's
    own starter area, on-grid, feeding from the bottom edge."""

    def __init__(self, design):
        w, h = design.area_hint_mm(F0)
        self._spec = {
            "area": (0.0, 0.0, w, h),
            "edge": "bottom",
            "frac": design.feed_frac,
            "rot_deg": 0.0,
            "pivot": (0.0, 0.0),
            "gap_mm": 0.5,
        }

    def spec(self):
        return dict(self._spec)

    def _markers(self):
        return []  # no marker on the board -> no preview to redraw


class _Board:
    """Just what a placement reads off a board: where the project is (the
    library folder) and the footprints on it -- no area marker here, so the
    preview cleanup finds nothing to strip."""

    def GetFileName(self):
        return ""  # simulate.output_dir falls back to a temp folder

    def GetFootprints(self):
        return []


class _Page:
    """Just what the two sections read off their page."""

    def __init__(self, design):
        self.design = design
        self.scroll = object()
        self.host = _Host()
        self.area = _Area(design)
        self.log_ctrl = None
        self.lines = []
        self.area_check_refreshes = 0

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def log(self, text):
        self.lines.append(text)

    def refresh_area_checks(self):
        self.area_check_refreshes += 1


class _Placed:
    """A stand-in for footprints.place: records the .kicad_mod it was asked to
    write, instead of touching the disk or pcbnew's footprint loader."""

    def __init__(self):
        self.calls = []

    def __call__(self, board, text, name, at_mm, lib_dir, rot_deg=0.0):
        self.calls.append(
            {
                "text": text,
                "name": name,
                "at": at_mm,
                "rot": rot_deg,
                "lib_dir": lib_dir,
            }
        )
        return f"/tmp/antenna.pretty/{name}.kicad_mod"


class _Problem:
    """One advisory overlap warning, as markers.area_checks reports them."""

    id = "area-antenna-overlap"
    severity = "warn"
    message = "the antenna overlaps existing copper"


class _Bench:
    """A wizard page under test: its real Scan and Footprint sections, the
    footprints a placement wrote (``placed``) and every chooser it opened
    (``dialogs`` -- what each was offered, which is the handoff these tests are
    really about)."""

    def __init__(self, page, section, placed, dialogs):
        self.page = page
        self.section = section
        self.placed = placed
        self.dialogs = dialogs

    @property
    def offered(self):
        """What the one chooser opened so far was handed."""
        assert len(self.dialogs) == 1, self.dialogs
        return self.dialogs[0]

    @property
    def status(self):
        return self.section._status_label.GetLabel()


def _pick_current(scanned, current):
    return current


@contextlib.contextmanager
def _bench(design, problems=(), confirm=True, pick=_pick_current):
    """A bench for ``design``. The board write, the overlap check, its dialog
    and the chooser are stubbed *for the duration of the with-block only*: they
    are real shared modules other test files drive (markers.area_checks has its
    own file), so a patch must never outlive the test that made it.

    ``pick(scanned, current)`` stands in for the user's row: the chooser is not
    built here (it is a wx.Dialog with two list controls), only what it was
    offered and what came back are."""
    page = _Page(design)
    page.scan = scan_section.ScanSection(page, wx.BoxSizer())
    page.scan.seed_from_freq()
    section = footprint_section.FootprintSection(page, wx.BoxSizer())
    placed, dialogs = _Placed(), []

    class _Dialog:
        def __init__(self, parent, design, scanned, suggested, current, reason=""):
            dialogs.append(
                {
                    "scanned": scanned,
                    "suggested": suggested,
                    "current": current,
                    "reason": reason,
                }
            )
            self.choice = pick(scanned, current)

        def ShowModal(self):
            return wx.ID_OK if self.choice is not None else wx.ID_CANCEL

        def Destroy(self):
            pass

    saved = (
        footprint_section.footprints.place,
        footprint_section.area_checks.antenna_problems,
        footprint_section.CandidateDialog,
        getattr(wx, "MessageBox", None),
    )
    footprint_section.footprints.place = placed
    footprint_section.area_checks.antenna_problems = lambda *a, **k: list(problems)
    footprint_section.CandidateDialog = _Dialog
    wx.MessageBox = lambda *a, **k: wx.YES if confirm else wx.NO
    scan_section.pcbnew.GetBoard = _Board
    try:
        yield _Bench(page, section, placed, dialogs)
    finally:
        (
            footprint_section.footprints.place,
            footprint_section.area_checks.antenna_problems,
            footprint_section.CandidateDialog,
            wx.MessageBox,
        ) = saved
        scan_section.pcbnew.GetBoard = lambda: None


def _scanned_results(design, page, count=3):
    """A finished scan's results and context, as ScanSection.results() hands
    them over: measured candidates at a few lengths."""
    ctx = dict(page.area.spec())
    ctx.update(
        {
            "design": design,
            "f0_ghz": F0,
            "feed_layer": "F_Cu",
            "band_ghz": [2.4, 2.4835],
            "impedance_ohm": 50.0,
            "return_loss_db": 10.0,
        }
    )
    base = page.scan._values()
    results = []
    for i in range(count):
        values = dict(base)
        values[design.LENGTH_KEY] = base[design.LENGTH_KEY] - i
        geo = design.solve(ctx["area"], ctx["edge"], ctx["frac"], values)
        results.append(
            {
                "design": design.key,
                "kind": "scan",
                "values": values,
                "geom": dict(geo.metrics),
                "f_res_ghz": F0,
                "s11_db": -20.0,
                "bw_mhz": 200.0,
                "r_ohm": 50.0,
                "x_ohm": 0.0,
                "error": None,
            }
        )
    return results, ctx


def _with_results(bench, design, count=3):
    """Hand the bench's scan section a finished scan, this session's own."""
    results, ctx = _scanned_results(design, bench.page, count)
    bench.page.scan.results = lambda: (results, ctx)
    return results, ctx


WHEN = "2026-08-12 09:41"


def _with_saved_results(bench, design, count=3, when=WHEN):
    """The same finished scan, but read back off disk (design.scan_store): the
    rows are identical, and all that travels with them is when that scan was
    run."""
    results, ctx = _with_results(bench, design, count)
    saved = scan_store.Saved(results, ctx, when, "/tmp/wizard/scan.json")
    bench.page.scan.saved_scan = lambda: saved
    return results, ctx


# --------------------------------------------------------------------------- #
# What the chooser is offered
# --------------------------------------------------------------------------- #
def test_the_current_rows_are_offered_without_a_scan():
    """The point of the second table: the button works on a page where no pass
    has ever been started, and what it offers is the shape on the marker."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            assert bench.page.scan.results() == ([], None), design.key
            bench.section.on_place()
            assert bench.offered["scanned"] == [], design.key
            assert bench.offered["current"] is not None, design.key
            assert bench.offered["reason"] == "", design.key
            assert len(bench.placed.calls) == 1, design.key


def test_the_chooser_offers_the_scan_and_the_current_rows_together():
    """After a scan there are two tables: every placeable result, ranked, and
    the one row for the shape the sliders are on right now."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            results, ctx = _with_results(bench, design)
            bench.section.on_place()
            offered = bench.offered
            assert [c.row for c in offered["scanned"]] == results, design.key
            assert all(c.simulated for c in offered["scanned"]), design.key
            assert all(c.ctx is ctx for c in offered["scanned"]), design.key
            assert offered["suggested"] is results[0], design.key
            assert offered["current"].simulated is False, design.key


def test_the_current_row_is_the_shape_the_preview_draws():
    """Same values, same geometry: the row offered is the candidate the marker
    is showing, not a re-derived or re-seeded one."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            # Move the swept slider off its seed, the way a user eyeing the
            # board would.
            bench.page.scan._sl[design.LENGTH_KEY].SetValue(72)
            values, ctx, geo = bench.page.scan.current_candidate()
            bench.section.on_place()
            current = bench.offered["current"]
            assert current.values == values, design.key
            assert current.ctx["area"] == ctx["area"], design.key
            assert current.row["geom"] == dict(geo.metrics), design.key
            # ... and that is what was placed, at its own feed point.
            call = bench.placed.calls[0]
            assert call["name"] == footprint_section.footprints.item_name(
                design, F0, geo.total_mm
            ), design.key
            assert call["at"] == geo.feed and call["rot"] == 0.0, design.key


def test_a_shape_the_area_cannot_hold_is_a_reason_not_a_row():
    """It is drawn on the marker's own layer rather than as copper, so placing
    it would fabricate metal outside the rectangle the user drew. The chooser
    says why instead of offering it."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            _with_results(bench, design)
            key = design.LENGTH_KEY
            bench.page.scan._lo[key].ChangeValue("10")
            bench.page.scan._hi[key].ChangeValue("10000")  # past any area
            bench.page.scan._sl[key].SetValue(100)
            bench.section.on_place()
            assert bench.offered["current"] is None, design.key
            assert bench.offered["reason"], design.key
            assert bench.placed.calls == [], design.key  # _pick_current: none


def test_nothing_to_place_opens_no_chooser():
    """No scan result and no placeable shape: the reason lands on the status
    line rather than in an empty dialog."""

    class _NoMarker:
        def spec(self):
            raise RuntimeError("place the area marker first")

        def _markers(self):
            return []

    design = registry.DESIGNS[0]
    with _bench(design) as bench:
        bench.page.area = _NoMarker()
        bench.section.on_place()
        assert bench.dialogs == []
        assert bench.placed.calls == []
        assert "area marker" in bench.status


def test_a_lone_scanned_candidate_still_places_straight_away():
    """The one shortcut kept: with nothing to choose between (no placeable
    current shape, one result), the chooser is not worth a click."""

    class _NoMarker:
        def spec(self):
            raise RuntimeError("place the area marker first")

        def _markers(self):
            return []

    design = registry.DESIGNS[0]
    with _bench(design) as bench:
        _with_results(bench, design, count=1)
        bench.page.area = _NoMarker()
        bench.section.on_place()
        assert bench.dialogs == []
        assert len(bench.placed.calls) == 1


def test_a_saved_scans_rows_are_offered_like_the_ones_this_session_ran():
    """A scan the plugin read back off disk is still a scan: its candidates
    fill the same table, ranked the same way, and were measured just as much --
    only when that happened travels with them."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            results, ctx = _with_saved_results(bench, design)
            bench.section.on_place()
            offered = bench.offered
            assert [c.row for c in offered["scanned"]] == results, design.key
            assert all(c.simulated for c in offered["scanned"]), design.key
            assert all(c.saved == WHEN for c in offered["scanned"]), design.key
            assert offered["suggested"] is results[0], design.key
            # The unsimulated row is this session's own either way.
            assert offered["current"].saved == "", design.key


def test_a_saved_candidate_places_exactly_as_a_fresh_one():
    """Nothing about the placement changes: the geometry is re-solved in the
    frame the scan carries, which is the area that scan was run in."""
    design = registry.DESIGNS[0]
    with _bench(design, pick=lambda scanned, current: scanned[0]) as bench:
        results, ctx = _with_saved_results(bench, design)
        bench.section.on_place()
        geo = design.solve(ctx["area"], ctx["edge"], ctx["frac"], results[0]["values"])
        call = bench.placed.calls[0]
        assert call["name"] == footprint_section.footprints.item_name(
            design, F0, geo.total_mm
        )
        assert call["at"] == geo.feed


def test_cancelling_the_chooser_places_nothing():
    design = registry.DESIGNS[0]
    with _bench(design, pick=lambda scanned, current: None) as bench:
        _with_results(bench, design)
        bench.section.on_place()
        assert bench.dialogs and bench.placed.calls == []


# --------------------------------------------------------------------------- #
# What a row is allowed to show (scoring)
# --------------------------------------------------------------------------- #
def test_the_current_row_shows_geometry_and_no_verdicts():
    """Nothing measured it, so every property cell is an em dash and the lead
    verdict glyph is blank -- shown beside the scanned rows without being
    scored against them, and without a verdict being invented."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            current, reason = bench.section._current()
            assert reason == "" and current is not None, design.key
            cells, overall = footprint_section.row_cells(design, current)
            assert overall == scoring.NONE, design.key
            assert cells[0] == "", design.key  # no glyph
            geometry = cells[1 : 1 + len(design.params) + len(design.columns)]
            assert all(c != "—" for c in geometry), (design.key, geometry)
            assert cells[1 + len(design.params) + len(design.columns) :] == ["—"] * len(
                scoring.PROPERTIES
            ), design.key


def test_a_scanned_row_still_carries_its_verdicts():
    """The other table is unchanged: measured properties are judged against
    the target, glyph and all."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            results, ctx = _with_results(bench, design)
            candidate = footprint_section.Candidate(results[0], ctx, True)
            cells, overall = footprint_section.row_cells(design, candidate)
            assert overall == scoring.PASS, design.key
            assert cells[0] == scoring.GLYPH[scoring.PASS], design.key
            assert "✓" in cells[-1], design.key  # input impedance, on target


# --------------------------------------------------------------------------- #
# What the status line claims afterwards
# --------------------------------------------------------------------------- #
def test_placing_the_current_row_says_nothing_was_simulated():
    """The copper is identical to a scanned candidate's, so this status line
    is the only thing that can say no numbers stand behind it."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            bench.section.on_place()
            assert "Nothing was simulated" in bench.status, design.key
            assert design.wiring in bench.status, design.key  # what to wire
            assert "Run simulation to verify" in bench.status, design.key


def test_placing_a_scanned_row_claims_nothing_extra():
    """It *does* have numbers behind it, so it says nothing about simulation
    being skipped."""
    for design in registry.DESIGNS:
        with _bench(design, pick=lambda scanned, current: scanned[0]) as bench:
            _with_results(bench, design)
            bench.section.on_place()
            assert len(bench.placed.calls) == 1, design.key
            assert "Nothing was simulated" not in bench.status, design.key


def test_placing_a_saved_candidate_says_which_scan_it_came_from():
    """It was simulated -- but not here, and not necessarily on the board as it
    stands now, so the status line names the scan it belongs to."""
    for design in registry.DESIGNS:
        with _bench(design, pick=lambda scanned, current: scanned[0]) as bench:
            _with_saved_results(bench, design)
            bench.section.on_place()
            assert f"saved scan of {WHEN}" in bench.status, design.key
            assert "Nothing was simulated" not in bench.status, design.key


def test_this_sessions_scan_claims_no_saved_one():
    design = registry.DESIGNS[0]
    with _bench(design, pick=lambda scanned, current: scanned[0]) as bench:
        _with_results(bench, design)
        bench.section.on_place()
        assert "saved scan" not in bench.status


def test_the_saved_scan_note_says_what_is_placeable():
    """What the wizard says when it opens on a board scanned in an earlier
    session: the expensive part is already done."""
    design = registry.DESIGNS[0]
    with _bench(design) as bench:
        results, ctx = _scanned_results(design, bench.page)
        results[1]["error"] = "solver failed"  # not placeable, not counted
        bench.section.note_saved_scan(
            scan_store.Saved(results, ctx, WHEN, "/tmp/wizard/scan.json")
        )
        assert f"{len(results) - 1} candidate(s)" in bench.status
        assert WHEN in bench.status


def test_placing_the_current_row_clears_the_preview_for_good():
    """The drawn preview *is* this copper: the board must not hold it twice,
    and a later area tweak must not redraw it over the placed footprint."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            bench.page.scan._preview_on = True
            bench.section.on_place()
            assert bench.page.scan._preview_on is False, design.key
            assert bench.page.area_check_refreshes > 0, design.key


def test_placing_drops_the_copper_the_overlap_check_was_judging():
    """The other half of the same cleanup, and the reason it matters: the
    recorded sweep covers the candidate just placed (asserted below), so the
    banner refresh at the end of a placement warned that the antenna overlaps
    existing copper -- the antenna's own footprint, a second old. The
    placement consumed that pass, so the scan section stops offering its copper
    to the check (ScanSection.forget_splice)."""
    for design in registry.DESIGNS:
        with _bench(design, pick=lambda scanned, current: scanned[0]) as bench:
            results, ctx = _with_results(bench, design)
            bench.page.scan._spliced = (ctx, wizard_scan.spliced_rects(ctx, results))
            bench.section.on_place()
            assert len(bench.placed.calls) == 1, design.key
            assert bench.page.scan.spliced_copper() is None, design.key


def test_the_placed_candidate_is_inside_the_copper_that_was_recorded():
    """Why the warning was never the user's to act on: the sweep's copper is
    every planned candidate's, so the winner's own rectangles are part of it
    and a placement collides with the record by construction, wherever the
    board's real metal is."""
    design = registry.DESIGNS[0]
    with _bench(design, pick=lambda scanned, current: scanned[0]) as bench:
        results, ctx = _with_results(bench, design)
        spliced = wizard_scan.spliced_rects(ctx, results)
        values = results[0]["values"]
        geo = design.solve(ctx["area"], ctx["edge"], ctx["frac"], values)
        placed = geo.copper_rects(values[design.WIDTH_KEY], 0.0, include_stub=False)
        assert placed and set(placed) <= set(spliced)


# --------------------------------------------------------------------------- #
# Guards every row shares
# --------------------------------------------------------------------------- #
def test_nothing_places_while_a_scan_runs():
    """A pass in flight is about to rewrite the results one row comes from and
    redraw the preview the other one is."""
    design = registry.DESIGNS[0]
    with _bench(design) as bench:
        _with_results(bench, design)
        bench.page.scan._running = True
        bench.section.on_place()
        assert bench.dialogs == [] and bench.placed.calls == []
        assert "Wait for the scan" in bench.status


def test_the_overlap_warning_guards_the_unsimulated_row_too():
    """The advisory check is about copper landing on copper, which has nothing
    to do with whether it was simulated: declining it places nothing."""
    design = registry.DESIGNS[0]
    with _bench(design, problems=[_Problem()], confirm=False) as bench:
        bench.section.on_place()
        assert bench.placed.calls == []
        assert "overlaps existing" in bench.status

    with _bench(design, problems=[_Problem()], confirm=True) as bench:
        bench.section.on_place()
        assert len(bench.placed.calls) == 1


def test_every_placed_row_carries_the_designs_pads():
    """Both rows go through the one emitter, so the inverted-F's ground pin is
    on the unsimulated footprint exactly as on a scanned one."""
    for design in registry.DESIGNS:
        with _bench(design) as bench:
            _values, ctx, geo = bench.page.scan.current_candidate()
            bench.section.on_place()
            pads = bench.placed.calls[0]["text"].count("(pad ")
            assert pads == len(design.footprint_pads(geo)), design.key
            assert ctx["f0_ghz"] == F0


def test_the_library_lands_beside_the_simulation_folder():
    """The .kicad_mod is a board asset the user keeps and re-places from;
    everything under ``simulation/`` is regenerated output that can be deleted
    wholesale. So the library folder is that folder's *sibling*, never a folder
    inside it — deleting the run results must not take the placed footprints'
    source with them."""
    with _bench(registry.DESIGNS[0]) as bench:
        bench.section.on_place()
        lib = pathlib.Path(str(bench.placed.calls[0]["lib_dir"]))
        sim = simulate.output_dir(_Board())
        assert lib == sim.parent
        assert sim not in lib.parents and lib != sim


if __name__ == "__main__":
    run_module_tests(globals())
