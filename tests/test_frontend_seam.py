"""The seam between the two frontends: neither may import the other's half.

The plugin has two front doors -- the toolbar button (``action_plugin`` ->
``gui/``) and the command line (``run_agent.py`` -> ``emkit/agent/``) -- over
one middle: ``sim/``, ``markers/``, ``config.py``, the product's ``runjob.py``.
The middle is stdlib and pcbnew, no wx, which is the whole reason a verb can do
what a button does. The rule that keeps it that way (see
dev_docs/frontend-lazy-loading.md):

  * **nothing outside the GUI half imports anything in it** -- not at module
    level, not inside a function. A headless run worker that reaches a wx
    section needs wx to exist, and on a plain Python it does not;
  * **no GUI module imports the agent at module level**. It may import it
    inside a method (the About page writes the shortcut), so that pressing the
    toolbar button loads none of it.

Both are checked by reading the source, not by importing it, for two reasons.
The leak this test was written for was a *function-level* import
(``si/runjob.py`` reaching into ``gui/sections/ports.py`` for ``read_ports``),
which a test that only imports modules cannot see; and reading needs neither wx
nor pcbnew, so it is the same answer on every machine.

    python3 tests/test_frontend_seam.py   (or pytest)
"""

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import modules, run_module_tests  # noqa: E402


def is_gui(dotted, source):
    """Is this module part of the window?

    Three answers, and the second is the one that keeps this rule in step with
    the tree by itself:

      * anything under a ``gui`` package, core's or the product's;
      * **anything whose module level says ``import wx``** -- whatever it is
        called and wherever it lives, so a widget written outside ``gui/``
        (``update/strip.py``, ``cellsize/ui.py``) is the GUI half by
        construction and no list here has to be maintained. Only the module
        level counts: a wx import *inside* a function is the deferral this
        whole test is about, and a middle module may well have one
        (``versions.wx_version`` reports which wx KiCad has, if any);
      * ``action_plugin``, by name. It is KiCad's front door -- opening the
        window is the one thing it does -- so its import of ``gui`` is the edge
        this rule protects rather than one to forbid.
    """
    if "gui" in dotted.split(".") or dotted.split(".")[-1] == "action_plugin":
        return True
    for node in source.body:
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "wx" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and not node.level:
            if (node.module or "").split(".")[0] == "wx":
                return True
    return False


def is_agent(dotted):
    """The command line's half: the ``agent`` package and its entry script."""
    parts = dotted.split(".")
    return "agent" in parts or parts[-1] == "run_agent"


def sources():
    """Every module parsed once: ``{dotted: (is_package, tree)}``."""
    return {
        dotted: (path.name == "__init__.py", ast.parse(path.read_text("utf-8")))
        for dotted, path in modules().items()
    }


def imports(dotted, package, tree, known):
    """Every edge this module has *inside the package*, as
    ``(target, module_level)`` pairs.

    Function-level imports count -- deferring an import moves when it happens,
    not whether the two halves are joined. Only relative imports can reach
    inside the package (an installed package's own name is unknown to it, see
    run_agent.py), so an absolute ``import wx`` or ``import os`` resolves to
    nothing here and is ignored.
    """
    # What a single leading dot means here: the package this module is *in* --
    # which for a package's own __init__ is itself.
    parts = dotted.split(".")
    if not package:
        parts = parts[:-1]
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        base = parts[: len(parts) - (node.level - 1)]
        target = ".".join([*base, *(node.module.split(".") if node.module else [])])
        for alias in node.names:
            # ``from .x import y``: y is a module of x, or a name in x.
            candidate = f"{target}.{alias.name}" if target else alias.name
            if candidate in known:
                found.append((candidate, node.col_offset == 0))
            elif target in known:
                found.append((target, node.col_offset == 0))
    return found


def graph():
    """The package: its import graph, and which half each module is in --
    ``({module: {module, ...}}, {gui module, ...})``."""
    parsed = sources()
    edges = {
        dotted: {target for target, _top in imports(dotted, package, tree, parsed)}
        for dotted, (package, tree) in parsed.items()
    }
    gui = {dotted for dotted, (_pkg, tree) in parsed.items() if is_gui(dotted, tree)}
    return edges, gui


def test_no_non_gui_module_reaches_the_gui():
    """Breadth-first from every module of the middle and of the command line.
    The failure names the whole chain, because "something needs wx" is not the
    fix -- the edge that should not be there is."""
    edges, gui = graph()
    chains = []
    for start in sorted(edges):
        if start in gui:
            continue
        seen, queue = {start}, [(start,)]
        while queue:
            chain = queue.pop(0)
            for target in sorted(edges[chain[-1]]):
                if target in seen:
                    continue
                if target in gui:
                    chains.append(" -> ".join([*chain, target]))
                    queue = []
                    break
                seen.add(target)
                queue.append((*chain, target))
    assert not chains, "non-GUI modules that reach the GUI:\n  " + "\n  ".join(chains)


def test_no_gui_module_imports_the_agent_at_module_level():
    """A window that is only *about* the command line (the About page's box)
    imports it where it uses it, so opening the window loads none of it."""
    parsed = sources()
    eager = []
    for dotted, (package, tree) in sorted(parsed.items()):
        if not is_gui(dotted, tree):
            continue
        for target, top in imports(dotted, package, tree, parsed):
            if top and is_agent(target):
                eager.append(f"{dotted}: {target}")
    assert not eager, (
        "GUI modules importing the command line at import time:\n  "
        + "\n  ".join(eager)
    )


def test_the_sweep_actually_found_both_halves():
    """Either rule passes in silence over a tree that was never found, and a
    graph with no edges is the same kind of nothing."""
    edges, gui = graph()
    assert len(edges) > 50, sorted(edges)
    assert gui
    assert any(is_agent(dotted) for dotted in edges)
    assert "runjob" in edges
    assert sum(len(targets) for targets in edges.values()) > 50


if __name__ == "__main__":
    run_module_tests(globals())
