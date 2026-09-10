"""Several passes at once: the warning, and who the shell counts as running.

The shell can drive one run plus one scan per design, and they really do run
together (dev_docs/concurrent-runs.md). Nothing stops that here -- what is tested
is the consent and the bookkeeping behind it: a second pass warns, naming what
is already in flight; a declined one changes nothing at all; and every way a
pass can end takes it back out of the live list, so a warning is never about a
pass that finished long ago.

The claims are files in the board's ``simulation/running/`` folder now
(sim.runlock), not a list in this process, so every section here is pointed at
one temporary directory standing in for one board.

The base's own bookkeeping is driven through a stand-in section (it drives no
solver); the two real ones are checked for what they call themselves and for
asking before they touch anything. See wx_stub.py for what "stubbed" means.

    python3 tests/test_concurrent_runs.py
"""

import importlib
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs wx)
from bare_package import load, run_module_tests  # noqa: E402

registry = load("design.registry")
runlock = load("emkit.sim.runlock")
solver = load("emkit.gui.sections.solver")
run_section = load("gui.sections.run")

# The one board every section in a test shares. Reset by _passes / _run_section,
# which is what "a just-opened shell on a board nothing has run on" means now
# that the live list is a directory rather than a class attribute.
_BOARD = None

# The wizard-scan harness (its stub page, host and area) is that test module's;
# a real ScanSection is built through it rather than stubbing a page twice.
# Imported by hand because it has to come *after* wx_stub -- an import
# statement here would be sorted above it, and it builds real wx sections.
scan_harness = importlib.import_module("test_scan_section")


class _Pass(solver.SolverSection):
    """A section that drives no solver at all: just the base's live-pass
    bookkeeping and its warning, with the answer the test wants."""

    def __init__(self, label, answer=True):
        super().__init__(None)  # no page: nothing here reaches one
        self._label = label
        self.answer = answer
        self.asked = []  # the ``others`` list each warning was given

    def _sim_dir(self):
        return _BOARD

    @property
    def busy_label(self):
        return self._label

    def _confirm_concurrent(self, others):
        self.asked.append(list(others))
        return self.answer


def _passes(*labels):
    """Fresh sections against a board nothing is running on -- the state a
    just-opened shell is in."""
    global _BOARD
    _BOARD = tempfile.mkdtemp(prefix="concurrent_")
    return [_Pass(label) for label in labels]


def _on_the_board(section):
    """Point a real section at the same board the stand-ins are claiming, so
    it can see them (it has no open board of its own here)."""
    section._sim_dir = lambda: _BOARD
    return section


class _RunPage:
    """Just what the Run section reads off its page while being built."""

    def __init__(self):
        self.scroll = object()
        self.lines = []

    def register_wrap(self, label):
        pass

    def _relayout_scroll(self):
        pass

    def log(self, text):
        self.lines.append(text)


def _run_section():
    return _on_the_board(run_section.RunSection(_RunPage(), wx_stub.wx.BoxSizer()))


# --------------------------------------------------------------------------- #
# The live list
# --------------------------------------------------------------------------- #
def test_the_first_pass_is_never_questioned():
    # Nothing else running is the ordinary case: no dialog, no delay.
    (first,) = _passes("the simulation run")
    assert first.confirm_concurrent() is True
    assert first.asked == []


def test_a_second_pass_is_told_what_is_already_running():
    run, scan = _passes("the simulation run", "the L-shaped monopole scan")
    run._claim()
    assert scan.confirm_concurrent() is True
    assert scan.asked == [["the simulation run"]]


def test_a_pass_is_told_about_every_other_one():
    run, mono, ifa = _passes("the simulation run", "the mono scan", "the ifa scan")
    run._claim()
    mono._claim()
    assert ifa.confirm_concurrent() is True
    assert ifa.asked == [["the simulation run", "the mono scan"]]


def test_a_section_is_never_warned_about_itself():
    # It can't happen through the buttons (a running section's button is Stop
    # or Cancel), but "already running" must mean somebody else either way.
    (only,) = _passes("the simulation run")
    only._claim()
    assert only.confirm_concurrent() is True
    assert only.asked == []


def test_declining_leaves_the_second_pass_unstarted():
    run, scan = _passes("the simulation run", "the L-shaped monopole scan")
    run._claim()
    scan.answer = False
    assert scan.confirm_concurrent() is False
    # Refusing to start is not a state change: only the first pass is live,
    # and the second one never called itself running.
    assert scan.running is False
    assert runlock.labels(_BOARD) == ["the simulation run"]


