"""``run`` and ``results``: the life cycle, without paying for a solve.

The solver is never launched here. What is under test is everything around it
-- what ``run start`` refuses and in whose words, that a job file and a spawn
really happen, that a worker which dies immediately is reported failed rather
than running forever, and that stop and sample reach a run this process did
not start.

The board tier needs a real pcbnew and a checked-in fixture, and **skips with
the reason** where KiCad is not installed (kicad_board.py). A board test that
silently passed there would report a green suite for the half of the code
nobody had run.

    python3 tests/test_agent_run.py   (or pytest)
"""

import io
import json
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402
from kicad_board import fixture  # noqa: E402

cli = load("emkit.agent.cli")
formparams = load("emkit.formparams")
jobs = load("emkit.sim.jobs")
runcontrol = load("emkit.sim.runcontrol")
results_verb = load("emkit.agent.verbs.results")
run_verb = load("emkit.agent.verbs.run")
runlock = load("emkit.sim.runlock")
settings = load("emkit.settings")
simulate = load("emkit.sim.simulate")

BOARD = "patch_antenna"

# The form the window would have saved for this board: a fresh one, at the
# cell size the patch fixture needs (its auto cell is wider than the 1.4 mm
# feed stub, which the solver then refuses -- FEED-019, and AUTO_GND-006
# behind it) and on a laminate, since the fixture's own stackup states no
# loss tangent and nothing here invents one.
FORM = dict(
    formparams.starter(("F_Cu", "B_Cu"), 1),
    freq="2.44",
    **{"adv.cell_mm": "0.5", "materials.sub0.choice": "FR-4"},
)


# A run's log in miniature: the flood, with the three lines that matter in the
# middle of it. Both diagnostics are printed at meshing time, which is the
# whole difficulty -- by the time anybody looks, they are thousands of step
# lines back.
FLOOD = (
    "\n".join(
        [
            "Note [MESH-019]: the substrate slab is meshed with its own z cell",
            "WARNING [GND-004]: port 1: the feed direction points toward +x",
            "error [FEED-016]: port 1: the feed point sits on 5.75 mm of copper",
            *(f"step {n}00  |E| 1.2e-03" for n in range(20)),
        ]
    )
    + "\n"
)


def _run(argv):
    out = io.StringIO()
    real = sys.stdout
    sys.stdout = out
    try:
        code = cli.main(argv)
    except SystemExit as exc:
        code = exc.code
    finally:
        sys.stdout = real
    return code, out.getvalue()


def _payload(argv):
    code, out = _run(["--json", *argv])
    return code, json.loads(out)


def _copy_of(name):
    """The fixture board, copied somewhere writable: a run writes its
    ``simulation/`` folder beside the board, and a test must not leave one in
    the checkout."""
    return fixture(name, into=tempfile.mkdtemp(prefix="agent_run_")).GetFileName()


# --------------------------------------------------------------------------- #
# start: what it refuses, and in whose words
# --------------------------------------------------------------------------- #
def test_a_board_with_no_saved_form_refuses_by_name():
    """A run is made of a form, and a board that has none is told exactly
    that -- the file it looked for, what writes it, and the verb that writes a
    starter. Never handed a frequency, a substrate or a 50 Ω port nobody
    chose."""
    path = _copy_of(BOARD)
    sim_dir = os.path.join(os.path.dirname(path), "simulation")
    code, payload = _payload(["run", "start", "--board", path])
    assert code == 1
    error = payload["error"]
    assert "settings.yaml" in error  # the file it looked for
    assert "window" in error  # what writes it
    assert "settings init" in error  # ...and what to do without one
    # Nothing was started: a run's first act is the folder it writes into.
    assert not os.path.isdir(str(simulate.results_dir(sim_dir)))


