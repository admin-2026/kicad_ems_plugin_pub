"""The shell's book pages: the top-level views AntennaShell hosts.

Each page is a base.BookPage — a scrolled form composed of reusable sections
(gui.sections) — that owns no widgets of its own, just the wiring between its
sections and the page-level glue (settings persistence, the wizard's facade).
Every page also describes its own sidebar tab (``tab_icon`` / ``tab_hint`` /
``tab_at_bottom``), so the shell builds the sidebar without knowing what any of
them is: adding a view is a module here plus a line in the shell's page list.

There are three page *classes* but any number of pages: the simulate view, one
DesignWizardPage per antenna design in design.registry (the shell builds them in
a loop; a design's page differs only by the design object it carries), and the
About view.

The Pattern-frequency, Speed and Advanced sections and the feed-width /
Feed-layer picks appear on the simulate and designer pages as views onto one
datastore (gui.model.FormModel) that the shell syncs on page switch; that sync
is DesignFormPage's, one implementation for both. Only the Marker-layer pick
stays on the simulate page — the designers borrow it (and the result viewers)
through host.WizardHost.

Modules:
    base       — BookPage, the scrolled-form base every page shares
    designform — DesignFormPage, the base of the pages carrying the shared
                 design form (the model sync and the feed picks over it)
    simulate   — SimulatePage, the settings/run view (form + feed + speed + run
                 + advanced + pre-flight banner)
    wizard     — DesignWizardPage, one antenna designer (form + area + speed +
                 scan + results + footprint + advanced), driven by its design
    info       — InfoPage, the About view (version table)
    host       — WizardHost, the wizard sections' facade onto their page
"""

from .base import BookPage
from .designform import DesignFormPage
from .info import InfoPage
from .simulate import SimulatePage
from .wizard import DesignWizardPage

__all__ = ["BookPage", "DesignFormPage", "DesignWizardPage", "InfoPage", "SimulatePage"]
