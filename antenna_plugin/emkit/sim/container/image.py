"""What the image is called, what it says about itself, and where it is built
from.

The tag is the product and the release, and nothing else::

    antenna-workbench:0.2.0        si-workbench:0.2.0

**No content digest.** The tempting alternative is to hash the Dockerfile so
that editing it changes the tag; it would be a second version to reason about
that could only ever agree with the first. The plugin, the solver it carries,
the config schema they speak and this image all move together as one release --
nothing in this product mixes versions across components -- so the release
version is already the answer to "is this image the one for this install".

That matters more here than it would for an image holding only a runtime,
because **this image carries the plugin's own code**: the package is copied in
at build time so that a person or an agent can work inside the container with
the command line already installed. An upgraded plugin is therefore an image
that no longer matches, and the tag saying so out loud -- the install asks for
``0.3.0`` and only ``0.2.0`` exists -- is how "rebuild it" gets said instead of
last release's code quietly answering.

``latest`` moves too, for the human typing ``docker run`` by hand.

The labels are the same facts written inside the image, for two questions an
image can be asked without starting it: which release built it (the same string
as the tag, so an image renamed by hand cannot lie about itself) and which
KiCad is in it -- the one that decides whether a board saved by the user's own
KiCad can be read in there at all.

Pure but for the product manifest: no subprocess, no filesystem beyond naming
the build context.
"""

import os
import shutil

from .... import product
from ... import versions

# The image's name, after the product. A workbench rather than a solver: what
# is inside is KiCad, the plugin, its command line and the solver, and calling
# it "-solver" would undersell it to the person deciding whether to go in.
SUFFIX = "workbench"

# The labels the Dockerfile sets and `inspect` reads back.
VERSION_LABEL = "org.opencontainers.image.version"
KICAD_LABEL = "io.kicad.version"
PRODUCT_LABEL = "product"

# What the Dockerfile installs, stated here as well because the image is only
# as good as the KiCad in it and a caller compares against this before a run.
# Pinned rather than floating: an image rebuilt in six months is the same
# product as the one built today, which is the whole reason to write a
# Dockerfile down instead of a paragraph of instructions.
KICAD_VERSION = "10.0"


def name():
    """The image's name without a tag -- ``antenna-workbench``."""
    return f"{product.NAME_KEY}-{SUFFIX}"


def tag(version=None):
    """The image this install wants: ``<product>-workbench:<release>``."""
    return f"{name()}:{version or versions.plugin_version()}"


def latest():
    """The moving tag, for a person typing the command by hand."""
    return f"{name()}:latest"


def labels(version=None):
    """What the build records inside the image, as ``(key, value)`` pairs."""
    return (
        (VERSION_LABEL, version or versions.plugin_version()),
        (KICAD_LABEL, KICAD_VERSION),
        (PRODUCT_LABEL, product.NAME_KEY),
    )


def package_dir():
    """This plugin's installed package -- the directory holding ``emkit/``."""
    # sim/container/image.py -> container/ -> sim/ -> emkit/ -> the package
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def dockerfile():
    """The recipe, which ships inside the core beside this module."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dockerfile")


# What the staged build context is called inside itself. Fixed names, because
# the Dockerfile has to name them and a Dockerfile with a variable layout is a
# Dockerfile nobody can read.
CONTEXT_PACKAGE = "package"
CONTEXT_BINARIES = "binaries"

# The terms the two halves of this image are used under: the plugin's Python is
# MIT, the solver beside it is proprietary and free for non-commercial use only.
# Both are staged, and the Dockerfile copies them in by name, for the same
# reason an install carries them (tools/install.py) -- the image holds the
# binary, so it has to hold the terms. Naming them here rather than letting the
# package copy carry them is what makes that true of *both* of this plugin's
# layouts: an install keeps its licences inside the package, an assembled
# checkout keeps them at its root, beside it.
LICENCE_FILES = ("LICENSE", "LICENSE-solver.txt")


def licence_paths(package=None):
    """Where this install's licence files are, as a list in LICENCE_FILES order.

    Looked for inside the package first and then beside it, which is the two
    layouts in one search. A missing one raises: an image carrying the solver
    without the terms it is used under is not an image worth building, and the
    build is the last place that can still say so.
    """
    package = package or package_dir()
    found = []
    for name in LICENCE_FILES:
        for folder in (package, os.path.dirname(package)):
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate):
                found.append(candidate)
                break
        else:
            raise FileNotFoundError(
                f"{name} is not in {package} or beside it; the image carries the "
                "solver, so it has to carry the terms it is used under"
            )
    return found


def stage_context(destination, package=None, binaries=None):
    """Copy what the image needs into *destination*, and answer that path.

    **Staged rather than pointed at the install**, which is the one design
    choice in this module that is not obvious. Docker can only copy from inside
    its context, and the two things the image needs do not live in one place in
    both layouts this plugin has: an install keeps ``binaries/`` *inside* the
    package, while an assembled checkout keeps it beside. Pointing the build at
    whichever directory happened to contain both would mean a Dockerfile whose
    ``COPY`` paths depend on how the plugin was installed -- and, in an
    install, a context that is the whole third-party plugins directory, which
    is every *other* plugin's code sent to the daemon for no reason.

    So the context is built: the package under ``package/``, the solver builds
    under ``binaries/``, the two licence files at the root, and that is all. It
    also means no ``.dockerignore`` to keep in step -- what is not copied here
    cannot be sent.
    """
    package = package or package_dir()
    # Asked for first, and copied last: it is the one thing here that can
    # refuse, and refusing before a few hundred megabytes have been copied is
    # the difference between a message and a wait followed by a message.
    licences = licence_paths(package)
    if binaries is None:
        from .. import simulate

        binaries = simulate.binaries_dir()

    destination = str(destination)
    os.makedirs(destination, exist_ok=True)
    shutil.copytree(
        package,
        os.path.join(destination, CONTEXT_PACKAGE),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "binaries"),
        dirs_exist_ok=True,
    )
    if binaries:
        # Only the builds a container could run -- which is Linux, whatever the
        # host is. The Windows build is several megabytes of a file this image
        # can never launch, and everything staged here is sent to the daemon.
        wanted = os.path.join(destination, CONTEXT_BINARIES)
        os.makedirs(wanted, exist_ok=True)
        for name in sorted(os.listdir(binaries)):
            if any(name.endswith(build.tag) for build in _container_builds()):
                shutil.copy2(os.path.join(binaries, name), os.path.join(wanted, name))
    for licence in licences:
        shutil.copy2(licence, os.path.join(destination, os.path.basename(licence)))
    shutil.copy2(dockerfile(), os.path.join(destination, "Dockerfile"))
    return destination


def _container_builds():
    """The builds a container could run: the shipped ones for the container's
    operating system. Asked of the table rather than listed here, so a third
    Linux architecture arrives without touching this file."""
    from .. import builds

    return [
        build
        for build in builds.shipped_builds()
        if build.os_key == builds.CONTAINER_OS
    ]


def stale(found, version=None):
    """Whether an image labelled *found* is for an older release than this one.

    ``found`` is the version label read back off the image (None when it has
    none, which is an image built before the label existed -- also stale).
    """
    return (found or "") != (version or versions.plugin_version())