def test_a_settings_file_the_caller_named_is_the_one_that_is_run():
    """``--settings`` is the whole point of the copy-and-edit loop: the window
    rewrites its own file, so an edit belongs in a copy, and the run has to
    take the copy's numbers rather than the board's."""
    path = _copy_of(BOARD)
    sim_dir = _record_form(path)
    mine = os.path.join(os.path.dirname(path), "mine.yaml")
    form = dict(FORM)
    form["freq"] = "5.8"
    settings.write(mine, form)
    code, payload = _without_spawning(
        ["run", "start", "--board", path, "--settings", mine]
    )
    assert code == 0, payload
    assert payload["settings"] == mine
    written = open(os.path.join(sim_dir, "pcb.yaml"), encoding="utf-8").read()
    assert "5.8" in written  # the copy's frequency, not the board's 2.44
    # ...and the job keeps that form, not the path it came from: the window
    # rewrites its own file whenever it closes, so a path would say what the
    # board is set to now rather than what this run was asked for.
    assert jobs.read(sim_dir, payload["job"]).form == form


def test_a_second_run_on_one_board_is_refused_not_raced():
    """Two runs here would write one pcb.yaml, overwrite each other's dumps
    and share one control file -- so a stop meant for one would end the other.
    That is a collision, not the shared-machine cost the window asks about."""
    path = _copy_of(BOARD)
    sim_dir = os.path.join(os.path.dirname(path), "simulation")
    _record_form(path)
    jobs.write(
        sim_dir,
        jobs.Job(
            id="20260101-000000",
            state=jobs.RUNNING,
            pid=os.getpid(),  # this process: certainly alive
            board=path,
            started=time.time(),
        ),
    )
    code, payload = _payload(["run", "start", "--board", path])
    assert code == 1
    assert "20260101-000000" in payload["error"]
    assert "run stop" in payload["error"]  # and how to end it


# --------------------------------------------------------------------------- #
# start: what it does
#
# "a start succeeds" is not a core test: whether a board can run at all is the
# product's answer (its markers must be the ports it needs), and the fixture
# boards are antennas. That half is plugins/antenna/tests/test_agent_start.py.
# --------------------------------------------------------------------------- #
def test_a_worker_that_dies_at_once_is_reported_failed_not_running_forever():
    """The failure that has actually happened: the child could not import the
    package, died on a stderr going to DEVNULL, and the job sat at "running"
    for good. The startup grace is what makes it reportable."""
    sim_dir = tempfile.mkdtemp(prefix="agent_grace_")
    jobs.write(
        sim_dir,
        jobs.Job(
            id="20260101-000000",
            state=jobs.RUNNING,
            pid=0,
            board="/nowhere/b.kicad_pcb",
            started=time.time() - jobs.STARTUP_GRACE_S - 1,
        ),
    )
    job = jobs.read(sim_dir, "20260101-000000")
    assert job.state == jobs.LOST
    assert "never started" in job.error


# --------------------------------------------------------------------------- #
# stop / sample / log
# --------------------------------------------------------------------------- #
def test_stop_and_sample_append_one_line_each_to_the_control_file():
    """By path, with no process handle: that is what makes them reach a run
    this process did not start -- one from the window, or from a shell that
    has since closed."""
    work = tempfile.mkdtemp(prefix="agent_ctl_")
    control = runcontrol.control_path(os.path.join(work, "pcb.yaml"))
    assert not os.path.exists(control)  # safe on a file that isn't there yet
    assert runcontrol.post(control, runcontrol.STOP) is True
    assert runcontrol.post(control, runcontrol.SAMPLE) is True
    with open(control, "rb") as handle:
        assert handle.read() == runcontrol.STOP + runcontrol.SAMPLE


def test_posting_where_nothing_can_be_written_is_a_plain_false():
    # Never a silent no-op, and never a guess that it landed.
    assert runcontrol.post("", runcontrol.STOP) is False
    assert runcontrol.post("/nowhere/at/all/run.ctl", runcontrol.STOP) is False


def test_stop_says_it_still_writes_a_report():
    """To a reader who has not been told, "stop" reads as "throw away", so
    both the answer and the follow-up lines a start prints say otherwise."""
    payload = {
        "job": "x",
        "requested": "stop",
        "posted": True,
        "next": "the run to end and write its report from the record so far",
        "state": "running",
    }
    assert "write its report" in "\n".join(run_verb.lines(payload))
    assert "still writes a report" in "\n".join(
        run_verb.lines(
            {
                "job": "x",
                "sim_dir": "",
                "settings": "settings.yaml",
                "config": "c",
                "solver": "s",
                "target": "",
                "grid_only": False,
                "board_notes": [],
                "also_running": [],
                "startup_grace_s": 30,
            }
        )
    )


