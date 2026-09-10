"""KiCad pcbnew action plugin: the Antenna Designer EM-simulation dialog."""

__version__ = "0.2.0"

from .emkit.kicad.hosted import hosted

# Only when KiCad is the one importing us. The command line runs out of this
# same package (``emkit/run_agent.py``), and registering a toolbar button
# outside the application prints a failed assertion to stderr -- see
# emkit/kicad/hosted.py for why the check is on the caller.
if hosted():
    from .action_plugin import AntennaPlugin

    AntennaPlugin().register()
