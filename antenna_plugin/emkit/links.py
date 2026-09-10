"""Where to find the project: the outward links the About page offers.

The source repository and the community chat, as one list a UI renders — the
same shape as the version facts next door (emkit.versions): this
module decides *what* is worth linking to, and the section that shows it
(gui.sections.links) decides nothing.

Both addresses are published and real. A link added here before its destination
exists is written under ``example.com`` instead — the domain IANA reserves for
exactly this, and the one address that can never turn out to belong to somebody
else while the real one is pending; ``is_placeholder`` is what then lets the
page own up to it rather than pretending a dead link works.

A URL here is a *configuration* fact, not a fact about the code — the same kind
as the release repository the update check reads (update.github.REPO), which
names the same repository as GITHUB_URL below and is the other line to edit if
the project ever moves.
"""

import collections

from .. import product

# The scheme+host a not-yet-published link is written under, and the marker
# ``is_placeholder`` looks for. Reserved by IANA (RFC 2606) and so unregistrable
# by anyone else: a link the user follows before we have published the real one
# lands nowhere, never on a squatter.
PLACEHOLDER_HOST = "https://example.com/"

# The public source repository. The product names it once (product.REPO, as
# "owner/repo", which is the spelling the update check needs); this is the
# browsable form of the same fact.
GITHUB_URL = product.GITHUB_URL

# Where a bug report or a feature request goes: the repository's issue tracker.
# Not a row of ``entries`` -- it is offered by the About page's Feedback box
# (gui.sections.feedback), beside the sentence that asks for one.
ISSUES_URL = f"{GITHUB_URL}/issues"

# The community chat: the Discord server's invite.
DISCORD_URL = "https://discord.gg/XDY6EE5WA"

# The product website.
WEBSITE_URL = "https://www.automaticphysics.com/"

# One row of the About page's links table: what the row is for ("Source
# code"), what the link itself is called ("GitHub") and where it goes.
Link = collections.namedtuple("Link", "label name url")


def entries():
    """The links to offer, in the order they should be shown."""
    return [
        Link("Website", "automaticphysics.com", WEBSITE_URL),
        Link("Source code", "GitHub", GITHUB_URL),
        Link("Community chat", "Discord", DISCORD_URL),
    ]


def is_placeholder(url):
    """Is ``url`` a stand-in (PLACEHOLDER_HOST) rather than a published
    address? A page shows such a link all the same -- it is what tells the user
    the thing is coming -- but says so, instead of letting them find out by
    following it. Nothing in ``entries`` is one today."""
    return url.startswith(PLACEHOLDER_HOST)
