"""The OS gate: macOS has no solver build yet, so say so instead of failing
sideways.

TEMPORARY, and written to be deleted in one commit. ``git grep os_support``
finds everything there is to remove:

    sim/simulate.py   ``locate()`` asks here before it hands out an executable
    versions.py       the About page's Simulator row says this instead of
                      "not found"
    tests/test_os_support.py

Nothing else imports it, and it imports nothing of the plugin's: the rest of
the system does not know the gate exists, and taking it out leaves the two
callers a line shorter each. When a macOS solver ships, that is the whole
change -- plus ``PLATFORMS`` in tools/make_package.py, which is what decides
whose build a release carries.

Why a gate rather than nothing: ``binaries/`` holds a Linux build and a Windows
build. On macOS ``locate()`` finds neither and raises its "reinstall the
plugin, or set ANTENNA_SIM_ROOT" guidance -- which sends a user after a file
that has never been in the package, on the machine where the advice cannot
work. One sentence naming the real reason is worth more than a correct message
about the wrong thing.

The gate is about running the *solver*, not about running the plugin: KiCad,
wx and everything the plugin draws work on macOS, and the geometry half of it
(markers, the design wizard's drawing, the material picker) is genuinely
usable there. Only a simulation cannot start, so only the paths that reach for
the binary consult this.
"""

import sys

# The platforms with no bundled solver build, as ``sys.platform`` spells them
# -> how to say it to a person. sys.platform (not platform.system()) because
# it is the same string the installer already branches on, it needs no
# subprocess, and it cannot answer "" on an odd host.
UNSUPPORTED = {"darwin": "macOS"}


class UnsupportedHost(RuntimeError):
    """No solver build exists for the machine the plugin is running on.

    A RuntimeError, so the GUI's existing "the run did not start" handlers
    print :func:`str` of it like any other refusal and no caller needs to know
    this type -- catching it is only worth doing where the *distinction*
    matters (versions.solver_version, which would otherwise report a
    perfectly-installed plugin as "not found").

    It carries the same fact in both lengths it is ever wanted in -- the
    sentence (``str``) and ``short``, a table cell's worth -- so a caller that
    caught this one never has to ask which OS it was about a second time and
    get a different answer.
    """

    def __init__(self, name):
        super().__init__(message(name))
        self.os_name = name  # "macOS"
        self.short = f"not built for {name}"


def host_name(platform=None):
    """How to say this host's OS, if it is one without a solver -- else None.
    ``platform`` overrides what is asked (tests; nothing else has a reason)."""
    key = sys.platform if platform is None else platform
    for prefix, name in UNSUPPORTED.items():
        if key.startswith(prefix):
            return name
    return None


def message(name):
    """What a user is told when they try to simulate on *name*."""
    return (
        f"The simulator does not run on {name} yet: the plugin ships a Linux "
        f"and a Windows build of it, and there is no {name} one to bundle. "
        "Drawing and editing an antenna works here; simulating it needs one "
        "of the supported systems."
    )


def check(platform=None):
    """Raise :class:`UnsupportedHost` when this machine has no solver build,
    and do nothing at all otherwise -- the shape that keeps the gate to a
    single line at each caller."""
    name = host_name(platform)
    if name:
        raise UnsupportedHost(name)
