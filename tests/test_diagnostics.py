"""Reading the solver's warnings back out of a run's log.

The log is a flood and a diagnostic is one line in it, so what matters here is
not that the happy line parses -- it is the two ways a warning goes missing.

**Nothing may be dropped for being worded differently.** The id is the stable
half (``ems/docs/diagnostics.md``); the severity word in front of it belongs to
the emitting call, and the same condition is a warning or an error depending on
how the run was configured. So the pattern captures the word rather than
listing it, and a word this side has never seen still comes back as a
diagnostic.

**Nothing may be caught for looking like one.** A step line that happens to
contain the word "error", or an id-shaped thing inside a sentence, must not be
reported as a diagnostic -- a summary that cries wolf is one a reader learns to
skip, which is the failure this whole module exists to fix.

    python3 tests/test_diagnostics.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

diagnostics = load("emkit.sim.diagnostics")

# A stretch of a real run's log, in the solver's own spelling: notes and
# warnings on stdout, errors on stderr, all of it merged into one pipe (and so
# into one log) by simulate.run_exe.
LOG = [
    "Auto mesh: cell 0.50 mm = min(feature 0.60, lambda/20 1.22)",
    "Note [MESH-019]: the substrate slab is meshed with its own z cell",
    "step 1000  |E| 1.2e-03",
    "WARNING [GND-004]: port 1: the feed direction points toward +x (the "
    "antenna side), so the ground-like copper was classified on -x",
    "step 2000  |E| 4.0e-04",
    "error [FEED-001]: feed point is not on copper -- move it onto the feed line",
]


def _at(found, id_):
    return next(one for one in found if one.id == id_)


# --------------------------------------------------------------------------- #
# What is a diagnostic
# --------------------------------------------------------------------------- #
def test_the_three_severities_are_read_off_the_line():
    found = diagnostics.scan(LOG, minimum=diagnostics.NOTE)
    assert [one.id for one in found] == ["MESH-019", "GND-004", "FEED-001"]
    assert _at(found, "MESH-019").severity == diagnostics.NOTE
    assert _at(found, "GND-004").severity == diagnostics.WARNING
    assert _at(found, "FEED-001").severity == diagnostics.ERROR


def test_the_id_and_the_message_come_apart():
    """The id is what a caller keys off -- a support answer, a grep through old
    logs, a mapping onto a dialog -- and the message is what a human reads."""
    one = _at(diagnostics.scan(LOG), "GND-004")
    assert one.id == "GND-004"
    assert one.message.startswith("port 1: the feed direction")
    assert "[GND-004]" not in one.message  # the frame is not part of it
    assert one.text == LOG[3]  # ...and the line as printed is still there


def test_a_severity_word_nobody_here_has_heard_of_is_still_a_diagnostic():
    """The word may change; the frame is the contract. Read as a warning,
    because the failure that matters is a line the solver thought worth
    printing that a filter silently ate."""
    one = diagnostics.parse("Caution [MESH-006]: cell 0.4 mm is coarse")
    assert one is not None and one.id == "MESH-006"
    assert one.severity == diagnostics.WARNING


def test_a_failure_with_no_id_still_counts():
    """What the worker writes when a run dies on this side of the binary. Not
    the solver's catalogue, so there is no id to carry -- but a caller asking
    what went wrong means the run, not the solver."""
    one = diagnostics.parse("ERROR: the solver exited with code 3")
    assert one is not None
    assert one.severity == diagnostics.ERROR and one.id == ""
    assert one.message == "the solver exited with code 3"


def test_ordinary_output_is_not_a_diagnostic():
    for text in (
        "step 2000  |E| 4.0e-04",
        "Auto mesh: cell 0.50 mm = min(feature 0.60, lambda/20 1.22)",
        "archived the report to results/20260101-000000",
        "the run finished with no error at all",  # the word, mid-sentence
        "see [GND-004] for what this means",  # an id, but not a diagnostic
    ):
        assert diagnostics.parse(text) is None, text


# --------------------------------------------------------------------------- #
# Where it was, and how loud
# --------------------------------------------------------------------------- #
def test_a_line_number_points_back_into_the_whole_log():
    """1-based, and counted from the start of the file rather than from the
    stretch it was found in -- so ``--since line - 1`` reads around it."""
    assert _at(diagnostics.scan(LOG), "GND-004").line == 4
    # The same stretch, read by a poller that had already seen the first two
    # lines: the numbers still point at the file.
    found = diagnostics.scan(LOG[2:], start=2)
    assert _at(found, "GND-004").line == 4


def test_a_minimum_severity_keeps_everything_louder():
    assert [one.id for one in diagnostics.scan(LOG, minimum=diagnostics.NOTE)] == [
        "MESH-019",
        "GND-004",
        "FEED-001",
    ]
    assert [one.id for one in diagnostics.scan(LOG, minimum=diagnostics.WARNING)] == [
        "GND-004",
        "FEED-001",
    ]
    assert [one.id for one in diagnostics.scan(LOG, minimum=diagnostics.ERROR)] == [
        "FEED-001"
    ]


def test_warnings_and_errors_are_what_a_bare_scan_means():
    # The default is the one a caller who did not think about it wants: what
    # went wrong, not what the mesher remarked on.
    assert diagnostics.scan(LOG) == diagnostics.scan(LOG, minimum=diagnostics.WARNING)


# --------------------------------------------------------------------------- #
# Saying so
# --------------------------------------------------------------------------- #
def test_every_severity_is_counted_even_at_zero():
    """A renderer should not have to ask whether a missing key means none or
    means nobody counted."""
    tally = diagnostics.counts(diagnostics.scan(LOG, minimum=diagnostics.NOTE))
    assert tally == {"note": 1, "warning": 1, "error": 1}
    assert diagnostics.counts([]) == {"note": 0, "warning": 0, "error": 0}


def test_the_summary_reads_as_a_sentence_loudest_first():
    assert diagnostics.summary({"note": 0, "warning": 2, "error": 1}) == (
        "1 error and 2 warnings"
    )
    assert diagnostics.summary({"note": 0, "warning": 1, "error": 0}) == "1 warning"
    assert diagnostics.summary({"note": 3, "warning": 0, "error": 0}) == "3 notes"
    assert diagnostics.summary({"note": 0, "warning": 0, "error": 0}) == ""


if __name__ == "__main__":
    run_module_tests(globals())
