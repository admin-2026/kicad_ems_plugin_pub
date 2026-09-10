"""``docker`` -- the container a solve can run inside, from a command line.

Five topics over ``sim.container`` and ``emkit.hostprefs``::

    docker status     is it ready, and if not, what to do about it
    docker build      build the image for this release
    docker rebuild    delete it and build it again
    docker on / off   remember the answer for this machine

The window has the same five things in a tick and two buttons (the About page's
Docker box). Both go through the same modules and neither decides anything of
its own, which is what keeps "Docker isn't running" from being phrased two
ways.

**Why a command line needs this at all.** The container exists for the case
where the thing driving a run is a script or an agent, and that caller has no
window to press a button in. Without these topics they could turn the container
on only by editing a JSON file by hand, and could find out it was not ready
only by starting a run and reading the refusal.

The two slow ones say so before they charge it: a build installs KiCad and is
minutes, which is the same bargain ``run start`` makes about a solve.
"""

from .... import product
from ... import hostprefs
from ...sim import container
from .. import render

NAME = "docker"
HELP = "The container a solve can run inside"

# What each topic is and its own manual, in the order --help lists them: the
# state of things first, then the two that change it, then the preference.
_TOPICS = (
    (
        "status",
        "Is the container ready, and if not what to do",
        """What stands between this machine and a run inside a container.

Answers one state and, when it is not `ready`, what to do about it -- the same
sentence the window's banner shows and the same one a refused run carries. The
states are: no_docker (nothing installed), no_daemon (installed, not running),
denied (running, not talking to this user), no_image (nothing built for this
release yet), stale (an image from an older release -- the plugin's own code is
inside it, so an upgrade means a rebuild), kicad_older (the image's KiCad
predates this host's, so it cannot read boards this KiCad saves), and ready.

It also prints the path of the Dockerfile the image is built from, which is the
one thing here that is otherwise hard to find: it lives inside the install, and
editing it and rebuilding is a supported thing to do.

Costs one short call to the engine and nothing else. Safe to poll.""",
    ),
    (
        "build",
        "Build the image for this release",
        """Build the workbench image: KiCad, this plugin, its command line and the
solver.

**Minutes, and a few hundred megabytes**, most of it installing KiCad -- and
it is worth saying that a container run is confined to the directory it is
given, which is the point of paying that once.

The image is tagged with this release's version. A plugin upgrade therefore
asks for a tag that does not exist, which is `status` reporting `stale` and
this topic being the answer.""",
    ),
    (
        "rebuild",
        "Delete the image and build it again",
        """Remove this release's image, then build it.

The removal is what makes it a rebuild rather than a cache hit on whichever
layer was wrong. What it is for: a plugin upgrade (the image carries the
plugin's code), a KiCad in the image that has fallen behind the one on this
machine, or an image somebody suspects.""",
    ),
    (
        "on",
        "Run solves in a container on this machine from now on",
        """Remember, for this machine, that solves go through a container.

Not for this board: a preference that travelled with a project would be a
setting about somebody else's laptop. It is the same answer the About page's
tick writes, and either can change it.

It does not build anything and does not check anything -- `status` is for
that, and a run that finds the container unready refuses with the reason.""",
    ),
    (
        "off",
        "Run solves natively on this machine from now on",
        """Forget it again: solves run natively.

Refused where there is no native solver to run -- on macOS this product has
none, and a flag quietly ignored would be worse than one refused.""",
    ),
)

TOPICS = tuple(name for name, _help, _description in _TOPICS)


def add_arguments(parser):
    topics = parser.add_subparsers(dest="topic", required=True, metavar="<topic>")
    for name, help_text, description in _TOPICS:
        topics.add_parser(name, help=help_text, description=description)


def run(args):
    return {
        "status": _status,
        "build": lambda: _build(rebuild=False),
        "rebuild": lambda: _build(rebuild=True),
        "on": lambda: _prefer(True),
        "off": lambda: _prefer(False),
    }[args.topic]()


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def _status():
    found = container.status()
    payload = found.as_dict()
    # What the *preference* says, which is a different question from whether
    # the container works: a machine can be ready and set to run natively, and
    # a caller deciding whether to trust a run's confinement needs both.
    payload["enabled"] = hostprefs.use_docker()
    payload["forced"] = hostprefs.docker_forced()
    # Where the recipe is. Printed because it is otherwise genuinely hard to
    # find -- it lives inside an install whose path KiCad chose -- and because
    # editing it and rebuilding is a supported thing to do.
    payload["dockerfile"] = container.image.dockerfile()
    return payload


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _build(rebuild):
    """Build (or rebuild) the image, streaming the engine's output to stdout.

    Streamed rather than captured: it is minutes long, and a caller staring at
    a silent terminal cannot tell a slow apt from a wedged one. The lines are
    the engine's own -- nothing here interprets them.
    """
    lines = []
    removed = container.image_remove() if rebuild else None
    ok = container.image_build(on_line=lines.append)
    return {
        "image": container.image.tag(),
        "rebuilt": bool(rebuild),
        "removed": removed,
        "ok": ok,
        "output": lines,
    }


# --------------------------------------------------------------------------- #
# the preference
# --------------------------------------------------------------------------- #
def _prefer(wanted):
    refusal = hostprefs.refused(None if wanted else False)
    if refusal:
        raise RuntimeError(refusal)
    written = hostprefs.save(hostprefs.DOCKER, wanted)
    return {"docker": wanted, "saved_to": written, "product": product.NAME_KEY}


# --------------------------------------------------------------------------- #
# reading it back
# --------------------------------------------------------------------------- #
def lines(payload):
    if "state" in payload:
        return _status_lines(payload)
    if "saved_to" in payload:
        state = "in a container" if payload["docker"] else "natively"
        return [f"Solves on this machine now run {state}.", f"  {payload['saved_to']}"]
    return _build_lines(payload)


def _status_lines(payload):
    rows = [
        {"label": "State", "value": payload["state"]},
        {"label": "Image", "value": payload["image"]},
    ]
    if payload["arch"]:
        rows.append({"label": "Container", "value": payload["arch"]})
    if payload["solver"]:
        rows.append({"label": "Solver", "value": payload["solver"]})
    if payload["kicad"]:
        rows.append({"label": "KiCad in it", "value": payload["kicad"]})
    if payload.get("dockerfile"):
        rows.append({"label": "Recipe", "value": payload["dockerfile"]})
    rows.append(
        {
            "label": "Solves run",
            "value": (
                "in a container (this OS has no native solver)"
                if payload["forced"]
                else ("in a container" if payload["enabled"] else "natively")
            ),
        }
    )
    out = render.columns(rows, (14, "label"), (0, "value"))
    if payload["detail"]:
        out.append(f"  {payload['detail']}")
    if payload["remedy"]:
        out.append(f"  {payload['remedy']}")
    return out


def _build_lines(payload):
    verb = "Rebuilt" if payload["rebuilt"] else "Built"
    if not payload["ok"]:
        # The engine's last few lines are where the reason is; the whole log
        # went to stdout as it happened.
        tail = [f"  {line}" for line in payload["output"][-5:]]
        return [f"Could not build {payload['image']}."] + tail
    return [f"{verb} {payload['image']}."]
