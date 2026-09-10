"""This plugin's window: the shell, its pages, and the sections only an
antenna designer needs.

Plain wx widgets — a small simulation form, a run button and a live log — no
HTML/JS and no browser bridge. The only embedded HTML viewer is the core's
ResultDialog: a page of the shipped viewer drawing a run's dump or a whole
scan's, or a pre-flight guide, each shown in the slot window ViewerHub keeps
for pages of that kind.

The widgets, the theme, the viewer host and every section that is not about
an antenna are the core's (``emkit.gui``), and a page imports each from
wherever it comes from — which is what keeps the seam visible where it is used.

Modules:
    shell   — AntennaShell, the window hosting the views (icon sidebar +
              Simplebook), plus the update strip pinned across their top (the
              feature itself is emkit.update, not this package)
    pages/  — the book pages (SimulatePage, DesignWizardPage, InfoPage): each a
              composition of sections, over the core's BookPage and the
              DesignFormPage the two form pages share, plus the wizard's host
              facade
    sections/ — this plugin's own form sections (the target form, the run flow,
              the area marker, the scan, the Results box, the footprint placer)
"""


def show(parent=None):
    """Open this plugin's window (or raise the one already open).

    Both imports are made here rather than above: importing ``.shell`` binds
    the submodule as this package's ``shell`` attribute -- which is this
    module's global namespace -- so a core ``shell`` imported at module level
    would be silently replaced by this plugin's own the first time the window
    was opened."""
    from ..emkit.gui.shell import show as show_window
    from .shell import AntennaShell

    return show_window(AntennaShell, parent)
