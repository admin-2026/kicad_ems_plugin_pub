"""The wizard's Results box: this board's last scan, as one page per view.

The shape -- a titled box of view buttons over a status line that says why a
view is not there yet -- is the core's ``ResultsSection``; what is here is the
one view only a design wizard has.
"""

from ...emkit.gui import viewers
from ...emkit.gui.sections.results import ResultsSection, _kind_of


class ScanResultsSection(ResultsSection):
    """The wizard's Results box: this board's last scan, as one page per view.

    A scan is a folder of runs, and what it leaves beside them is a manifest
    naming every candidate (design.scan_views). The viewer opened on one shows
    a run switcher over the whole sweep, so a single page covers the scan --
    there is nothing archived, because the candidates' dumps stay where the
    scan put them. The report shares the results window with a run's pages; the
    grids get their own, so a finished scan can show both at once.

    A grid-only pass (Generate grids) writes the grid manifest alone and
    removes the report's, so after one the report button says there is none
    rather than opening the previous scan's data under freshly meshed
    candidates.
    """

    _TITLE = "Scan results"
    _NOTE = (
        "This board's last scan — every candidate in one page, stepped "
        "through from the run list."
    )
    _TIP = "Open the {key} view of this board's last scan"
    _MISSING = "No scan {key} yet — run a scan first."

    # The keys are design.scan_views kinds (its MANIFEST_FILES names each).
    _VIEWS = (
        ("Show scan report", "report", "Scan — report", viewers.RESULTS),
        ("Show scan grids", "grid", "Scan — grid views", viewers.SCAN_GRID),
    )

    def _locate(self, board, key):
        """This *design's* scan folder (each topology scans into its own, so
        one wizard's results never shadow another's). The view keys are
        scan_views' own kinds, so its MANIFEST_FILES names the manifest to
        open -- missing when the last pass didn't write that view (a grid-only
        pass writes no report)."""
        from ...design import scan_views
        from ...emkit.sim import simulate

        path = (
            simulate.scan_dir(board, self.page.design.key)
            / scan_views.MANIFEST_FILES[key]
        )
        return path if path.is_file() else None

    def _url(self, path):
        """The viewer page for a scan manifest: the same report/grid page a
        single run opens, pointed at several runs instead of one."""
        from ...design import scan_views
        from ...emkit.sim import simulate

        return simulate.viewer_url(
            self._sim_dir(),
            _kind_of(path, scan_views.MANIFEST_FILES),
            path,
            simulate.SCAN,
        )
