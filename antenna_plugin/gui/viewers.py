"""ViewerHub: the embedded HTML viewer windows a page shows its pages in.

Everything the plugin renders as HTML -- a run's grid preview and report, the
scan's combined views, a pre-flight guide -- opens in an embedded WebView dialog
(viewer.ResultDialog) inside KiCad, never the OS browser. There are only ever a
handful of such windows, one per *slot*: a slot is a named window that pages of
one kind take turns in, so re-showing that kind reuses its window instead of
piling up dialogs, while kinds that belong side by side (a scan's report and its
grid views) keep their own. Guides get a third slot so one never replaces a
report the user is reading.

The hub owns those windows: it creates one on first use, raises and loads it on
every show, and destroys it when the user closes it or the shell shuts down. It
knows nothing about runs, boards or the simulator -- a caller hands it a URL and
a title -- so any section can present a page without owning a viewer. A URL
rather than a path because a result page is a page plus what it was pointed at
(``report.html?d=…``, see sim.simulate.viewer_url); ``file_url`` below is for
the callers that really do just have a file.

The simulate page builds the hub and tears it down on close; the wizard page
borrows it (both expose ``page.viewers``), so a scan's views and a run's land in
the same windows.
"""

from pathlib import Path

import wx

from .viewer import ResultDialog

# The viewer slots. Grid/report pages and the scan's combined report share the
# results window (the primary view, one at a time); the scan's grid views get
# their own so a finished scan can show both at once; guides get a third.
RESULTS = "results"
SCAN_GRID = "scan_grid"
HELP = "help"

# Each slot's window caption (its title bar carries this plus the page title).
_RESULTS_CAPTION = "Simulation results"
_CAPTIONS = {
    RESULTS: _RESULTS_CAPTION,
    SCAN_GRID: _RESULTS_CAPTION,
    HELP: "Antenna Designer help",
}


def file_url(path):
    """A local file as the URL ``present`` wants -- for a page that is just a
    file (a pre-flight guide), with nothing to point it at."""
    return Path(path).resolve().as_uri()


def show_guide(page, filename, title):
    """Open the bundled guide ``antenna_plugin/help/<filename>`` in ``page``'s
    help window -- the HELP slot, its own window, so a guide never replaces a
    grid or report the user is reading.

    A guide is plain HTML that links its stylesheet from the sibling
    ``assets/`` dir and runs no scripts, and there is nothing to point it at,
    so it is shown as the file it is. Returns False when the page is missing
    from the install (a partial one) or the WebView can't be created; the
    caller says so in its own words, since a banner row and the About page have
    different things to fall back on.

    Every guide the plugin opens comes through here -- a pre-flight banner row
    (sections.banner) and the About page's settings reference alike."""
    from ..sim import simulate

    path = simulate.guide_page(filename)
    if path is None:
        page.log(f"help page {filename} is missing from this install")
        return False
    return page.viewers.present(HELP, file_url(path), title)


class ViewerHub:
    """The viewer windows of one page tree, keyed by slot (see the module
    docstring). ``parent`` is the window the dialogs parent on; ``on_log``
    receives the viewer's own messages (load and JS errors)."""

    def __init__(self, parent, on_log=None):
        self._parent = parent
        self._log = on_log or (lambda text: None)
        self._viewers = {}  # slot -> ResultDialog (created on demand)

    def present(self, slot, url, title):
        """Show ``url`` (a local ``file://`` one -- ``file_url``, or a viewer
        page with what it draws in its query) in ``slot``'s viewer window,
        creating and centring the window on first use. Returns False when the
        WebView can't be created (an install without wx.html2), having logged
        where the page can be opened by hand.

        Show comes before load so the WebView backend is realised first --
        it matters for the async Edge/WebView2 backend, which can drop a
        LoadURL issued before it signals that it was created.
        """
        viewer = self._viewers.get(slot)
        if viewer is None:
            try:
                viewer = ResultDialog(
                    self._parent,
                    on_log=self._log,
                    caption=_CAPTIONS.get(slot, _RESULTS_CAPTION),
                )
            except Exception as exc:
                self._log(f"Embedded viewer unavailable ({exc}); open manually: {url}")
                return False
            viewer.Bind(wx.EVT_CLOSE, lambda event, s=slot: self.close(s))
            viewer.Centre()
            self._viewers[slot] = viewer
        viewer.Show()
        viewer.Raise()
        viewer.load(url, title)
        return True

    def close(self, slot):
        """Destroy ``slot``'s window if it is open (the user closed it, or the
        shell is shutting down); the next present builds a fresh one."""
        viewer = self._viewers.pop(slot, None)
        if viewer is not None:
            viewer.Destroy()

    def close_all(self):
        """Tear down every open viewer -- symmetric with their creation in
        ``present``; called when the shell closes."""
        for slot in list(self._viewers):
            self.close(slot)
