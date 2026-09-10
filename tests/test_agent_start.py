"""``run start``, all the way to the spawn, on a board this flow can run.

The shared suite covers what ``run start`` *refuses* and in whose words
(``tests/test_agent_run.py``); this covers the other half, which is not a core
test. Whether a board can run at all is the product's answer -- its markers
have to be the ports this flow needs -- and the fixture boards are antennas, so
an SI plugin running the same core test would be refused by its own config
writer for having one marker where it wants two.

What is under test is the mechanics around the solver, not the solver: the
spawn is stubbed, and nothing here costs more than reading a board.

    python3 tests/test_agent_start.py   (or pytest)
"""

import io
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402
from kicad_board import fixture  # noqa: E402

cli = load("emkit.agent.cli")
formparams = load("emkit.formparams")
jobs = load("emkit.sim.jobs")
runjob = load("runjob")
run_verb = load("emkit.agent.verbs.run")
settings = load("emkit.settings")

BOARD = "patch_antenna"

# The form the window would have saved for this board -- a fresh one (what
# ``settings init`` writes), with the two things a fixture cannot be given: the
# cell size the patch needs (its auto cell is wider than the 1.4 mm feed stub,
# which the solver then refuses -- FEED-019, and AUTO_GND-006 behind it) and a
# laminate, since the board's own stackup states no loss tangent and nothing
# here invents one.
FORM = dict(
    formparams.starter(("F_Cu", "B_Cu"), 1),
    freq="2.44",
    **{"adv.cell_mm": "0.5", "materials.sub0.choice": "FR-4"},
)


def _board():
    """The fixture, copied somewhere writable with its form beside it -- a run
    is made of that file, and writes its ``simulation/`` folder next to the
    board."""
    path = fixture(BOARD, into=tempfile.mkdtemp(prefix="agent_start_")).GetFileName()
    sim_dir = os.path.join(os.path.dirname(path), "simulation")
    settings.save(sim_dir, FORM)
    return path, sim_dir


def _start(path):
    """``run start``, without letting go of a detached worker: the solver is
    the one part of this that costs minutes and the one part nothing here is
    testing."""
    real, spawned = run_verb._spawn, []
    run_verb._spawn = lambda sim_dir, job_id: spawned.append((sim_dir, job_id))
    out = io.StringIO()
    stdout = sys.stdout
    sys.stdout = out
    try:
        code = cli.main(["--json", "run", "start", "--board", path])
    finally:
        sys.stdout = stdout
        run_verb._spawn = real
    return code, json.loads(out.getvalue()), spawned


def test_a_start_prepares_the_run_writes_a_job_and_spawns_a_worker():
    path, sim_dir = _board()
    code, payload, spawned = _start(path)
    assert code == 0, payload
    # The config the solver will be pointed at, really written.
    assert os.path.isfile(payload["config"])
    # A job file, and a worker told which one it is.
    job = jobs.read(sim_dir, payload["job"])
    assert job is not None and job.state == jobs.RUNNING
    assert spawned == [(sim_dir, payload["job"])]
    # Written *before* the worker exists, with no pid: the worker's first act
    # is to read this file, so writing it afterwards is a race it loses on a
    # fast machine. It fills in its own pid, and until it does, a job with no
    # pid reads as starting rather than as lost.
    assert job.pid == 0


def test_the_answer_comes_after_the_run_has_been_started():
    """A rendering path that fell through without returning would start the
    solve and then die printing it, which has happened. So the payload is
    complete enough to render, and rendering it raises nothing."""
    path, _ = _board()
    code, payload, _ = _start(path)
    assert code == 0
    rendered = "\n".join(run_verb.lines(payload))
    assert payload["job"] in rendered
    assert "run status" in rendered  # how to follow it
    assert "still writes a report" in rendered  # ...and that stop is not throw-away


def test_the_port_comes_off_the_board_not_out_of_the_saved_parameters():
    """The knobs are the form's and travel in the file; a port is read off the
    board every time. A marker the user has since dragged has to move the run
    with it, which is the whole point of the marker being on the board."""
    path, sim_dir = _board()
    assert "feed" not in formparams.params(settings.load(sim_dir))
    notes = []
    params = runjob.apply_ports(
        fixture(BOARD, into=tempfile.mkdtemp(prefix="agent_ports_")), {}, notes.append
    )
    assert params["feed"]  # a point and a direction, off the placed marker
    assert notes and "feed marker" in notes[0]


