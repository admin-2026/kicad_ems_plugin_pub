"""The rows every run-starting page's banner carries (gui.sections.banner), on
the wx stand-in.

The rows themselves are written elsewhere (sim.simulate.preflight and
container_problems, both checked in test_preflight.py). What is checked here is
the part that turned out to be easy to get wrong when a second page needed it:

* **which pages ask.** A banner on a page that can start the solver shows what
  would stop one -- the board's blockers and the machine's container -- and one
  on a page that starts nothing shows neither. Both used to be the simulate
  view's alone, so a designer offered a Start scan button on an unsaved board
  with no Docker and said nothing until it was pressed.
* **how often, and on which thread.** The probe is two subprocesses and a
  banner refreshes on a keystroke, so the answer is fetched on a worker
  (``run_async``, replaced here so what is checked is the sequence and not a
  race) and then shared by every banner in the window for a few seconds. A
  check of exactly this shape on the wx thread is what made the window
  sluggish after a scan once already.
* **that the cache can be dropped**, since the two things that change the
  answer while the window is open -- the About page's tick and its Build
  button -- are both things the user does deliberately and then walks away
  from.

    python3 tests/test_banner_container.py   (or pytest)
"""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs the stand-in wx)
from bare_package import load, run_module_tests  # noqa: E402

banner = load("emkit.gui.sections.banner")
simulate = load("emkit.sim.simulate")

wx = wx_stub.wx
pcbnew = sys.modules["pcbnew"]

BLOCKER = simulate.Problem(
    "docker-not-ready",
    "block",
    "the docker command was not found. Install Docker Engine",
)
UNSAVED = simulate.Problem("board-unsaved", "block", "the board was never saved")


class _Page:
    """Just what a banner reads off its page."""

    def __init__(self):
        self.logged = []
        self.footers = 0

    def log(self, text):
        self.logged.append(text)

    def relayout_footer(self):
        self.footers += 1

    def _relayout_scroll(self):
        pass


class _DockerBox:
    """Stands in for the About page's Docker box: the one thing the banner asks
    of it, and a record of how it was asked."""

    def __init__(self, busy=False):
        self.busy = busy  # a build is already running
        self.asked = []

    def start_build(self, rebuild=False, on_done=None):
        self.asked.append(rebuild)
        if self.busy:
            return False
        self.done = on_done
        return True


class _Info:
    """...and for the page that has one."""

    def __init__(self, busy=False):
        self.docker = _DockerBox(busy)


class _Shell:
    """Just what a fix on one page needs of the window: what the pages are."""

    def __init__(self, pages):
        self._pages = list(pages)

    def pages(self):
        return list(self._pages)


class _Runs(banner.BannerSection):
    """A banner on a page that can start the solver."""

    starts_runs = True

    def _collect(self):
        return list(self.own)

    own = ()


class _Reads(_Runs):
    """...and one on a page that cannot."""

    starts_runs = False


@contextlib.contextmanager
def _asking(rows=(BLOCKER,), board=(), fail=None):
    """The board's answer and the machine's stood in for, and the worker run
    here and now -- with the remembered answer emptied at both ends, since it
    is module state shared with every other test in this process.

    ``asked`` comes back with one entry per question actually put: a page that
    starts nothing must not merely filter the answers out, it must not ask.
    """
    kept = (
        simulate.container_problems,
        simulate.preflight,
        banner.run_async,
        pcbnew.GetBoard,
    )
    asked = []

    def machine():
        asked.append("container")
        if fail is not None:
            raise RuntimeError(fail)
        return list(rows)

    def check_board(_board, _params=None):
        asked.append("board")
        return list(board)

    banner._probed = None
    simulate.container_problems = machine
    simulate.preflight = check_board
    banner.run_async = lambda work: work()
    pcbnew.GetBoard = lambda: object()  # a board is open
    try:
        yield asked
    finally:
        (
            simulate.container_problems,
            simulate.preflight,
            banner.run_async,
            pcbnew.GetBoard,
        ) = kept
        banner._probed = None


def _messages(section):
    return [p.message for p in section.refresh()]


# --------------------------------------------------------------------------- #
# which pages ask
# --------------------------------------------------------------------------- #
def test_a_page_that_can_start_a_run_shows_what_would_stop_one():
    with _asking(board=(UNSAVED,)):
        assert _messages(_Runs(_Page())) == [UNSAVED.message, BLOCKER.message]


def test_a_page_that_starts_nothing_is_not_even_asked():
    # Not merely filtered out afterwards: one of these questions is a pair of
    # processes and the other reads the board file, and a page with no button
    # that spends them has no business paying for them.
    with _asking(board=(UNSAVED,)) as asked:
        assert _messages(_Reads(_Page())) == []
        assert asked == []


def test_the_run_blockers_come_before_the_pages_own_rows():
    # They stop every run this page could start, so they are not something to
    # find underneath three advisory warnings.
    section = _Runs(_Page())
    section.own = (simulate.Problem("area-overlap", "warn", "copper overlaps"),)
    with _asking(board=(UNSAVED,)):
        assert _messages(section) == [
            UNSAVED.message,
            BLOCKER.message,
            "copper overlaps",
        ]


def test_a_ready_machine_leaves_the_page_saying_what_it_would_have_said():
    section = _Runs(_Page())
    section.own = (simulate.Problem("area-overlap", "warn", "copper overlaps"),)
    with _asking(rows=()):
        assert _messages(section) == ["copper overlaps"]


