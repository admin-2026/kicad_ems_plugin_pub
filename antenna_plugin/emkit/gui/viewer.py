"""ResultDialog: the only embedded HTML viewer.

Shows a page of the shipped viewer (emkit/viewer/, three.js and all)
inside KiCad, pointed at the dump it should draw. One instance is reused per
parent dialog — the grid preview loads first, then the report replaces it in
the same window. The pre-flight
banner's help pages open in a second instance (caption "<product name>
help") so a guide never replaces a report the user is reading.
"""

import wx

# Injected into the result pages at document start: a throwing module script
# (e.g. three.js failing to import) renders a silent blank page, so forward JS
# errors to the run log instead. The error listener runs in the capture phase
# because resource-load failures (a blocked/missing script) fire on the element
# and do not bubble; for those, report the URL that failed to load.
_ERR_HOOK = (
    "window.addEventListener('error',function(e){"
    "try{var t=e&&e.target,u=t&&(t.src||t.href);"
    "var m=(e&&(e.message||e.error))||(u&&('failed to load '+u))||e;"
    "window.kicadlog.postMessage(String(m).slice(0,500));}"
    "catch(_){}},true);"
    "window.addEventListener('unhandledrejection',function(e){"
    "try{window.kicadlog.postMessage('promise: '+String(e&&e.reason).slice(0,500));}"
    "catch(_){}});"
)


def _script_message_event():
    """The WebView script-message event binder for this wx build (the binder
    was renamed across wxWidgets versions, so resolve it by name)."""
    import wx.html2

    for name in (
        "EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED",  # wxWidgets 3.1.5+
        "EVT_WEBVIEW_SCRIPT_MESSAGE",
    ):
        binder = getattr(wx.html2, name, None)
        if binder is not None:
            return binder
    raise RuntimeError("this wx.html2 build has no script-message event")


class ResultDialog(wx.Dialog):
    def __init__(self, parent, on_log=None, caption="Simulation results"):
        import wx.html2

        super().__init__(
            parent,
            title=caption,
            size=(1280, 900),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )
        self.SetMinSize((640, 480))
        self._caption = caption
        self._on_log = on_log
        self._pending = None
        self.web = wx.html2.WebView.New(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.web, 1, wx.EXPAND)
        self.SetSizer(sizer)

        # The Edge/WebView2 backend initialises asynchronously and can drop a
        # LoadURL issued before it is ready; re-issue it once it signals that
        # it was created. Surface load failures so a blank page isn't silent.
        created = getattr(wx.html2, "EVT_WEBVIEW_CREATED", None)
        if created is not None:
            self.web.Bind(created, self._on_created)
        error = getattr(wx.html2, "EVT_WEBVIEW_ERROR", None)
        if error is not None:
            self.web.Bind(error, self._on_error)

        # A blank result page is almost always a JS error (a three.js module
        # that failed to import/run), which EVT_WEBVIEW_ERROR does not report.
        # Register a log channel and inject a document-start hook that forwards
        # window errors to it, so "nothing showed" always has a reason. Best
        # effort: guarded so an older wx build without these APIs still loads.
        try:
            self.web.AddScriptMessageHandler("kicadlog")
            self.web.Bind(_script_message_event(), self._on_js_log)
            add_user = getattr(self.web, "AddUserScript", None)
            if add_user is not None:
                add_user(_ERR_HOOK)
        except Exception:
            pass

    def load(self, url, title):
        self.SetTitle(f"{self._caption} — {title}")
        self._pending = url
        self.web.LoadURL(url)

    def _on_created(self, event):
        if self._pending:
            self.web.LoadURL(self._pending)

    def _on_error(self, event):
        if self._on_log:
            detail = ""
            try:
                detail = event.GetString()
            except Exception:
                pass
            self._on_log(f"viewer could not load the page ({detail})".strip())

    def _on_js_log(self, event):
        if self._on_log:
            try:
                self._on_log(f"viewer JS error: {event.GetString()}")
            except Exception:
                pass
