"""What this installation is made of, as version strings.

One place answers "which plugin, which simulator, which host?" — the pieces
that have to agree when something misbehaves: the plugin itself, the bundled
solver binary and the config schema they speak, plus the KiCad / Python / wx
the plugin is running inside. Versions only, no paths: where a file sits is a
fact about this machine, not about what is running. The shell's About page
shows exactly this list (gui.sections.versions renders it; it decides nothing).

Every probe is best-effort: a fact that can't be established answers UNKNOWN
rather than raising, so an odd host can never keep the page from opening.

**Every value here is free.** There was one that was not — the solver's own
version, which used to be read by launching the binary — and the whole list
carried a deferred-value protocol for it: a callable instead of a string, a
PENDING placeholder, a ``resolve`` for a caller to run off its UI thread, and a
worker thread in the About page to run it on. The solver declares its version
now (``solver_version``), so there is nothing slow left to defer and none of
that machinery remains. A caller reads ``entries()`` and shows it.
"""

import platform

from .. import product

UNKNOWN = "unknown"

# The row naming this plugin's own version. Named because a caller looks the
# row up by it -- the About page annotates it when the update check (the
# ``update`` package) has found a newer release than the one it reports.
PLUGIN_LABEL = f"{product.NAME} plugin"


# --------------------------------------------------------------------------- #
# the individual facts
# --------------------------------------------------------------------------- #
def plugin_version():
    """This plugin's version (the package's ``__version__``)."""
    try:
        from .. import __version__

        return __version__
    except ImportError:
        return _version_from_init()  # a package assembled without its __init__


def _version_from_init():
    """``__version__`` read out of the package's ``__init__.py`` as text.

    The command line reaches the plugin through a *bare* package -- one with
    no ``__init__`` to run, because running it is what registers the toolbar
    button and that belongs to KiCad (see emkit/run_agent.py). So the import
    above cannot answer there, and without this the one row that says which
    plugin you are running reads "unknown" on the surface most likely to be
    reporting a bug.

    Read rather than executed, and by hand rather than with ast, because the
    line is a literal assignment at the top of a file this project writes.
    """
    import re
    from pathlib import Path

    init = Path(__file__).resolve().parents[1] / "__init__.py"
    try:
        text = init.read_text(encoding="utf-8")
    except OSError:
        return UNKNOWN
    found = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    return found.group(1) if found else UNKNOWN


def config_schema_version():
    """The runner-config schema the plugin writes -- the contract with the
    solver binary, which rejects a config whose MAJOR differs from its own."""
    try:
        from ..config import CONFIG_VERSION

        return CONFIG_VERSION
    except ImportError:
        return UNKNOWN


def kicad_version():
    """The running KiCad's full build version string."""
    try:
        import pcbnew

        return pcbnew.GetBuildVersion() or UNKNOWN
    except Exception:
        return UNKNOWN


def supported_kicad_version():
    """The oldest KiCad the plugin is written against (kicad.version). Older
    hosts run, with a warning -- so this is a fact, not a gate."""
    from .kicad.version import supported_kicad_version_str

    return supported_kicad_version_str()


def python_version():
    return platform.python_version()


def wx_version():
    """The wxPython the GUI is drawn with (e.g. "4.2.1 gtk3 (phoenix)")."""
    try:
        import wx

        return str(wx.version())
    except Exception:
        return UNKNOWN


def solver_version():
    """The bundled solver's version, as this release declares it
    (``product.BINARY_VERSION``).

    **Read, not asked.** It used to be asked -- launch the binary with
    ``--version`` and take the last word -- which is a process spawn, and on a
    machine whose solver runs in a container it is a *container start*: far too
    slow for a page that opens on a click, and unanswerable whenever the engine
    is not running. Since nothing here mixes versions across components (the
    plugin, its solver and the config schema they speak move together), the
    manifest already knows, and a declaration cannot be more wrong than a probe
    is slow.

    What made that trade safe is that the declaration is checked where a
    machine can actually check it: ``tools/binary_sync.py`` runs the build it
    copies out of the simulator's tree and refuses a mismatch. The check moved
    off every user's About page, where it cost a spawn and could only report,
    onto the maintainer's, where it costs nothing and stops the mismatch from
    shipping.
    """
    return getattr(product, "BINARY_VERSION", UNKNOWN)


# --------------------------------------------------------------------------- #
# the list a UI shows
# --------------------------------------------------------------------------- #
def entries():
    """Every version fact as ``(label, value)``, in display order: what this
    plugin is, what it runs, what they agree on, and what it runs inside.

    Every value is a string and every one of them is cheap, so there is nothing
    for a caller to do but show them."""
    return [
        (PLUGIN_LABEL, plugin_version()),
        ("Simulator", solver_version()),
        ("Runner config schema", config_schema_version()),
        ("KiCad", kicad_version()),
        ("Written for KiCad", f"{supported_kicad_version()} or later"),
        ("Python", python_version()),
        ("wxPython", wx_version()),
    ]
