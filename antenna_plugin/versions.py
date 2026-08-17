"""What this installation is made of, as version strings.

One place answers "which plugin, which simulator, which host?" — the pieces
that have to agree when something misbehaves: the plugin itself, the bundled
solver binary and the config schema they speak, plus the KiCad / Python / wx
the plugin is running inside. Versions only, no paths: where a file sits is a
fact about this machine, not about what is running. The shell's About page
shows exactly this list (gui.sections.versions renders it; it decides nothing).

Every probe is best-effort: a fact that can't be established answers UNKNOWN
rather than raising, so an odd host can never keep the page from opening.

A value in ``entries()`` may be a *callable* instead of a string — a probe too
slow for a UI thread (running the solver binary is a process spawn). A caller
shows PENDING for those and calls ``resolve`` off its main thread.
"""

import platform

UNKNOWN = "unknown"
PENDING = "checking…"  # shown while a deferred probe is still running

# The row naming this plugin's own version. Named because a caller looks the
# row up by it -- the About page annotates it when the update check (the
# ``update`` package) has found a newer release than the one it reports.
PLUGIN_LABEL = "Antenna Designer plugin"

# How long the solver gets to print its version before the probe gives up. It
# prints and exits immediately; the timeout is only there so a binary that
# can't run on this host (the wrong platform's build, a blocked executable)
# can't wedge the worker.
SOLVER_TIMEOUT_S = 10


# --------------------------------------------------------------------------- #
# the individual facts
# --------------------------------------------------------------------------- #
def plugin_version():
    """This plugin's version (antenna_plugin.__version__)."""
    try:
        from . import __version__

        return __version__
    except ImportError:
        return UNKNOWN  # a package assembled without its __init__


def config_schema_version():
    """The runner-config schema the plugin writes -- the contract with the
    solver binary, which rejects a config whose MAJOR differs from its own."""
    try:
        from .sim.config import CONFIG_VERSION

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
    """The bundled binary's own version, asked of the binary (``--version``
    prints ``monopole <major>.<minor>.<patch>``). A binary that isn't there --
    ``locate`` raises with install guidance -- reads "not found", which is a
    version fact of its own; on a host no build exists for, the same row says
    that instead (sim.os_support, a temporary gate: remove this arm with it),
    because a plugin installed perfectly is not one missing a file. A process
    spawn: call it off a UI thread."""
    from .sim import os_support, simulate

    try:
        exe = simulate.locate()[0]
    except os_support.UnsupportedHost as exc:
        return exc.short
    except Exception:
        return "not found"
    try:
        out = simulate.capture(exe, "--version", timeout=SOLVER_TIMEOUT_S)
    except Exception:
        return UNKNOWN
    return _version_word(out) or UNKNOWN


def _version_word(text):
    """The version out of a ``--version`` line (``"monopole 1.18.0"`` -> the
    last word of the first non-blank line); '' when there is nothing to take."""
    for line in (text or "").splitlines():
        if line.strip():
            return line.split()[-1]
    return ""


# --------------------------------------------------------------------------- #
# the list a UI shows
# --------------------------------------------------------------------------- #
def entries():
    """Every version fact as ``(label, value)``, in display order: what this
    plugin is, what it runs, what they agree on, and what it runs inside. A
    ``value`` that is callable is a deferred probe -- see ``resolve``."""
    return [
        (PLUGIN_LABEL, plugin_version()),
        ("Simulator", solver_version),  # deferred: runs the binary
        ("Runner config schema", config_schema_version()),
        ("KiCad", kicad_version()),
        ("Written for KiCad", f"{supported_kicad_version()} or later"),
        ("Python", python_version()),
        ("wxPython", wx_version()),
    ]


def resolve(entries_):
    """``entries_`` with every deferred value called, so the whole list is
    strings. The slow half of the list: call it off a UI thread and show the
    result when it lands."""
    return [(label, value() if callable(value) else value) for label, value in entries_]
