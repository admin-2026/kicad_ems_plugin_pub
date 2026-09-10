"""The solver's warnings and errors, picked back out of a run's log.

A run's log is a flood -- thousands of step lines -- and the handful of lines
that say something is wrong with the board sit in the middle of it, framed no
louder than the rest. The solver prints every one of them with a stable id
(``ems/docs/diagnostics.md``)::

    Note [MESH-019]: ...
    WARNING [GND-004]: port 1: the feed direction points toward +x ...
    error [FEED-001]: feed point is not on copper -- move it onto the feed line

That frame -- ``severity [AREA-NNN]: message`` -- is the whole grammar this
module knows. The **id** is the machine-facing half and is never reused or
renumbered; the message is the human half and may be reworded at any time, so
nothing here matches on words. Severity is the emitting call's and carries no
letter in the id, because the same condition can be a warning or an error
depending on how the run was configured (``GND-003`` is both).

**Why this exists at all: pre-flight cannot cover these.** Pre-flight reads the
*board* -- an outline, a stackup, a marker, a file that matches what is being
edited -- and answers before a solver has been launched. The ground check, the
lattice and the geometry around the port are the solver's, decided a minute
into a run pre-flight has already called clean. So "No problems with the board
itself" and ``WARNING [GND-004]`` are both true statements about one run, and
this module is what carries the second one back out of the log to a caller who
would otherwise have to grep a flood for it.

Errors go to the solver's stderr and warnings to its stdout, but a run's log
holds both: the two streams are merged into one pipe at launch
(``simulate.run_exe``).

Pure stdlib -- no wx, no pcbnew.
"""

import re
from typing import NamedTuple

# The three severities, quietest first. The order is the API: a caller asks for
# one and means "this or louder".
NOTE, WARNING, ERROR = "note", "warning", "error"
SEVERITIES = (NOTE, WARNING, ERROR)
RANK = {severity: index for index, severity in enumerate(SEVERITIES)}

# ``WARNING [GND-004]: message``. The severity word is captured rather than
# spelled into the pattern: it is not part of the id, and a word this side has
# not heard of must not make the line vanish -- see _severity.
_FRAMED = re.compile(r"^\s*([A-Za-z]+)\s+\[([A-Z][A-Z_]*-\d+)\]:\s*(.*)$")

# A failure with no id: what the worker writes when a run dies on this side of
# the binary (``agent/worker.py``), and what a process that never got as far as
# the diagnostic machinery prints. Not the solver's catalogue, so there is no
# id to carry -- but a caller asking what went wrong means the run, not the
# solver, so it counts.
_PLAIN = re.compile(r"^\s*(error|warning)s?\s*:\s*(.*)$", re.IGNORECASE)


class Diagnostic(NamedTuple):
    """One line of a log that says something. ``line`` is 1-based and counts
    from the start of the log, not from the stretch it was found in, so it is
    an offset a caller can go back and read around (``--since line - 1``)."""

    severity: str
    id: str  # "" for a failure that carries no catalogue id
    message: str
    line: int
    text: str  # the line as printed, which is what a reader wants shown


def parse(text, line=0):
    """One log line as a :class:`Diagnostic`, or None if it is ordinary
    output."""
    match = _FRAMED.match(text)
    if match:
        return Diagnostic(
            severity=_severity(match.group(1)),
            id=match.group(2),
            message=match.group(3).strip(),
            line=line,
            text=text.rstrip(),
        )
    match = _PLAIN.match(text)
    if match:
        return Diagnostic(
            severity=match.group(1).lower(),
            id="",
            message=match.group(2).strip(),
            line=line,
            text=text.rstrip(),
        )
    return None


def _severity(word):
    """The severity word as one of :data:`SEVERITIES`.

    An id-framed line whose severity word this side does not know is read as a
    warning. It is a diagnostic either way -- the id says so -- and the failure
    that matters here is the silent one: a filter dropping a line the solver
    thought worth printing.
    """
    word = word.lower()
    return word if word in RANK else WARNING


def loud_enough(one, minimum=WARNING):
    """Is ``one`` (a :class:`Diagnostic` or None) at ``minimum`` or louder?

    The one place severities are compared, so a caller with a single line in
    hand -- the window, reading each line as it arrives -- asks the same
    question :func:`scan` asks of a whole log.
    """
    if one is None:
        return False
    return RANK[one.severity] >= RANK.get(minimum, RANK[WARNING])


def scan(lines, minimum=WARNING, start=0):
    """Every diagnostic in ``lines`` at ``minimum`` severity or louder.

    ``start`` is how many lines of the log come before this stretch, so a
    caller scanning a window read with an offset still gets line numbers into
    the whole file.
    """
    found = []
    for offset, text in enumerate(lines):
        one = parse(text, line=start + offset + 1)
        if loud_enough(one, minimum):
            found.append(one)
    return found


def at_least(found, minimum=WARNING):
    """The diagnostics in ``found`` at ``minimum`` or louder.

    :func:`scan` filters while it reads a log; this filters a list already
    read, so a caller that wants two views of one log -- every severity to
    count, the loud ones to report -- pays for a single pass rather than
    scanning the same flood twice.
    """
    return [one for one in found if loud_enough(one, minimum)]


def counts(found):
    """How many of each severity, every severity present as a key -- a
    renderer should not have to ask whether zero warnings means zero or means
    nobody counted.

    A tally is only ever as true as what was scanned: count a list gathered at
    :data:`WARNING` and the ``note`` key reads 0 for a log full of notes. So
    count what :func:`scan` returned at :data:`NOTE` and narrow afterwards --
    with :func:`at_least` for the diagnostics, with ``minimum`` on
    :func:`summary` for the sentence.
    """
    return {
        severity: sum(1 for one in found if one.severity == severity)
        for severity in SEVERITIES
    }


def summary(tally, minimum=NOTE):
    """``"1 error and 2 warnings"``, loudest first, or "" for a clean log.

    Takes the mapping :func:`counts` returns rather than the diagnostics
    themselves, so a renderer working from a serialised payload can say this
    without rebuilding them. English rather than a table because it is one
    line at the foot of a log, and the point is that it is impossible to read
    past.

    ``minimum`` is for the caller whose tally covers more than its sentence
    does: a footer that lists the warnings under a log must say "3 warnings"
    and not "40 notes and 3 warnings", or the count and the list below it
    disagree about what is being summarised.
    """
    said = [
        f"{tally[severity]} {severity}{'' if tally[severity] == 1 else 's'}"
        for severity in reversed(SEVERITIES)
        if tally.get(severity) and RANK[severity] >= RANK.get(minimum, RANK[NOTE])
    ]
    return " and ".join(said)
