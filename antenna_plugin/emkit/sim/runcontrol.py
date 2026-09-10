"""Control channel to a running solver process: stop it, sample it, kill it.

The bundled solver binary is interruptible. While it steps, it polls a
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

Two spellings, because there are two kinds of caller. :func:`post` takes a
*path* and nothing else, which is what makes ``run stop`` from a shell
possible at all -- the process that started the solve may be gone, and a file
does not care. :func:`request_stop` and :func:`request_sample` take a
``Popen`` as well and add the one thing a parent additionally knows: whether
its own child is still alive. The window keeps calling those and does not
change.

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


# The solver arms POSIX signal handlers whenever it can and announces them in
# one line before it starts stepping, ahead of the control file's own line.
# That announcement is written for somebody running the binary by hand in a
# terminal, and neither caller here is one: a run started from the window has
# no console to press Ctrl-C at, and one started from `run start` is detached
# from the shell that asked for it, so the pid it names belongs to a process
# the caller is not the parent of. Following it would take the run down with
# no report -- exactly what this module's channel exists to avoid.
#
# We cannot stop the binary printing it (it is a shipped artifact, and the
# line comes from SignalRunControl::hint in the simulator's own source), so
# the log this side shows says what is true here instead. Kept narrow on
# purpose: an exact prefix, one line, replaced whole. Anything else the solver
# prints -- including a future rewording of this -- passes through untouched,
# which is the failure this trades for, and the safe direction.
_SIGNAL_HINT = "Ctrl-C stops the run early"

_FILE_HINT = (
    "(this run is driven by its control file, not by signals: "
    "`run sample` writes a report mid-run, `run stop` ends it and writes one)"
)


def restate_signal_hint(text):
    """``text``, unless it is the solver's signal advice -- then this side's.

    A log is shown to a reader who may act on it, so a line telling them to
    press a key they do not have and signal a pid they do not own is worse
    than no line: the two verbs below reach the same run and leave a report
    behind, and they are what the frontends offer.
    """
    return _FILE_HINT if text.lstrip().startswith(_SIGNAL_HINT) else text


def alive(proc):
    """True while ``proc`` is a launched process that hasn't exited yet."""
    return proc is not None and proc.poll() is None


def kill(proc):
    """Stop ``proc`` now, without waiting for it to write anything (SIGKILL /
    TerminateProcess -- the solver cannot catch either, so nothing is written
    from the run). Best effort: a process that just exited on its own, or was
    never launched, is a no-op. Returns whether a live process was killed.

    **A container run is not the process we are holding.** There the handle is
    the engine's client; killing it kills the client and leaves the container
    stepping, which is a run nobody is watching and a folder nobody can claim.
    So a handle that carries a container name (``simulate.run_exe`` puts it
    there) is ended by asking the engine, and the client is killed after, as
    the belt to that braces. This is still the only place in the plugin that
    takes a run down -- the window's close path, the command line's forced
    stop and the stale-claim sweep all arrive here -- which is exactly why the
    second way of doing it belongs here and not beside them.
    """
    if not alive(proc):
        return False
    name = getattr(proc, "container_name", None)
    if name:
        _kill_container(name)
    try:
        proc.kill()
    except OSError:
        return False
    return True


def _kill_container(name):
    """Ask the engine to end the container *name*. Best effort and quiet: the
    caller is already killing what it can reach, and a container that has
    exited on its own is the ordinary case rather than a problem."""
    import subprocess

    from . import hostos
    from .container import cmd, enginepath

    try:
        subprocess.run(
            enginepath.resolved(cmd.kill_argv(name)),
            env=enginepath.environ(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_KILL_TIMEOUT_S,
            **hostos.launch_kwargs(),  # and no console window on Windows
        )
    except (OSError, subprocess.SubprocessError):
        pass


# How long the engine gets to end a container before we stop waiting on it and
# kill the client anyway. A kill is what a closing window does, and a window
# that would not close because a daemon was slow is a worse bug than a
# container that outlives it by a moment.
_KILL_TIMEOUT_S = 15


# The two request lines, as the solver reads them. Named because both the
# ``Popen`` form below and a caller holding nothing but a path post them.
STOP, SAMPLE = b"stop\n", b"sample\n"


def post(control, line):
    """Append one request line to the control file at ``control``.

    **No process handle.** That is the whole point of the channel being a
    file: a run started by the window, by another shell, or by a session that
    has since closed is reached the same way, because nothing has to be the
    solver's parent to append to a file. The overloads below add the one thing
    a parent additionally knows -- whether its own child is still alive.

    Everything that can go wrong maps to a plain False: the run directory
    gone, the file unwritable, no path given at all. Never a silent no-op and
    never a guess that it landed.

    Binary append: one atomic-enough write, and no CRLF translation to differ
    per OS. Safe on a file that does not exist yet -- the solver remembers how
    far it has read, so the channel is append-only and nothing is ever
    truncated mid-run.
    """
    if not control:
        return False
    try:
        with open(control, "ab") as f:
            f.write(line)
    except OSError:
        return False
    return True


def request_stop(proc, control):
    """Ask the solver to end its run early and still write its outputs from
    the record so far. Returns whether the request could be posted; a False
    means the caller must fall back to :func:`kill` (and gets no report).

    The ``Popen`` form, for a caller that launched the solver itself: a
    request only means something for a process that is still running, and a
    parent is the one caller that can tell."""
    return alive(proc) and post(control, STOP)


def request_sample(proc, control):
    """Ask the running solver to write one set of outputs from the record so
    far and keep stepping. Returns whether the request could be posted. The
    ``Popen`` form, as :func:`request_stop`."""
    return alive(proc) and post(control, SAMPLE)
