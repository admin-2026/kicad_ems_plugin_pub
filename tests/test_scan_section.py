"""The wizard's Scan section, driven by a design (no KiCad, real wx stubbed).

The section builds one row per ``design.params`` entry, seeds each from the
design's Seed at the target frequency, greys the rows it isn't sweeping, and
turns the whole thing into a scan spec. None of that mentions a topology, so
these run over every registered design -- and end with the spec actually
feeding ``wizard_scan.plan``, which is the handoff that has to hold.

See wx_stub.py for what "stubbed" means here.

    python3 tests/test_scan_section.py
"""

import contextlib
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
sizing = load("design.sizing")
scan_store = load("design.scan_store")
wizard_scan = load("design.wizard_scan")
scan_section = load("gui.sections.scan")

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
    """The Area section's contribution to the spec: a decoded marker sized to
    the design's own starter area, on-grid, feeding from the bottom edge."""

    def __init__(self, design):
        w, h = design.area_hint_mm(F0)
        self._spec = {
            "area": (0.0, 0.0, w, h),
            "edge": "bottom",
            "frac": 0.3,
            "rot_deg": 0.0,
            "pivot": (0.0, 0.0),
            "gap_mm": 0.5,
        }

    def spec(self):
        return dict(self._spec)

    def _markers(self):
        return []  # no marker on the board -> no preview


class _Footprint:
    """The Footprint section as the scan section reaches it: it is told when a
    saved scan was restored, and nothing else."""

    def __init__(self):
        self.notes = []

    def note_saved_scan(self, saved):
        self.notes.append(saved)


class _Page:
    """Just what a Section reads off its page."""

    def __init__(self, design):
        self.design = design
        self.scroll = object()
        self.host = _Host()
        self.area = _Area(design)
        self.footprint = _Footprint()
        self.log_ctrl = None
        self.wrapped = []
        self.lines = []  # the run log
        self.area_check_refreshes = 0  # refresh_area_checks call count

    def register_wrap(self, label):
        self.wrapped.append(label)

    def _relayout_scroll(self):
        pass

    def log(self, text):
        self.lines.append(text)

    def refresh_area_checks(self):
        self.area_check_refreshes += 1


def _section(design):
    page = _Page(design)
    section = scan_section.ScanSection(page, wx_stub.wx.BoxSizer())
    section.seed_from_freq()
    return section


def _each_design():
    return [(d, _section(d)) for d in registry.DESIGNS]


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
def test_one_row_per_design_parameter():
    for design, section in _each_design():
        keys = [p.key for p in design.params]
        assert sorted(section._radio) == sorted(keys), design.key
        assert sorted(section._sl) == sorted(keys)
        assert sorted(section._lo) == sorted(section._hi) == sorted(keys)


def test_the_resonant_length_is_swept_first():
    for design, section in _each_design():
        assert section._swept_param() == design.LENGTH_KEY, design.key


def test_only_the_swept_row_stays_live():
    # The sweep's controls -- a range and a slider inside it -- belong to the
    # one row being swept; the value box is the mirror image, since the swept
    # row's is only the slider's readout and a fixed row's is where its value
    # is typed.
    for design, section in _each_design():
        for param in design.params:
            section._radio[section._swept_param()].SetValue(False)
            section._radio[param.key].SetValue(True)
            section._on_scan_param()
            for other in design.params:
                live = other.key == param.key
                for ctrl in (
                    section._lo[other.key],
                    section._sl[other.key],
                    section._hi[other.key],
                ):
                    assert ctrl.enabled is live, (design.key, other.key)
                assert section._val[other.key].enabled is not live, other.key


def test_a_fixed_value_is_typed_rather_than_slid():
    # The point of the value box: setting what every candidate carries for a
    # parameter nobody is sweeping, without selecting its row first.
    for design, section in _each_design():
        for param in design.params:
            if param.key == design.LENGTH_KEY:
                continue  # the swept row
            section._val[param.key].type("3.25")
            assert section._value(param.key) == 3.25, (design.key, param.key)
            assert section._spec()["values"][param.key] == 3.25, param.key


def test_a_blank_fixed_value_says_so_instead_of_guessing():
    design = registry.DESIGNS[0]
    section = _section(design)
    section._val[design.WIDTH_KEY].type("")
    try:
        section._value(design.WIDTH_KEY)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert design.param_label(design.WIDTH_KEY).lower() in str(exc)