def test_a_board_check_that_raises_still_leaves_the_machines_answer():
    # The two are asked separately for this reason: one of them failing must
    # not take the other's row down with it.
    section = _Runs(_Page())
    with _asking() as asked:
        simulate.preflight = _explode
        assert _messages(section) == [BLOCKER.message]
        assert "container" in asked


def _explode(*args, **kwargs):
    raise RuntimeError("the stackup reader fell over")


# --------------------------------------------------------------------------- #
# the button on the row
# --------------------------------------------------------------------------- #
def _hosted(busy=False):
    """A banner on a page in a window that has an About page with the Docker
    box on it -- which is every real window."""
    page = _Page()
    info = _Info(busy)
    page.shell = _Shell([page, info])
    return _Runs(page), info.docker


def _row(state="no_image"):
    return simulate.Problem("docker-not-ready", "block", "no image", state=state)


def test_an_image_that_was_never_built_offers_the_button_that_builds_it():
    # The one state a window can fix by itself, and the row is where the user
    # is standing when they find out.
    section, _box = _hosted()
    label, _handler = section._fix_action(_row())
    assert label == "Build image"


def test_the_button_builds_it_through_the_box_that_owns_the_build():
    # Not a second implementation of the build, and not a page switch: the
    # About page's section does the work and prints the engine's output into
    # its own terminal, which is where four minutes of installing KiCad can
    # actually be watched.
    section, box = _hosted()
    _label, handler = section._fix_action(_row())
    handler(None)
    assert box.asked == [False], "the row did not ask the box to build"
    assert section.page.logged[-1].startswith("Building the container image")


def test_an_image_from_an_older_release_asks_for_a_rebuild():
    # Rebuild and not build: the removal is what keeps it from being a cache
    # hit on the layer that was wrong (sim.container.build).
    section, box = _hosted()
    for state in ("stale", "kicad_older"):
        label, handler = section._fix_action(_row(state))
        assert label == "Rebuild image", state
        handler(None)
    assert box.asked == [True, True]


def test_a_build_already_running_is_said_and_not_started_twice():
    # Every banner in the window shows this row, so the second press may come
    # from another page entirely; the box is the one thing that knows.
    section, box = _hosted(busy=True)
    _label, handler = section._fix_action(_row())
    handler(None)
    assert box.asked == [False]
    assert "already being built" in section.page.logged[-1]


def test_the_row_is_redrawn_when_the_build_ends():
    # However it ended: a failure leaves the same row on screen, and that row
    # still has a disabled "Building…" where its button was.
    section, _box = _hosted()
    with _asking():
        section.refresh()
        state_before = section._state
        section._built(False, "E: Unable to locate package kicad")
    assert "The build failed" in section.page.logged[-1]
    assert state_before is not None and section._state is not None


def test_a_docker_that_is_not_installed_gets_no_button():
    # Nothing in this window fixes it, and a button that cannot do what it
    # says is worse than the sentence the user already has.
    section, _box = _hosted()
    for state in ("no_docker", "no_daemon", "denied"):
        assert section._fix_action(_row(state)) is None, state


def test_a_window_with_no_such_box_offers_nothing():
    # The banner asks what a page has rather than which page it is, so a
    # window arranged differently loses the button and keeps the row.
    section = _Runs(_Page())
    assert section._fix_action(_row()) is None


# --------------------------------------------------------------------------- #
# how often
# --------------------------------------------------------------------------- #
def test_the_answer_is_asked_for_once_and_shared():
    # A banner refreshes on a keystroke, and there are four banners in the
    # window: one probe per refresh per page is the sluggishness bug again.
    with _asking() as asked:
        for section in (_Runs(_Page()), _Runs(_Page())):
            section.refresh()
            section.refresh()
        assert asked.count("container") == 1


def test_nothing_is_asked_on_the_wx_thread():
    # The first refresh draws what is known -- nothing -- and sends a worker.
    # The row arrives when the worker does, which looks like it arriving with
    # the page and never like the window stopping to talk to Docker.
    later = []
    with _asking() as asked:
        banner.run_async = later.append
        section = _Runs(_Page())
        assert section.refresh() == []
        assert "container" not in asked, "the probe ran where the keystrokes are"

        later.pop()()  # the worker, now
        assert [row[0] for row in section._state] == ["docker-not-ready"]


def test_forgetting_the_answer_asks_again():
    # What the About page's tick and its Build button do: the state they just
    # changed must not be answered from before they changed it.
    with _asking() as asked:
        _Runs(_Page()).refresh()
        banner._probed = None
        _Runs(_Page()).refresh()
        assert asked.count("container") == 2


# --------------------------------------------------------------------------- #
# when it goes wrong
# --------------------------------------------------------------------------- #
def test_a_probe_that_raises_hides_the_row_and_never_the_window():
    # Same rule as the banner's own check: a broken check costs a row, it does
    # not stop the page drawing. What a misbehaving engine does is a row of its
    # own from container_problems (test_preflight.py), so what is being
    # survived here is a bug, and it must not be survived by a blank window.
    section = _Runs(_Page())
    section.own = (simulate.Problem("area-overlap", "warn", "copper overlaps"),)
    with _asking(fail="docker exploded"):
        assert _messages(section) == ["copper overlaps"]


if __name__ == "__main__":
    run_module_tests(globals())
