"""``results show`` -- what the last run of this board came to.

The dump the solver writes is several hundred kilobytes of browser payload and
is not even JSON. This is the small answer: how far the run got, and -- where
there is something to judge it against -- the same pass/warn/fail table the
report page shows, from the same scorer. A run that cannot be read back is a
run an agent cannot learn from, which is why the slice is not useful without
this verb.

**One vocabulary for "which run": ``--job <id>``,** the same id ``run start``
answers and ``run status``/``log``/``stop`` take. It needs no path because the
id *is* the folder its outputs were archived into. Without one, the newest run
of this board.

**What the board is for is the form's to say.** Nothing in a dump knows it:
the binary is handed a geometry and a frequency, never a purpose. So the
target is read off the form -- the same design-target field the window's
picker writes -- and never asked for again here. **The run's own copy of that
form**, the one ``run start`` recorded with it, rather than the board's file as
it stands now: the file is rewritten whenever the window closes, so reading it
would score a run against whatever the board has been retargeted to since, and
disagree with the sidecar the report page draws from (which the worker wrote
from the record). A run that kept no record is the window's, and the board's
file is the best there is for it. A flow whose form has no such field, or a run
too short to have an impedance sweep in it, comes back unjudged, and says
which.

**Two timestamps, not one.** ``stamp`` is the run's -- the id, minted when it
started -- and ``written`` is the report's own, off the file. A solve is
minutes and ``run sample`` writes a report mid-flight, so the two differ by
however long the run had been going, and a reader asking how fresh a reading
is means the second one.

The payload carries the ``viewer_url`` of the page that draws this exact dump,
so an agent can hand the human the graphical view of what it just described.
That is the two frontends meeting.

It also carries ``data``: the run's own numbers as bare JSON, when the run was
asked to write them (``output_json`` on the form). Nothing is re-serialized
here -- the answer to "where are the arrays" is a path to the file the solver
wrote, or the line saying which key would have produced one.
"""

import os

from ... import settings
from ...sim import jobs, results
from .. import kicad

NAME = "results"
HELP = "What the last run came to"

TOPICS = ("show",)

# How many ids a refusal names before it stops listing. Enough to recognise the
# one meant, short enough that a board with a hundred runs still prints a
# message rather than a directory.
_LISTED = 5


def add_arguments(parser):
    parser.add_argument("topic", choices=TOPICS)
    kicad.add_board_arg(parser)
    parser.add_argument(
        "--job",
        default=None,
        help=(
            "Which run: the id run start answered, e.g. 20260905-162223 -- "
            "which is also the folder it wrote under simulation/results/. "
            "The newest run of this board by default"
        ),
    )


def run(args):
    from .... import runjob

    sim_dir = kicad.sim_dir(args.board)
    dump = _dump(sim_dir, args)
    verdicts, target, unjudged = _judge(runjob, sim_dir, dump)
    payload = results.read(sim_dir, dump, verdicts=verdicts)
    payload["target"] = target
    # Said out loud rather than left as an empty space: a reader who saw no
    # table would not know whether the run passed or was never judged.
    payload["unjudged"] = unjudged
    return payload


def _dump(sim_dir, args):
    """The report to read, as a path: the run ``--job`` named, or the newest.

    Checked here, before anything opens it, because the next thing that
    happens to this path is the product's scorer -- and a wrong id reaching
    that comes back as its ``FileNotFoundError`` rather than as a sentence
    about which runs this board has.
    """
    job_id = args.job
    if not job_id:
        newest = results.latest(sim_dir)
        if newest is None:
            raise RuntimeError(
                f"this board has no results yet -- nothing under {sim_dir}. "
                f"Start one with: run start --board {args.board}"
            )
        return newest
    dump = results.for_job(sim_dir, job_id)
    if os.path.isfile(dump):
        return dump
    if results.grid_only(sim_dir, job_id):
        raise RuntimeError(
            f"{job_id} was a --grid-only run: it wrote the lattice and no "
            "report, so there are no numbers to show.\n"
            "What it made of the board is in its log:\n"
            f"  run log --board {args.board} --job {job_id}"
        )
    if os.path.isdir(os.path.dirname(dump)):
        # A real run of this board that archived nothing: it failed, or it was
        # stopped during the mesh pass, which is the one stop that keeps no
        # report. Its id is good and the list below would not help.
        raise RuntimeError(
            f"{job_id} is a run of this board but wrote no report -- it ended "
            "before the first one.\n"
            f"What became of it:\n"
            f"  run status --board {args.board} --job {job_id}"
        )
    raise RuntimeError(
        f"this board has no run {job_id} -- nothing at {dump}.{_had(sim_dir)}"
    )


