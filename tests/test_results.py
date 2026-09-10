"""Tests for what a run leaves and what shows it (no KiCad, no wx).

The solver writes data, never pages: a run's whole deliverable is the two
"pcb_*.js" dumps (simulate.DUMPS), which the next run overwrites in place, so
archive_dump copies each run's into a per-run folder (results/<stamp>/) and
latest_result finds the newest.

What draws them is the viewer the plugin ships (antenna_plugin/viewer/):
install_viewer puts a copy in the board's simulation folder, and viewer_url
names a page in it with the dump -- or a whole scan's manifest -- in its query,
relative to the page so the project folder stays movable. The package is
assembled by hand around the real modules because antenna_plugin/__init__
imports pcbnew:

    python3 tests/test_results.py
"""

import os
import pathlib
import tempfile
import time
import urllib.parse

from bare_package import load

_ROOT = pathlib.Path(__file__).resolve().parents[1]

results = load("emkit.sim.results")
simulate = load("emkit.sim.simulate")

# The dumps this product's solver writes. Named through simulate rather than
# spelled out: the core's tests run in every assembled product, and a flow's
# dumps are its own (product.DUMPS -- pcb_data.js here, scattering_data.js
# next door). What is asserted below is the *shape* of an archive, not one
# runner's file names.
GRID_JS = simulate.DUMPS[simulate.GRID]
DATA_JS = simulate.DUMPS[simulate.REPORT]
REPORT_PAGE = simulate.PAGES[simulate.REPORT]


def _write_dumps(run_dir, **bodies):
    """The dumps a solver pass leaves in its outdir, by kind."""
    for kind, body in bodies.items():
        (run_dir / simulate.DUMPS[kind]).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# archiving a run
# --------------------------------------------------------------------------- #
def test_archive_dump_copies_it_into_the_run_folder():
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, grid="window.FDTD={s:{}};")
        archived = pathlib.Path(
            simulate.archive_dump(str(run), simulate.GRID, "20260720-101112")
        )
        assert archived == run / "results" / "20260720-101112" / GRID_JS
        assert archived.read_text() == "window.FDTD={s:{}};"
        # The dump in the run dir is untouched (the binary overwrites it next
        # run); the archive is a copy, not a move.
        assert (run / GRID_JS).is_file()


def test_archiving_the_report_takes_the_runs_data_dump():
    """The report's data is the run's own data dump -- the file every reader of
    these results opens -- and nothing named after a page is invented."""
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, report='window.FDTD={s:{"run":{}}};')
        archived = pathlib.Path(
            simulate.archive_dump(str(run), simulate.REPORT, "20260720-101112")
        )
        assert archived.name == DATA_JS
        assert archived.read_text() == 'window.FDTD={s:{"run":{}}};'
        assert not list(archived.parent.glob("*.html"))


def test_a_bare_json_dump_is_archived_with_the_run_that_wrote_it():
    """``output_json`` puts a readable copy of the same numbers beside the
    page's dump. It lands in the outdir like everything else, so the next run
    overwrites it -- archiving it with the run is what makes "read run X back"
    answerable at all."""
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, report='window.FDTD={s:{"run":{}}};')
        data = run / simulate.JSON_DUMPS[simulate.REPORT]
        data.write_text('{"run":{}}', encoding="utf-8")
        archived = pathlib.Path(
            simulate.archive_dump(str(run), simulate.REPORT, "20260720-101112")
        )
        kept = archived.parent / data.name
        assert kept.read_text() == '{"run":{}}'
        assert data.is_file()  # a copy, like the dump beside it


def test_a_run_that_wrote_no_json_archives_none():
    """The tick is off by default, and a run without it is not a broken run:
    the archive simply holds the one dump."""
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, report="window.FDTD={s:{}};")
        archived = pathlib.Path(
            simulate.archive_dump(str(run), simulate.REPORT, "20260720-101112")
        )
        assert not list(archived.parent.glob("*.json"))


def test_latest_result_picks_newest_stamp_folder():
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, grid="window.FDTD={s:{}};")
        for stamp in ("20260720-090000", "20260720-100000", "20260719-235959"):
            simulate.archive_dump(str(run), simulate.GRID, stamp)
        latest = simulate.latest_result(str(run), simulate.GRID)
        assert pathlib.Path(latest).parent.name == "20260720-100000"
        # No report archived yet -> None, and a fresh run dir -> None.
        assert simulate.latest_result(str(run), simulate.REPORT) is None
        assert simulate.latest_result(str(run / "nope"), simulate.GRID) is None


def test_the_json_flavour_is_found_beside_the_dump_it_belongs_to():
    """Asked of the archive, not of the form: whether a run wrote one is a fact
    about that run, and the board's form may have been re-ticked since."""
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, report="window.FDTD={s:{}};")
        dump = simulate.archive_dump(str(run), simulate.REPORT, "20260720-101112")
        assert results.data_json(dump) is None
        (run / simulate.JSON_DUMPS[simulate.REPORT]).write_text("{}", encoding="utf-8")
        dump = simulate.archive_dump(str(run), simulate.REPORT, "20260720-101113")
        assert results.data_json(dump) == f"{dump[: -len('.js')]}.json"


