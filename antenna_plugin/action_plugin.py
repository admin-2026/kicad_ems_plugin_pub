"""Action plugin definition shown on the pcbnew toolbar."""

import os

import pcbnew

from . import __version__


class AntennaPlugin(pcbnew.ActionPlugin):
    """Toolbar button that opens the native Antenna Designer dialog."""

    def defaults(self):
        self.name = "Antenna Designer"
        self.category = "Antenna"
        self.description = f"Open the antenna EM-simulation dialog (v{__version__})"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        try:
            from .kicad.version import kicad_version_warning

            warning = kicad_version_warning()
            if warning:
                _notify(warning)  # say it, then open anyway

            from . import gui

            gui.show()
        except Exception as exc:
            _notify(f"Antenna Designer failed to open: {exc}")


def _notify(text):
    """Best-effort status message; never fatal if wx is unavailable."""
    try:
        import wx

        wx.LogMessage(text)
    except Exception:
        print(text)