def test_a_typed_fixed_value_reaches_the_banner():
    # Every candidate carries it, so the sweep the banner judges changes with
    # it -- the same duty a typed bound has.
    design = registry.DESIGNS[0]
    section = _section(design)
    before = section.page.area_check_refreshes
    section._val[design.WIDTH_KEY].type("2.0")
    assert section.page.area_check_refreshes == before + 1


def test_a_row_picked_for_sweeping_starts_from_its_fixed_value():
    # Selecting a row must not move the candidate under the user: the slider
    # takes over where the typed value left off (clamped into the row's range).
    for design, section in _each_design():
        key = design.WIDTH_KEY
        section._lo[key].ChangeValue("1")
        section._hi[key].ChangeValue("3")
        section._val[key].type("2")
        section._pick_param(key, object())
        assert section._value(key) == 2.0, design.key


def test_every_row_wears_its_own_illustration():
    # The picture beside a row is the design's own artwork for that parameter
    # (Param.icon), loaded from the bundled set at the row's icon size.
    for design, section in _each_design():
        assert sorted(section._icon) == sorted(p.key for p in design.params)
        for param in design.params:
            bmp, lit, faded = section._icon[param.key]
            assert lit.image.path.endswith(param.icon), param.key
            assert lit.image.size == (scan_section.ICON_SIZE,) * 2
            assert faded.image.alpha == scan_section.ICON_FADED_ALPHA
            assert bmp.GetBitmap() in (lit, faded)


def test_an_illustrated_row_shows_no_parameter_text():
    # The picture *is* the label: the radio beside it wears no words (every
    # shipped design illustrates every knob, tests/test_designs.py).
    for design, section in _each_design():
        for param in design.params:
            assert param.key in section._icon, (design.key, param.key)
            assert section._radio[param.key].GetLabel() == "", param.key


def test_rows_without_artwork_keep_their_names():
    # The fallback for a topology under development: a knob nobody has drawn
    # yet wears its name, rather than leaving the row a nameless bullet.
    shipped = registry.DESIGNS[0]

    class _Undrawn(type(shipped)):
        params = tuple(p._replace(icon="") for p in shipped.params)

    section = _section(_Undrawn())
    assert section._icon == {}
    for param in _Undrawn.params:
        assert section._radio[param.key].GetLabel() == param.label


def test_the_parameters_name_is_a_hover_away():
    # It has to be reachable somewhere: the row shows a drawing, and the
    # result table below talks in these words. The name is the whole of the
    # tooltip -- what the sweep does is the drawing's job, not a sentence's.
    for design, section in _each_design():
        for param in design.params:
            for ctrl in (section._radio[param.key], section._icon[param.key][0]):
                assert ctrl.tooltip == param.label, (design.key, param.key)


def test_only_the_swept_rows_illustration_is_lit():
    # The fixed rows' pictures fade with the controls they belong to, so the
    # lit one is always the sweep the section would run.
    for design, section in _each_design():
        for param in design.params:
            section._radio[section._swept_param()].SetValue(False)
            section._radio[param.key].SetValue(True)
            section._on_scan_param()
            for other in design.params:
                bmp, lit, faded = section._icon[other.key]
                want = lit if other.key == param.key else faded
                assert bmp.GetBitmap() is want, (design.key, other.key)


def test_clicking_an_illustration_selects_its_row():
    # The pictures pick a sweep as well as explain one: a click does what the
    # radio beside it does, greying the other rows and lighting this one.
    for design, section in _each_design():
        for param in design.params:
            section._pick_param(param.key, object())  # the click event
            assert section._swept_param() == param.key, design.key
            assert (
                section._icon[param.key][0].GetBitmap() is section._icon[param.key][1]
            )


def test_no_prose_explains_the_sweep():
    # The drawings say what a sweep does, so nothing under the grid says it
    # again in words -- and no design carries a sentence for one to say.
    for design, section in _each_design():
        assert not hasattr(section, "_geo_note")
        for param in design.params:
            assert not hasattr(param, "hint"), (design.key, param.key)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def test_seeding_fills_every_row_from_the_designs_own_seeds():
    for design, section in _each_design():
        seeds = design.seed_values(F0)
        for key, (lo, hi, value) in seeds.items():
            got_lo, got_hi = section._range(key)
            assert abs(got_lo - lo) < 0.1 and abs(got_hi - hi) < 0.1, key
            # The slider lands on the seed value inside those bounds.
            assert abs(section._value(key) - value) < 0.1 * (hi - lo), key


