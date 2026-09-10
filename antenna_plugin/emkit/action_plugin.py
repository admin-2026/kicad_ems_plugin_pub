"""The pcbnew toolbar button, as far as it is the same button for every plugin.

KiCad asks an ``ActionPlugin`` for its name, its category, its icon and what
to do when it is pressed. Three of those the product's manifest already
answers; the fourth is one line in the subclass:

    class AntennaPlugin(PluginBase):
        def open(self):
            from . import gui

            gui.show()

Everything else -- the version in the tooltip, the old-KiCad advisory, turning
a failure to open into a message instead of a traceback in KiCad's log -- is
the same whichever plugin this is.
"""

import os

import pcbnew

from .. import product
from .kicad.version import kicad_version_warning


class PluginBase(pcbnew.ActionPlugin):
    """Toolbar button that opens the plugin's native window."""

    def defaults(self):
        from . import versions

        self.name = product.NAME
        self.category = product.CATEGORY
        self.description = (
            f"Open the {product.NAME} window (v{versions.plugin_version()})"
        )
        self.show_toolbar_button = True
        # Beside the package's own root, not the core's: the glyph is the
        # product's identity and cannot be one shared drawing.
        self.icon_file_name = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), product.ICON
        )

    def open(self):
        """Show the plugin's window. The one thing a subclass must answer."""
        raise NotImplementedError

    def Run(self):
        try:
            _record_interpreter()
            warning = kicad_version_warning()
            if warning:
                notify(warning)  # say it, then open anyway
            self.open()
        except Exception as exc:
            notify(f"{product.NAME} failed to open: {exc}")


def _record_interpreter():
    """Write down the Python this is running on, which is by definition one
    with ``pcbnew`` in it. The command line reads it and re-execs into it, so
    an agent learns one command rather than a per-OS table of paths
    (agent/hostpy.py). Here because it is the one moment the plugin is
    certainly inside KiCad; never fatal, since a window must open whether or
    not a file could be written.

    A shortcut the user installed has that same path baked into it, so it is
    rewritten from the fresh recording (agent/shim.py) -- an upgraded KiCad
    moves the interpreter, and this is where the shim catches up. Only ever a
    rewrite: one the user removed stays removed."""
    try:
        from .agent import hostpy, shim

        hostpy.record()
        shim.refresh()
    except Exception:
        pass


def notify(text):
    """Best-effort status message; never fatal if wx is unavailable."""
    try:
        import wx

        wx.LogMessage(text)
    except Exception:
        print(text)
