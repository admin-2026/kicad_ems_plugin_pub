"""The release source: GitHub's "latest release" API.

One GET of
``https://api.github.com/repos/<owner>/<repo>/releases/latest``, whose JSON
names the newest published release -- its tag (``tag_name``, the version) and
the page a human downloads it from (``html_url``). The endpoint already skips
drafts and pre-releases; the parse re-checks both anyway, since being wrong
here means nagging every user about a version they can't have.

The repository is a *configuration* fact, not a fact about the code, and this
checkout has no remote to read it from -- so it is written down, once, as
``product.REPO`` (the same repository ``links.GITHUB_URL`` offers on the About
page and ``tools/publish.py`` mirrors into). Left
empty it would mean "no update source configured", which the checker treats as
"nothing to check" (see checker.check: a skipped check, silent in the window,
one line in the log). ``ANTENNA_UPDATE_REPO`` overrides it, which is how a test
or a fork points the check elsewhere without editing the install.

Transport rules, all of them about not making the user wait: stdlib urllib (the
plugin ships no HTTP dependency and KiCad's Python has none to borrow), a hard
timeout, a size cap on the reply, and no retries -- a check that doesn't answer
promptly is simply not answered this launch. Failures raise; the checker is
what turns them into an Outcome. The one thing this module does not decide is
which certificates the connection is verified against, because on some hosts
the interpreter has none: see ``trust``.
"""

import json
import os
import urllib.request

from ... import product
from . import trust
from .model import Release

# The repository the releases are published from, as "owner/repo". Empty means
# no update source is configured: the checker then makes no request at all.
REPO = product.REPO

# Overrides REPO for one run (a fork, a staging repo, a test).
REPO_ENV = "ANTENNA_UPDATE_REPO"

API_URL = "https://api.github.com/repos/{repo}/releases/latest"

# Seconds any single socket operation gets. Short on purpose: this runs while
# the user is opening the window, and an answer that arrives after they have
# started working is worth nothing.
TIMEOUT_S = 6

# Bytes of the reply that are read. A release payload is a few kB; the cap is
# only there so a wrong URL (a captive portal's login page, a proxy error) can
# never hand the worker a stream to swallow.
MAX_BYTES = 256 * 1024

# GitHub rejects an API request without a User-Agent, and asks for the API
# version to be pinned so a future one can't change the fields read below.
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": f"{product.NAME.replace(' ', '')}-KiCad-plugin",
}


def repo():
    """The configured "owner/repo", or '' when there is none (see REPO)."""
    return (os.environ.get(REPO_ENV) or REPO).strip().strip("/")


def latest_url(slug):
    return API_URL.format(repo=slug)


def fetch_release(timeout=TIMEOUT_S):
    """The newest published release, as a ``Release`` -- or None when there is
    nothing to compare against: no repository configured, or a repository whose
    latest release is a draft/pre-release or carries no usable tag.

    Raises whatever the request raises (URLError, HTTPError, timeout, a reply
    that isn't JSON). This is the callable ``checker.check`` defaults to, and
    the shape any other source has to match: no arguments it insists on, a
    Release or None back, exceptions allowed."""
    slug = repo()
    if not slug:
        return None
    return release(_get_json(latest_url(slug), timeout))


def release(payload):
    """A ``Release`` out of the API's JSON, or None if the payload doesn't
    describe a release a user should be pointed at."""
    if not isinstance(payload, dict):
        return None
    if payload.get("draft") or payload.get("prerelease"):
        return None
    version = (payload.get("tag_name") or "").strip()
    url = (payload.get("html_url") or "").strip()
    if not version or not url:
        return None
    return Release(version=version, url=url, name=(payload.get("name") or "").strip())


def _get_json(url, timeout):
    """GET ``url`` and parse the (capped) reply as JSON."""
    request = urllib.request.Request(url, headers=_HEADERS)
    with trust.urlopen(request, timeout) as response:
        body = response.read(MAX_BYTES)
    return json.loads(body.decode("utf-8", "replace"))
