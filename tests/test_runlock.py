"""The cross-process claim: what is already simulating this board.

One file per claim, swept when the process that made it is gone. The three
things that matter are all failure modes somebody hit: two claims made in the
same millisecond used to overwrite each other (a list, then a timestamped
name); a claim whose process died used to wedge a board forever; and a
half-written file must not read as evidence that anything is running.

    python3 tests/test_runlock.py   (or pytest)
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

runlock = load("emkit.sim.runlock")
hostos = load("emkit.sim.hostos")


def _tmp(name):
    import tempfile

    return tempfile.mkdtemp(prefix=f"runlock_{name}_")


def test_a_board_nothing_has_ever_run_on_has_no_claims():
    assert runlock.live(_tmp("empty")) == []


def test_a_claim_is_visible_and_releasing_it_is_not():
    sim = _tmp("one")
    entry = runlock.claim(sim, "the simulation run")
    assert runlock.labels(sim) == ["the simulation run"]
    assert entry.mine and entry.age_s() >= 0
    runlock.release(entry)
    assert runlock.live(sim) == []
    runlock.release(entry)  # every finish path calls it; twice is harmless


def test_two_claims_made_in_the_same_millisecond_both_survive():
    # The regression: as a list, and then as a timestamped file name, the
    # second claim overwrote the first. A run plus a scan is a pair the
    # window allows on purpose, so this is the ordinary case, not a race.
    sim = _tmp("pair")
    run = runlock.claim(sim, "the simulation run")
    scan = runlock.claim(sim, "the L-shaped monopole scan")
    assert sorted(runlock.labels(sim)) == [
        "the L-shaped monopole scan",
        "the simulation run",
    ]
    assert run.path != scan.path


def test_a_caller_can_leave_its_own_claim_out():
    sim = _tmp("exclude")
    mine = runlock.claim(sim, "the simulation run")
    runlock.claim(sim, "the ifa scan")
    assert runlock.labels(sim, exclude=(mine.path,)) == ["the ifa scan"]


def test_a_claim_whose_process_is_gone_is_swept():
    # Otherwise a killed window, or a machine that lost power mid-run, leaves
    # a board that warns about a run nobody can ever end.
    sim = _tmp("stale")
    entry = runlock.claim(sim, "the simulation run")
    _rewrite_pid(entry.path, _dead_pid())
    assert runlock.live(sim) == []
    assert not os.path.exists(entry.path)


def test_a_half_written_claim_is_not_evidence_of_a_run():
    sim = _tmp("corrupt")
    entry = runlock.claim(sim, "the simulation run")
    with open(entry.path, "w", encoding="utf-8") as handle:
        handle.write('{"pid": 1')  # cut off mid-write
    assert runlock.live(sim) == []


def test_a_claim_from_another_pid_namespace_is_left_alone():
    # A run inside the container writes its claim into the mounted project and
    # a window on the host reads it. Pid 7 in there is not pid 7 here, so
    # asking about it gives an answer that is right by coincidence -- usually
    # "dead", which sweeps a live run's claim and lets a second run start on
    # top of it.
    sim = _tmp("foreign")
    entry = runlock.claim(sim, "the simulation run")
    _patch(entry.path, pid=_dead_pid(), origin="a1b2c3d4e5f6")

    assert runlock.labels(sim) == ["the simulation run"]
    assert os.path.exists(entry.path)


def test_a_claim_from_here_is_still_swept_when_its_process_is_gone():
    # The bias is only for what cannot be established. This one can be.
    sim = _tmp("ours")
    entry = runlock.claim(sim, "the simulation run")
    _patch(entry.path, pid=_dead_pid(), origin=runlock.origin())
    assert runlock.live(sim) == []


def test_a_claim_written_before_origins_existed_is_treated_as_ours():
    # An upgrade must not turn every claim on the machine into one that can
    # never be swept: before this field there was nowhere else to write one.
    sim = _tmp("upgrade")
    entry = runlock.claim(sim, "the simulation run")
    _patch(entry.path, pid=_dead_pid(), origin=None)
    _patch_delete(entry.path, "origin")
    assert runlock.live(sim) == []


def test_a_claim_records_where_its_pid_means_something():
    sim = _tmp("origin")
    entry = runlock.claim(sim, "the simulation run")
    assert entry.origin == runlock.origin() and entry.origin
    assert entry.here and entry.mine


def test_claims_come_back_oldest_first():
    sim = _tmp("order")
    first = runlock.claim(sim, "first")
    second = runlock.claim(sim, "second")
    _rewrite_started(first.path, 100.0)
    _rewrite_started(second.path, 200.0)
    assert runlock.labels(sim) == ["first", "second"]
    _rewrite_started(second.path, 50.0)
    assert runlock.labels(sim) == ["second", "first"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _dead_pid():
    """A pid that is certainly not running: a child, run to completion."""
    import subprocess

    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    assert not hostos.alive(proc.pid)
    return proc.pid


def _patch(path, **fields):
    import json

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.update(fields)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _patch_delete(path, key):
    """Take a key back out of a claim file -- what one written by an older
    version of the plugin looks like."""
    import json

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.pop(key, None)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _rewrite_pid(path, pid):
    _patch(path, pid=pid)


def _rewrite_started(path, started):
    _patch(path, started=started)


if __name__ == "__main__":
    run_module_tests(globals())
