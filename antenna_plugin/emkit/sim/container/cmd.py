"""Every command line this plugin gives a container engine, and nothing else.

Pure: this module builds argument lists. It starts no process, reads no file,
asks no question of the operating system it is on -- what the host is, what the
image is called and where the mounts point are all arguments. That is what
makes the interesting half of the container feature testable on a machine with
no Docker at all, which is every machine this suite runs on.

The commands, and why each exists::

    docker version --format {{.Server.Arch}}   is the engine there, is the
                                               daemon answering, and which
                                               architecture will its containers
                                               be? One question, one process.
    docker image inspect <tag> --format ...    is the image for this release
                                               built, and what is in it?
    docker build -t <tag> <context>            build it.
    docker image rm <tag>                      take it away (Rebuild is this,
                                               then a build).
    docker run ... <exe> <args>                one solve.
    docker exec -it <name> <shell>             a look inside a live one.
    docker kill <name>                         end it now.

**Why the run command looks the way it does**, since every flag on it is load
bearing:

``--rm``            a finished run leaves no container behind. There may be
                    several runs a day and none of them is worth keeping.
``--init``          the solver is not pid 1. Without it nothing reaps and
                    signals behave unlike every other way it is launched.
``--network none``  neither the solver nor the command line makes a network
                    connection. The plugin's one network user is the update
                    check, which belongs to the window and is not in here.
``--name``          two runs may be in flight at once (a run and a scan), so
                    the name is per run -- and it is what a kill needs, since
                    killing the ``docker run`` client leaves the container
                    stepping.
                    (There is no ``--cidfile``: the id it wrote down had no
                    reader, the path was the same for every run of a board, and
                    an engine refuses to start a run whose cidfile is already
                    there -- so the second run of a board never started. The
                    name is derived from the run's stamp and answers the same
                    question.)
``-v <dir>:/work``  the run's tree, read-write: the config, the gerbers, the
                    control file and everything the run writes. The *only*
                    thing mounted read-write, and the only thing of the user's
                    the container can see at all. Usually the config's own
                    folder; for a scan, the scan folder, because a candidate's
                    config names the gerbers plotted once beside it.
``-v <bin>:/opt/solver:ro``
                    the install's binaries, read-only. Mounted rather than
                    baked into the image so that an image survives a plugin
                    upgrade unchanged.
``-w <yaml dir>``   the solver's cwd -- the config's own folder as the
                    container sees it, ``/work`` itself whenever that is what
                    is mounted. ``config.write_yaml`` writes every path in the
                    config relative to the yaml's folder, which is exactly why
                    the host runs it this way too -- so the same config
                    resolves identically inside and out, and nothing has to be
                    rewritten on the way in.
``--user``          the caller's, on Linux only, so a run's outputs belong to
                    the person who started it rather than to root. Docker
                    Desktop maps ownership itself and passing it there breaks
                    more than it fixes.

Nothing here spells a product's name, a solver's name or an image tag: every
one of those is passed in (``sim.container.image`` decides the tag,
``product.py`` names the solver).
"""

import os

# Where the two mounts land inside the container. Fixed, not derived: the
# whole point of a mount is that the path inside is the same whatever the path
# outside is, so a run's command line reads identically on every machine and a
# person reproducing one by hand types what they see.
WORK_DIR = "/work"
SOLVER_DIR = "/opt/solver"

# What a container is asked its architecture with. Go's vocabulary (amd64,
# arm64) -- sim.builds.container_build knows both that and the kernel's.
ARCH_FORMAT = "{{.Server.Arch}}"

# What an image is asked about itself: the labels the Dockerfile set, as JSON.
# One inspect answers both "is it there" (exit status) and "what is in it".
LABEL_FORMAT = "{{json .Config.Labels}}"

# The shell a person gets when they ask to look inside. bash, because the image
# has one and this is a debugging affordance, not a runtime dependency.
SHELL = "bash"