def _had(sim_dir):
    """The ids this board does have, as a tail for the refusal above. A caller
    who got the id wrong is one listing away from the right one, and the list
    is the run folders themselves -- so a run started from the window, which
    keeps no job record, is in it."""
    have = results.stamps(sim_dir)
    if not have:
        return " It has never run."
    # Sliced rather than counted: this package does no arithmetic, and the
    # rest of the list is the thing being described anyway.
    newest, older = have[:_LISTED], have[_LISTED:]
    more = f", and {len(older)} older" if older else ""
    return f"\nRuns it does have: {', '.join(newest)}{more}"


def _judge(runjob, sim_dir, dump):
    """This run scored against what the board's form says it is for, as
    ``(verdicts, target name, why there is no table)`` -- the last two of them
    strings, empty when there is nothing to say.

    The target is resolved before the dump is read, so a form naming one this
    install no longer has is a message about the form rather than a table with
    a hole in it. ``score`` also writes the sidecar the report page reads, so
    asking for a verdict here is what puts one on the page a human opens next.
    """
    form = _form(sim_dir, dump)
    if not form:
        return (
            None,
            "",
            f"Not scored — this run recorded no form, and there is no "
            f"{settings.path(sim_dir)} either; a form is what says what this "
            "board is for.",
        )
    try:
        target = runjob.form_target(form)
    except ValueError as exc:
        return None, "", f"Not scored — {exc}"
    if target is None:
        return (
            None,
            "",
            "Not scored — this flow's numbers are the answer; its form has "
            "nothing it is designed for.",
        )
    try:
        verdicts = runjob.score(dump, target)
    except RuntimeError as exc:
        # Numbers that would be judged wrongly, not numbers with nothing to
        # judge them by -- an older run solved against another impedance, say.
        # The refusal says which, so print it rather than the fallback below.
        return None, target.name, f"Not scored against {target.name} — {exc}"
    if verdicts:
        return verdicts, target.name, ""
    return (
        None,
        target.name,
        f"Not scored against {target.name} — the run carries no impedance "
        "sweep yet (it may have stopped before its first one).",
    )


def _form(sim_dir, dump):
    """The form this run was built from: its own record first (``sim.jobs``
    keeps the whole form beside the dumps, which is why nothing here has to
    guess), the board's settings file only for a run that kept none.

    A run started from the window is that second case -- it archives its dumps
    and records no job -- and so is a record written before the form was kept
    in one. Both are scored against the board as it stands, which is all there
    is to go on and is what this verb always did.
    """
    job = jobs.read(sim_dir, results.job_of(dump))
    if job is not None and job.form:
        return job.form
    return settings.load(sim_dir)


def lines(payload):
    out = [payload["dump"]]
    when = _when(payload)
    if when:
        out.append(when)
    out.append("")
    if payload["run"]:
        out.append(payload["run"]["summary"])
    out.append("")
    verdicts = payload["verdicts"]
    if verdicts:
        out.append(f"{verdicts['overall_glyph']} {verdicts['target']}")
        for prop in verdicts["props"]:
            # Where the scorer said a row was read, printed where it said one:
            # a stacked table otherwise reads as one operating point, and half
            # of these rows are at the target while the other half are at
            # whatever the run actually did.
            at = f"  at {prop['at']}" if prop.get("at") else ""
            out.append(
                f"  {prop['glyph'] or '·'} {prop['label']:<14} {prop['text']}{at}"
            )
    else:
        out.append(payload["unjudged"])
    if payload["viewer_url"]:
        out.append("")
        out.append(f"Draw it: {payload['viewer_url']}")
    out.append("")
    out.append(_read_it(payload))
    return out


def _when(payload):
    """The one line of clock under the dump's path: when the run started, and
    when this report was written.

    Both, because the gap between them is the answer to a question a reader of
    a long run actually has -- is this the report the solve finished with, or
    the one ``run sample`` asked for four minutes in? Naming the run's stamp
    "written" (which this line used to do) answers it wrongly and confidently.
    A dump under a folder that is not a run stamp has neither, and gets no
    line rather than a half one.
    """
    said = []
    if payload.get("stamp"):
        said.append(f"started {payload['stamp']}")
    if payload.get("written"):
        said.append(f"written {payload['written']}")
    return " · ".join(said)


def _read_it(payload):
    """Where this run's numbers are for a reader that is not a browser, or how
    to have the next one write them.

    The dump above is a page's payload -- an assignment with an unquoted key,
    which no JSON parser will take -- so a caller holding a terminal has
    nothing to open unless the run was asked for the bare-JSON flavour. That
    ask is a form key, so the answer to "there isn't one" is a line the caller
    can act on rather than a fact about a file.
    """
    if payload["data"]:
        return f"Read it: {payload['data']}"
    return (
        "Read it: nothing to — the dump above is a page's payload, not JSON. "
        "Set output_json: true in the form (settings.yaml) and run again to "
        "have the numbers written beside it as bare JSON."
    )
