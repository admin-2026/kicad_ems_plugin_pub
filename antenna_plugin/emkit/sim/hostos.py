"""What still differs per OS about running the bundled solver: how to launch
it, and whether a process is still there.

That is the whole list, and it is short for a reason. Reaching a running
solver is *not* on it: stop / sample requests go through a control *file* the
solver polls (``--control``, sim/runcontrol.py), which behaves identically
everywhere. That is exactly why a file was chosen over the OS's own process
signalling -- see runcontrol.py.

*Which file* to launch is not here either, and that is the one thing that
moved: a solver build is per machine rather than per OS (two of them are
Linux), so the name it is filed under is sim/builds.py's answer and not an
``os.name`` branch's.

Killing never was: ``Popen.kill()`` is SIGKILL / TerminateProcess on the
respective OS, uncatchable on both, and stays with its callers.

Asking whether a pid is alive is here because the obvious portable spelling is
not portable and is *destructive* when it is wrong -- see :func:`alive`. There
is one copy of that answer, and both callers (sim.runlock's claims and
sim.jobs' detached runs) read it from here.

Every function takes the OS name as an argument defaulting to ``os.name``, so
the branch this machine is not can still be tested on the machine it is.
"""

import os

# The Windows process-creation flags used below, by value. Named here rather
# than read off ``subprocess`` because the attributes only exist on Windows,
# and the whole point of the ``name`` argument is that the other OS's branch
# can be driven from a test on this one.
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def launch_kwargs(detached=False, name=None):
    """Extra ``Popen`` keywords for launching a child of this plugin.

    Two cases, and they are not the same one:

      * a solver run the caller waits on (``detached=False``) -- all that is
        wanted is that no console window flashes up on Windows;
      * the worker a command line spawns and lets go of (``detached=True``) --
        which must outlive the shell that started it. ``start_new_session`` is
        the POSIX spelling and is *silently ignored* on Windows, where the
        child then stays in the parent's console and dies with it: closing the
        window would take the solve with it, which is the exact thing
        detaching was for. Windows needs ``DETACHED_PROCESS`` (no console at
        all, so ``CREATE_NO_WINDOW`` is redundant and not combined with it)
        plus its own process group, so a Ctrl-C in the shell does not reach it.
    """
    name = os.name if name is None else name
    if name != "nt":
        return {"start_new_session": True} if detached else {}
    if detached:
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {"creationflags": CREATE_NO_WINDOW}


def alive(pid, name=None):
    """Whether ``pid`` is a process on this machine right now.

    **``os.kill(pid, 0)`` is not a liveness probe on Windows.** CPython maps
    every signal there except ``CTRL_C_EVENT`` / ``CTRL_BREAK_EVENT`` onto
    ``TerminateProcess`` with the exit code set to the signal -- so the
    "probe" kills what it is measuring, with exit code 0, which then reads as
    a clean finish. Every caller of this (a status report, a stale-claim
    sweep) would terminate a live run. So the Windows branch opens a handle
    and waits on it for zero milliseconds, which observes and does nothing.

    The bias is that **what cannot be established counts as alive**: a pid
    owned by another user, a probe that raised something unrecognised, a
    ctypes call that is not available. Nothing is ever swept, lost or
    reported dead for a reason nobody understood -- this drives a warning and
    a status line, never a refusal.

    The one thing it cannot tell is a pid the system has since reused, which
    reads as live. That costs one unnecessary question.
    """
    if not pid or pid <= 0:
        return False
    name = os.name if name is None else name
    if name == "nt":
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # EPERM: somebody else's live process
    return True


# Win32 constants for the handle probe below.
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000  # the handle is signalled -- the process exited
_ERROR_INVALID_PARAMETER = 87  # OpenProcess' answer for "no such pid"


def _alive_windows(pid):
    """The Windows half of :func:`alive`: open a handle, wait zero
    milliseconds, close it. Nothing is signalled to the process."""
    try:
        import ctypes
    except ImportError:  # pragma: no cover -- ctypes is stdlib
        return True
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:
        # Not Windows after all (this is how the branch is reachable from a
        # test on Linux). Unknown, so: alive.
        return True
    kernel32 = kernel32.kernel32
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
    if not handle:
        return kernel32.GetLastError() != _ERROR_INVALID_PARAMETER
    try:
        return kernel32.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)