def test_starting_anyway_runs_both():
    run, scan = _passes("the simulation run", "the L-shaped monopole scan")
    run._claim()
    scan._claim()
    assert run.running and scan.running
    assert sorted(runlock.labels(_BOARD)) == sorted(
        ["the simulation run", "the L-shaped monopole scan"]
    )


def test_a_finished_pass_stops_being_counted():
    run, scan = _passes("the simulation run", "the L-shaped monopole scan")
    run._claim()
    run._release()
    assert run.running is False
    assert scan.confirm_concurrent() is True
    assert scan.asked == []  # nothing left to warn about


def test_a_window_closed_mid_run_releases_its_pass():
    # The worker's finish path bails out on a page that is going away, so
    # shutdown is what has to end the pass -- otherwise the next shell would
    # warn about a run that died with the last one.
    run, scan = _passes("the simulation run", "the L-shaped monopole scan")
    run._claim()
    run.shutdown()
    assert runlock.labels(_BOARD) == []
    assert scan.confirm_concurrent() is True
    assert scan.asked == []


def test_releasing_a_pass_that_never_started_is_harmless():
    # Every finish path releases, including the ones a pass can reach without
    # having claimed (a failure before launch).
    (run,) = _passes("the simulation run")
    run._release()
    assert runlock.labels(_BOARD) == []


# --------------------------------------------------------------------------- #
# The wording
# --------------------------------------------------------------------------- #
def test_the_live_passes_are_named_in_one_sentence():
    assert solver._and_list(["the run"]) == "the run"
    assert solver._and_list(["the run", "the scan"]) == "the run and the scan"
    assert (
        solver._and_list(["the run", "the mono scan", "the ifa scan"])
        == "the run, the mono scan and the ifa scan"
    )


def test_each_pass_names_itself_by_what_it_runs():
    # The label is what the warning shows, so it has to say which view to go
    # to if the user would rather stop that pass instead.
    _passes()  # a board of its own; nothing is claimed on it
    section = _run_section()
    section._grid_only = False
    assert section.busy_label == "the simulation run"
    section._grid_only = True
    assert section.busy_label == "the grid pass on the Simulate page"

    for design in registry.DESIGNS:
        scan = scan_harness._section(design)
        scan._grid_only = False
        assert scan.busy_label == f"the {design.name} scan"
        scan._grid_only = True
        assert scan.busy_label == f"the {design.name} grid pass"


# --------------------------------------------------------------------------- #
# The real sections ask first
# --------------------------------------------------------------------------- #
def _decline(section):
    """Make ``section`` answer "no" to the concurrency warning, and record it."""
    section.asked = []

    def confirm(others):
        section.asked.append(list(others))
        return False

    section._confirm_concurrent = confirm


def test_the_scan_asks_before_it_touches_the_board():
    # Declined, the pass must not have plotted gerbers or stripped the drawn
    # preview off the marker -- so the question comes before _prepare.
    (other,) = _passes("the simulation run")
    other._claim()
    scan = _on_the_board(scan_harness._section(registry.DESIGNS[0]))
    _decline(scan)
    scan.on_scan()
    assert scan.asked == [["the simulation run"]]
    assert scan.running is False
    assert scan._spliced is None  # nothing was planned or spliced
    assert scan.page.area_check_refreshes == 0


def test_an_accepted_scan_carries_on_into_the_pass():
    # The same click with "Start anyway": past the question, into the work --
    # which stops at the board, since this harness has none open.
    (other,) = _passes("the simulation run")
    other._claim()
    scan = _on_the_board(scan_harness._section(registry.DESIGNS[0]))
    scan._confirm_concurrent = lambda others: True
    scan.on_scan()
    assert scan._status_label.GetLabel() == "No board is open."


def test_the_run_asks_before_it_touches_the_board():
    (other,) = _passes("the L-shaped monopole scan")
    section = _run_section()
    other._claim()
    _decline(section)
    section.on_run()
    assert section.asked == [["the L-shaped monopole scan"]]
    assert section.running is False
    assert section.page.lines == []  # not a word logged about a run


def test_an_accepted_run_carries_on_into_the_pass():
    (other,) = _passes("the L-shaped monopole scan")
    section = _run_section()
    other._claim()
    section._confirm_concurrent = lambda others: True
    section.on_run()
    assert section._status_label.GetLabel() == "No board is open."


if __name__ == "__main__":
    run_module_tests(globals())