def test_a_posted_request_reads_as_one_sentence():
    """It did not: "waiting for" was glued to a clause, and `run sample`
    answered "waiting for one more report is written and the run keeps
    stepping". The key is what is being waited *for*, so it holds a noun
    phrase and the renderer supplies the verb."""
    for what, expected in (
        (
            "sample",
            "sample: requested — waiting for one more report to be written; "
            "the run keeps stepping",
        ),
        (
            "stop",
            "stop: requested — waiting for the run to end and write its "
            "report from the record so far",
        ),
    ):
        payload = {
            "job": "x",
            "requested": what,
            "posted": True,
            "next": run_verb.AWAITING[what],
            "state": "running",
        }
        assert run_verb.lines(payload) == [expected]


def test_a_request_that_never_landed_does_not_claim_to_be_waiting():
    """False from post means nothing was appended, so there is nothing on its
    way -- and "could not reach the run — waiting for ..." is two answers."""
    payload = {
        "job": "x",
        "requested": "stop",
        "posted": False,
        "next": "the run to end and write its report from the record so far",
        "state": "running",
    }
    line = "\n".join(run_verb.lines(payload))
    assert "could not reach the run" in line
    assert "waiting for" not in line


def test_status_does_not_report_the_listed_run_as_a_second_one():
    """A run leaves a claim, and the claim names the pid the job file names.
    Reported unfiltered, ``run status`` said something was "also running"
    about the one run the caller had asked about -- which, on a verb that
    spends its other words refusing concurrent runs, reads as a warning."""
    sim_dir = tempfile.mkdtemp(prefix="agent_also_")
    job = jobs.Job(
        id="20260101-000000",
        state=jobs.RUNNING,
        pid=os.getpid(),  # this process: certainly alive, like a real worker
        board="/nowhere/b.kicad_pcb",
        started=time.time(),
    )
    claim = runlock.claim(sim_dir, "a simulation run started from the command line")
    try:
        assert run_verb._others(sim_dir, [job]) == []
        # ...and a pass the table does *not* hold is still reported: the
        # window's run and scan write no job file at all.
        assert run_verb._others(sim_dir, []) == [claim.label]
    finally:
        runlock.release(claim)


def test_the_log_resumes_from_where_it_stopped():
    """The solver's output is a flood, so a poller reads from an offset rather
    than re-reading all of it."""
    sim_dir = _with_log("step 1000\nstep 2000\nstep 3000\n")
    payload = _log(sim_dir)
    assert payload["lines"] == ["step 1000", "step 2000", "step 3000"]
    assert payload["next"] == 3
    assert _log(sim_dir, since=3)["lines"] == []
    with open(jobs.log_path(sim_dir, "j"), "a", encoding="utf-8") as handle:
        handle.write("step 4000\n")
    assert _log(sim_dir, since=3)["lines"] == ["step 4000"]


def test_a_severity_answers_with_the_diagnostics_and_nothing_else():
    """The whole point of the option: an agent cannot read a flood, and the
    lines that say the board is wrong are three of ten thousand."""
    sim_dir = _with_log(FLOOD)
    payload = _log(sim_dir, severity="warning")
    assert payload["lines"] == [
        "WARNING [GND-004]: port 1: the feed direction points toward +x",
        "error [FEED-016]: port 1: the feed point sits on 5.75 mm of copper",
    ]
    # Narrowed what is shown, never what was read: the offset is still the
    # whole log's, so a poller alternating between filtered and full reads
    # does not lose its place or re-read what it has seen.
    assert payload["next"] == len(FLOOD.splitlines())
    assert _log(sim_dir, severity="note")["lines"][0].startswith("Note [MESH-019]")
    assert _log(sim_dir, severity="error")["lines"] == [payload["lines"][1]]
    # Shown once, not twice: the tally under a filtered read does not repeat
    # the lines that are already the answer.
    rendered = "\n".join(run_verb.lines(payload))
    assert rendered.count("GND-004") == 1