def test_result_timestamp_from_folder_name():
    p = f"/x/simulation/results/20260720-101112/{DATA_JS}"
    assert simulate.result_timestamp(p) == "2026-07-20 10:11:12"
    assert simulate.result_timestamp(f"/x/results/not-a-stamp/{GRID_JS}") is None


def test_when_a_report_was_written_is_not_when_its_run_started():
    """The two clocks a result carries. `run sample` writes a report minutes
    into the run whose stamp names it, so reading the stamp as the writing
    time dates a fresh reading to before the solver produced it."""
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, report="window.FDTD={s:{}};")
        dump = simulate.archive_dump(str(run), simulate.REPORT, "20200101-000000")
        # An hour of solving between the stamp and the report it wrote.
        written = time.time() + 3600
        os.utime(dump, (written, written))
        assert simulate.result_timestamp(dump) == "2020-01-01 00:00:00"
        assert simulate.dump_written(dump) == time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(written)
        )
        payload = results.read(str(run), dump)
        assert payload["stamp"] == "2020-01-01 00:00:00"
        assert payload["written"] == simulate.dump_written(dump)


def test_a_dump_that_cannot_be_stat_ed_has_no_written_time():
    # Best effort, like the viewer url beside it: a missing clock is a missing
    # line, never a raised error over a result that is otherwise readable.
    assert simulate.dump_written("/nowhere/at/all/pcb_data.js") is None


# --------------------------------------------------------------------------- #
# the viewer that draws it
# --------------------------------------------------------------------------- #
def test_install_viewer_copies_the_shipped_pages():
    with tempfile.TemporaryDirectory() as td:
        viewer = simulate.install_viewer(pathlib.Path(td))
        assert viewer == pathlib.Path(td) / "viewer"
        for page in simulate.PAGES.values():
            assert (viewer / page).is_file()
        # The pages are useless without what they load.
        assert (viewer / "vendor" / "three.js").is_file()
        assert (viewer / "css" / "theme.css").is_file()
        assert (viewer / "js" / "dump.js").is_file()


def test_the_installed_viewer_is_only_what_a_page_loads():
    """The viewer folder is copied wholesale into a user's project, so anything
    put beside the pages lands there too. Documentation about the viewer lives
    in docs/viewer.md for exactly that reason -- a stray README in a board's
    simulation folder is litter."""
    with tempfile.TemporaryDirectory() as td:
        viewer = simulate.install_viewer(pathlib.Path(td))
        stray = [
            p.relative_to(viewer).as_posix()
            for p in viewer.rglob("*")
            if p.is_file() and p.suffix not in (".html", ".css", ".js")
        ]
        # The install stamp is the one file that is not a page or its parts.
        assert stray == [simulate._VIEWER_STAMP]


def test_install_viewer_is_idempotent_but_repairs_a_damaged_copy():
    with tempfile.TemporaryDirectory() as td:
        viewer = simulate.install_viewer(pathlib.Path(td))
        # A second install of an unchanged viewer leaves the folder alone --
        # opening a result twice must not recopy three quarters of a megabyte.
        marker = viewer / "js" / "dump.js"
        marker.write_text("edited", encoding="utf-8")
        simulate.install_viewer(pathlib.Path(td))
        assert marker.read_text() == "edited"
        # Losing the stamp is how a partial or interrupted copy shows up, and
        # that does get replaced.
        (viewer / ".installed").unlink()
        simulate.install_viewer(pathlib.Path(td))
        assert marker.read_text() != "edited"


def _query(url):
    """The one query parameter of a viewer URL, as (key, value)."""
    base, _, query = url.partition("?")
    key, _, value = query.partition("=")
    return key, urllib.parse.unquote(value), base


def test_viewer_url_points_a_page_at_a_dump_relative_to_itself():
    with tempfile.TemporaryDirectory() as td:
        sim = pathlib.Path(td)
        dump = sim / "results" / "20260720-101112" / DATA_JS
        dump.parent.mkdir(parents=True)
        dump.write_text("window.FDTD={s:{}};", encoding="utf-8")
        url = simulate.viewer_url(sim, simulate.REPORT, dump)
        key, value, base = _query(url)
        assert base.startswith("file://")
        assert base.endswith(f"/viewer/{REPORT_PAGE}")
        # Relative to the page, and with forward slashes whatever the OS uses,
        # so a copied project folder still opens.
        assert (key, value) == ("d", f"../results/20260720-101112/{DATA_JS}")
        # And the viewer came along with the URL.
        assert (sim / "viewer" / REPORT_PAGE).is_file()


def test_viewer_url_points_a_page_at_a_whole_scans_manifest():
    with tempfile.TemporaryDirectory() as td:
        sim = pathlib.Path(td)
        manifest = sim / "wizard" / "lmonopole" / "scan_grid.js"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("window.FDTD_SCAN={};", encoding="utf-8")
        url = simulate.viewer_url(sim, simulate.GRID, manifest, simulate.SCAN)
        key, value, base = _query(url)
        assert base.endswith("/viewer/grid.html")
        assert (key, value) == ("scan", "../wizard/lmonopole/scan_grid.js")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
