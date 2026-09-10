"""Who is importing the plugin: KiCad's plugin loader, or a shell.

The package's ``__init__`` registers an ``ActionPlugin`` the moment it is
imported. Under KiCad that is exactly right -- it is how the toolbar button
appears. Outside it, it is wrong twice over: in a plain Python there is no
``pcbnew`` to subclass at all, and under KiCad's own Python (which the command
line uses, because it is the interpreter that has ``pcbnew``) registering
outside the application prints

    action_plugin.cpp(163): assert "PgmOrNull()" failed

to stderr before any verb has done anything. Every command's output is
polluted, which is why this is the first thing the command line needed.

**The check is on the caller, not on the environment.** The two obvious probes
do not work, and that was established by trying them: ``pcbnew.Pgm`` is not in
the 9.0.2 SWIG surface, and ``GetBoard()`` is ``None`` inside KiCad as well as
outside. Importing ``wx`` to ask whether an app exists makes every later
``LoadBoard`` print a screenful of warnings. What *is* visible is the stack: a
``runpy`` frame means somebody ran ``python -m``, and nothing else in this
tree is imported that way.

**The bias is to register.** A stray line on stderr is a nuisance; a plugin
that fails to appear in KiCad is the whole product missing. So anything this
cannot identify counts as KiCad, and only the one recognisable non-KiCad
caller is excluded.

Pure stdlib, and the answer is a pure function of a list of module names, so
the branch that cannot be reached from a test run can still be tested.
"""

import sys

# The stdlib module that runs ``python -m <package>``: it is on the stack for
# the whole of the import it triggers, under this name or a submodule of it.
RUNNER = "runpy"


def caller_modules():
    """Every module name on the stack above this call, innermost first."""
    names = []
    frame = sys._getframe(1)
    while frame is not None:
        names.append(frame.f_globals.get("__name__", ""))
        frame = frame.f_back
    return names


def hosted(callers=None):
    """Whether this import looks like KiCad loading the plugin.

    ``callers`` is the stack's module names (the live stack by default), so a
    test can put a ``runpy`` frame on it without running one.
    """
    names = caller_modules() if callers is None else list(callers)
    return not any(name == RUNNER or name.startswith(RUNNER + ".") for name in names)