def test_a_warning_is_resurfaced_even_when_nobody_asked_for_one():
    """The bug this option was cut for: pre-flight said the board was fine,
    the solver warned about its ground at meshing time, and the poller that
    read past that chunk never saw it again. So the scan is over the *whole*
    log on every call, filtered or not."""
    sim_dir = _with_log(FLOOD)
    # Read from the very end, exactly as a poller that has seen it all does.
    payload = _log(sim_dir, since=len(FLOOD.splitlines()))
    assert payload["lines"] == []  # nothing new to say...
    assert [one["id"] for one in payload["diagnostics"]] == ["GND-004", "FEED-016"]
    assert payload["counts"] == {"note": 1, "warning": 1, "error": 1}
    rendered = "\n".join(run_verb.lines(payload))
    # The tally covers the log; the sentence covers the lines under it. The
    # note is counted and not announced, because it is not one of the two
    # printed below the head.
    assert "1 error and 1 warning" in rendered
    assert "note" not in rendered.split("in this run's log")[0]
    assert "GND-004" in rendered  # the line itself, not just a tally
    assert "--severity warning" in rendered  # ...and how to read the rest


def test_the_log_does_not_repeat_the_solvers_advice_to_press_ctrl_c():
    """A detached run has no console to press it at, and the pid the solver
    names is not this caller's child. Restated where the log is read, so the
    line an agent parses out of --json is the same one a human is shown."""
    sim_dir = _with_log(
        "Ctrl-C stops the run early and still writes the report from the "
        "data so far; `kill -USR1 46868` writes one mid-run.\n"
        "step 100  |E| 1.2e-03\n"
    )
    shown = "\n".join(_log(sim_dir)["lines"])
    assert "kill -USR1" not in shown
    assert "run stop" in shown
    assert "step 100  |E| 1.2e-03" in shown  # and nothing else was touched


def test_counts_covers_the_whole_log_not_just_the_loud_half():
    """The reading that made this wrong: ``--severity note`` printed a
    screenful of notes over ``counts: {"note": 0}``, because the tally was
    taken from the warnings-and-errors scan rather than from the log."""
    sim_dir = _with_log(FLOOD)
    payload = _log(sim_dir, severity="note")
    assert "Note [MESH-019]" in "\n".join(payload["lines"])
    assert payload["counts"]["note"] == 1
    # ...and the diagnostics stay the loud half: a note is not something
    # pre-flight failed to catch, it is the mesher thinking out loud.
    assert [one["id"] for one in payload["diagnostics"]] == ["GND-004", "FEED-016"]


def test_a_clean_log_says_nothing_about_diagnostics():
    """A summary that appears when there is nothing to summarise is one a
    reader learns to skip."""
    payload = _log(_with_log("step 1000\nstep 2000\n"))
    assert payload["diagnostics"] == []
    rendered = "\n".join(run_verb.lines(payload))
    assert "⚠" not in rendered


def test_a_filtered_read_with_no_diagnostics_in_it_says_which_lines_it_read():
    """ "Nothing" and "nothing yet" are different answers, and an empty one
    reads as a broken filter."""
    sim_dir = _with_log("step 1000\nstep 2000\n")
    rendered = "\n".join(run_verb.lines(_log(sim_dir, severity="warning")))
    assert "No warning or louder" in rendered
    assert "lines 1–2" in rendered
    # ...and a filtered read that lands past the run's warnings still shows
    # them: a tally of two over an empty answer reads as a contradiction.
    rendered = "\n".join(
        run_verb.lines(_log(_with_log(FLOOD), since=20, severity="warning"))
    )
    assert "1 error and 1 warning" in rendered and "GND-004" in rendered


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
def test_a_board_with_no_results_says_so_and_says_what_to_do():
    path = _copy_of(BOARD)
    code, payload = _payload(["results", "show", "--board", path])
    assert code == 1
    assert "no results yet" in payload["error"]
    assert "run start" in payload["error"]


def test_a_run_is_named_by_its_job_id_here_too():
    """One vocabulary for "which run". ``run start`` answers an id, and that
    id is what every verb after it takes -- this one included, which used to
    want the path to a dump instead and so had callers pasting an id into a
    flag that could not use one."""
    sim_dir = tempfile.mkdtemp(prefix="agent_byjob_")
    older = _archived(sim_dir, "20260904-090000")
    newest = _archived(sim_dir, "20260905-162223")
    assert results_verb._dump(sim_dir, _Args(job="20260904-090000")) == str(
        older / simulate.DUMPS[simulate.REPORT]
    )
    # ...and no id at all is still the newest run, which is the common case.
    assert results_verb._dump(sim_dir, _Args()) == str(
        newest / simulate.DUMPS[simulate.REPORT]
    )


