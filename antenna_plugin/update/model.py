"""What an update check found, as plain data.

Two frozen records shared by every layer of the folder: a ``Release`` (what the
source offers) and an ``Outcome`` (what the checker made of it). They import
nothing of their own, so the source module, the checker and the wx strip can
each hold one without any of them having to import the others.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Release:
    """One published release of the plugin, as the source describes it."""

    version: str  # the released version, as published ("0.2.0")
    url: str  # the page a user downloads it from
    name: str = ""  # the release's title, when it has one worth showing


@dataclass(frozen=True)
class Outcome:
    """The answer to "is there a newer version?", including the answers that
    are not a version: the check was switched off, or it could not be made.

    ``status`` is one of the checker's four constants; ``release`` is set only
    when the status is UPDATE, and ``detail`` carries the one line explaining a
    SKIPPED or FAILED check (for the run log -- the window shows nothing for
    either: a plugin that cannot reach the internet is not a problem the user
    asked to hear about)."""

    status: str
    release: Optional[Release] = None
    detail: str = ""
