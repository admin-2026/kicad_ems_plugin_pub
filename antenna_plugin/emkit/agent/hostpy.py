"""Which Python has ``pcbnew`` in it -- recorded by the one process that knows.

Nobody installs a Python for this plugin. KiCad ships one, and installing
another actively hurts: it has no ``pcbnew``, and it captures ``python`` on
PATH. The path to KiCad's own is version- and install-dependent
(``C:\\Program Files\\KiCad\\9.0\\bin\\python.exe``, a framework path inside
``KiCad.app``, ``/usr/bin/python3``), so a table of it rots.

What cannot rot is the interpreter *actually running the plugin*. The window
writes it here the first time it opens, and ``run_agent.py`` reads it and
re-execs into it when the Python it was started with has no pcbnew. So an agent
learns one command instead of a table, and the answer is right by construction
on whatever machine wrote it.

**It is not ``sys.executable``.** KiCad embeds Python rather than launching it,
so inside the plugin ``sys.executable`` is *KiCad* --
``…\\bin\\pcbnew.exe`` on Windows, the app binary inside ``KiCad.app`` on
macOS. Handing that to a shell runs KiCad, and KiCad answers by trying to open
the script as a project ("does not appear to be a valid KiCad project file").
What is wanted is the interpreter belonging to that install, which sits where
Python itself says its home is (``sys._base_executable``, then
``sys.base_exec_prefix``, then beside the host binary). Every candidate is
checked for being python-*named* and for existing, and a value that is neither
is no answer at all -- including one an older version of this file wrote, which
is how a recording made before this was understood repairs itself rather than
sending somebody to delete a file they have never heard of.

The file is in the user's config directory beside their saved materials and
design targets (``userlib.store``), not beside a board: it is a fact about
this machine, not about a project. Everything here is best effort -- a
recording that fails must never keep the window from opening, and a file that
is missing or nonsense simply means "no answer", which the launcher and
``kicad.py``'s message both cope with.
"""

import json
import os
import sys

from ..userlib.store import DIR_NAME, config_home

FILENAME = "interpreter.json"


def path():
    return os.path.join(str(config_home()), DIR_NAME, FILENAME)


def record():
    """Write down the interpreter of the KiCad this is running inside. Called
    from inside KiCad, where whatever Python owns this process is by definition
    one with pcbnew. Returns the path written, or None if it could not be (or
    if this process could not say which Python that is).
    """
    found = this_interpreter()
    if not found:
        return None
    entry = {"python": found, "package": _package_dir()}
    target = path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, indent=1)
    except OSError:
        return None
    return target


def recorded():
    """What was written, or ``{}``. Never raises: a hand-edited or truncated
    file is the same as no file."""
    try:
        with open(path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def interpreter():
    """The recorded interpreter's path, if it is still there and is still a
    Python. ``None`` when nothing has been recorded, when the file it names has
    since gone (an uninstalled or upgraded KiCad), or when what was recorded is
    not an interpreter at all -- which is what a file written by an older
    version of this module holds, and running it would start KiCad rather than
    Python."""
    return _usable(recorded().get("python"))


def this_interpreter():
    """The Python of the KiCad running this, or ``None``.

    Only meaningful from inside KiCad; the candidates are, in order, what
    CPython itself records as the real executable behind an embedded or
    virtual environment, this process' own executable (right whenever Python
    was launched rather than embedded), the interpreter under Python's own
    home, and one beside the host binary -- KiCad ships ``python.exe`` next to
    ``pcbnew.exe``.
    """
    home = sys.base_exec_prefix
    beside = os.path.dirname(sys.executable)
    if os.name == "nt":
        under_home = os.path.join(home, "python.exe")
        under_beside = os.path.join(beside, "python.exe")
    else:
        under_home = os.path.join(home, "bin", "python3")
        under_beside = os.path.join(beside, "python3")
    for candidate in (
        getattr(sys, "_base_executable", ""),
        sys.executable,
        under_home,
        under_beside,
    ):
        usable = _usable(candidate)
        if usable:
            return usable
    return None


def _usable(candidate):
    """``candidate`` if it is a Python that is really there, else None. Named
    rather than run: starting a process to ask is not something a window
    opening can afford, and a file called ``python`` that is not one is not a
    failure this can do anything about anyway."""
    if not candidate or not os.path.isfile(candidate):
        return None
    stem = os.path.splitext(os.path.basename(candidate))[0].lower()
    return candidate if stem.startswith("python") else None


def _package_dir():
    """The installed package this recording came from -- two levels up from
    here (``<package>/emkit/agent/``). Written for a human reading the file,
    and for a launcher that wants to check it is talking about itself."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
