"""Where the container engine actually is, for a process that did not come
from a shell.

``docker`` is on the PATH of the terminal the user tried it in. It is very
often *not* on the PATH of this plugin, because this plugin runs inside KiCad
and KiCad was started from the Dock, the Start menu or a desktop file -- none of
which read a login shell's profile. On macOS a GUI application inherits
launchd's PATH, which is ``/usr/bin:/bin:/usr/sbin:/sbin`` and nothing else,
while Docker Desktop puts its client in ``/usr/local/bin`` or under the user's
home. The symptom is "the docker command was not found" from a window, on a
machine where ``docker version`` answers instantly in a terminal.

So a name is looked up the ordinary way first (``shutil.which``, which is what
``subprocess`` would have done) and then in the handful of places each engine's
own installer puts it. Nothing is guessed at: each folder below is where a
supported installation actually lands.

Answering the bare name when nothing is found is deliberate -- the spawn then
fails with ``FileNotFoundError`` and the probe turns that into "not installed,
here is what to install", which is the right message on a machine that really
has no Docker.

**Finding the client is only half of it** (:func:`environ`). ``docker`` is not
one program: it runs a *credential helper* to read the registry login
(``docker-credential-desktop`` on Desktop, ``-osxkeychain``, ``-secretservice``,
``-wincred``) and CLI plugins for its subcommands (``docker-buildx``, which is
what ``docker build`` has been since Desktop 4.x). Those it looks up on its own
PATH -- the one it inherited from us. Handing it a full path to itself and the
same starved PATH we were given gets a build that starts and then stops on::

    error getting credentials - err: exec: "docker-credential-desktop":
    executable file not found in $PATH

with nothing wrong except where the window was started from. The helpers live
beside the client, so every spawn in this package passes an environment whose
PATH has the client's own directory and the installers' on it.

Not a preference and not a setting: this is a fact about the machine, asked
fresh each time. An engine installed while the window is open is found by the
next probe.
"""

import os
import shutil

from .. import builds

# The engine this plugin drives. Named here so the rest of the package can stop
# spelling it: every argv builder takes it as an argument (sim.container.cmd).
DEFAULT = "docker"

# Where each host's installers put the client, in the order they are tried.
# PATH is always tried first, so these only ever answer for the process that
# inherited a PATH without them -- which is any window KiCad opened.
#
#   macOS    Docker Desktop's own symlink, then Homebrew's, then the
#            per-user install (Desktop 4.x offers one that touches no system
#            directory), then the app bundle itself, which is where the client
#            really lives and the one that cannot be un-symlinked.
#   Linux    the distribution's, /usr/local for a tarball install, and snap.
#   Windows  Desktop's own directory. Rarely needed: a Windows GUI process
#            does inherit the user and machine PATH.
_FOLDERS = {
    "macos": (
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "~/.docker/bin",
        "/Applications/Docker.app/Contents/Resources/bin",
    ),
    "linux": (
        "/usr/bin",
        "/usr/local/bin",
        "/snap/bin",
        "~/.docker/bin",
    ),
    "windows": (r"C:\Program Files\Docker\Docker\resources\bin",),
}


def find(name=DEFAULT, system=None):
    """The engine's executable: PATH's answer, a known install location, or
    *name* itself when neither has one."""
    found = shutil.which(name)
    if found:
        return found
    os_key = builds.host_os(system)
    filename = f"{name}.exe" if os_key == "windows" else name
    for folder in _FOLDERS.get(os_key, ()):
        candidate = os.path.join(os.path.expanduser(folder), filename)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return name


def resolved(argv, system=None):
    """*argv* with its first word turned into the engine's path.

    Every command in this package is built as ``["docker", ...]`` by a module
    that is deliberately pure (:mod:`cmd`), and this is applied where the
    process is actually started -- four places, all of which spawn. Doing it
    here rather than in the builders keeps the command lines exactly what a
    person would type, which is what the tests assert and what the guide
    prints.
    """
    if not argv:
        return argv
    return [find(argv[0], system=system), *argv[1:]]


def search_path(name=DEFAULT, system=None, env=None):
    """A PATH the engine's own helper programs can be found on.

    The inherited PATH first -- it is the user's, and a helper they arranged
    for is the one they want -- then the directory the client itself was found
    in, then the installers'. Appended rather than prepended for the same
    reason: nothing of ours should shadow something of theirs.
    """
    env = os.environ if env is None else env
    current = env.get("PATH") or ""
    folders = [part for part in current.split(os.pathsep) if part]
    beside = os.path.dirname(find(name, system=system))
    known = (os.path.expanduser(f) for f in _FOLDERS.get(builds.host_os(system), ()))
    for folder in (beside, *known):
        if folder and folder not in folders:
            folders.append(folder)
    return os.pathsep.join(folders)


def environ(name=DEFAULT, system=None, env=None):
    """The environment to start the engine in: this one, with a PATH its
    helpers are on (:func:`search_path`).

    Everything else is inherited untouched. The engine reads a good deal from
    the environment -- ``DOCKER_HOST`` for a rootless or remote daemon,
    ``DOCKER_CONFIG`` for where the login lives, the proxy variables -- and a
    hand-built environment would quietly drop the lot.
    """
    made = dict(os.environ if env is None else env)
    made["PATH"] = search_path(name, system=system, env=made)
    return made
