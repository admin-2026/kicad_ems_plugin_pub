"""AreaBanner: the wizard's advisory area-marker banner, docked under its form.

It runs the area-marker checks (markers.area_checks -- the scanned antenna's
copper over existing metal in the area, feed-axis grounding / shielding, and
copper stacked over the area) against the live board and lists them as
**warnings** in the shared banner strip (banner.BannerSection). Unlike the
simulate view's PreflightBanner these never gate anything: the checks flag
reasons to look, not blockers (see dev_docs/area-checks.md). It refreshes when the
wizard is shown, when the area marker is reshaped/placed, when the previewed
candidate changes, when a scan or grid pass is started, and when the window
regains focus (the user may move the marker in the editor and come back).

Two rows come from the scan section rather than the board:

* ``spliced_copper()`` -- the copper the last started pass splices into the
  feed layer -- feeds the overlap check (``_overlap_rows``). Until Start scan
  or Generate grids is pressed there is no such copper and that check says
  nothing: it is about the splice, and a candidate sitting in the sliders
  splices nothing. Placing a footprint ends it the same way (section 3 calls
  ``forget_splice``): the pass' winner is copper on the board now, not copper
  waiting to go onto it.
* ``plan_problems()`` -- the candidates of the current sweep the **area marker
  can't hold**, which a pass skips rather than simulates
  (design.wizard_scan.Plan). This one deliberately does *not* wait for a pass:
  it needs no board and no splice, only the rows and the rectangle, and the
  whole value of it is being told before the scan is paid for that it will run
  two of the five candidates asked for. A sweep that fits says nothing.

The *previewed* candidate not fitting is still not a row here, and needs no
words: the wizard draws it on the marker's own layer, spilling out of the
rectangle (sections/scan.py + design.fit), which shows how much too big it is
better than a sentence could. The plan's row is the other question -- not "is
this shape too big" but "how much of the sweep survives", which nothing on the
board shows.

Help rows open the same way as the pre-flight banner's (BannerSection), through
the page's viewer hub -- for the wizard that is the simulate view's, borrowed
like its result windows (pages.wizard.DesignWizardPage.viewers).
"""

from ...markers import area_checks
from .banner import BannerSection


class AreaBanner(BannerSection):
    _check_name = "area"

    def _collect(self):
        import pcbnew

        board = pcbnew.GetBoard()
        if board is None:
            return []
        # The spliced copper comes from the scan section (see the module
        # docstring); guarded because it is built after this banner's first
        # callers exist, and None-quiet on its own before a pass is started.
        scan = getattr(self.page, "scan", None)
        return (
            self._overlap_rows(board, scan)
            + self._plan_rows(scan)
            + area_checks.area_problems(board, self.page.feed_layer_name())
        )

    def _plan_rows(self, scan):
        """The sweep's own advisory: the candidates the area marker can't hold,
        which a pass skips (ScanSection.plan_problems). Board-free -- the rows
        and the rectangle decide it -- so it holds its place in the banner even
        while the board-reading checks below have nothing to say."""
        return [] if scan is None else scan.plan_problems()

    def _overlap_rows(self, board, scan):
        """The antenna-overlap warning for the copper the last started pass
        splices (ScanSection.spliced_copper), against the live board -- so it
        clears as soon as the user moves the copper out of the way. Nothing
        before a pass is started: that check is about the splice, and the
        sliders alone splice nothing. It sits ahead of the board-only checks,
        the order markers.area_checks.CHECKS reads in."""
        spliced = None if scan is None else scan.spliced_copper()
        if spliced is None:
            return []
        frame, rects = spliced
        return area_checks.antenna_problems(
            board, self.page.feed_layer_name(), frame, rects
        )
