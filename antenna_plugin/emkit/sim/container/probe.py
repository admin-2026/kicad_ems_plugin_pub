"""Is the container ready, and if not, what should the user do about it?

One question, asked the same way by every frontend, and answered with a
:class:`Status` that carries three things: what state it is in, what was
actually observed, and **what to do next**. The remedy is not decoration. On
macOS this plugin has no native solver, so every state below stands between a
user and their first simulation; and the whole feature exists to be driven by
somebody -- an agent, a script -- who cannot see a window and has only the text.

The states, quietest failure first::

    NO_DOCKER    no `docker` on PATH
    NO_DAEMON    the command is there and the daemon is not answering
    DENIED       the daemon is there and will not talk to this user
    NO_IMAGE     ready, but no image for this release has been built
    STALE        an image is there, built by an older release of the plugin
    KICAD_OLDER  the image's KiCad is older than the one running this
    READY        nothing in the way

Three of those exist because of what the image *is*. It carries the plugin's
own code, so an upgrade leaves it stale (``STALE``); and it carries KiCad, so
its KiCad can be older than the user's -- which matters because a board saved
by a newer KiCad comes back from an older one's ``LoadBoard`` as a bare
``None`` (``emkit.kicad.version`` exists to turn that into a sentence).
Reporting it here means saying it before a run rather than after one.

The order is deliberate: each state is only askable once the ones above it are
settled, so a probe stops at the first thing that is wrong and never reports a
stale image on a machine where the daemon is not running.

Every remedy is the *host's* -- no "add yourself to the docker group" on
Windows -- which is why this module takes the OS as an argument (defaulting to
this one) the way ``sim.hostos`` and ``sim.builds`` do: the branch this machine
is not is still testable on the machine it is.
"""

import json
import subprocess

from .... import product
from .. import builds, hostos
from . import cmd, enginepath, image

NO_DOCKER = "no_docker"
NO_DAEMON = "no_daemon"
DENIED = "denied"
NO_IMAGE = "no_image"
STALE = "stale"
KICAD_OLDER = "kicad_older"
READY = "ready"

# How long the engine gets to answer a question about itself. It answers at
# once when it is well; the bound is for the case that made this a bounded call
# in the first place -- a Desktop VM starting up, which can sit for a long time
# without ever refusing.
TIMEOUT_S = 20

# No URL in any remedy below. A remedy is one line in a banner, and a link
# there is neither clickable nor short: what Docker is and where to get it is
# the container guide's job (help/docker.html), which every one of these rows
# has a button for and which the command line names as `docker guide`.


class Status:
    """What the probe found: a state, what was seen, and what to do.

    ``ready`` is the only thing most callers need; ``detail`` is what was
    observed (a stderr line, a version pair) and ``remedy`` is the sentence to
    put in front of the user. Both are plain text: a section shows them, a verb
    prints them, and neither writes its own words for a state.
    """

    def __init__(self, state, detail="", remedy="", arch=None, kicad=None):
        self.state = state
        self.detail = detail
        self.remedy = remedy
        self.arch = arch  # the container architecture, once the engine says
        self.kicad = kicad  # the KiCad in the image, once one exists

    @property
    def ready(self):
        return self.state == READY

    @property
    def build(self):
        """The solver build a container of this architecture runs, or None."""
        return builds.container_build(self.arch) if self.arch else None

    def __repr__(self):  # pragma: no cover -- diagnostics
        return f"<Status {self.state} {self.detail!r}>"

    def as_dict(self):
        """The same answer as data, for ``--json`` callers."""
        build = self.build
        return {
            "state": self.state,
            "ready": self.ready,
            "detail": self.detail,
            "remedy": self.remedy,
            "arch": self.arch,
            "kicad": self.kicad,
            "image": image.tag(),
            "solver": build.filename(product.BINARY) if build else None,
        }


# --------------------------------------------------------------------------- #
# the remedies, per state and per host
# --------------------------------------------------------------------------- #
def _install_remedy(os_key):
    where = {
        "macos": "Install Docker Desktop",
        "windows": "Install Docker Desktop",
    }.get(os_key, "Install Docker Engine")
    return f"{where}, then build the image -- the container guide has the link."


