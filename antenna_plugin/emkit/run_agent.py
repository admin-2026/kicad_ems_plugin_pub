#!/usr/bin/env python3
"""The command line's entry point: one script, runnable from anywhere.

    python3 <install>/<package>/emkit/run_agent.py versions
    python3 <install>/<package>/emkit/run_agent.py preflight --board b.kicad_pcb

**Why not ``python -m <package>.emkit.agent``.** The Plugin Manager extracts an
install to ``<3rdparty>/plugins/<identifier with dots replaced by
underscores>/`` -- for this project ``com_github_admin-2026_kicad-ems-plugin-pub``,
which is neither the package's own name nor a legal Python identifier. Only a
``tools/install.py`` install is named after ``product.PACKAGE``. So the
documented entry point names no package at all: it is a file, it finds the
package by being *inside* it, and it works in both install shapes and in an
assembled checkout.

**How it reaches the package.** Not by importing it -- the package's
``__init__`` is what registers the toolbar button, and that belongs to KiCad.
A bare package is built around the same directory instead, exactly as
``tools/install.py`` and the test harness already do, so every relative import
below it works untouched and nothing runs on the way in.

**Which Python.** The board verbs need ``pcbnew``, which lives only in KiCad's
own interpreter. Rather than making the caller know which one that is, this
re-execs into the interpreter the plugin recorded the last time its window
opened (``agent/hostpy.py``) -- so an agent learns one command instead of a
table of paths. If nothing was ever recorded, or the recorded one is this one,
it carries on and the board verbs explain themselves (``agent/kicad.py``).

``--worker`` is the detached child ``run start`` spawns. It is not a verb: it
never appears in ``--help``, and no caller should reach it by accident.

**The short spelling.** The About page can write a one-word shortcut for the
command above -- interpreter and this path baked in, so neither has to be
typed (``agent/shim.py``). It is a convenience *over* this file, never a
replacement for it: the spelling here is the one that always works, and the
one every message and guide gives.
"""

import importlib
import os
import sys
import types

# This file, with every symlink on the way resolved: a caller may well have
# put a link to it on their PATH, and the package is found by where this file
# *is*, not by the name it was reached through. ``abspath`` would make the
# package the link's own directory and every import below it fail.
LAUNCHER = os.path.realpath(__file__)

# The installed package: the directory this file's own directory sits in.
PACKAGE_DIR = os.path.dirname(os.path.dirname(LAUNCHER))

# What the package is imported as here. Not its own name, which may be
# anything at all after a Plugin Manager install, and not one that runs its
# ``__init__``.
BARE_NAME = "_plugin_package"

# The first argument that means "be the detached run worker, not the command
# line". A flag rather than a verb, so it is neither listed nor reachable by a
# caller reading --help.
WORKER_FLAG = "--worker"


def load(dotted):
    """One module of the plugin, without running the package's ``__init__``."""
    if BARE_NAME not in sys.modules:
        module = types.ModuleType(BARE_NAME)
        module.__path__ = [PACKAGE_DIR]
        sys.modules[BARE_NAME] = module
    return importlib.import_module(f"{BARE_NAME}.{dotted}")


def reexec_into_kicad_python():
    """Hand this command to the interpreter that has ``pcbnew``, if this one
    does not and one was recorded.

    Cannot loop: the child is a different executable, so it either has pcbnew
    and returns here at once, or it is the one recorded and stops on the
    identity check.
    """
    try:
        import pcbnew  # noqa: F401
    except ImportError:
        pass
    else:
        return
    interpreter = load("emkit.agent.hostpy").interpreter()
    if not interpreter:
        return
    if os.path.abspath(interpreter) == os.path.abspath(sys.executable):
        return
    os.execv(interpreter, [interpreter, LAUNCHER, *sys.argv[1:]])


def main():
    argv = sys.argv[1:]
    if argv[:1] == [WORKER_FLAG]:
        # The worker needs no pcbnew -- every board-reading step happened in
        # the parent -- so it never re-execs, which also means a detached
        # child can never be spawned twice over.
        return load("emkit.agent.worker").main(argv[1:])
    reexec_into_kicad_python()
    return load("emkit.agent.cli").main(argv)


if __name__ == "__main__":
    sys.exit(main())
