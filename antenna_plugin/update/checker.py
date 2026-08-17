"""The policy: ask the source, compare, answer -- without ever raising.

``check`` is the whole decision. It runs the source (by default
github.fetch_release), compares what came back with the version that is
running (update.version), and answers one ``Outcome``:

    UPDATE   a newer release exists; ``outcome.release`` is it
    CURRENT  this install is the newest published release
    SKIPPED  there was nothing to decide -- the check is switched off, no
             source is configured, the source offered no release, or one of
             the two versions isn't a version at all
    FAILED   the source was asked and couldn't answer (offline, proxy, rate
             limit, a reply that isn't the JSON expected)

FAILED and SKIPPED are separate because they read differently in a log line,
and identical to the window, which shows nothing for either. That is the point
of the module: a version check is a courtesy, so *every* way it can go wrong
lands in a returned value, not in an exception on the caller's thread. The
source is called inside a bare ``except Exception`` for exactly that reason --
the caller is a window opening, and there is no failure here worth interrupting
it for.

``check_async`` is the same call on a daemon thread, handing the Outcome to a
callback. It answers immediately (a started Thread) and cannot be waited on by
accident; nothing in the plugin joins it, and a KiCad that quits mid-check
takes it with it. The callback runs *on that worker thread* -- a GUI caller
marshals it back itself (update.strip does, through wx.CallAfter), because a
module that decides which toolkit's main loop this is would be one more thing
coupling the checker to the window.
"""

import os
import threading

from . import github, version
from .model import Outcome

# The four answers (Outcome.status).
UPDATE = "update"
CURRENT = "current"
SKIPPED = "skipped"
FAILED = "failed"

# Set to 0/no/off/false to switch the check off entirely -- no request is made.
# An off switch that needs no UI: it is read per check, so a site that forbids
# the call can set it in the environment KiCad launches from.
CHECK_ENV = "ANTENNA_UPDATE_CHECK"
_OFF = ("0", "no", "off", "false")


def enabled():
    """Is the check switched on? (CHECK_ENV, on unless it says otherwise.)"""
    return os.environ.get(CHECK_ENV, "").strip().lower() not in _OFF


def check(current_version, source=None):
    """Is there a newer release than ``current_version``? Answers an
    ``Outcome`` and never raises -- see the module docstring for the four
    statuses.

    ``source`` is any zero-argument callable answering a ``Release`` or None
    (github.fetch_release by default); it is allowed to raise, and a raise is
    what FAILED means."""
    if not enabled():
        return Outcome(SKIPPED, detail=f"switched off ({CHECK_ENV})")
    try:
        release = (source or github.fetch_release)()
    except Exception as exc:
        return Outcome(FAILED, detail=_reason(exc))
    return _compare(release, current_version)


def _compare(release, current_version):
    """The comparison half of ``check``, once a source has answered."""
    if release is None:
        return Outcome(SKIPPED, detail="no published release to compare against")
    if version.parse(release.version) is None:
        return Outcome(
            SKIPPED, detail=f"unreadable released version {release.version!r}"
        )
    if version.parse(current_version) is None:
        return Outcome(
            SKIPPED, detail=f"unreadable installed version {current_version!r}"
        )
    if version.is_newer(release.version, current_version):
        return Outcome(UPDATE, release=release)
    return Outcome(CURRENT, release=release)


def check_async(current_version, deliver, source=None):
    """Run ``check`` on a daemon thread and hand the Outcome to ``deliver``.

    Returns the started thread (for a test that wants to join it); callers
    don't wait on it -- that is the whole point. ``deliver`` is called on the
    worker thread, so a GUI caller marshals it onto its own loop; a ``deliver``
    that raises is swallowed here, since by then there is no one left to tell.
    """

    def run():
        outcome = check(current_version, source)
        try:
            deliver(outcome)
        except Exception:
            pass  # the window went away mid-check, or its own handler broke

    thread = threading.Thread(target=run, name="antenna-update-check", daemon=True)
    thread.start()
    return thread


def _reason(exc):
    """A failed check as one log line: the exception's own message where it has
    one (urllib's "<urlopen error [Errno -2] Name or service not known>"), its
    type where it doesn't (a bare timeout)."""
    text = str(exc).strip()
    return text or exc.__class__.__name__