def version_argv(engine="docker"):
    """Ask the engine for its server's architecture.

    Doubles as the "is any of this going to work" probe: the command not
    existing, the daemon not answering and the socket refusing permission are
    three different failures of this one call, and they are three different
    things to tell the user.
    """
    return [engine, "version", "--format", ARCH_FORMAT]


def inspect_argv(tag, engine="docker"):
    """Ask about the image *tag* -- its labels, and by its exit status whether
    it is built at all."""
    return [engine, "image", "inspect", tag, "--format", LABEL_FORMAT]


def build_argv(tag, context, dockerfile=None, labels=(), engine="docker"):
    """Build *tag* from *context*.

    ``labels`` are ``(key, value)`` pairs recorded in the image itself: what
    this image was built from, and which plugin version -- read back by
    ``inspect_argv`` to answer "is this image stale" without starting anything.
    """
    argv = [engine, "build", "-t", tag]
    if dockerfile:
        argv += ["-f", str(dockerfile)]
    for key, value in labels:
        argv += ["--label", f"{key}={value}"]
    return argv + [str(context)]


def remove_argv(tag, engine="docker"):
    """Delete the image *tag*. What Rebuild does before it builds -- so that a
    rebuild is a rebuild and not a cache hit on the layer that was wrong."""
    return [engine, "image", "rm", tag]


def kill_argv(name, engine="docker"):
    """End the running container *name* now.

    The one command that has to exist for a container run to be as
    interruptible as a native one: ``Popen.kill()`` reaches the ``docker run``
    client, and the client is not the thing stepping the fields.
    """
    return [engine, "kill", name]


def shell_argv(name, engine="docker"):
    """A shell inside the running container *name*."""
    return [engine, "exec", "-it", name, SHELL]


def mount(source, target, read_only=False):
    """One ``-v`` pair, as the two arguments it takes."""
    spec = f"{source}:{target}"
    return ["-v", spec + ":ro" if read_only else spec]


def run_argv(
    tag,
    exe,
    args=(),
    work_dir=None,
    solver_dir=None,
    cwd=None,
    name=None,
    user=None,
    engine="docker",
    interactive=False,
):
    """One container run: the solver *exe* (a path *inside* the container) with
    *args*, over the two mounts.

    ``work_dir`` is the host directory that becomes :data:`WORK_DIR` and
    ``solver_dir`` the host directory of binaries that becomes
    :data:`SOLVER_DIR`; either may be None when the caller has nothing to mount
    there (a version probe needs no run directory).

    ``cwd`` is where inside the container the solver runs, :data:`WORK_DIR`
    unless the caller says otherwise -- it is the mount root only when the
    mount is the config's own folder. A scan mounts the folder *above* its
    candidates (their configs reach up to the shared gerbers), so the cwd is
    the candidate's directory under the mount.

    ``interactive`` swaps ``--rm`` for an attached terminal -- what a person
    asking for a shell wants, and never what a run wants.
    """
    argv = [engine, "run", "--rm", "--init", "--network", "none"]
    if interactive:
        argv += ["-it"]
    if name:
        argv += ["--name", name]
    if user:
        argv += ["--user", user]
    if work_dir:
        argv += mount(work_dir, WORK_DIR)
    if solver_dir:
        argv += mount(solver_dir, SOLVER_DIR, read_only=True)
    argv += ["-w", cwd or WORK_DIR, tag, str(exe), *[str(arg) for arg in args]]
    return argv


def inside(path, base, target):
    """*path*, as the container sees it once *base* is mounted at *target*.

    The only path translation there is, and it is deliberately this small: the
    run directory is mounted whole, so a file in it keeps its name and loses
    its prefix. Anything that needed more translation than this would be a file
    the container has no business seeing.
    """
    relative = os.path.relpath(str(path), str(base))
    if relative == os.curdir:
        return target
    return target + "/" + relative.replace(os.sep, "/")
