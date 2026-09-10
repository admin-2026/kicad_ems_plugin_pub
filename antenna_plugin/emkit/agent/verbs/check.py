"""``preflight`` -- what would stop a run, before one is started.

The same blockers the window's banner shows, from the same two functions
(``sim.simulate.preflight`` for the board, ``container_problems`` for the
machine's container), serialised rather than drawn.

**What it does not cover, and why that has to be said.** Pre-flight is about
the *board*: an outline, a stackup with thicknesses, a feed marker, a file on
disk that matches what is being edited. The mesh is decided later, by the
solver, out of knobs pre-flight never looks at -- so a clean answer here is
"nothing about this board will stop a run", not "this run will start". A
person reads that distinction off the banner's position on screen; a caller
cannot, and will read "ok" as a promise unless told otherwise.

That is not hypothetical. The patch fixture passes pre-flight and then has the
meshing pass refuse it twice, once because the feed stub is finer than the
cell the lattice sampled it at (FEED-019) and once because auto-ground then
had no source-side copper to strap (AUTO_GND-006). Both are real, both are the
solver's to find, and neither is a pre-flight failure.

So the clean answer names where the other half of the question is answered:
``run log --severity warning``, which is the solver's own diagnostics without
the flood around them. Otherwise "No problems with the board itself" is the
last thing a caller reads on the subject, and a ``WARNING [GND-004]`` printed
a minute into the run is one nobody goes looking for.
"""

from .. import kicad

NAME = "preflight"
HELP = "What would stop a run"

# What pre-flight looked at, in a caller's words. Not a list of check ids: the
# point is the *boundary*, and an id-by-id inventory would invite reading the
# absence of an id as a guarantee about it.
COVERS = (
    "the board outline and copper layers",
    "the physical stackup and its thicknesses",
    "the port markers",
    "whether the saved file matches the board being edited",
)

DEFERS = (
    "the mesh, its cell sizes and its memory budget",
    "the port's geometry and the copper around it",
    "anything that depends on a knob set in the window",
)

# ...and where what it decides is read back. Carried on the answer rather than
# left to the guide: this verb's clean line is the one a caller stops reading
# at, so the pointer has to be on it.
SOLVER_SAYS = (
    "What it finds it prints with an id (WARNING [GND-004]: ...) into the run's "
    "log; read those alone with: run log --severity warning --board <board>."
)


def add_arguments(parser):
    kicad.add_board_arg(parser)


def run(args):
    from ...sim import simulate

    # The board's own blockers, plus the one that is about this machine: a
    # container that is not ready stops every run started here, and a caller
    # asking "would a run start?" is asking about that too. Named separately
    # because preflight() is a board check and this is not one (see
    # simulate.container_problems).
    problems = simulate.preflight(kicad.board(args.board))
    problems += simulate.container_problems()
    return {
        "ok": not any(p.severity == "block" for p in problems),
        "problems": [
            {
                "id": p.id,
                "severity": p.severity,
                "message": p.message,
                "help": p.help,
            }
            for p in problems
        ],
        # Carried on every answer, not just the clean one: a board with a
        # warning is just as easy to mistake for a fully checked board.
        "covers": list(COVERS),
        "defers_to_solver": list(DEFERS),
        "solver_says": SOLVER_SAYS,
    }


def lines(payload):
    if payload["problems"]:
        out = [
            f"{p['severity']:<5} {p['id']}: {p['message']}" for p in payload["problems"]
        ]
    else:
        out = ["No problems with the board itself."]
    out.append("")
    out.append("Checked: " + "; ".join(payload["covers"]) + ".")
    out.append(
        "Not checked here — the solver decides these once a run starts: "
        + "; ".join(payload["defers_to_solver"])
        + "."
    )
    out.append(payload["solver_says"])
    return out
