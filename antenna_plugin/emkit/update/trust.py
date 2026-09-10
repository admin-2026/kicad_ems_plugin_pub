"""Which certificates the check verifies GitHub against.

The API call is HTTPS, so OpenSSL has to be told which root certificates to
trust. Python asks the OpenSSL it was built against, and on Linux that answers
the distribution's bundle -- but a KiCad shipped as a macOS app carries its own
Python framework, whose ``OPENSSLDIR`` points inside a bundle that holds no
certificates at all. Nothing is misconfigured on the machine; the interpreter
simply has an empty trust store, and *every* verification against it fails the
same way::

    update check: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate
    verify failed: unable to get local issuer certificate>

which is the failure this module exists to answer. (The usual cure, running
python.org's "Install Certificates.command", is not something a plugin may ask
of a user, and not something it may do to KiCad's own interpreter.)

So the trust store is *chosen* rather than assumed: ``contexts`` answers the
verifying contexts worth trying, best first -- the interpreter's own default
whenever it actually has roots loaded, then a context built on the first CA
bundle found on disk (certifi if this Python has it, else macOS's own
``/etc/ssl/cert.pem``, else Homebrew's). ``urlopen`` walks that list, moving on
only when the failure was the verification itself.

Two rules hold the module together. Verification is never switched off: a
``check_hostname``/``CERT_REQUIRED`` context is the only thing built here, and
an install with no bundle anywhere raises the original error rather than
trusting whatever answered. And nothing here is macOS-specific by *test* -- no
branch on the platform, only a search for a file that exists, which is why the
same code answers the Linux and Windows cases (where the default store is
populated and the first context is the only one tried).

``SSL_CERT_FILE``/``SSL_CERT_DIR`` still work, and are the escape hatch for a
site with a private root or a TLS-inspecting proxy: OpenSSL reads them when the
default context loads, so a bundle named there simply makes the first context
the one that succeeds.
"""

import os
import ssl
import urllib.error
import urllib.request

# CA bundles to fall back on, in the order they are tried, when the running
# interpreter has no roots of its own. The first two are macOS's own copy of
# the system roots (the same file under both spellings of /etc); the rest are
# where Homebrew's ca-certificates and openssl formulae keep theirs. A path
# that isn't there is skipped, so this list costs nothing on a machine that
# needs none of it.
BUNDLES = (
    "/etc/ssl/cert.pem",
    "/private/etc/ssl/cert.pem",
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/usr/local/etc/ca-certificates/cert.pem",
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/usr/local/etc/openssl@3/cert.pem",
)

# What to say after "certificate verify failed" in a log line, once the
# fallbacks have been tried too (see hint).
HINT = "no CA bundle found; set SSL_CERT_FILE to one"


def urlopen(request, timeout):
    """``urllib.request.urlopen``, verified against the first trust store that
    works. Returns the response (the caller reads and closes it).

    Raises exactly what urlopen raises; a verification failure is retried
    against the next candidate store, and the last one's failure is the one
    that propagates. Anything else -- a timeout, a refused connection, an HTTP
    error -- is raised where it happened, since another set of roots cannot
    answer it."""
    candidates = contexts()
    for index, context in enumerate(candidates):
        try:
            return urllib.request.urlopen(request, timeout=timeout, context=context)
        except urllib.error.URLError as exc:
            if index == len(candidates) - 1 or not is_verify_error(exc):
                raise
    raise AssertionError("contexts() answered nothing")  # pragma: no cover


def contexts():
    """The verifying SSL contexts to try, best first -- never empty.

    The interpreter's own default comes first, and is left out only when it has
    no roots loaded at all (the macOS case above), where trying it would buy a
    guaranteed failure and a wasted handshake while the user waits. A context
    built on the first bundle found on disk follows it. With no roots anywhere
    the default is answered alone, so the caller fails against the store the
    machine actually has, with the machine's own error."""
    default = ssl.create_default_context()
    chosen = [default] if has_roots(default) else []
    path = bundle()
    if path:
        chosen.append(ssl.create_default_context(cafile=path))
    return tuple(chosen) or (default,)


def bundle():
    """The CA bundle to fall back on -- certifi's if this Python has it, else
    the first of BUNDLES that exists, else None."""
    return _certifi() or next((p for p in BUNDLES if os.path.isfile(p)), None)


def has_roots(context):
    """Does ``context`` trust anything? An interpreter whose OpenSSL points at
    a directory with no certificates in it builds a context with an empty
    store, and that is the whole macOS symptom."""
    try:
        return bool(context.cert_store_stats().get("x509"))
    except Exception:
        return True  # can't tell: treat the default as usable, as it usually is


def is_verify_error(exc):
    """Is ``exc`` the certificate verification failing, rather than the network
    or the server? urlopen wraps it, so the reason is what carries it."""
    return isinstance(
        getattr(exc, "reason", exc), ssl.SSLCertVerificationError
    ) or isinstance(exc, ssl.SSLCertVerificationError)


def hint(exc):
    """The one clause worth adding to a failed check's log line, or ''.

    Only a verification failure earns one, and only when there was no bundle to
    fall back on -- with a bundle present and verification still failing, the
    roots are not what is wrong (a proxy substituting certificates, most
    likely) and a line about them would send the reader the wrong way."""
    if is_verify_error(exc) and not bundle():
        return HINT
    return ""


def _certifi():
    """certifi's bundle, if this interpreter has certifi installed. The plugin
    does not ship it and must not require it; a KiCad whose Python happens to
    carry it (many do, via other packages) simply gets the better answer."""
    try:
        import certifi
    except Exception:
        return None
    try:
        path = certifi.where()
    except Exception:
        return None
    return path if path and os.path.isfile(path) else None
