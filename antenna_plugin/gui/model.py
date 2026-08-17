"""FormModel: the shared design-form datastore behind the shell's design pages.

The simulate view (pages.simulate.SimulatePage) and every designer
(pages.wizard.DesignWizardPage) each build their own *Design target*,
*Speed / accuracy* and *Advanced* sections, their own feed-width /
Feed-layer / Marker-layer picks (a designer's in its area section) and their own
pass knobs (the simulate view's in its Run section, a designer's in its Scan
section), but those are views onto
one model: the values live here, not in any page's widgets. The pages sit in a
wx.Simplebook and are never visible at once, so the visible page's widgets are
just the live edit buffer -- the shell reads the outgoing page into the model
and writes the model onto the incoming page as the user switches pages
(gui.shell), and flushes the visible page before persisting. Editing the
frequency (or any speed/advanced knob) on one page thus changes one shared
value every other page reflects.

The model is a plain flat ``key: value`` string dict, the same shape ``settings``
serialises, so persistence reads straight from it. It carries every field of
that form -- the Marker-layer pick included, which is why the feed marker and a
designer's area marker are always drawn on the same User layer, and the pass
knobs each page builds beside its own solver button (sections.passknobs), which
is why a scan and the verification run after it are solved the same way. What
stays off
it is what belongs to one page alone: a designer's scan rows, tuned to its own
design (pages.wizard.DesignWizardPage.settings_snapshot).

The page side of the seam is two methods every model-backed page exposes
(pages.designform.DesignFormPage implements them for all of them):
    shared_snapshot() -> dict   the page's shared widgets as a flat dict
    shared_restore(data)        set those widgets from ``data`` (no edit events)

A page carrying none of this form (the About view) inherits no-op versions from
pages.base.BookPage: it contributes nothing to the model and takes nothing from
it, so the shell can sync every page it switches between without asking what
each one is.
"""


class FormModel:
    def __init__(self):
        self.data = {}

    def read(self, page):
        """Snapshot ``page``'s shared sections into the model (widgets -> model)."""
        self.data.update(page.shared_snapshot())

    def write(self, page):
        """Restore the model onto ``page``'s shared sections (model -> widgets)."""
        page.shared_restore(self.data)