def test_the_form_is_the_only_place_the_design_target_comes_from():
    """A picked application is the target; the ``Custom…`` sentinel means the
    three fields beside the picker are, and they are synthesized into the same
    kind of target so nothing downstream has to special-case one."""
    picked = runjob.form_target(dict(FORM, app="Wi-Fi 2.4 GHz"))
    assert picked.name == "Wi-Fi 2.4 GHz"
    assert picked.f0_ghz == 2.45  # the catalog's, not the form's 2.44

    typed = runjob.form_target(dict(FORM, bandwidth="100", impedance="50"))
    assert typed.f0_ghz == 2.44  # the field, on the Custom pick a starter has
    assert typed.bandwidth_mhz == 100  # a band straddling it, from the field
    assert typed.impedance_ohm == 50


def test_a_picked_application_is_the_frequency_the_run_is_solved_at():
    """The pick carries its own frequency, so a form that names one needs no
    frequency typed beside it -- and the run solves at exactly the frequency it
    will be scored at, which is the whole point of reading one key instead of
    two. The window says the same thing by hiding the field behind a named
    pick; headless there is no field to hide, so the rule lives in the
    translation both frontends come through."""
    form = dict(FORM, app="Wi-Fi 2.4 GHz", freq="")
    params = runjob.form_params(form, {})
    assert params["fpattern_ghz"] == runjob.form_target(form).f0_ghz == 2.45

    # ...and that is a run that starts, which before was a refusal saying to
    # type a frequency the form had already named.
    path, sim_dir = _board()
    settings.save(sim_dir, form)
    code, payload, spawned = _start(path)
    assert code == 0, payload
    assert spawned


def test_a_frequency_that_disagrees_with_the_pick_is_refused_naming_both():
    """One curve read at two points is what this prevents: solving at the typed
    2.44 GHz while the verdict table judges the result against the pick's 2.45.
    Neither number quietly wins -- the refusal spells both and says which key
    to change."""
    try:
        runjob.form_params(dict(FORM, app="Wi-Fi 2.4 GHz"), {})  # freq: 2.44
    except RuntimeError as exc:
        assert "2.44" in str(exc) and "2.45" in str(exc)
        assert "Wi-Fi 2.4 GHz" in str(exc)  # which pick it disagrees with
    else:
        raise AssertionError("a frequency the pick contradicts should be refused")


def test_a_typed_target_with_no_frequency_is_still_refused():
    """The Custom… sentinel means the fields *are* the target, and a blank one
    is not a frequency. Nothing is invented for it: there is no default
    frequency for an antenna, and a run at a made-up one would be worse than
    no run."""
    try:
        runjob.form_params(dict(FORM, freq=""), {})  # the starter's Custom pick
    except RuntimeError as exc:
        assert "Pattern frequency" in str(exc)
    else:
        raise AssertionError("a typed target with no frequency should be refused")


def test_an_application_this_install_does_not_have_is_refused_by_name():
    """A pick that stands for nothing must not quietly become the first entry
    in the list -- the same refusal a material row gets, for the same reason.
    And it is refused *before* a gerber is plotted or a job written, so a form
    nobody can act on never costs a run."""
    try:
        runjob.form_target(dict(FORM, app="No Such Band"))
    except ValueError as exc:
        assert "No Such Band" in str(exc)
        assert "Application" in str(exc)  # which pick on the form
    else:
        raise AssertionError("an unknown application should be refused by name")

    path, sim_dir = _board()
    settings.save(sim_dir, dict(FORM, app="No Such Band"))
    code, payload, spawned = _start(path)
    assert code == 1 and "No Such Band" in payload["error"]
    assert spawned == [] and jobs.recent(sim_dir) == []
    assert not os.path.isfile(os.path.join(sim_dir, "pcb.yaml"))


if __name__ == "__main__":
    run_module_tests(globals())
