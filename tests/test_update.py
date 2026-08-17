"""The launch-time update check (antenna_plugin.update), off KiCad and offline.

The folder is layered so this suite needs neither: version comparison is pure,
the GitHub source's payload parsing is separate from its one HTTP call, and the
checker takes the source as an argument -- so every case below hands it a stub,
including the ones that raise. What is being pinned is the promise the feature
rests on: **no way for this check to interrupt the user**. Every failure shape
comes back as an Outcome, and a newer version is only ever claimed when both
versions are readable and one really is later.

    python3 tests/test_update.py
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

links = load("links")
update = load("update")
checker = load("update.checker")
github = load("update.github")
version = load("update.version")
model = load("update.model")

RELEASE = model.Release(version="0.2.0", url="https://example.invalid/releases/0.2.0")


def _source(release=RELEASE):
    return lambda: release


def _raising(exc):
    def source():
        raise exc

    return source


# --- version comparison ---------------------------------------------------- #
def test_a_later_version_is_newer():
    assert version.is_newer("0.2.0", "0.1.0")
    assert version.is_newer("v0.2.0", "0.1.9")  # a git tag's "v"
    assert version.is_newer("1.0.0", "0.99.99")
    assert version.is_newer("0.1.1", "0.1.0")


def test_same_or_older_is_not_newer():
    assert not version.is_newer("0.1.0", "0.1.0")
    assert not version.is_newer("0.1.0", "0.2.0")
    # Missing components are zero, so these are the same version.
    assert not version.is_newer("0.2", "0.2.0")
    assert not version.is_newer("0.2.0", "0.2")


def test_build_metadata_is_ignored_and_prereleases_sort_below():
    assert not version.is_newer("0.2.0+3f2a1c", "0.2.0")
    assert version.is_newer("0.2.0", "0.2.0-rc1")  # the release beats its rc
    assert not version.is_newer("0.2.0-rc1", "0.2.0")


def test_an_unreadable_version_is_never_newer():
    """The install whose version can't be read is never nagged."""
    for text in ("", "v", "unknown", "release-candidate", "1.2.beta", None, 3):
        assert version.parse(text) is None, text
        assert not version.is_newer(text, "0.1.0")
        assert not version.is_newer("0.2.0", text)


# --- the GitHub source ----------------------------------------------------- #
def test_payload_becomes_a_release():
    release = github.release(
        {
            "tag_name": "v0.2.0",
            "html_url": "https://example.invalid/releases/tag/v0.2.0",
            "name": "Antenna Designer 0.2.0",
        }
    )
    assert release.version == "v0.2.0"
    assert release.url.endswith("/tag/v0.2.0")
    assert release.name == "Antenna Designer 0.2.0"


def test_payloads_with_nothing_to_offer_are_none():
    assert github.release({"tag_name": "v0.2.0", "draft": True}) is None
    assert (
        github.release({"tag_name": "v0.2.0", "html_url": "u", "prerelease": True})
        is None
    )
    assert github.release({"html_url": "u"}) is None  # no tag
    assert github.release({"tag_name": "v0.2.0"}) is None  # nowhere to send them
    assert github.release({"message": "Not Found"}) is None
    assert github.release("not json we know") is None


def test_the_configured_repository_is_the_published_one():
    """REPO ships set to the repository the releases come from, and the About
    page's GitHub link names the same one -- the two are one configuration
    fact, so they are checked against each other rather than typed twice."""
    assert github.repo() == "admin-2026/kicad_ems_plugin_pub"
    assert github.latest_url(github.repo()) == (
        "https://api.github.com/repos/admin-2026/kicad_ems_plugin_pub/releases/latest"
    )
    assert links.GITHUB_URL == "https://github.com/" + github.repo()


def test_an_unconfigured_source_makes_no_request():
    """An empty REPO means no update source, and must answer None rather than
    build a nonsense URL -- _get_json is replaced here so a regression shows up
    as a call, not as a network timeout in the suite."""
    called = []
    original_get, original_repo = github._get_json, github.REPO
    github._get_json = lambda url, timeout: called.append(url)
    github.REPO = ""
    try:
        assert github.repo() == ""
        assert github.fetch_release() is None
        assert called == []
    finally:
        github._get_json, github.REPO = original_get, original_repo


def test_the_environment_overrides_the_configured_repo():
    os.environ[github.REPO_ENV] = "owner/repo"
    try:
        assert github.repo() == "owner/repo"
        assert github.latest_url(github.repo()) == (
            "https://api.github.com/repos/owner/repo/releases/latest"
        )
    finally:
        del os.environ[github.REPO_ENV]


# --- the checker ----------------------------------------------------------- #
def test_a_newer_release_is_an_update():
    outcome = checker.check("0.1.0", _source())
    assert outcome.status == update.UPDATE
    assert outcome.release is RELEASE


def test_the_newest_installed_version_is_current():
    assert checker.check("0.2.0", _source()).status == update.CURRENT
    assert checker.check("0.3.0", _source()).status == update.CURRENT


def test_nothing_to_compare_is_skipped_not_failed():
    assert checker.check("0.1.0", _source(None)).status == update.SKIPPED
    unreadable = model.Release(version="latest", url="u")
    assert checker.check("0.1.0", _source(unreadable)).status == update.SKIPPED
    assert checker.check("unknown", _source()).status == update.SKIPPED


def test_a_source_that_raises_is_a_failed_outcome_not_an_exception():
    """The promise the whole feature rests on: whatever the network does, the
    caller (a window opening) gets a value back."""
    for exc in (
        OSError("[Errno -2] Name or service not known"),
        ValueError,
        TimeoutError(),
    ):
        outcome = checker.check("0.1.0", _raising(exc))
        assert outcome.status == update.FAILED
        assert outcome.detail  # a log line, never empty
        assert outcome.release is None


def test_the_check_can_be_switched_off():
    os.environ[checker.CHECK_ENV] = "0"
    try:
        assert not checker.enabled()
        # Switched off means no request at all: a source that would raise is
        # never reached.
        outcome = checker.check("0.1.0", _raising(AssertionError("asked anyway")))
        assert outcome.status == update.SKIPPED
        assert checker.CHECK_ENV in outcome.detail
    finally:
        del os.environ[checker.CHECK_ENV]


# --- off the caller's thread ----------------------------------------------- #
def test_check_async_answers_on_a_daemon_thread():
    landed = []
    thread = checker.check_async("0.1.0", landed.append, _source())
    assert thread.daemon, "a check in flight must never hold KiCad open"
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert [o.status for o in landed] == [update.UPDATE]


def test_a_broken_callback_dies_with_the_worker():
    """By the time the answer lands the window may be gone; a delivery that
    raises must not surface anywhere (there is no one left to tell)."""

    def deliver(_outcome):
        raise RuntimeError("the window closed")

    thread = checker.check_async("0.1.0", deliver, _source())
    thread.join(timeout=5)
    assert not thread.is_alive()


if __name__ == "__main__":
    run_module_tests(globals())