def test_seeding_leaves_bounds_the_user_typed():
    design = registry.DESIGNS[0]
    section = _section(design)
    section._lo[design.LENGTH_KEY].ChangeValue("11")
    section._hi[design.LENGTH_KEY].ChangeValue("13")
    section.seed_from_freq()  # idempotent: must not overwrite
    assert section._range(design.LENGTH_KEY) == (11.0, 13.0)


def test_a_cleared_length_row_falls_back_to_the_ladder_band():
    for design, section in _each_design():
        section._lo[design.LENGTH_KEY].ChangeValue("")
        section._hi[design.LENGTH_KEY].ChangeValue("")
        lo, hi = section._range(design.LENGTH_KEY)
        est = sizing.quarter_wave_mm(F0)
        assert abs(lo - est * sizing.LADDER_LO) < 1e-6
        assert abs(hi - est * sizing.LADDER_HI) < 1e-6


def test_an_unusable_row_says_so_instead_of_guessing():
    design = registry.DESIGNS[0]
    section = _section(design)
    section._lo[design.WIDTH_KEY].ChangeValue("")
    section._hi[design.WIDTH_KEY].ChangeValue("")
    try:
        section._range(design.WIDTH_KEY)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert design.param_label(design.WIDTH_KEY).lower() in str(exc)


# --------------------------------------------------------------------------- #
# Persisted rows (settings)
# --------------------------------------------------------------------------- #
def _tuned(design):
    """A section whose rows the user has moved off their seeds: every row
    bounded by hand and valued a quarter of the way in, the width row swept,
    six candidates."""
    section = _section(design)
    for i, param in enumerate(design.params):
        section._lo[param.key].ChangeValue(f"{2 + i}")
        section._hi[param.key].ChangeValue(f"{20 + i}")
        section._set_value(param.key, 6.5 + i)  # 25% of the row's range
    section._radio[design.LENGTH_KEY].SetValue(False)
    section._radio[design.WIDTH_KEY].SetValue(True)
    section.count.SetValue(6)
    return section


def test_a_snapshot_is_flat_strings_namespaced_by_design():
    """The settings file is flat ``key: value`` strings shared by every page,
    so each designer's rows must be strings under their own prefix."""
    seen = {}
    for design, section in _each_design():
        data = section.snapshot()
        assert all(isinstance(v, str) for v in data.values()), design.key
        assert all(k.startswith(f"scan.{design.key}.") for k in data), design.key
        for key in data:
            assert key not in seen, (key, seen.get(key))
            seen[key] = design.key


def test_the_rows_survive_a_save_and_reload():
    for design in registry.DESIGNS:
        data = _tuned(design).snapshot()
        fresh = _section(design)  # a new launch, rows on their seeds
        fresh.restore(data)
        assert fresh._swept_param() == design.WIDTH_KEY, design.key
        assert fresh.count.GetValue() == 6, design.key
        for i, param in enumerate(design.params):
            assert fresh._range(param.key) == (2.0 + i, 20.0 + i), param.key
            # The value, not the slider position: it lands back on the same mm.
            assert abs(fresh._value(param.key) - (6.5 + i)) < 0.2, param.key


def test_restoring_a_file_without_this_designs_rows_changes_nothing():
    """An older settings file (or one written before this design shipped)
    leaves every row on its seed rather than blanking it."""
    for design, section in _each_design():
        before = {p.key: section._range(p.key) for p in design.params}
        section.restore({"freq": "2.45", "scan.other-design.length.min": "3"})
        assert section._swept_param() == design.LENGTH_KEY, design.key
        assert {p.key: section._range(p.key) for p in design.params} == before, (
            design.key
        )


def test_a_restored_value_outlives_the_frequency_seeding():
    """A row saved with blank bounds (the length's automatic ladder) has its
    band seeded from the target frequency on the next launch -- and must keep
    the value that was saved with it, not the seed's."""
    for design in registry.DESIGNS:
        key = design.LENGTH_KEY
        section = _section(design)
        section._lo[key].ChangeValue("")
        section._hi[key].ChangeValue("")
        section._sl[key].SetValue(80)
        saved, value = section.snapshot(), section._value(key)

        fresh = scan_section.ScanSection(_Page(design), wx_stub.wx.BoxSizer())
        fresh.restore(saved)  # before the frequency is known
        fresh.seed_from_freq()  # ... which then fills the bounds
        assert abs(fresh._value(key) - value) < 0.2, design.key


