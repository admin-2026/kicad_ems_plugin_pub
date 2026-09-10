"""VersionsSection: the version table of the About page.

A titled box of label / value rows built straight from the version facts
(emkit.versions) — the plugin, the bundled solver, the schema they
agree on and the KiCad / Python / wx underneath. This section decides nothing
about *what* is worth showing: it renders the list that module hands it, so
adding a fact is a line there, not here.

Every value is free to read, so the table is drawn once and never revisited.
It was not always: the solver's version used to be read by launching the
binary, which is a process spawn and on a container-only machine a container
start, so this section had a worker thread, a PENDING placeholder and a
``refresh`` that started them. The solver declares its version now, and all of
that went with it.

The plugin's own row also carries the launch-time update check's answer, when
there is one to carry ("0.1.0 — 0.2.0 available"): the page hands it in
(``show_update``) from the shell's update strip, which is what actually ran the
check. Nothing is asked of the network here.

Values are ellipsized to the field width rather than wrapped, so a long one (a
wx build string) can't force the form wider than the window; the full text is
on the row's tooltip.
"""

import wx

from ... import update, versions
from ..theme import ROW
from ..widgets import FIELD_W, muted
from .base import Section


class VersionsSection(Section):
    _TITLE = "Versions"

    def __init__(self, page, body):
        super().__init__(page)
        self._entries = versions.entries()
        self._values = []  # the value labels, in row order
        self._update_note = ""  # "0.2.0 available", once a check says so
        self._build(body)

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        p = self.scroll
        box = self.box(self._TITLE)
        grid = wx.FlexGridSizer(2, ROW, 2 * ROW)  # 2 columns; vgap, hgap
        for label, _value in self._entries:
            name = wx.StaticText(p, label=label)
            muted(name)
            grid.Add(name, 0, wx.ALIGN_CENTER_VERTICAL)
            shown = wx.StaticText(
                p, label="", size=(FIELD_W, -1), style=wx.ST_ELLIPSIZE_MIDDLE
            )
            self._values.append(shown)
            grid.Add(shown, 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(grid, 0, wx.EXPAND)
        self._show(self._entries)
        self.add_to_body(body, box)

    # --- the rows -------------------------------------------------------------
    def _show(self, entries):
        """Write ``entries``' values onto the value labels. The full text also
        goes on the tooltip, since a long one is ellipsized in the middle. The
        rendered list is kept, so a later note (``show_update``) can re-render
        without re-reading anything."""
        self._entries = entries
        for shown, (label, value) in zip(self._values, entries):
            text = value
            if label == versions.PLUGIN_LABEL and self._update_note:
                text = f"{text} — {self._update_note}"
            shown.SetLabel(text)
            shown.SetToolTip(text)

    def refresh(self):
        """The About page came up. Nothing to do: every value was read when the
        page was built and none of them can change while it is open. Kept as
        the page's own call, so a fact that one day *is* worth re-reading has a
        place to be read in."""

    def show_update(self, outcome):
        """Note a newer release on the plugin's own row ("0.1.0 — 0.2.0
        available"), the shell's update strip having already found it: the
        table is where a user looks up what they have, so it is where the
        answer belongs once the strip has been dismissed. Every other outcome
        -- no check yet, up to date, a check that failed or was switched off --
        leaves the table alone. This section checks nothing itself; it is
        handed the answer (gui.pages.info)."""
        note = ""
        if outcome is not None and outcome.status == update.UPDATE:
            note = f"{outcome.release.version} available"
        if note == self._update_note:
            return
        self._update_note = note
        try:
            self._show(self._entries)
            self._relayout()
        except RuntimeError:
            pass  # the page went away with the window (the check is async)
