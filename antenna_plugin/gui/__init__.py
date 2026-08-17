"""Native wxPython GUI for the Antenna Designer plugin.

The main dialog is plain wx widgets — a small simulation form, a run button
and a live log — no HTML/JS and no browser bridge. The only embedded HTML
viewer is viewer.ResultDialog: a page of the shipped viewer drawing a run's
dump or a whole scan's (antenna_plugin/viewer/), or a pre-flight guide, each
shown in the slot window viewers.ViewerHub keeps for pages of that kind.

Modules:
    shell   — AntennaShell, the window hosting the views (icon sidebar +
              Simplebook), plus the update strip pinned across their top (the
              feature itself is antenna_plugin.update, not this package)
    pages/  — the book pages (SimulatePage, DesignWizardPage, InfoPage): each a
              composition of sections, over the BookPage / DesignFormPage bases
              they share, plus the wizard's host facade
    sections/ — composable form sections (target form, speed, feed marker,
              Advanced, the run flow, the Results box, the run log, …) the
              views build from
    place   — clipboard + simulated-paste cursor placement for markers
    activelayer — switching the PCB editor's active layer from the plugin
    reveal  — taking the PCB editor to a board item (a placed marker)
    icons   — the bundled PNGs (tab icons, scan and marker drawings) as bitmaps
    viewer  — ResultDialog, the embedded grid/report HTML viewer
    viewers — ViewerHub, the named viewer windows a page shows its pages in
    options — static choice tables and the speed/accuracy presets
    settings— save/restore the form to a YAML file across launches
    board   — pcbnew queries (board facts, copper layer names)
    theme   — the look: the spacing scale, the type scale and the frame every
              section is built into
    widgets — small shared wx helpers and fixed control widths
"""

import wx

_dialogs = []  # keep modeless dialogs alive (avoid GC)


def show(parent=None):
    """Show the modeless native window. One instance: re-invoking the plugin
    raises the existing window instead of opening a second one, whose run
    would race the first on the board's simulation folder."""
    from .shell import AntennaShell

    if _dialogs:
        dlg = _dialogs[-1]
        _bring_to_front(dlg)
        return dlg
    if parent is None:
        parent = wx.GetActiveWindow()
    dlg = AntennaShell(parent)
    _dialogs.append(dlg)
    dlg.Bind(wx.EVT_CLOSE, _on_close)
    dlg.Centre()
    dlg.Show()
    _bring_to_front(dlg)
    return dlg


def _bring_to_front(dlg):
    """Put ``dlg`` in front of the editor window the plugin was invoked from.
    Raise() alone leaves a minimised window minimised and the keyboard on the
    editor, so un-minimise first and take the focus after."""
    if dlg.IsIconized():
        dlg.Iconize(False)
    dlg.Raise()
    dlg.SetFocus()


def _on_close(event):
    dlg = event.GetEventObject()
    if dlg in _dialogs:
        _dialogs.remove(dlg)
    dlg.save_settings()  # persist the form for the next launch
    dlg.shutdown()  # stop a run in flight + tear down the viewers
    dlg.Destroy()
