"""Preferences about *this machine*, kept where the board cannot carry them.

There is already a per-project answer to "what should the next run do": the
saved form (``emkit.settings``), one ``settings.yaml`` per board, read by the
window and by the command line alike. This is the other kind of question --
the ones whose answer belongs to the machine and not to the design:

    docker    run the solver inside a container instead of natively

A board's settings file is copied between machines with the project, shared in
a repository and edited by hand; an answer that is only true of the laptop it
was written on has no business travelling with it. So these live beside the
user's saved materials and their command-line shortcut
(``userlib.store.config_home()`` / ``product.CONFIG_DIR``), one small JSON file
per product.

**Both frontends read this, which is the point.** The tick that turns the
container on is on the About page, and the thing it has to reach is a
``run start`` in some other process -- an agent's, a script's, a shell's. A
preference the window kept to itself would leave the case this exists for
unserved.

``resolve`` is the whole contract, and it takes the answer from the most
specific source that has one::

    an explicit argument     --docker / --no-docker on the command line
    the environment          <PRODUCT>_SOLVER_DOCKER=1|0
    the saved preference     what the About page's tick wrote
    the default              off

with one exception above all of them: an operating system that ships no solver
of its own has no native option to fall back to, so there the answer is "on"
whatever anything else says (:func:`docker_forced`). That is not a preference
being overridden, it is the only way the product runs there.

Reading is best-effort -- a missing, unreadable or corrupt file is "nothing
saved", so a broken file can never stop the plugin opening or a run starting.
Writing is not: saving is something the user asked for, so a failure raises and
the caller says so.

Pure stdlib: no wx, no pcbnew, no subprocess. Nothing here asks whether Docker
is actually installed -- that is ``sim.container``'s question, and this module
would be the wrong place to answer it, since a preference is worth recording
before the engine is there and worth keeping after it goes away.
"""

import json
import os

from .. import product
from .sim import builds
from .userlib.store import DIR_NAME, config_home

FILENAME = "machine.json"

# The keys this file may hold. One so far; named rather than free-form so a
# typo in a hand-edited file reads as an unknown key rather than as a setting
# nothing acts on.
DOCKER = "docker"
KEYS = (DOCKER,)

# The environment variable that overrides the saved preference, spelled from
# the product's own name: two plugins on one machine are two solvers, two
# images and two answers, and one variable steering both would be a setting
# that means different things depending on which window last wrote it.
DOCKER_ENV = f"{product.NAME_KEY.upper()}_SOLVER_DOCKER"

# What an environment variable may say. Anything else is not an answer and is
# ignored -- an unparseable override must not silently mean "off", which is
# the one reading that could send a run out of its container.
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# the file
# --------------------------------------------------------------------------- #
def path():
    """Where the preferences live: beside the user's saved entries."""
    return os.path.join(str(config_home()), DIR_NAME, FILENAME)


def load():
    """Everything saved, as a dict; ``{}`` when there is nothing readable.

    Never raises. A preference file is read on the way to opening a window and
    on the way to starting a run, and neither is a place to fail over a stray
    byte."""
    try:
        with open(path(), encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return saved if isinstance(saved, dict) else {}


def save(key, value):
    """Record *key* and return the file it was written to.

    Raises on failure: the user ticked a box, and a tick that quietly did not
    persist is worse than one that says it could not."""
    if key not in KEYS:
        raise ValueError(f"not a machine preference: {key}")
    saved = load()
    saved[key] = value
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(saved, handle, indent=1, sort_keys=True)
        handle.write("\n")
    return target


# --------------------------------------------------------------------------- #
# the answer
# --------------------------------------------------------------------------- #
def docker_forced(system=None):
    """Whether this OS can *only* run the solver in a container.

    True where no build of the solver ships for the machine (macOS): there is
    no native path to prefer, so nothing above this can turn it off.
    """
    return not builds.host_ships(system)


def env_choice(environ=None):
    """What the environment says: True, False, or None for "nothing usable"."""
    raw = (environ if environ is not None else os.environ).get(DOCKER_ENV)
    if raw is None:
        return None
    word = raw.strip().lower()
    if word in _TRUE:
        return True
    if word in _FALSE:
        return False
    return None


def saved_choice():
    """What the About page's tick last wrote, or None if it never has."""
    value = load().get(DOCKER)
    return bool(value) if isinstance(value, bool) else None


def use_docker(explicit=None, environ=None, system=None):
    """Whether this run goes through a container: the most specific answer
    there is.

    ``explicit`` is a caller's own (a ``--docker`` / ``--no-docker`` flag),
    ``None`` when they did not say. See the module docstring for the order.
    """
    if docker_forced(system):
        return True
    if explicit is not None:
        return bool(explicit)
    chosen = env_choice(environ)
    if chosen is not None:
        return chosen
    chosen = saved_choice()
    return False if chosen is None else chosen


def refused(explicit=None, system=None):
    """Why an explicit ``--no-docker`` could not be honoured, or None.

    A flag that is quietly ignored is worse than one that is refused: on an OS
    with no native solver, "run it outside the container" is not a thing the
    caller can be given, and they should hear that rather than watch a run go
    through a container they asked it not to.
    """
    if explicit is False and docker_forced(system):
        return (
            f"No native solver ships for this operating system, so {product.NAME} "
            "cannot run one outside a container here."
        )
    return None