def test_an_id_that_names_no_run_is_told_which_ones_do():
    """The failure this verb used to hand back was the *scorer's*
    FileNotFoundError, because nothing checked the path before the product
    opened it. A caller one character out needs the list, not a traceback."""
    sim_dir = tempfile.mkdtemp(prefix="agent_nojob_")
    _archived(sim_dir, "20260905-171402")
    _archived(sim_dir, "20260905-162901")
    try:
        results_verb._dump(sim_dir, _Args(job="20260905-162223"))
        assert False, "a run that does not exist was read anyway"
    except RuntimeError as exc:
        assert "no run 20260905-162223" in str(exc)
        assert "20260905-171402, 20260905-162901" in str(exc)


def test_a_grid_only_run_says_that_rather_than_no_such_run():
    """``--grid-only`` is half the loop the guide teaches, and it writes a
    lattice and no report. "No such run" would send the caller looking for a
    typo in an id that is perfectly good."""
    sim_dir = tempfile.mkdtemp(prefix="agent_gridonly_")
    _archived(sim_dir, "20260905-162223", kinds=(simulate.GRID,))
    try:
        results_verb._dump(sim_dir, _Args(job="20260905-162223"))
        assert False, "a run with no report was read anyway"
    except RuntimeError as exc:
        assert "--grid-only" in str(exc) and "run log" in str(exc)


def test_a_run_that_archived_nothing_is_not_offered_as_one_that_did():
    """A run that failed, or was stopped during the mesh pass, leaves a folder
    and no report. Its id is good, so "no such run" would be a lie -- and it
    stays out of the list the *other* refusal prints, which would otherwise
    offer an id that earns a second refusal."""
    sim_dir = tempfile.mkdtemp(prefix="agent_noreport_")
    _archived(sim_dir, "20260905-171402")
    simulate.run_results_dir(sim_dir, "20260905-162223").mkdir(parents=True)
    try:
        results_verb._dump(sim_dir, _Args(job="20260905-162223"))
        assert False, "a run with nothing in it was read anyway"
    except RuntimeError as exc:
        assert "wrote no report" in str(exc) and "run status" in str(exc)
    assert results_verb.results.stamps(sim_dir) == ["20260905-171402"]


def test_a_run_the_window_started_is_readable_but_has_no_state():
    """The window archives its dumps under a stamp and keeps no job record.
    Its numbers are readable by id like any other run's; its *state* is not,
    and saying "no job" about a run the caller can see the folder of would be
    the confusing half of the truth."""
    sim_dir = tempfile.mkdtemp(prefix="agent_windowrun_")
    _archived(sim_dir, "20260905-162223")
    assert results_verb._dump(sim_dir, _Args(job="20260905-162223"))
    try:
        run_verb._pick(sim_dir, "20260905-162223", running_only=False)
        assert False, "a run with no job record reported a state"
    except RuntimeError as exc:
        assert "not one started from a command line" in str(exc)
        assert "results show" in str(exc)


def test_what_a_run_is_judged_against_is_read_off_the_form():
    """The form, and nowhere else: the flow's target used to be a flag of this
    verb too, which meant a board could be run against one target and read back
    against another. The form is the run, so it is also the verdict."""
    sim_dir = tempfile.mkdtemp(prefix="agent_judge_")
    settings.save(sim_dir, FORM)
    judged = results_verb._judge(_Runjob("Wi-Fi 2.4 GHz"), sim_dir, "dump.js")
    assert judged[0] == {"overall": "pass"}  # the product's own scorer
    assert judged[1] == "Wi-Fi 2.4 GHz" and judged[2] == ""