def test_a_new_area_marker_puts_the_rows_back_on_their_seeds():
    """Placing an area marker starts over: the bounds a previous area was
    tuned for are gone (area.AreaSection._forget_scan_params)."""
    for design in registry.DESIGNS:
        section = _tuned(design)
        section.reset_params()
        assert section._swept_param() == design.LENGTH_KEY, design.key
        assert section.count.GetValue() == scan_section.COUNT_DEFAULT
        seeds = design.seed_values(F0)
        for key, (lo, hi, value) in seeds.items():
            got_lo, got_hi = section._range(key)
            assert abs(got_lo - lo) < 0.1 and abs(got_hi - hi) < 0.1, key
            assert abs(section._value(key) - value) < 0.1 * (hi - lo), key
        # ... and the reset is what a later snapshot saves.
        assert section.snapshot() == _section(design).snapshot(), design.key


# --------------------------------------------------------------------------- #
# The spec
# --------------------------------------------------------------------------- #
def test_spec_auto_ladder_when_the_length_bounds_are_cleared():
    for design, section in _each_design():
        section._lo[design.LENGTH_KEY].ChangeValue("")
        section._hi[design.LENGTH_KEY].ChangeValue("")
        spec = section._spec()
        assert spec["design"] is design
        assert spec["scan_param"] == design.LENGTH_KEY
        assert spec["sweep_lo"] is None and spec["sweep_hi"] is None
        # Every parameter is carried, plus the area marker and the target.
        assert sorted(spec["values"]) == sorted(p.key for p in design.params)
        assert spec["f0_ghz"] == F0 and spec["feed_layer"] == "F_Cu"
        assert spec["area"] and spec["edge"] == "bottom"
        assert spec["band_ghz"] == [2.4, 2.4835]
        assert spec["impedance_ohm"] == 50.0 and spec["return_loss_db"] == 10.0


def test_spec_of_a_bounded_sweep_holds_the_others_fixed():
    for design, section in _each_design():
        for param in design.params:
            if param.key == design.LENGTH_KEY:
                continue
            section._radio[section._swept_param()].SetValue(False)
            section._radio[param.key].SetValue(True)
            spec = section._spec()
            assert spec["scan_param"] == param.key
            lo, hi = section._range(param.key)
            assert (spec["sweep_lo"], spec["sweep_hi"]) == (lo, hi)
            # The swept row's own value is a placeholder at the sweep's low
            # end (the driver overrides it per candidate); the rest are the
            # sliders' fixed values.
            assert spec["values"][param.key] == lo
            for other in design.params:
                if other.key != param.key:
                    assert spec["values"][other.key] == section._value(other.key)


def test_spec_rejects_a_single_value_sweep():
    design = registry.DESIGNS[0]
    section = _section(design)
    section._radio[design.LENGTH_KEY].SetValue(False)
    section._radio[design.WIDTH_KEY].SetValue(True)
    section._lo[design.WIDTH_KEY].ChangeValue("1.0")
    section._hi[design.WIDTH_KEY].ChangeValue("1.0")
    try:
        section._spec()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "single value" in str(exc)


def test_spec_rejects_a_length_below_the_floor():
    design = registry.DESIGNS[0]
    section = _section(design)
    section._radio[design.LENGTH_KEY].SetValue(False)
    section._radio[design.WIDTH_KEY].SetValue(True)
    section._val[design.LENGTH_KEY].ChangeValue("0.5")  # the held length
    try:
        section._spec()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert f"{sizing.MIN_TOTAL_MM:g} mm" in str(exc)


# --------------------------------------------------------------------------- #
# The candidate the preview draws (design.fit)
# --------------------------------------------------------------------------- #
def test_a_candidate_too_long_for_the_area_is_still_a_shape_to_draw():
    """A candidate the area can't hold is reported, not raised, and it comes
    with the geometry the preview puts on the marker layer instead of on
    copper (design.fit.Fit.preview)."""
    for design, section in _each_design():
        key = design.LENGTH_KEY
        section._lo[key].ChangeValue("10")
        section._hi[key].ChangeValue("10000")  # far past any starter area
        section._sl[key].SetValue(100)
        state, spec = section._candidate()
        assert not state.ok, design.key
        assert state.preview is state.overflow is not None, design.key
        assert state.detail, design.key  # ... and why it doesn't fit
        assert spec["area"] == section.page.area.spec()["area"]


