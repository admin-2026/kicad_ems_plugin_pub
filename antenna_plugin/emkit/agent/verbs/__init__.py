"""The verb table: every command this surface offers, in help order.

The same arrangement as ``design/registry.py``, and for the same reason.
Adding a verb is writing one module and adding it to ``VERBS`` -- no edit to
the parser, the renderer or the entry point -- so the cost of a new verb does
not grow with the number of verbs already here. That property is the whole
reason this is a package rather than a long file.

A verb module is four names, and no more::

    NAME             what the caller types
    HELP             one line, for ``--help``
    add_arguments(p) whatever else it takes, on its own subparser
    run(args)        the payload, as plain JSON-able data
    lines(payload)   that payload as lines, for a reader who wants prose

``run`` returns data and raises on failure; it never prints, never formats and
never decides an exit code. ``lines`` is a pure function of what ``run``
returned -- it may not reach for the board, the arguments or anything else,
because ``--json`` skips it entirely and the two views have to be the same
answer.

The rule that keeps this thin: **a verb does not compute.** It maps arguments
to one call into ``sim/`` and hands back what came out. A verb that starts
working something out has drifted, and what it worked out belongs in ``sim/``
where the window can reach it too.

Two tiers, and an agent should live in the cheap one. ``preflight``,
``settings init``, ``results show`` and ``versions`` are milliseconds; ``run
start`` is minutes of solver. An expensive verb says its price before charging
it, and never runs in the foreground.
"""

from . import check, docker, guide, meta, results, settings
from . import run as run_verb

# In the order `--help` should list them. The guide leads, and that is not
# housekeeping filed at the top: a caller who does not know this surface
# exists starts at `--help`, reads the first line under `positional
# arguments`, and that line has one job -- to say that there is a page
# explaining the rest. Then: the form a run is made of, what would stop one,
# the run itself, what it came to, and the versions. `docker` sits with the
# versions at the end: it is about this machine rather than about a board, and
# most callers never touch it -- except on macOS, where it is how the product
# runs and the guide says so up front.
VERBS = (guide, settings, check, run_verb, results, meta, docker)


def names():
    return tuple(verb.NAME for verb in VERBS)
