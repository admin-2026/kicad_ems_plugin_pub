"""This plugin's toolbar button: it opens the Antenna Designer window.

Everything else about the button -- its name, its icon, the version in its
tooltip, the old-KiCad advisory it shows first -- is the core's
``emkit.action_plugin.PluginBase`` reading the product manifest.
"""

from .emkit.action_plugin import PluginBase


class AntennaPlugin(PluginBase):
    def open(self):
        from . import gui

        gui.show()
