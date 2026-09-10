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
import ssl
import sys
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import PRODUCT, load, run_module_tests  # noqa: E402

links = load("emkit.links")
update = load("emkit.update")
checker = load("emkit.update.checker")
github = load("emkit.update.github")
trust = load("emkit.update.trust")
version = load("emkit.update.version")
model = load("emkit.update.model")

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
    """REPO ships set to the repository this product's releases come from, and
    the About page's GitHub link names the same one -- one configuration fact
    (product.REPO), so they are checked against each other and against the
    manifest rather than typed out again here."""
    slug = PRODUCT.REPO
    assert slug and slug.count("/") == 1
    assert github.repo() == slug
    assert github.latest_url(slug) == (
        f"https://api.github.com/repos/{slug}/releases/latest"
    )
    assert links.GITHUB_URL == "https://github.com/" + slug


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


# --- the trust store ------------------------------------------------------- #
def _verify_error(message="unable to get local issuer certificate"):
    """The failure a KiCad-on-macOS check comes back with, as urlopen raises
    it: the verification error wrapped in a URLError."""
    return urllib.error.URLError(ssl.SSLCertVerificationError(message))


def _fake_urllib(answers):
    """A stand-in for the urllib trust.urlopen calls, answering ``answers`` in
    order (an Exception is raised, anything else returned). Records the context
    each call was made with."""
    used = []

    def urlopen(request, timeout=None, context=None):
        used.append(context)
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    fake = type(urllib)("urllib")
    fake.request = type(urllib)("request")
    fake.request.urlopen = urlopen
    fake.error = urllib.error
    return fake, used


def _with_urllib(fake, call):
    original = trust.urllib
    trust.urllib = fake
    try:
        return call()
    finally:
        trust.urllib = original


def _installed_bundle():
    """A CA bundle this machine really has, or None -- the fallback tests need
    a file OpenSSL will actually load, and can't invent one."""
    path = ssl.get_default_verify_paths().cafile
    return path if path and os.path.isfile(path) else None


def test_a_python_with_roots_of_its_own_tries_only_its_own():
    """The Linux/Windows case: the interpreter's default store is populated,
    so it is the only context built and nothing else is searched for."""
    original_roots, original_bundle = trust.has_roots, trust.bundle
    trust.has_roots = lambda context: True
    trust.bundle = lambda: None
    try:
        contexts = trust.contexts()
    finally:
        trust.has_roots, trust.bundle = original_roots, original_bundle
    assert len(contexts) == 1
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED


def test_an_empty_store_falls_back_to_a_bundle_on_disk():
    """The macOS case: KiCad's own Python trusts nothing, so the default
    context is skipped (trying it is a guaranteed failure the user waits for)
    and a bundle found on disk is what verifies the call."""
    path = _installed_bundle()
    if path is None:
        return  # no CA bundle on this machine; nothing to build the case from
    original_roots, original_bundle = trust.has_roots, trust.bundle
    trust.has_roots = lambda context: False
    trust.bundle = lambda: path
    try:
        contexts = trust.contexts()
    finally:
        trust.has_roots, trust.bundle = original_roots, original_bundle
    assert len(contexts) == 1
    assert contexts[0].cert_store_stats()["x509"] > 0


def test_no_roots_anywhere_still_answers_the_machines_own_context():
    """With an empty store and no bundle to be found, the check fails against
    the store the machine has -- with its own error, never with no context and
    never with verification off."""
    original_roots, original_bundle = trust.has_roots, trust.bundle
    trust.has_roots = lambda context: False
    trust.bundle = lambda: None
    try:
        contexts = trust.contexts()
    finally:
        trust.has_roots, trust.bundle = original_roots, original_bundle
    assert len(contexts) == 1
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED


def test_verification_is_never_switched_off():
    """The rule the fallback must not quietly break: every context this module
    builds checks the certificate *and* the hostname."""
    for context in trust.contexts():
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname


def test_an_unverifiable_certificate_is_retried_against_the_next_store():
    response = object()
    fake, used = _fake_urllib([_verify_error(), response])
    original = trust.contexts
    trust.contexts = lambda: ("first", "second")
    try:
        answer = _with_urllib(fake, lambda: trust.urlopen("request", 6))
    finally:
        trust.contexts = original
    assert answer is response
    assert used == ["first", "second"]


def test_the_last_stores_failure_is_the_one_raised():
    fake, used = _fake_urllib([_verify_error(), _verify_error("still no")])
    original = trust.contexts
    trust.contexts = lambda: ("first", "second")
    try:
        raised = None
        try:
            _with_urllib(fake, lambda: trust.urlopen("request", 6))
        except urllib.error.URLError as exc:
            raised = exc
    finally:
        trust.contexts = original
    assert raised is not None and "still no" in str(raised)
    assert len(used) == 2


def test_a_failure_that_isnt_about_certificates_is_not_retried():
    """Another set of roots cannot answer a timeout or a refused connection, so
    trying one only makes the user wait twice."""
    fake, used = _fake_urllib([urllib.error.URLError(TimeoutError("timed out"))])
    original = trust.contexts
    trust.contexts = lambda: ("first", "second")
    try:
        raised = None
        try:
            _with_urllib(fake, lambda: trust.urlopen("request", 6))
        except urllib.error.URLError as exc:
            raised = exc
    finally:
        trust.contexts = original
    assert raised is not None
    assert used == ["first"], "one store's timeout is every store's timeout"


def test_a_certificate_failure_says_what_to_do_about_it():
    """The log line the user reported, plus the clause that makes it
    actionable -- but only when missing roots really are the explanation."""
    original = trust.bundle
    trust.bundle = lambda: None
    try:
        detail = checker.check("0.1.0", _raising(_verify_error())).detail
        assert "CERTIFICATE_VERIFY_FAILED" in detail or "certificate" in detail
        assert trust.HINT in detail
        # A bundle was found and verification failed anyway: the roots are not
        # what is wrong, so pointing at them would mislead.
        trust.bundle = lambda: "/somewhere/cert.pem"
        for exc in (_verify_error(), TimeoutError()):
            assert trust.HINT not in checker.check("0.1.0", _raising(exc)).detail
    finally:
        trust.bundle = original


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
