"""One run, as a container invocation: what to mount, who to be, what to call
it.

:mod:`cmd` knows the shape of every command line; this knows what to fill into
the one that runs a solve. The split is worth the two files: the shape can be
asserted exactly in a test with no host involved, while the things decided here
-- which directory is the run's, which build the container's architecture takes,
what a container may be named -- are host questions with real answers.

**The container's build is not the host's.** A container is Linux whatever the
machine is, and its architecture is the *daemon's*: Docker Desktop on an Apple
Silicon Mac runs arm64 images, so the build to launch there is the AArch64 one
even though the host is a Mac with no build of its own. That is
``sim.builds.container_build``'s answer and it is asked with the arch the
engine reported, never with ``platform.machine()``.

**Ownership is a per-OS question and it is answered here**, not in
``sim.hostos``: that module is deliberately two answers wide (launch flags and
liveness) and a mount option is neither. On Linux the run is given the caller's
uid and gid, so the gerbers, configs and results a run writes into the mounted
project belong to the person who started it rather than to root. On macOS and
Windows the Desktop engines map ownership themselves and passing ``--user``
there breaks more than it fixes.
"""

import os
import time

from .. import builds
from . import cmd

# What a run's container is called: the product, the word, and the stamp that
# already names the run's own results folder. Unique per run because two may be
# in flight at once (a run and a designer's scan), and *guessable* on purpose --
# a person looking at `docker ps` should be able to tell which of their runs is
# which without consulting anything.
NAME_PREFIX = "run"


def container_name(product_key, stamp=None):
    """A name for one run's container."""
    return f"{product_key}-{NAME_PREFIX}-{stamp or time.strftime('%Y%m%d-%H%M%S')}"


def user_argument(name=None):
    """``uid:gid`` where the host wants it, else None.

    POSIX only, and in practice Linux: on macOS and Windows the engine is a VM
    with its own mapping and this would name a user that does not exist there.
    """
    if (os.name if name is None else name) == "nt":
        return None
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return None
    return f"{getuid()}:{getgid()}"


def is_desktop(system):
    """Whether this host's engine is a Desktop VM rather than the kernel's own.

    macOS and Windows, where ownership is mapped for us. Taken from the OS
    rather than asked of the engine: Docker Desktop on Linux exists, but it
    still runs containers as this kernel does, which is what the question is
    actually about.
    """
    return builds.host_os(system) in ("macos", "windows")


def solver_path(arch, stem):
    """Where the solver for a container of *arch* is, inside the container --
    or None when nothing is built for that architecture.

    The binaries directory is mounted, so this is just the mount point and the
    name of the build that runs there.
    """
    build = builds.container_build(arch)
    if build is None:
        return None
    return f"{cmd.SOLVER_DIR}/{build.filename(stem)}"


def solve_argv(
    tag,
    stem,
    arch,
    yaml_path,
    args=(),
    name=None,
    system=None,
    engine="docker",
):
    """The whole command line for one solve of *yaml_path*.

    The run directory is the yaml's own folder -- which is what the native
    launcher uses as its cwd, for the same reason: every path the config names
    is written relative to it, so the config resolves identically whether it is
    read from ``/work`` or from the folder itself. Nothing in the config is
    rewritten for the container, and that is by design rather than by luck.
    """
    run_dir = os.path.dirname(os.path.abspath(str(yaml_path)))
    exe = solver_path(arch, stem)
    if exe is None:
        return None
    return cmd.run_argv(
        tag,
        exe,
        args=[cmd.inside(yaml_path, run_dir, cmd.WORK_DIR), *args],
        work_dir=run_dir,
        solver_dir=binaries_dir(),
        name=name,
        user=None if is_desktop(system) else user_argument(),
        engine=engine,
    )


def binaries_dir():
    """The install's ``binaries/`` -- what gets mounted read-only.

    Beside the package, exactly where ``simulate.locate`` looks for it: the two
    have to agree, because a container that mounted a different directory from
    the one the native path searches would run a different solver from the one
    the About page reports.
    """
    from .. import simulate

    return simulate.binaries_dir()