def test_a_run_is_judged_against_the_form_it_was_started_from():
    """...and *that* form is the one the run recorded, not the board's file as
    it stands now. The window rewrites that file whenever it closes, so a board
    retargeted between two runs would otherwise have its older run re-scored
    against the newer target -- and disagree with the sidecar on the report
    page this same verb links to, which the worker wrote from the record."""
    sim_dir = tempfile.mkdtemp(prefix="agent_judge_started_")
    dump = _recorded_run(sim_dir, "20260906-101500", dict(FORM, freq="5.8"))
    settings.save(sim_dir, dict(FORM, freq="2.44"))  # retargeted since
    runjob = _Runjob("5.8 GHz")
    results_verb._judge(runjob, sim_dir, dump)
    assert runjob.seen["freq"] == "5.8"


def test_a_run_the_window_started_is_judged_against_the_board_as_it_stands():
    """The window keeps no job record, so its runs have no form of their own
    and the board's file is the whole of what there is to score them against --
    which is what this verb always did, and must go on doing."""
    sim_dir = tempfile.mkdtemp(prefix="agent_judge_window_")
    dump = str(_archived(sim_dir, "20260906-101500") / simulate.DUMPS[simulate.REPORT])
    settings.save(sim_dir, dict(FORM, freq="2.44"))
    runjob = _Runjob("Wi-Fi 2.4 GHz")
    results_verb._judge(runjob, sim_dir, dump)
    assert runjob.seen["freq"] == "2.44"


def test_a_job_record_without_a_form_falls_back_rather_than_scoring_nothing():
    """A record written before a run carried its whole form is still a record,
    and reading its empty form as "no target" would refuse to judge a run whose
    board says perfectly well what it is for."""
    sim_dir = tempfile.mkdtemp(prefix="agent_judge_oldjob_")
    dump = _recorded_run(sim_dir, "20260906-101500", {})
    settings.save(sim_dir, dict(FORM, freq="2.44"))
    runjob = _Runjob("Wi-Fi 2.4 GHz")
    assert results_verb._judge(runjob, sim_dir, dump)[0] == {"overall": "pass"}
    assert runjob.seen["freq"] == "2.44"


def test_why_there_is_no_verdict_table_is_said_rather_than_left_blank():
    """Three ways to have no table, and a reader who saw an empty space would
    not know which: no form at all, a flow that designs for nothing, and a run
    too short to have an impedance sweep in it yet."""
    empty = tempfile.mkdtemp(prefix="agent_judge_none_")
    assert "settings.yaml" in results_verb._judge(_Runjob(""), empty, "dump.js")[2]

    sim_dir = tempfile.mkdtemp(prefix="agent_judge_why_")
    settings.save(sim_dir, FORM)
    nothing = results_verb._judge(_Runjob(None), sim_dir, "dump.js")
    assert nothing[1] == "" and "the answer" in nothing[2]

    unscored = results_verb._judge(_Runjob("Wi-Fi 2.4 GHz", scored=None), sim_dir, "d")
    assert unscored[0] is None
    assert "Wi-Fi 2.4 GHz" in unscored[2] and "impedance sweep" in unscored[2]


def test_a_verdict_row_prints_the_frequency_the_scorer_read_it_at():
    """Half a verdict table is read at what the run was aimed at and half at
    what it actually did, and stacked one per line they read as one operating
    point. So a row carrying an ``at`` prints it, and one that is itself a
    frequency does not grow a second one.

    Printed, not decided: which rows have an ``at`` is the product's scorer's
    (a flow whose props carry none renders exactly as before)."""
    props = [
        {"key": "resonance", "label": "Resonance", "glyph": "✓", "text": "2.47 GHz"},
        {
            "key": "return_loss",
            "label": "Return loss",
            "glyph": "✓",
            "text": "16.7 dB",
            "at": "2.45 GHz",
        },
    ]
    shown = results_verb.lines(
        {
            "dump": "d.js",
            "stamp": "",
            "run": None,
            "viewer_url": "",
            "data": None,
            "unjudged": "",
            "verdicts": {
                "overall_glyph": "✓",
                "target": "Wi-Fi 2.4 GHz",
                "props": props,
            },
        }
    )
    assert any(line.endswith("16.7 dB  at 2.45 GHz") for line in shown)
    assert any(line.endswith("2.47 GHz") for line in shown)
    assert not any("2.47 GHz  at" in line for line in shown)


