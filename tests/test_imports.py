"""The package's import mechanics: every module loads, and no name is shadowed.

Three import bugs shipped in one week -- ``from . import product`` where the
manifest is a level further up, ``from ...`` in a page three levels deep, and a
core ``shell`` replaced by the plugin's own. Each cost the whole plugin (no
toolbar button, then no window, then a window that would not open), and none
was reachable from another test: the modules that reach across the seam are the
ones that talk to wx and pcbnew, so nothing imported them.

The core sits *nested* inside the package, which is what makes these recurring
mistakes rather than one-offs. How many dots reach ``product`` depends on how
deep in ``emkit/`` the module lives, so moving a file quietly changes what its
imports mean; and the core and the plugin have modules of the same name on
purpose (``shell``, ``config``, ``gui.sections.run``), which is what makes a
name imported into a package collide with its own. A grep can't answer either.
Importing every module, and reading every package's own imports, can.

Not a substitute for the tests that exercise these modules -- this asserts only
what KiCad reports as a message box and a line in a log nobody has open.

    python3 tests/test_imports.py   (or pytest)
"""

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_pcbnew  # noqa: E402,F401  (a pcbnew with a board in it)
import wx_stub  # noqa: E402,F401  (installs the empty wx / pcbnew)
from bare_package import PKG, load, run_module_tests  # noqa: E402
from bare_package import modules as _modules  # noqa: E402


def modules():
    """Every importable module of the plugin, core included, dotted. The
    package's own ``__init__`` is not one of them (see bare_package)."""
    return sorted(_modules())


def test_every_module_imports():
    broken = []
    for dotted in modules():
        try:
            load(dotted)
        except Exception as exc:  # noqa: BLE001 -- the report is the point
            broken.append(f"{dotted}: {type(exc).__name__}: {exc}")
    assert not broken, "modules that would not load in KiCad:\n  " + "\n  ".join(broken)


def test_no_package_imports_a_name_one_of_its_modules_already_has():
    """A package's ``__init__`` globals *are* its attributes, and importing a
    submodule rebinds the attribute of that name. So ``from ..emkit.gui import
    shell`` at the top of a package that also holds ``shell.py`` works until
    something imports the sibling -- and then the name silently becomes the
    sibling, in a module that has already been imported and will not run
    again. Nothing raises; a call just lands somewhere else."""
    clashes = []
    for path in sorted(PKG.rglob("__init__.py")):
        if "tests" in path.relative_to(PKG).parts:
            continue
        pkg = path.parent
        siblings = {p.stem for p in pkg.glob("*.py")} - {"__init__"}
        siblings |= {d.name for d in pkg.iterdir() if (d / "__init__.py").is_file()}
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # Only a module-level import binds a name for the package's life.
            if not isinstance(node, ast.ImportFrom) or node.col_offset:
                continue
            if node.level == 1 and not node.module:
                continue  # `from . import x` -- the sibling itself, not a clash
            for alias in node.names:
                name = alias.asname or alias.name
                if name in siblings:
                    where = path.relative_to(PKG)
                    clashes.append(f"{where}:{node.lineno}: {name} (also {name}.py)")
    assert not clashes, (
        "imported names shadowed by a sibling module:\n  " + "\n  ".join(clashes)
    )


def test_the_sweep_actually_found_the_tree():
    """A glob that matched nothing would pass the test above in silence."""
    found = modules()
    assert len(found) > 50, found
    assert "product" in found
    assert "config" in found
    assert "emkit.action_plugin" in found


if __name__ == "__main__":
    run_module_tests(globals())
