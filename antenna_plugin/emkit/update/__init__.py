"""Is there a newer release of this plugin than the one running?

A launch-time courtesy, and nothing more: when the shell opens it asks the
release source in the background whether a newer version exists and, if one
does, shows a dismissible strip across the top of the window with a link to it.
Everything else about the plugin carries on regardless -- the check runs on a
daemon thread, answers an ``Outcome`` instead of raising, and a failure (no
network, a proxy, a rate limit, a mangled reply) is a log line, never a dialog
and never a block. The user's work is not waiting on it.

The folder is layered so the part worth testing needs neither wx nor a network:

    model    — Release / Outcome: what the check found, as plain data
    version  — comparing two version strings, and nothing else (pure)
    trust    — which root certificates the HTTPS call is verified against, on a
               Python (KiCad's, on macOS) that may ship none
    github   — the release source: the API URL, the fetch, the payload -> Release
    checker  — the policy: fetch, compare, answer an Outcome; check_async runs
               that off the caller's thread
    strip    — UpdateStrip, the wx strip that shows the answer (the only module
               here that knows what a window is)

The dependency arrows all point one way (strip -> checker -> github -> trust /
model / version), and the source is injected: ``check`` takes any zero-argument
callable answering a ``Release``, so swapping GitHub for a JSON manifest on the
product website is a new module beside ``github`` plus the argument -- no other
file here changes, and the tests pass a stub instead of touching the network.

Nothing outside this folder imports anything but this facade; the shell's whole
share of the feature is building ``UpdateStrip`` and starting it
(gui.shell). ``UpdateStrip`` is deliberately *not* re-exported here: it is the
one module that imports wx, and the rest must stay importable without it.
"""

from .checker import CURRENT, FAILED, SKIPPED, UPDATE, check, check_async
from .model import Outcome, Release

__all__ = [
    "CURRENT",
    "FAILED",
    "Outcome",
    "Release",
    "SKIPPED",
    "UPDATE",
    "check",
    "check_async",
]
