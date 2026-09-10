"""The one-word spelling of the command line, written when it is asked for.

``run_agent.py`` needs two things typed in front of every verb: a Python that
has ``pcbnew``, and the path to the install. Neither is short and neither is
guessable, so this writes them once into a tiny script the user can put on
their PATH::

    antenna-agent run start --board b.kicad_pcb

**Generated, not shipped.** A wrapper that lived in the repository would have
to *find* KiCad's Python at run time, which is the table ``kicad.py`` refuses
to keep -- and on Windows there is often no Python on PATH at all to run the
finding with (the Store's ``python.exe`` stub is worse than none). The one
moment the answer is known for certain is the moment the plugin's window
opens, inside KiCad, which is where ``hostpy`` already records it. So the shim
is written from that recording, with both paths baked in.

**Nothing here creates it by itself.** The checkbox on the About page
(``gui.sections.cli``) writes and deletes the file, and the file's existence is
the whole of that checkbox's state -- there is no setting to keep in step with
it. A checkout has the same pair of steps without a window
(``make install-cli`` -> ``tools/install.py``), and untick is still the undo,
since the box reads the disk. ``refresh`` only rewrites a shim that is
already there, which is what keeps one pointing at the right interpreter
across a KiCad upgrade without ever bringing back one the user removed.

**It is a convenience, not a gate.** Removing the shim removes a name, not the
command line: ``run_agent.py`` is a file in the install and anyone holding its
path can always run it. The status line under the checkbox spells the shim's
own path for that reason -- the guide is written for the short name, since a
reader who has read this far has ticked the box.

The name is the product's (``antenna-agent``, ``si-agent``), so two products
installed side by side each get their own.
"""

import os
import stat
import sys

from ... import product
from ..userlib.store import DIR_NAME, config_home
from . import hostpy

# The launcher this shim runs: emkit/agent/ -> emkit/run_agent.py.
LAUNCHER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "run_agent.py"
)

# What the shortcut is called. ``.cmd`` on Windows, which has no shebang: the
# extension is what makes a file runnable by name there.
STEM = f"{product.NAME_KEY}-agent"
NAME = f"{STEM}.cmd" if os.name == "nt" else STEM

_POSIX = """\
#!/bin/sh
# {stem} -- {name}'s command line, with KiCad's Python and this install
# baked in. Written by the plugin's About page (or `make install-cli`);
# delete it there (or here).
exec "{python}" "{launcher}" "$@"
"""

_WINDOWS = """\
@echo off
rem {stem} -- {name}'s command line, with KiCad's Python and this install
rem baked in. Written by the plugin's About page (or `make install-cli`);
rem delete it there (or here).
"{python}" "{launcher}" %*
"""


def path():
    """Where the shortcut goes: beside the recorded interpreter and the user's
    saved materials, because it is a fact about this machine and not about a
    project. A directory of ours, so putting it on PATH exposes this and
    nothing else."""
    return os.path.join(str(config_home()), DIR_NAME, NAME)


def installed():
    """Is the shortcut there? The checkbox's state, read from the one place it
    is really kept."""
    return os.path.isfile(path())


def interpreter():
    """The Python to bake in: the one the window recorded, else the one this
    process belongs to. Both go through ``hostpy``, which is where the one
    thing that must not happen here is known -- baking in KiCad's own binary,
    which runs KiCad on the script instead of running the script."""
    return hostpy.interpreter() or hostpy.this_interpreter() or sys.executable


def script():
    """The shortcut's text for this machine, as it would be written now."""
    # Off the name rather than off ``os.name`` again, so the two can't
    # disagree -- and so a test can generate either spelling on one machine.
    template = _WINDOWS if NAME.endswith(".cmd") else _POSIX
    return template.format(
        stem=STEM,
        name=product.NAME,
        python=interpreter(),
        launcher=LAUNCHER,
    )


def write():
    """Write the shortcut and make it executable. Returns its path; raises
    ``OSError`` like any other write -- the caller has a status line to say so
    on, and a checkbox that must not claim a file it has not got."""
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # Default newline translation on purpose: cmd.exe wants CRLF in a .cmd,
    # and that is exactly what a text-mode write gives it on Windows.
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(script())
    # +x for everyone who can already read it (0o755 minus the user's umask
    # is what a shell would give it).
    mode = os.stat(target).st_mode
    os.chmod(target, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def remove():
    """Take the shortcut away. A file that is already gone is the wanted state,
    not an error; anything else (a Windows lock, a read-only directory) is the
    caller's to report."""
    try:
        os.remove(path())
    except FileNotFoundError:
        pass


def refresh():
    """Rewrite an installed shim *when it would come out different*, so it keeps
    pointing at KiCad's Python after an upgrade moved it. Never creates one: a
    shim the user removed must stay removed. Best effort -- called while a
    window is opening, which must not fail over a shortcut.

    The comparison is what keeps installing a once-only thing: every launch
    would otherwise rewrite a file whose content nobody changed, which is a
    reinstall as far as anything watching the disk is concerned.
    """
    if not installed():
        return None
    try:
        with open(path(), encoding="utf-8") as handle:
            if handle.read() == script():
                return path()  # already what an upgrade would produce
    except OSError:
        pass  # unreadable: fall through and write it again
    try:
        return write()
    except OSError:
        return None