def test_the_candidate_cannot_be_asked_for_without_a_marker():
    """No marker / an unusable row is the area section's and the rows' story
    to tell; here it is simply an error, which the preview reports on its
    status line (_preview_failed) instead of drawing anything."""

    class _NoMarker:
        def spec(self):
            raise RuntimeError("place the area marker first")

        def _markers(self):
            return []

    design = registry.DESIGNS[0]
    section = _section(design)
    section.page.area = _NoMarker()
    try:
        section._candidate()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "area marker" in str(exc)
    section.on_preview()  # ... and it is only a status
    assert "✗" in section._status_label.GetLabel()

    section = _section(design)
    section._val[design.WIDTH_KEY].ChangeValue("")  # unusable width row
    try:
        section._candidate()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert design.param_label(design.WIDTH_KEY).lower() in str(exc)


# --------------------------------------------------------------------------- #
# The copper the advisory overlap check judges (markers.area_checks)
# --------------------------------------------------------------------------- #
def test_nothing_is_spliced_until_a_pass_is_started():
    """The overlap check is about the splice: before Start scan / Generate
    grids the section hands the banner nothing, so a designer just opened
    cannot greet the user with an overlap warning."""
    for design, section in _each_design():
        assert section.spliced_copper() is None, design.key
        section.on_preview()  # sliders alone splice nothing
        assert section.spliced_copper() is None, design.key
        section._start(grid_only=False)  # no board: the pass never starts
        assert section.spliced_copper() is None, design.key


def test_the_sweeps_own_warning_needs_no_pass_and_no_board():
    """The other half of the banner's scan input: the candidates the area
    can't hold, warned about *before* a pass -- unlike the overlap check, which
    is about the splice. A sweep that fits says nothing."""
    for design, section in _each_design():
        key = design.LENGTH_KEY
        # A sweep well inside the design's own starter area: nothing to say.
        section._lo[key].ChangeValue("10")
        section._hi[key].ChangeValue("15")
        assert section.plan_problems() == [], design.key

        # Sweep the resonant length far past any starter area: most of the
        # range no longer fits, and the section says so without a board, a
        # splice or a started pass.
        section._hi[key].ChangeValue("400")
        problems = section.plan_problems()
        assert len(problems) == 1, design.key
        assert problems[0].severity == "warn"
        assert problems[0].id == "area-candidates-skipped"
        assert section.spliced_copper() is None, design.key


def test_a_form_that_cannot_be_planned_warns_about_nothing():
    """A blank value or a missing marker is the rows' and the area section's
    story (the Start scan button tells it); the sweep check stays quiet rather
    than turning it into an area warning."""
    design = registry.DESIGNS[0]
    section = _section(design)
    section._val[design.WIDTH_KEY].ChangeValue("")  # unusable width row
    assert section.plan_problems() == []


def test_the_candidate_count_re_reads_the_plan():
    """How many candidates were asked for is half of "the area holds only 2 of
    the 5", so changing it has to reach the banner -- nothing else would tell
    it, since the drawn preview doesn't move with the count."""
    design = registry.DESIGNS[0]
    section = _section(design)
    before = section.page.area_check_refreshes
    section.count.adjust(9)
    assert section.page.area_check_refreshes == before + 1


def test_a_typed_bound_reaches_the_banner_without_a_preview():
    """A bound is the sweep, so it must re-check even on a board with no
    preview drawn (refresh_preview redraws nothing there and says so)."""
    design = registry.DESIGNS[0]
    section = _section(design)
    assert section.refresh_preview() is False  # _Area has no marker
    before = section.page.area_check_refreshes
    section._hi[design.LENGTH_KEY].type("400")
    assert section.page.area_check_refreshes == before + 1


def _stub_pass(section, spec):
    """Let ``_start`` go through without a board or a solver: everything it
    does with either is out of scope for the results it keeps.

    These passes are started and never finished, and a claim is a file beside
    the board (sim.runlock), so each one is pointed at no board at all --
    otherwise the pass the previous test left running would warn about
    starting this one (test_concurrent_runs)."""
    section._sim_dir = lambda: None
    planned = wizard_scan.plan(spec)
    section._prepare = lambda board, grid_only: (
        spec,
        planned,
        len(planned),
        "work",
        (),
    )
    section._begin_session = lambda: None
    section._start_worker = lambda *a, **k: None
    section.page.log_ctrl = wx_stub.wx.TextCtrl(None)
    return planned


