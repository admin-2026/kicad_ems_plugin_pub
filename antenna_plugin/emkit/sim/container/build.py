"""Building the image, and taking it away again.

The one module here that is slow. A build installs KiCad, so it is minutes and
a few hundred megabytes, and both frontends have to be able to show it
happening: the About page streams it into a status line, the command line
streams it to stdout. So the engine's output is handed out line by line as it
arrives -- the same shape ``simulate.run_exe`` uses for a solve, and for the
same reason. A caller staring at a silent terminal cannot tell a slow ``apt``
from a wedged one.

Nothing here interprets those lines. They are the engine's own words, and the
one thing this module decides is whether the build succeeded, which is its
exit status.

**The context is staged and then thrown away** (``image.stage_context``): a
copy of the package and the solver builds, in a temporary directory that is
removed whether the build worked or not. It is a few megabytes and it is what
lets the Dockerfile name fixed paths.

``remove`` is what makes Rebuild a rebuild: without it the engine is free to
answer from its layer cache, which is exactly what somebody rebuilding a
suspect image does not want.
"""

import shutil
import subprocess
import tempfile

from .... import product
from .. import hostos
from . import cmd, enginepath, image


def _stream(argv, on_line=None):
    """Run *argv*, handing each output line to *on_line*. Answers the exit
    status, or None when the engine could not be started at all."""
    try:
        proc = subprocess.Popen(
            # The engine where it is, not where PATH says (enginepath): a build
            # is started from the same window a probe is. The environment
            # matters as much as the path here -- a build is the command that
            # runs the credential helper and the buildx plugin, and both are
            # looked up on the PATH we hand it.
            enginepath.resolved(argv),
            env=enginepath.environ(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **hostos.launch_kwargs(),
        )
    except OSError as exc:
        if on_line:
            on_line(str(exc))
        return None
    with proc:
        for line in proc.stdout:
            line = line.rstrip()
            if line and on_line:
                on_line(line)
    return proc.returncode


def build(on_line=None, engine="docker", version=None):
    """Build this release's image. Answers whether it worked.

    Both tags are written: the release's, which is what an install asks for,
    and ``latest``, which is what a person typing ``docker run`` by hand
    reaches for.
    """
    context = tempfile.mkdtemp(prefix="emkit-image-")
    try:
        image.stage_context(context)
        argv = cmd.build_argv(
            image.tag(version),
            context,
            labels=image.labels(version),
            engine=engine,
        )
        # The product's own name reaches the Dockerfile as a build argument:
        # it is what the command-line shortcut inside the image is called, and
        # a Dockerfile that spelled it would be one file per product.
        argv = argv[:-1] + [
            "--build-arg",
            f"PRODUCT={product.NAME_KEY}",
            "--build-arg",
            f"VERSION={image.tag(version).split(':')[-1]}",
            "-t",
            image.latest(),
            argv[-1],
        ]
        return _stream(argv, on_line) == 0
    finally:
        shutil.rmtree(context, ignore_errors=True)


def remove(engine="docker", version=None, on_line=None):
    """Delete this release's image. Answers whether one was there to delete.

    A missing image is not a failure: "make sure it is gone" is what the
    caller meant, and it is.
    """
    return _stream(cmd.remove_argv(image.tag(version), engine), on_line) == 0
