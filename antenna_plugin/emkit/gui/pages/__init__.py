"""The page bases and the one page every plugin's window has.

``base.BookPage`` is the scrolled form that composes sections and describes its
own sidebar tab; ``info.InfoPage`` is the About view -- the versions, the
project links and the bundled documentation -- which is the same page whatever
the plugin simulates. Which *other* pages a window holds is the plugin's
answer, in its own ``gui.pages`` package.
"""

from .base import BookPage
from .info import InfoPage

__all__ = ["BookPage", "InfoPage"]
