"""``guide`` -- the briefing to read before the first verb.

Everything the rest of this surface assumes you already know: the command, the
interpreter, the order the verbs go in, what a run costs, which files beside
the board are yours to touch, and what this plugin can build. One page, no
sub-topics -- a topic list is one more thing to discover before you can
discover anything, and a reader that can hold this page can hold it whole.

**It takes no board and needs no ``pcbnew``.** This is the first command
somebody types, usually before they have learned which interpreter has the
board bindings, so a guide that needed one would fail exactly where it is
needed most. That also means it names no resolved project path: the folder
beside a board is described relative to the board, and the paths it *does*
print are this install's own, which are true without asking anything.

The page is assembled next door (``agent/guide.py``) because a verb does not
compute. What is here is the four names and nothing else.
"""

from .. import guide

NAME = "guide"
HELP = "Start here: how this plugin works, what to edit, what it can build"


def add_arguments(parser):
    """Nothing. No board, no topic, no options -- the whole page, always."""


def run(args):
    from .. import shim

    return {"command": shim.STEM, "guide": guide.page()}


def lines(payload):
    return payload["guide"].splitlines()
