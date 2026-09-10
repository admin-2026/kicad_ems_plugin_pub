"""Getting at a board from a command line, and saying so when you cannot.

Two things, both about the same fact: the board-reading verbs need ``pcbnew``,
which lives only in KiCad's own Python. One module owns both because they are
one sentence -- "this needs that interpreter, and here is which" -- and
because the message is the likeliest thing a first-time caller will ever read
from this program.

The recorded answer (``hostpy``) comes first, because it is the only one that
cannot rot: it is the interpreter the window itself ran on. The table below is
the fallback for a machine where the window has never been opened, and it is
pinned to KiCad 9.0, which is exactly why it is second.

The board is always loaded from a path (``pcbnew.LoadBoard``), never taken
from a running pcbnew: the Python API offers no handle on the board a user has
open. That makes every verb built on this read-only by construction, and it
means a board somebody is editing is read as it was last *saved* -- including
its zone fills, which nothing here refills.

And that load fails silently -- ``None``, no message, for a missing file, a
file that is not a board and a board from a newer KiCad alike. So the third
thing here is the sentence saying which (:func:`_unreadable`), which is the
same job as the two above: a caller told what is wrong rather than left to
guess at the program.
"""

import os
import sys

from . import hostpy

# Where KiCad keeps the Python that has pcbnew in it. Named rather than
# searched for: the failure this answers happens once, on somebody's first
# command, and "not that python, this one" is the whole of the fix.
#
# No package to install on Linux -- pcbnew ships inside `kicad` itself, and
# there is no python3-pcbnew on Debian or Ubuntu to point anyone at.
INTERPRETERS = (
    "Linux:   /usr/bin/python3 (pcbnew ships inside the `kicad` package)",
    "Windows: C:\\Program Files\\KiCad\\9.0\\bin\\python.exe",
    "macOS:   /Applications/KiCad/KiCad.app/Contents/Frameworks/"
    "Python.framework/Versions/Current/bin/python3",
)

# The trap that costs the most time, and the one a list of paths does not
# cover: `python3` is whatever comes first on PATH, and a virtualenv or a
# pyenv shim does not see the system dist-packages KiCad installed into.
SHADOWING = (
    "If `python3` is a virtualenv or pyenv Python, it will not see KiCad's "
    "pcbnew however it was installed -- name the interpreter above outright "
    "rather than installing anything."
)


def missing_message():
    """What to tell somebody whose interpreter has no pcbnew."""
    recorded = hostpy.interpreter()
    if recorded:
        return (
            "this verb reads a board, which needs KiCad's own Python (the one "
            "pcbnew lives in). This plugin has run inside KiCad on "
            f"{recorded} -- use that interpreter.\n"
            f"This one is {sys.executable}."
        )
    return (
        "this verb reads a board, which needs KiCad's own Python (the one "
        "pcbnew lives in) -- run it with that interpreter:\n  "
        + "\n  ".join(INTERPRETERS)
        + f"\n{SHADOWING}"
        + f"\nThis one is {sys.executable}."
        + "\nOpening the plugin's window once records the right one, and then "
        "any Python will do."
    )


# The application object this process was missing, kept for as long as it runs.
# wx owns exactly one, and a collected one is worse than never having made it.
_app = None


def wx_app():
    """Give this process the wxApp pcbnew's C++ side assumes there is.

    Loading or saving a board reaches ``wxStandardPaths::Get()``, which asks
    the application object for its traits -- and with none ever constructed
    that is an assertion, ``create wxApp before calling this``, which on a
    build with assertions live ends the command before it has printed
    anything. KiCad's window makes one on the way up; a command line has to
    make its own.

    ``AppConsole`` rather than ``App``: it needs no display, so this stays
    true over ssh and in CI, where ``wx.App()`` exits with "Unable to access
    the X Display". Nothing here draws -- the assert is about the object
    existing, not about a GUI.

    Best effort: a Python with pcbnew but no wx is not one this can fix, and
    the message that pcbnew's own absence earns is the more useful one.
    """
    global _app
    try:
        import wx

        if _app is None and wx.GetApp() is None:
            _app = wx.AppConsole()
            # With an app in place wx has somewhere to log, and pcbnew's
            # import chatters a dozen "Adding duplicate image handler" lines
            # onto stderr. A verb's output is read by a program; warnings and
            # errors are worth interrupting it for, and nothing below them is.
            wx.Log.SetLogLevel(wx.LOG_Warning)
    except Exception:
        pass


def pcbnew():
    """The ``pcbnew`` module, or a :class:`RuntimeError` naming the Python that
    has one. Every board-touching verb goes through here rather than importing
    pcbnew itself, so there is one copy of that message -- and one place that
    settles what pcbnew needs around it (:func:`wx_app`)."""
    wx_app()
    try:
        import pcbnew as module
    except ImportError as exc:
        raise RuntimeError(missing_message()) from exc
    return module


def board(path):
    """The board saved at ``path``, or a refusal that says what is wrong with
    it.

    ``LoadBoard`` answers a bare ``None`` for every way of failing there is --
    a path with no file at it, a file that is not a board, and a board saved by
    a KiCad newer than this one -- and prints nothing on the way. So the reason
    is worked out here, from the file itself, and the caller is told which of
    the three it has: the last one in particular looks like a broken plugin
    from the outside, and is not.
    """
    loaded = pcbnew().LoadBoard(path)
    if loaded is None:
        raise RuntimeError(_unreadable(path))
    return loaded


# Enough of a board file to hold its header (`(kicad_pcb (version …)
# (generator_version …)`), and no more: the rest is megabytes of a file this
# has already established nothing can read.
_HEAD_BYTES = 4096


def _unreadable(path, host=None):
    """Why ``LoadBoard`` refused ``path``, as a sentence. ``host`` is the
    running KiCad's ``(major, minor)``, asked of pcbnew when not handed in --
    a parameter so this is testable without one."""
    from ..kicad import version

    if not os.path.isfile(path):
        what = "a folder" if os.path.isdir(path) else "nothing"
        return f"there is no board at {path} -- {what} is there."
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(_HEAD_BYTES)
    except OSError as exc:
        return f"could not read {path}: {exc}"
    if "(kicad_pcb" not in head:
        return (
            f"{path} is not a KiCad board -- a .kicad_pcb file starts with "
            "`(kicad_pcb`. A schematic (.kicad_sch) and a project (.kicad_pro) "
            "are different files, and a run is plotted from the board."
        )
    saved = version.board_saved_by(head)
    host = host or version.get_kicad_version()
    if saved and host and saved > host:
        return (
            f"{path} was saved by KiCad {saved[0]}.{saved[1]}, and the pcbnew "
            f"running this is KiCad {host[0]}.{host[1]}. A newer board format "
            "is the one thing pcbnew refuses without a word -- it is not the "
            "board and it is not this program.\n"
            f"Run it with KiCad {saved[0]}.{saved[1]}'s own Python (the "
            "interpreter inside that install), which is the only thing that "
            "can read this file."
        )
    return (
        f"could not read a board from {path} -- pcbnew refused it and said "
        "nothing, and its header explains nothing either. Opening it in KiCad "
        "is the fastest way to see what it makes of the file."
    )


def sim_dir(path):
    """The ``simulation/`` folder beside the board at ``path`` -- where its
    config, its claims and one folder per run all live."""
    from ..sim import simulate

    return str(simulate.output_dir(board(path)))


def add_board_arg(parser):
    """``--board PATH``, spelled the same way on every verb that needs one."""
    parser.add_argument("--board", required=True, help="Path to a .kicad_pcb file")
