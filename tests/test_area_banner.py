"""The designer's banner and the rows that stop a scan
(gui.sections.area_banner).

A designer starts the solver -- a scan is one solve per candidate of the sweep
-- so its banner has to carry what would stop one, the same rows the simulate
view's does: the board's pre-flight and this machine's container. It carried
neither until they moved into the shared base, which is what this file is here
to keep true.

The rows themselves belong to other tests (emkit's test_preflight.py for what
they say, test_banner_container.py for the base's rules). Here the board is
deliberately empty of area problems, which is the interesting case: with the
page's own check saying nothing, the blockers must still be there, because they
are not about the marker at all.

    python3 tests/test_area_banner.py   (or pytest)
"""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx and pcbnew)
from bare_package import load, run_module_tests  # noqa: E402

area_banner = load("gui.sections.area_banner")
banner = load("emkit.gui.sections.banner")
simulate = load("emkit.sim.simulate")

wx = wx_stub.wx
pcbnew = sys.modules["pcbnew"]

NO_DOCKER = simulate.Problem(
    "docker-not-ready", "block", "the docker command was not found"
)
UNSAVED = simulate.Problem("board-unsaved", "block", "the board was never saved")


class _Page:
    """Just what the banner reads off a designer page."""

    def __init__(self):
        self.scan = None
        self.logged = []

    def log(self, text):
        self.logged.append(text)

    def relayout_footer(self):
        pass

    def _relayout_scroll(self):
        pass

    def feed_layer_name(self):
        return "F.Cu"


@contextlib.contextmanager
def _machine(rows=(), board=()):
    """The two answers stood in for, and the container's worker run here and
    now (the banner asks off the wx thread). The remembered answer is module
    state shared with every other test in this process, so it is emptied at
    both ends."""
    kept = (
        simulate.container_problems,
        simulate.preflight,
        banner.run_async,
        pcbnew.GetBoard,
    )
    banner._probed = None
    simulate.container_problems = lambda: list(rows)
    simulate.preflight = lambda _board, _params=None: list(board)
    banner.run_async = lambda work: work()
    pcbnew.GetBoard = lambda: object()
    try:
        yield
    finally:
        (
            simulate.container_problems,
            simulate.preflight,
            banner.run_async,
            pcbnew.GetBoard,
        ) = kept
        banner._probed = None


def _ids(rows):
    return [p.id for p in rows]


def test_a_designer_says_what_would_stop_its_scan():
    # The area checks have nothing to say here, and the rows are there anyway:
    # what they report is the board and the machine, not the marker.
    with _machine(rows=[NO_DOCKER], board=[UNSAVED]):
        problems = area_banner.AreaBanner(_Page()).refresh()
    assert _ids(problems) == ["board-unsaved", "docker-not-ready"]


def test_a_designer_with_nothing_in_the_way_shows_an_empty_banner():
    with _machine():
        assert area_banner.AreaBanner(_Page()).refresh() == []


if __name__ == "__main__":
    run_module_tests(globals())