def _start_a_pass(section):
    """Press Start scan with everything ``_start`` does with the board and the
    solver stubbed out: the spec and the planned candidates it recorded the
    splice from."""
    spec = section._spec()
    planned = _stub_pass(section, spec)
    board = scan_section.pcbnew.GetBoard
    scan_section.pcbnew.GetBoard = lambda: object()
    try:
        section._start(grid_only=False)
    finally:
        scan_section.pcbnew.GetBoard = board
    return spec, planned


def test_starting_a_pass_hands_over_the_copper_it_splices():
    """...and once a pass is under way, the whole sweep's copper is what the
    check judges, in the spec frame it was solved in."""
    design = registry.DESIGNS[0]
    section = _section(design)
    before = section.page.area_check_refreshes
    spec, planned = _start_a_pass(section)
    frame, rects = section.spliced_copper()
    assert frame["area"] == spec["area"] and frame["edge"] == spec["edge"]
    assert rects == wizard_scan.spliced_rects(spec, planned) and rects
    # The banner is told to re-read it right away.
    assert section.page.area_check_refreshes > before


def test_a_placement_ends_the_passs_claim_on_the_overlap_check():
    """The winning candidate became a footprint, so the sweep it came from is
    copper on the board rather than copper waiting to be spliced onto it --
    and the recorded sweep covers that candidate, so left standing it warned
    about the antenna overlapping itself (sections/footprint.py calls this)."""
    for design in registry.DESIGNS:
        section = _section(design)
        _start_a_pass(section)
        assert section.spliced_copper() is not None, design.key
        section.forget_splice()
        assert section.spliced_copper() is None, design.key


def test_the_next_pass_records_its_copper_again_after_a_placement():
    """Nothing is silenced for good: with the placed antenna still on the
    board, the next Start scan is exactly when the overlap warning is worth
    having -- so the copper that pass splices is handed over as always."""
    design = registry.DESIGNS[0]
    section = _section(design)
    _start_a_pass(section)
    section.forget_splice()
    section._running = False  # the placement waited for the pass to finish
    spec, planned = _start_a_pass(section)
    frame, rects = section.spliced_copper()
    assert frame["area"] == spec["area"]
    assert rects == wizard_scan.spliced_rects(spec, planned) and rects


# --------------------------------------------------------------------------- #
# The preview stays wanted (so it comes back when the candidate fits again)
# --------------------------------------------------------------------------- #
class _Marker:
    """A placed area marker carrying no drawn preview."""

    def GraphicalItems(self):
        return []


def test_a_marker_that_never_had_a_preview_is_left_alone():
    section = _section(registry.DESIGNS[0])
    section.page.area._markers = lambda: [_Marker()]
    before = section.page.area_check_refreshes
    section.refresh_preview()
    assert section.page.area_check_refreshes == before


def test_a_preview_wiped_by_a_bad_candidate_is_still_redrawn_later():
    """The fix for the vanishing antenna: once a preview has been asked for,
    a redraw is attempted on every later change even though the failed one
    left no copper on the marker to notice -- so growing the area back brings
    the antenna back by itself."""
    section = _section(registry.DESIGNS[0])
    section.page.area._markers = lambda: [_Marker()]
    section.on_preview()  # fails (no board), wants one
    assert section._preview_on is True
    before = section.page.area_check_refreshes
    section.refresh_preview()
    assert section.page.area_check_refreshes == before + 1


def test_placing_the_footprint_stops_the_preview_coming_back():
    """The footprint section clears the preview for good; a later area tweak
    must not redraw the candidate on top of the placed copper."""
    section = _section(registry.DESIGNS[0])
    section.page.area._markers = lambda: [_Marker()]
    section.on_preview()
    section.forget_preview()
    before = section.page.area_check_refreshes
    section.refresh_preview()
    assert section.page.area_check_refreshes == before


def test_a_preview_redraw_rechecks_the_area():
    # on_preview re-runs the advisory checks either way -- the candidate they
    # test just changed (here the stubbed board is absent, the failure path).
    design = registry.DESIGNS[0]
    section = _section(design)
    before = section.page.area_check_refreshes
    section.on_preview()
    assert section.page.area_check_refreshes == before + 1


# --------------------------------------------------------------------------- #
# The buttons
# --------------------------------------------------------------------------- #
def test_both_passes_start_from_the_same_row_at_rest():
    design = registry.DESIGNS[0]
    section = _section(design)
    assert section.scan_btn.GetLabel() == "Start scan"
    assert section.grids_btn.enabled


