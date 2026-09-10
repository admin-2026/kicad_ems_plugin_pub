"""The run sequence, with no window and no solver.

One solver invocation with two phases -- lifted out of the window's worker
thread so that a detached command-line run drives the same sequence rather than
a second copy of it. RunSession already takes an injected runner, so nothing
here spawns anything.

What is asserted is that a full run launches the solver *once* (it meshes as
its first act, so a separate --grid-only pass meshed the board twice), that the
grid is still archived and the solve phase still reported at the moment the
grid lands (a run with no grid preview is a run nobody can check the mesh of),
and that a grid-only run is the one that still passes --grid-only.

    python3 tests/test_runner.py   (or pytest)
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

runner = load("emkit.sim.runner")
runsession = load("emkit.sim.runsession")
simulate = load("emkit.sim.simulate")

EXE = "/nowhere/solver"


class _Runner:
    """Stands in for the solver: records the invocations, writes the dumps the
    run archives (so archive_dump has something real to copy) and prints the
    same lines the binary does around them -- the grid marker is how the run
    learns its lattice is built."""

    def __init__(self, run_dir, fail=None):
        self.run_dir = pathlib.Path(run_dir)
        self.calls = []
        self.fail = fail
        self.quiet = False  # writes the dumps, prints no markers at all

    def __call__(self, exe, yaml_path, grid_only=False, on_line=None, **kwargs):
        self.calls.append("grid" if grid_only else "solve")
        if self.fail:
            raise RuntimeError(self.fail)
        say = (lambda _text: None) if self.quiet else (on_line or (lambda _t: None))
        self._dump(simulate.GRID)
        say(f"Wrote {self.run_dir / simulate.DUMPS[simulate.GRID]}")
        if grid_only:
            return
        self._dump(simulate.REPORT)
        say(f"Wrote outputs to {self.run_dir}/")

    def _dump(self, kind):
        (self.run_dir / simulate.DUMPS[kind]).write_text(
            "window.FDTD={};", encoding="utf-8"
        )


def _session(run_dir, fail=None, **kwargs):
    stub = _Runner(run_dir, fail=fail)
    return runsession.RunSession(runner=stub, **kwargs), stub


def _dir():
    return tempfile.mkdtemp(prefix="runner_")


def test_a_run_meshes_once():
    # The solve builds the lattice itself; a --grid-only pass in front of it
    # would mesh the same board a second time, for minutes, for nothing.
    run_dir = _dir()
    session, stub = _session(run_dir)
    archived = []
    runner.solve(session, EXE, run_dir, "20260902-141133", on_grid=archived.append)
    assert stub.calls == ["solve"]
    assert len(archived) == 1
    assert pathlib.Path(archived[0]).is_file()


def test_the_grid_is_archived_when_the_solver_says_it_wrote_it():
    # Mid-run, not at the end: the preview is worth having while the fields
    # are still stepping.
    run_dir = _dir()
    seen = []
    session, _ = _session(run_dir, on_outputs=lambda sample: seen.append("outputs"))
    runner.solve(
        session, EXE, run_dir, "20260902-141133", on_grid=lambda _p: seen.append("grid")
    )
    assert seen == ["grid", "outputs"]


def test_a_silent_solver_still_gets_its_grid_archived():
    # A binary too old to print the marker still wrote the dump; late is
    # better than never.
    run_dir = _dir()
    session, stub = _session(run_dir)
    stub.quiet = True
    archived = []
    runner.solve(session, EXE, run_dir, "s", on_grid=archived.append)
    assert len(archived) == 1


def test_the_phases_are_reported_in_order():
    run_dir = _dir()
    session, _ = _session(run_dir)
    phases = []
    runner.solve(session, EXE, run_dir, "s", on_phase=phases.append)
    assert phases == [runner.MESH, runner.SOLVE]


def test_a_grid_only_run_stops_after_the_mesh():
    run_dir = _dir()
    session, stub = _session(run_dir)
    phases = []
    runner.solve(session, EXE, run_dir, "s", grid_only=True, on_phase=phases.append)
    assert stub.calls == ["grid"]
    assert phases == [runner.MESH]


def test_a_cancel_raises_after_the_run():
    # The narrow case: the request landed once the solver had already exited
    # cleanly, so there was no process to kill.
    run_dir = _dir()
    session, stub = _session(run_dir)
    try:
        runner.solve(session, EXE, run_dir, "s", cancelled=lambda: True)
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("a cancelled run should raise")
    assert stub.calls == ["solve"]


def test_a_failed_pass_raises_whatever_it_raised():
    run_dir = _dir()
    session, _ = _session(run_dir, fail="monopole exited with code 3")
    try:
        runner.solve(session, EXE, run_dir, "s")
    except RuntimeError as exc:
        assert "code 3" in str(exc)
    else:
        raise AssertionError("a failed run should raise")


if __name__ == "__main__":
    run_module_tests(globals())
