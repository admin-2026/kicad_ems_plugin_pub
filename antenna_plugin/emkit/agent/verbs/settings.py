"""``settings`` -- the file a run is built from, when a board has none yet.

    settings init   write a starter settings file for a board

A run is made of a **form**: a flat ``key: value`` YAML file the window saves
beside the board (``simulation/settings.yaml``) and the command line reads. A
board that has never had the plugin's window open on it has no such file, and
that used to be the end of the road for a shell. This writes one.

**What it writes is a starter, not a run.** The toggles, the picks and the
material rows come out as a fresh form -- the same state the window opens on,
one material row per copper foil and per dielectric gap this board actually
has -- and everything the plugin has no business choosing is left blank. There
is no default frequency for a board, so the file says so by leaving the field
empty and the payload names what a run would still refuse. Filling those in is
the caller's, and it is the whole of what a caller has to do.

**It never overwrites.** The window rewrites its own settings file whenever it
closes or starts a run, so a hand-edited one is a file with a short life; and
a file somebody edited is worth more than this can generate. An existing target
is refused, naming it, with ``--out`` as the way to write a copy elsewhere --
which is the way to work here anyway: edit a copy, run the copy
(``run start --settings <copy>``), and leave the window's own file to the
window.
"""

import os

from ... import formparams, settings
from .. import kicad, render

NAME = "settings"
HELP = "Write a starter settings file for a board that has none"

TOPICS = ("init",)


def add_arguments(parser):
    parser.add_argument("topic", choices=TOPICS)
    kicad.add_board_arg(parser)
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Where to write it; the board's own simulation/settings.yaml by "
            "default. Give a path of your own to keep a copy the window will "
            "not rewrite"
        ),
    )


def run(args):
    from ...sim import simulate

    board = kicad.board(args.board)
    target = args.out or settings.path(simulate.output_dir(board))
    if _exists(target):
        raise RuntimeError(
            f"{target} is already there, and this will not overwrite a form "
            "somebody has filled in.\n"
            "Read it, copy it, edit the copy, and run that:\n"
            f"  run start --board {args.board} --settings <your copy>"
        )
    stack = simulate.collect_stackup(board)
    form = formparams.starter(*_layers(stack))
    written = settings.write(target, form)
    return {
        "file": written,
        "form": form,
        # What a run would still refuse, asked by running the translation this
        # file was just written for. A starter is deliberately incomplete, and
        # a caller is better told which field than left to start a run to find
        # out.
        "blocker": _blocker(form),
    }


def _exists(target):
    return os.path.exists(str(target))


def _layers(stack):
    """How many material rows this board's stackup wants: the copper foils by
    name (the first of which a fresh form feeds from), and the dielectric gaps
    between them. Off the stackup the run itself reads, so the rows line up
    with the layers the config walks."""
    entries = stack.get("stackup") or []
    copper = [e["name"] for e in entries if e.get("type") == "copper"]
    cores = [e for e in entries if e.get("type") == "core"]
    return tuple(copper), max(1, len(cores))


def _blocker(form):
    try:
        formparams.params(form)
    except Exception as exc:
        return str(exc)
    return ""


def lines(payload):
    out = [payload["file"], ""] + render.kv(payload["form"])
    if payload["blocker"]:
        out.append("")
        out.append("Fill this in before a run will start:")
        out.append(f"  {payload['blocker']}")
    return out