def test_a_running_pass_turns_the_scan_button_into_cancel_and_locks_grids():
    """One pass at a time, either kind: whichever is running is cancelled
    through the first button -- which names it -- and Generate grids can't
    race it."""
    for design in registry.DESIGNS:
        for grid_only, cancel in ((False, "Cancel scan"), (True, "Cancel grids")):
            section = _section(design)
            section._running = True
            section._grid_only = grid_only
            section._sync_scan_buttons()
            assert section.scan_btn.GetLabel() == cancel, design.key
            assert not section.grids_btn.enabled

            section._running = False
            section._sync_scan_buttons()
            assert section.scan_btn.GetLabel() == "Start scan"
            assert section.grids_btn.enabled


# --------------------------------------------------------------------------- #
# The last scan, read back from its folder (design.scan_store)
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _board_in(folder):
    """A board saved in ``folder`` for the duration of the block, so
    simulate.scan_dir points at a temp tree. pcbnew is the shared stub other
    test files drive, so the patch is put back afterwards."""

    class _Board:
        def GetFileName(self):
            return str(pathlib.Path(folder) / "board.kicad_pcb")

    saved = scan_section.pcbnew.GetBoard
    scan_section.pcbnew.GetBoard = _Board
    try:
        yield
    finally:
        scan_section.pcbnew.GetBoard = saved


def _scan_folder(project, design):
    return pathlib.Path(project) / "simulation" / "wizard" / design.key


def _measured(section):
    """A finished scan's rows for ``section``'s current spec: the planner's
    real candidates with numbers on them."""
    spec = section._spec()
    rows = wizard_scan.plan(spec)
    for i, row in enumerate(rows):
        row.update({"f_res_ghz": F0, "s11_db": -18.0 - i, "bw_mhz": 150.0})
    return rows, spec


def test_a_saved_scan_is_read_back_when_the_wizard_opens():
    """The point of the store: a session that ran no scan still has the last
    one's candidates to place, and the footprint section is told so."""
    for design, section in _each_design():
        project = tempfile.mkdtemp(prefix="scan_saved_")
        rows, spec = _measured(section)
        scan_store.save(_scan_folder(project, design), rows, spec)
        with _board_in(project):
            assert section.load_saved() is True, design.key
        results, ctx = section.results()
        assert results == rows, design.key
        assert ctx["design"] is design, design.key
        assert ctx["area"] == spec["area"], design.key
        assert section.saved_scan().when, design.key
        assert section.page.footprint.notes, design.key


def test_a_board_with_no_saved_scan_restores_nothing():
    for design, section in _each_design():
        with _board_in(tempfile.mkdtemp(prefix="scan_empty_")):
            assert section.load_saved() is False, design.key
        assert section.results() == ([], None), design.key
        assert section.saved_scan() is None, design.key
        assert section.page.footprint.notes == [], design.key


def test_a_saved_scan_never_shadows_this_sessions_results():
    """This session's scan is the newer truth -- and the sliders' own row is
    not a scan at all, so neither is overwritten by what the folder holds."""
    design = registry.DESIGNS[0]
    section = _section(design)
    project = tempfile.mkdtemp(prefix="scan_live_")
    rows, spec = _measured(section)
    scan_store.save(_scan_folder(project, design), rows, spec)
    mine = [dict(rows[0], s11_db=-30.0)]
    section._results, section._ctx = mine, spec
    with _board_in(project):
        assert section.load_saved() is False
    assert section.results()[0] is mine
    assert section.saved_scan() is None  # these are this session's own


def test_starting_a_scan_forgets_the_saved_one():
    """The restored rows are about to be replaced by the pass that is
    starting, so nothing may go on calling them a saved scan."""
    design = registry.DESIGNS[0]
    section = _section(design)
    project = tempfile.mkdtemp(prefix="scan_forget_")
    rows, spec = _measured(section)
    scan_store.save(_scan_folder(project, design), rows, spec)
    with _board_in(project):
        assert section.load_saved() is True
        assert section.saved_scan() is not None
        _stub_pass(section, spec)
        section._start(grid_only=False)
    assert section.saved_scan() is None
    assert section.results() == ([], spec)


