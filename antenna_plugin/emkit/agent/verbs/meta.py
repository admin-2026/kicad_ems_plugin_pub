"""``versions`` -- what this installation is made of.

The same list the About page shows (``emkit.versions``), which is the list of
things that have to agree when something misbehaves: the plugin, the solver
binary, the config schema they speak, and the KiCad, Python and wx it is all
running inside.

Worth a verb of its own because two of the rows cannot be inferred from
anywhere else. **The bundled binary's version string does not track the config
schema major** -- they are separate numbers -- so an agent puzzled by a solver
refusing its config has no way to check the pairing without asking. That
matters most on Windows, where the bundled ``.exe`` has repeatedly lagged the
Linux build: a stale one means either a loud refusal (CFG-005) or, worse, a
key accepted and silently ignored.

It needs no board, which makes it the one verb that proves the entry point on
a machine with no KiCad state at all. Every row is free to read: the solver's
version is what this release declares (``product.BINARY_VERSION``), checked
against the binary when it is copied in rather than by launching it here, so
there is no ``--probe-solver`` and nothing costs a process.
"""

from ... import versions
from .. import render

NAME = "versions"
HELP = "What this installation is made of"


def add_arguments(parser):
    """No arguments: there is nothing to opt into. Kept so this verb has the
    same shape as every other one the registry loads."""


def run(args):
    return {
        "versions": [
            {"label": label, "value": value} for label, value in versions.entries()
        ]
    }


def lines(payload):
    return render.columns(payload["versions"], (24, "label"), (0, "value"))
