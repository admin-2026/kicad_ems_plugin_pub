"""What still differs per OS about running the bundled solver: what the
binary is called, and how to launch it. That is the whole list.

Reaching a running solver is not on that list: stop / sample requests go
through a control *file* the solver polls (``--control``, sim/runcontrol.py),
which behaves identically everywhere. That is exactly why a file was chosen
over the OS's own process signalling -- see runcontrol.py.

Killing never was: ``Popen.kill()`` is SIGKILL / TerminateProcess on the
respective OS, uncatchable on both, and stays with its callers.
"""

import os
import subprocess


def exe_names(stem):
    """Candidate file names for the bundled binary, the running OS's own
    convention first. Both appear on both: CreateProcess does not insist on
    the ``.exe`` extension, and a ``.exe`` is a real find on POSIX too -- under
    WSL, Windows binaries run through the interop layer, and a checkout with
    only the Windows build bundled is a real setup."""
    if os.name == "nt":
        return (f"{stem}.exe", stem)
    return (stem, f"{stem}.exe")


def launch_kwargs():
    """Extra ``Popen`` keywords for launching the solver from a GUI process.
    CREATE_NO_WINDOW keeps a console window from flashing up on Windows; the
    constant only exists there, so everywhere else this is simply empty."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags} if flags else {}