def test_a_result_says_where_its_numbers_are_or_how_to_ask_for_them():
    """The dump this verb names is a page's payload and no parser will take it,
    so a caller that wanted the arrays is one line away from either the file
    that holds them or the key that would have written it. "There is no JSON"
    on its own would leave an agent with nowhere to go."""
    base = {
        "dump": "d.js",
        "stamp": "",
        "run": None,
        "viewer_url": "",
        "unjudged": "",
        "verdicts": None,
    }
    written = "\n".join(results_verb.lines(dict(base, data="/x/1/pcb_data.json")))
    assert "Read it: /x/1/pcb_data.json" in written
    missing = "\n".join(results_verb.lines(dict(base, data=None)))
    assert "output_json: true" in missing and "settings.yaml" in missing


class _Runjob:
    """A product, as this verb reaches one: what the form is aiming at, and
    what its scorer makes of a dump. Stubbed because the answer is the
    product's -- what is core is which of them is asked, and when."""

    def __init__(self, target, scored="pass"):
        self.target = None if target is None else _Target(target)
        self.scored = {"overall": scored} if scored else None
        self.seen = None  # the form it was handed -- which one is the question

    def form_target(self, form):
        assert form  # never called without one: an empty form has no target
        self.seen = form
        return self.target

    def score(self, dump, target):
        assert target is self.target
        return self.scored


class _Target:
    def __init__(self, name):
        self.name = name


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _record_form(board_path_):
    """Stand in for the window having been open on this board: the form it
    would have saved. A whole one, off ``formparams.starter`` (which is what
    ``settings init`` writes), so a key added at either end shows up here."""
    sim_dir = os.path.join(os.path.dirname(board_path_), "simulation")
    settings.save(sim_dir, FORM)
    return sim_dir


class _Args:
    """The parsed arguments a log read is, without a parser or a board. The
    verb resolves its folder through ``kicad.sim_dir``, which loads the board
    to find it -- _log stands that one call in, because everything under test
    here is what happens to the log afterwards."""

    def __init__(self, **fields):
        self.board = "/nowhere/b.kicad_pcb"
        self.job = None
        self.since = 0
        self.severity = None
        self.__dict__.update(fields)


def _archived(sim_dir, stamp, kinds=(simulate.REPORT,)):
    """A run of this board as it looks on disk afterwards: its folder, named
    by the id, holding the dumps it archived. Only the names matter here --
    nothing under test reads a byte of them."""
    folder = simulate.run_results_dir(sim_dir, stamp)
    folder.mkdir(parents=True, exist_ok=True)
    for kind in kinds:
        (folder / simulate.DUMPS[kind]).write_text("window.FDTD={}", encoding="utf-8")
    return folder


def _recorded_run(sim_dir, stamp, form):
    """A run started from a *command line* as it looks on disk afterwards: the
    archived dumps plus the job record beside them, carrying the form it was
    built from. The path to its report, which is what a reader has."""
    folder = _archived(sim_dir, stamp)
    jobs.write(
        sim_dir,
        jobs.Job(
            id=stamp, state=jobs.DONE, pid=1, board="b", form=form, started=time.time()
        ),
    )
    return str(folder / simulate.DUMPS[simulate.REPORT])


def _with_log(text):
    """A finished job with ``text`` as its log."""
    sim_dir = tempfile.mkdtemp(prefix="agent_log_")
    jobs.write(
        sim_dir,
        jobs.Job(id="j", state=jobs.DONE, pid=1, board="b", started=time.time()),
    )
    with open(jobs.log_path(sim_dir, "j"), "w", encoding="utf-8") as handle:
        handle.write(text)
    return sim_dir


def _log(sim_dir, **fields):
    real = run_verb.kicad.sim_dir
    run_verb.kicad.sim_dir = lambda _path: sim_dir
    try:
        return run_verb._log(_Args(**fields))
    finally:
        run_verb.kicad.sim_dir = real


def _without_spawning(argv):
    """Everything ``run start`` does except let go of a detached worker. The
    solver itself is the one part of this that costs minutes, and it is the
    one part nothing here is testing."""
    real, spawned = run_verb._spawn, []
    run_verb._spawn = lambda sim_dir, job_id: spawned.append((sim_dir, job_id))
    try:
        return _payload(argv)
    finally:
        run_verb._spawn = real


if __name__ == "__main__":
    run_module_tests(globals())