def test_a_saved_scan_that_cannot_be_trusted_is_logged_not_raised():
    """Reopening a wizard must not fail because of what an old folder holds:
    the store's reason goes to the run log and the section carries on."""
    design = registry.DESIGNS[0]
    section = _section(design)
    project = tempfile.mkdtemp(prefix="scan_bad_")
    folder = _scan_folder(project, design)
    rows, spec = _measured(section)
    scan_store.save(folder, rows, spec)
    payload = json.loads((folder / scan_store.FILE).read_text(encoding="utf-8"))
    payload["version"] = scan_store.VERSION + 99
    (folder / scan_store.FILE).write_text(json.dumps(payload), encoding="utf-8")
    with _board_in(project):
        assert section.load_saved() is False
    assert section.results() == ([], None)
    assert any("last scan" in line for line in section.page.lines)


def test_a_grid_pass_leaves_the_saved_scan_alone():
    """A grid pass measures nothing, so the last real scan's file stays the
    last numbers anybody measured -- in the folder as in memory."""
    design = registry.DESIGNS[0]
    section = _section(design)
    project = tempfile.mkdtemp(prefix="scan_grids_")
    folder = _scan_folder(project, design)
    rows, spec = _measured(section)
    scan_store.save(folder, rows, spec)
    with _board_in(project):
        assert section.load_saved() is True
        _stub_pass(section, spec)
        section._start(grid_only=True)
        assert section.saved_scan() is not None
        assert section.results()[0] == rows
    assert scan_store.load(folder).results == rows


# --------------------------------------------------------------------------- #
# The handoff
# --------------------------------------------------------------------------- #
def test_the_spec_the_section_builds_plans_a_real_scan():
    """The section's spec must be exactly what the driver expects -- the seam
    between the GUI and the headless scan, for every design."""
    for design, section in _each_design():
        section._lo[design.LENGTH_KEY].ChangeValue("")
        section._hi[design.LENGTH_KEY].ChangeValue("")
        rows = wizard_scan.plan(section._spec())
        # Up to the requested candidate count -- an area that can't hold the
        # top of the ladder clips those rungs onto its capacity, and the
        # ladder drops the duplicates.
        assert 0 < len(rows) <= section.count.GetValue(), design.key
        assert all(r["error"] is None for r in rows), design.key
        assert all(r["design"] == design.key for r in rows)
        assert all(r["geom"] for r in rows)


def test_a_single_candidate_is_a_scan_too():
    """One candidate is allowed (COUNT_RANGE), and it plans one run: the
    middle of the sweep, which on the automatic length ladder is the lambda/4
    estimate. The quick "simulate just this shape" pass."""
    for design, section in _each_design():
        section.count.SetValue(1)
        assert section.count.GetValue() == 1, design.key  # not clamped to 2
        for param in design.params:
            section._radio[section._swept_param()].SetValue(False)
            section._radio[param.key].SetValue(True)
            rows = wizard_scan.plan(section._spec())
            assert len(rows) == 1, (design.key, param.key)
            assert rows[0]["error"] is None, (design.key, param.key)
        # ...and on the auto ladder (both bounds blank), where the one rung is
        # the estimate itself.
        section._radio[section._swept_param()].SetValue(False)
        section._radio[design.LENGTH_KEY].SetValue(True)
        section._lo[design.LENGTH_KEY].ChangeValue("")
        section._hi[design.LENGTH_KEY].ChangeValue("")
        rows = wizard_scan.plan(section._spec())
        assert len(rows) == 1, design.key
        est = sizing.quarter_wave_mm(section._spec()["f0_ghz"])
        assert rows[0]["values"][design.LENGTH_KEY] == sizing.snap(est, est), design.key


def test_one_candidate_may_pin_an_exact_value():
    """Equal bounds are rejected as a sweep (above) -- but at one candidate
    they are how the single run is pinned to a value instead of landing in the
    middle of a range."""
    design = registry.DESIGNS[0]
    section = _section(design)
    section._radio[design.LENGTH_KEY].SetValue(False)
    section._radio[design.WIDTH_KEY].SetValue(True)
    section._lo[design.WIDTH_KEY].ChangeValue("1.0")
    section._hi[design.WIDTH_KEY].ChangeValue("1.0")
    section.count.SetValue(1)
    rows = wizard_scan.plan(section._spec())
    assert len(rows) == 1
    assert rows[0]["values"][design.WIDTH_KEY] == 1.0


def test_every_bounded_sweep_also_plans():
    for design, section in _each_design():
        for param in design.params:
            section._radio[section._swept_param()].SetValue(False)
            section._radio[param.key].SetValue(True)
            rows = wizard_scan.plan(section._spec())
            assert rows, (design.key, param.key)
            assert all(r["error"] is None for r in rows), (design.key, param.key)


if __name__ == "__main__":
    run_module_tests(globals())
