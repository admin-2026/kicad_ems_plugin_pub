"""KiCad pcbnew action plugin: the Antenna Designer EM-simulation dialog."""

__version__ = "0.1.0"

from .action_plugin import AntennaPlugin

AntennaPlugin().register()
