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

import importlib
import pathlib
import sys
import tempfile
import types
import urllib.parse

_ROOT = pathlib.Path(__file__).resolve().parents[1]

_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(_ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)
simulate = importlib.import_module("antenna_plugin.sim.simulate")


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
        assert archived == run / "results" / "20260720-101112" / "pcb_grid.js"
        assert archived.read_text() == "window.FDTD={s:{}};"
        # The dump in the run dir is untouched (the binary overwrites it next
        # run); the archive is a copy, not a move.
        assert (run / "pcb_grid.js").is_file()


def test_archiving_the_report_takes_the_runs_data_dump():
    """The report's data is the run's pcb_data.js -- the file every reader of
    these results opens -- and nothing named after a page is invented."""
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        _write_dumps(run, report='window.FDTD={s:{"run":{}}};')
        archived = pathlib.Path(
            simulate.archive_dump(str(run), simulate.REPORT, "20260720-101112")
        )
        assert archived.name == "pcb_data.js"
        assert archived.read_text() == 'window.FDTD={s:{"run":{}}};'
        assert not list(archived.parent.glob("*.html"))


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


def test_result_timestamp_from_folder_name():
    p = "/x/simulation/results/20260720-101112/pcb_data.js"
    assert simulate.result_timestamp(p) == "2026-07-20 10:11:12"
    assert simulate.result_timestamp("/x/results/not-a-stamp/pcb_grid.js") is None


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
        dump = sim / "results" / "20260720-101112" / "pcb_data.js"
        dump.parent.mkdir(parents=True)
        dump.write_text("window.FDTD={s:{}};", encoding="utf-8")
        url = simulate.viewer_url(sim, simulate.REPORT, dump)
        key, value, base = _query(url)
        assert base.startswith("file://") and base.endswith("/viewer/report.html")
        # Relative to the page, and with forward slashes whatever the OS uses,
        # so a copied project folder still opens.
        assert (key, value) == ("d", "../results/20260720-101112/pcb_data.js")
        # And the viewer came along with the URL.
        assert (sim / "viewer" / "report.html").is_file()


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
