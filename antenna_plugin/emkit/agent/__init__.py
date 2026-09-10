"""The plugin's machine surface: the same code, driven by argv instead of a mouse.

    <kicad-python> <install>/emkit/run_agent.py <verb> [options] [--json]

Two frontends over one plugin, not two products. What the window does by
reading widgets when a button is pressed, this does by reading a saved form
when a verb is called, and both reach the solver through the same modules in
``sim/``. See docs/cli-for-llm.md for why this is a command line rather than a
socket, and execution_plan/cli-simulation-lifecycle.md for what is built so
far.

This package is a thin adapter and is built to stay one::

    __main__.py   the name Python runs, and an exit code
    cli.py        the parser, the --json contract, failure rendering
    render.py     payload -> lines: the view, and the only part that is taste
    kicad.py      pcbnew, or the message naming the interpreter that has one
    hostpy.py     which interpreter that is, recorded by the window itself
    worker.py     the detached child that actually drives a run
    verbs/        one module per verb, listed in verbs/__init__.py

**A verb does not compute.** Each one maps arguments to a call into ``sim/``
(or the module ``sim/`` would delegate to) and hands back what came out. The
window and this share the work itself, not merely a resemblance to it, which
is the whole reason those modules were pulled out of the wx sections. A verb
that starts working something out has drifted, and what it worked out belongs
in ``sim/`` where the window can reach it too.

Adding a verb is one new module plus one entry in ``verbs.VERBS`` -- no edit to
the parser, the renderer or the entry point. That is the same bargain
``design/registry.py`` makes for antenna topologies, and it is what keeps this
package from growing back into the single file it started as.

**Shared, not antenna-specific.** A second plugin over the same solver stack
drives its runs with the same verbs; what is product-specific is only the
*judging*, which arrives through the product's own module the way its config
block does.

**Which board.** A path, loaded here (``pcbnew.LoadBoard``) -- never the board
a running pcbnew has open, because the Python API offers no handle on one.
That also makes every verb in this slice read-only by construction: nothing
here saves a board.
"""
