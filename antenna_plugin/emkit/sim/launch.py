"""How a solve is started on this machine: natively, or inside a container.

One module answers that, so that nothing downstream has to. ``simulate.run_exe``
streams a solver's output and raises on a bad exit; what it does *not* do is
decide what the command line is, because there are two of them now and a branch
in the runner would be a branch in the wizard's scan and in the command line's
worker as well.

    launch.prepare()  ->  Launcher      what this machine will do
    launcher.command(yaml, ...)  ->     the argv, the cwd, and (for a
                                        container) the name to kill it by

A native launcher is the old behaviour, unchanged: the binary, the config, and
the yaml's own folder as the working directory. A container launcher is the
same run seen through a mount -- and the reason nothing in the config has to be
rewritten for it is that ``config.write_yaml`` already writes every path
relative to the yaml's folder, which is why the native launcher sets its cwd
there too. The two agree by construction rather than by translation.

**A string is a launcher.** Anything that already holds a path to the binary --
the wizard's per-candidate scan, a test driving one solve -- passes it where a
launcher goes and gets the native behaviour it has always had. That is
deliberate: this seam was added under working code, and code that had no
opinion about containers should not have acquired one.
"""

import os

from ... import product
from .. import hostprefs
from . import builds, container


class LaunchError(RuntimeError):
    """A run that cannot be started, with the reason and the fix in it.

    Carries the ``Status`` when there was one, so a frontend with somewhere
    better than a log to put a remedy (a banner with a Build button on it) can
    reach for it instead of parsing the sentence.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Launcher:
    """What starting one solve takes. Native unless a tag is given."""

    def __init__(self, exe, tag=None, arch=None, stem=None):
        self.exe = str(exe)
        self.tag = tag
        self.arch = arch
        self.stem = stem or product.BINARY

    @property
    def docker(self):
        return self.tag is not None

    @property
    def env(self):
        """The environment a solve is spawned in, or None to inherit this one.

        None for a native run -- the solver is a program of ours, started by
        its full path, and it reads nothing from the environment. A container
        run starts the *engine*, which looks its credential helper and its
        ``build``/``buildx`` plugin up on PATH, and the PATH a window inherits
        does not have them (container.enginepath).
        """
        return container.enginepath.environ() if self.docker else None

    @property
    def label(self):
        """One line for a log: what is about to run, and where."""
        if not self.docker:
            return f"solver: {self.exe}"
        return f"solver: {os.path.basename(self.exe)} in {self.tag} ({self.arch})"

    def command(
        self, yaml_path, grid_only=False, control=None, stamp=None, mount=None
    ):
        """``(argv, cwd, name)`` for one solve of *yaml_path*.

        ``name`` is the container's, or None for a native run -- it is what a
        kill needs, and only one of the two kinds has one.

        ``mount`` is the directory the run's files live under, when that is not
        the yaml's own folder: the scan's candidate configs name gerbers
        plotted once in the scan folder above them, and a native run resolves
        that ``../`` happily while a container cannot see above its mount. It
        changes nothing about a native run.
        """
        run_dir = os.path.dirname(os.path.abspath(str(yaml_path)))
        base = os.path.abspath(str(mount)) if mount else run_dir
        args = []
        if grid_only:
            args.append("--grid-only")
        if control:
            args += ["--control", str(control)]

        if not self.docker:
            return [self.exe, str(yaml_path), *args], run_dir, None

        name = container.runtime.container_name(product.NAME_KEY, stamp)
        # The control file is the caller's path on the host; inside the
        # container it is under the mount like everything else in the run
        # directory. Translated here rather than by the caller, who does not
        # know the run is in a container and should not have to.
        argv = container.runtime.solve_argv(
            self.tag,
            self.stem,
            self.arch,
            yaml_path,
            args=[
                container.cmd.inside(part, base, container.cmd.WORK_DIR)
                if _is_run_file(part, base)
                else part
                for part in args
            ],
            mount_dir=base,
            name=name,
        )
        if argv is None:
            raise LaunchError(
                f"No solver is built for a {self.arch} container, so this run "
                "cannot start. Report this with the architecture named here."
            )
        # The engine by its full path: this run is spawned by the window as
        # often as by a shell, and a window's PATH is not a shell's
        # (container.enginepath).
        return container.enginepath.resolved(argv), run_dir, name


def _is_run_file(word, base):
    """Whether an argument is a path inside the mounted directory (so it has to
    be named as the container sees it) rather than a flag."""
    if word.startswith("-"):
        return False
    return os.path.abspath(word).startswith(os.path.abspath(base) + os.sep)


def of(value):
    """*value* as a :class:`Launcher` -- itself, or a path to the binary."""
    return value if isinstance(value, Launcher) else Launcher(value)


def native():
    """The launcher for a native run, or a raise saying why there is none."""
    from . import simulate

    exe, _root = simulate.locate()
    return Launcher(exe)


def in_container(status):
    """The launcher for a run inside the image *status* found ready."""
    build = builds.container_build(status.arch)
    if build is None:
        raise LaunchError(
            f"The container runs on {status.arch}, which no solver is built for.",
            status,
        )
    return Launcher(
        f"{container.cmd.SOLVER_DIR}/{build.filename(product.BINARY)}",
        tag=container.image.tag(),
        arch=status.arch,
    )


def prepare(explicit=None, kicad_version=None, engine="docker"):
    """How the next run starts on this machine.

    ``explicit`` is a caller's own answer to "container or not" (a
    ``--docker`` / ``--no-docker`` flag), None when they did not say; the rest
    of the order is ``hostprefs``'.

    Raises :class:`LaunchError` when the container is asked for and is not
    ready, with the probe's own remedy in the message. **It does not fall back
    to a native run**, and that is the point: a confinement that silently does
    not confine is worse than a run that did not start, and on macOS there is
    no native run to fall back to anyway.
    """
    refusal = hostprefs.refused(explicit)
    if refusal:
        raise LaunchError(refusal)
    if not hostprefs.use_docker(explicit):
        return native()

    status = container.status(engine=engine, kicad_version=kicad_version)
    if not status.ready:
        raise LaunchError(f"{status.detail}. {status.remedy}".strip(), status)
    return in_container(status)
