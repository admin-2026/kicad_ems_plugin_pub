"""AntennaShell: which views this plugin's window holds.

The window itself -- the sidebar of tabs, the page book, the update strip
across their top, the shared-form sync on a page switch and the whole
lifecycle -- is the core's ``emkit.gui.shell.Shell``. What is here is the one
thing it asks a plugin for: the pages, in tab order.

They are the simulate view (settings + Run, pages.simulate.SimulatePage), one
designer per antenna in design.registry (pages.wizard.DesignWizardPage -- so
shipping another topology adds a tab without an edit here) and the About view
(pages.info.InfoPage), which sits at the foot of the sidebar because it says
``tab_at_bottom``.
"""

from ..design import registry
from ..emkit.gui.shell import Shell
from .pages import DesignWizardPage, InfoPage, SimulatePage


class AntennaShell(Shell):
    def build_pages(self, book):
        """Every page, in tab order. Simulate comes first -- it is the primary
        page (the log, the viewers and the settings are its), and the designers
        borrow its feed-marker picks and its result windows, so it must exist
        before they do."""
        self.simulate = SimulatePage(book)
        # Seed the model from the simulate page's just-loaded settings, so a
        # designer picks up the same values when it is first shown.
        self.model.read(self.simulate)
        # One designer page per registered antenna design, in registry order.
        self.wizards = [
            DesignWizardPage(book, self.simulate, design) for design in registry.DESIGNS
        ]
        return [self.simulate, *self.wizards, InfoPage(book)]
