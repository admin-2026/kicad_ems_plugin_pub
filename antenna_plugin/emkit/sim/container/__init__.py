"""Running the solver -- and, if you like, the whole command line -- inside a
container.

A run is otherwise a native process with the user's own rights, reading and
writing anywhere they can. That is fine when a person started it and watched
it. It is a poor default when the thing driving the run is an agent, which is
what the command line exists for: a confined process that can see one mounted
directory and no network is a better answer, and the confinement costs a flag.

**On macOS it is not a preference.** No macOS build of the solver ships, so
there the container is how this product runs at all (``sim.builds``,
``emkit.hostprefs.docker_forced``).

The image is a *workbench*, not a runtime: KiCad, this plugin, its command line
and the solver, so that

    docker run --rm -v "$PWD:/work" <image> run start --board /work/b.kicad_pcb
    docker run --rm -it -v "$PWD:/work" <image> bash

both work, and a window on the host asking for one solve is the same image with
the solver named directly. One image, three ways in.

The modules, in dependency order -- and the first two are the ones worth
reading, because they are the ones with no host in them:

    cmd      PURE. every command line given to the engine, as argument lists
    enginepath  where the engine is, for a process KiCad started rather than a
             shell (a window's PATH is not a terminal's)
    image    what the image is called, what it records, what is staged into it
    runtime  one run's invocation: mounts, uid, container name, the build
    probe    is it ready, and if not what to do about it (a Status with a
             remedy on it, which every frontend prints rather than rewording)
    build    the slow one: building the image and removing it, streamed line
             by line so a frontend can show minutes happening

Nothing here imports wx or pcbnew, so the whole feature is drivable from a
shell; nothing here spells a product's name or a solver's, which is the rule
the core lives by -- the manifest is asked (``product.NAME_KEY``,
``product.BINARY``) and never quoted.

**What is deliberately not here**: whether to use a container at all. That is
``emkit.hostprefs``, because it is a preference about the machine and it is
worth recording before an engine is installed and worth keeping after one is
removed.
"""

from . import build, cmd, enginepath, image, probe, runtime
from .build import build as image_build
from .build import remove as image_remove
from .probe import (
    DENIED,
    KICAD_OLDER,
    NO_DAEMON,
    NO_DOCKER,
    NO_IMAGE,
    READY,
    STALE,
    Status,
    status,
)

__all__ = [
    "DENIED",
    "KICAD_OLDER",
    "NO_DAEMON",
    "NO_DOCKER",
    "NO_IMAGE",
    "READY",
    "STALE",
    "Status",
    "build",
    "cmd",
    "enginepath",
    "image",
    "image_build",
    "image_remove",
    "probe",
    "runtime",
    "status",
]