def _daemon_remedy(os_key):
    if os_key in ("macos", "windows"):
        return "Start Docker Desktop and wait for it to say it is running."
    return "Start the service (`sudo systemctl start docker`), then try again."


def _denied_remedy(os_key):
    if os_key == "linux":
        return (
            "Add yourself to the `docker` group (`sudo usermod -aG docker "
            "$USER`) and log in again -- a new shell alone does not pick it up."
        )
    return "The engine refused this user. Check that it is running as you."


# --------------------------------------------------------------------------- #
# asking
# --------------------------------------------------------------------------- #
def _run(argv, timeout=TIMEOUT_S):
    """Run a short engine command. Returns ``(status, stdout, stderr)``, with
    status None when the command could not be started at all."""
    try:
        done = subprocess.run(
            # ...at wherever it is, which for a window KiCad opened is not
            # something PATH knows (enginepath) -- and with a PATH its own
            # credential helper is on, for the same reason.
            enginepath.resolved(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=enginepath.environ(),
            # No console window. A probe is two spawns and the About page runs
            # one every time it is shown, so on Windows the flags are the
            # difference between a quiet page and a terminal blinking at the
            # user twice per visit (hostos.launch_kwargs).
            **hostos.launch_kwargs(),
        )
    except FileNotFoundError:
        return None, "", "no docker command was found on this machine"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", str(exc)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def _engine(engine, os_key):
    """The first three states, which are all one call's failures."""
    code, out, err = _run(cmd.version_argv(engine))
    if code is None:
        return Status(NO_DOCKER, err, _install_remedy(os_key)), None
    if code == 0:
        return None, out
    lowered = err.lower()
    if "permission denied" in lowered or "access is denied" in lowered:
        return Status(DENIED, err, _denied_remedy(os_key)), None
    return Status(NO_DAEMON, err, _daemon_remedy(os_key)), None


def _image_labels(engine, tag):
    """The image's labels as a dict, or None when there is no such image."""
    code, out, _err = _run(cmd.inspect_argv(tag, engine))
    if code != 0:
        return None
    try:
        found = json.loads(out or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def status(engine="docker", system=None, kicad_version=None):
    """Probe, and answer one :class:`Status`.

    ``kicad_version`` is the host KiCad's ``(major, minor)`` when the caller
    has one -- the window has, a command line on a machine with no KiCad has
    not, and where it is unknown the comparison is simply not made rather than
    guessed at.
    """
    os_key = builds.host_os(system)
    problem, arch = _engine(engine, os_key)
    if problem is not None:
        return problem

    tag = image.tag()
    labels = _image_labels(engine, tag)
    if labels is None:
        return Status(
            NO_IMAGE,
            f"no image {tag}",
            "Build the image (it installs KiCad, so allow a few minutes).",
            arch=arch,
        )

    found_version = labels.get(image.VERSION_LABEL)
    found_kicad = labels.get(image.KICAD_LABEL)
    if image.stale(found_version):
        return Status(
            STALE,
            f"{tag} was built by {product.NAME} {found_version or 'an older release'}",
            "Rebuild the image: this install's code is what goes inside it.",
            arch=arch,
            kicad=found_kicad,
        )

    older = _kicad_older(found_kicad, kicad_version)
    if older is not None:
        return Status(
            KICAD_OLDER,
            older,
            "Rebuild the image. Until then a board saved by your KiCad cannot "
            "be read inside it.",
            arch=arch,
            kicad=found_kicad,
        )
    return Status(READY, f"{tag} is ready", "", arch=arch, kicad=found_kicad)


def _kicad_older(in_image, host):
    """A sentence when the image's KiCad is older than the host's, else None.

    One-directional on purpose: an image *newer* than the host's KiCad reads
    the host's boards perfectly, and is the ordinary state of things for
    anybody who has not upgraded yet.
    """
    if not in_image or not host:
        return None
    try:
        theirs = tuple(int(part) for part in str(in_image).split(".")[:2])
    except ValueError:
        return None
    if theirs >= tuple(host[:2]):
        return None
    return f"the image has KiCad {in_image}; this one is {host[0]}.{host[1]}"
