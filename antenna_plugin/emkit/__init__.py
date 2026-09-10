"""emkit -- the parts of a KiCad EM-simulation plugin that are not about one
kind of simulation.

One tracked copy, nested inside every plugin built out of this repository
(``tools/assemble.py`` puts it there; it is never a top-level package on
``sys.path``, because KiCad imports a plugin's directory under a name that is
not its own and two plugins carrying a shared top-level module would silently
get whichever loaded first).

What lives here reads the board, drives the solver process, and draws wx: the
stackup and gerbers, the marker geometry, the run session and its control
file, the widgets, the theme, the shared sections and page base, the viewer
host, the update check, the material and application catalogs, the viewer app
and the help pages. What does not is anything that knows what a particular
solver's keys and outputs *mean* -- that is the plugin's.

The dependency runs one way, with exactly two exceptions: every plugin hosting
this package must provide two modules of its own at its root, and the core
reaches out to them by relative import.

    ``product``  what the plugin is called, which solver it drives, which
                 repository it is released from (``from ...product import``).
                 It imports nothing, so the build-time tools can read it too.
    ``config``   the runner YAML this flow writes, and the schema version it
                 is written against. Each flow tracks its own solver's reader,
                 so this is deliberately not shared code.

There is no version number here. What ships, and what a user reports, is the
product's ``__version__``; an internal one would be a second thing to bump and
a first thing to forget.
"""
