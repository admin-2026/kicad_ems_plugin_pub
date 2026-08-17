"""Control channel to a running solver process: stop it, sample it, kill it.

The bundled monopole binary is interruptible. While it steps, it polls a
request channel between chunks of steps and honours two requests:

    stop    -- end the run now and still write every output (report page,
               data dump) from the record accumulated so far
    sample  -- write one set of outputs from the record so far and keep
               stepping

plus the one no process can refuse:

    kill    -- take it down at once; nothing is written from the run

``kill`` is what a closing window wants (never leave a solver running
detached); the two cooperative requests are what the Stop and Snapshot report
buttons want.

The cooperative requests travel through a *control file*: the solver is
launched with ``--control <file>`` and polls that file for appended request
lines (~5/s); posting one is appending ``stop\\n`` or ``sample\\n``. A file
was chosen over the OS's own process-signalling exactly because this plugin
lives inside a GUI host: Windows has no per-process signals, and delivering
console control events from inside KiCad meant attaching to the solver's
console -- a dance that twice took KiCad down (see dev_docs/interruptible-runs.md
for the post-mortems). Appending to a file has no failure mode that can touch
the host, works the same on every OS, and the solver acknowledges on its own
stdout (``--- Report sample:`` / ``Wrote outputs to``), which the session
already watches.

The file is append-only while the solver runs -- the solver remembers how far
it has read, so nothing need ever be deleted or truncated mid-run, which is
where cross-process races would live. Requests are whole lines: the solver
only acts on a line once its newline is written. This module opens, appends
one line and closes per request; the launcher (RunSession) removes a stale
file before the solver starts so a leftover "stop" from a previous run cannot
end the new one at its first poll.

A request only means something for a process that is still running, and
posting can fail (the run directory gone, unwritable); the honest answer then
is False -- never a silent no-op and never a guess that it landed. A caller
that gets False and needs the run to end falls back to :func:`kill`,
accepting that there will be no report (see RunSection._stop_run, which logs
exactly that).

Stdlib only, no wx / pcbnew, so the whole channel stays unit-testable off
KiCad (tests/test_runcontrol.py).
"""

import os

# The control file's name, next to the run's pcb.yaml (the solver's cwd).
_CONTROL_NAME = "run.ctl"


def control_path(yaml_path):
    """Where the control file for the run driven by ``yaml_path`` lives:
    beside the yaml, so it stays with the run directory it belongs to."""
    return os.path.join(os.path.dirname(os.path.abspath(yaml_path)), _CONTROL_NAME)


def alive(proc):
    """True while ``proc`` is a launched process that hasn't exited yet."""
    return proc is not None and proc.poll() is None


def kill(proc):
    """Stop ``proc`` now, without waiting for it to write anything (SIGKILL /
    TerminateProcess -- the solver cannot catch either, so nothing is written
    from the run). Best effort: a process that just exited on its own, or was
    never launched, is a no-op. Returns whether a live process was killed."""
    if not alive(proc):
        return False
    try:
        proc.kill()
    except OSError:
        return False
    return True


def request_stop(proc, control):
    """Ask the solver to end its run early and still write its outputs from
    the record so far. Returns whether the request could be posted; a False
    means the caller must fall back to :func:`kill` (and gets no report)."""
    return _post(proc, control, b"stop\n")


def request_sample(proc, control):
    """Ask the running solver to write one set of outputs from the record so
    far and keep stepping. Returns whether the request could be posted."""
    return _post(proc, control, b"sample\n")


def _post(proc, control, line):
    """Append one request line to the ``control`` file of the live ``proc``,
    mapping everything that can go wrong to a plain False. Binary append: one
    atomic-enough write, and no CRLF translation to differ per OS."""
    if not alive(proc) or not control:
        return False
    try:
        with open(control, "ab") as f:
            f.write(line)
    except OSError:
        return False
    return True
