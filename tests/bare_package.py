"""Import the plugin's modules in a plain Python (no KiCad, no wx).

The package ``__init__.py`` imports pcbnew, so the tests can't import the
package the normal way. They go through ``tools/install.py``, which already
has to answer the same question at build time and answers it by assembling a
bare package around the real module tree -- every subpackage ``__init__`` is
docstring-only, so relative imports inside it work untouched. Each test module
does::

    from bare_package import load
    geometry = load("design.geometry")

and stays runnable both under pytest and directly
(``python3 tests/test_geometry.py``).

Which tree that is comes from ``install.SOURCE``: the package is the one
directory beside these tests holding a ``product.py``, which is the same
question an install asks and so the same answer. It also means these tests run
where the plugin is *assembled* -- ``build/<product>/`` -- rather than in the
development checkout, where the package does not exist as one directory yet
(see tools/assemble.py).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from tools_module import load as _tool  # noqa: E402

_install = _tool("install")

# The checkout these tests run in.
ROOT = _install.PROJECT_ROOT

# The package's source directory, its manifest, and the name its modules are
# imported under here -- which is *not* the plugin's own name, for the same
# reason it isn't at build time.
PKG = _install.SOURCE
CORE = PKG / "emkit"  # the shared core, nested inside the package
PRODUCT = _install.PRODUCT
PACKAGE = _install.BARE_NAME


def load(dotted):
    """A module of the plugin by its path below the package."""
    return _install.load_plugin_module(dotted)


def modules():
    """Every importable module of the plugin, core included: ``{dotted: path}``.

    The tests and the caches are left out, and so is the package's own
    ``__init__`` (dotted ``""``): it is what registers the plugin with pcbnew,
    and loading it is test_action_plugin's job. Two tests sweep the tree --
    test_imports loads each module, test_frontend_seam reads each one's imports
    -- and they must sweep the same one.
    """
    found = {}
    for path in sorted(PKG.rglob("*.py")):
        parts = path.relative_to(PKG).parts
        if "tests" in parts or "__pycache__" in parts:
            continue
        if parts[-1] == "__init__.py":
            dotted = ".".join(parts[:-1])
        else:
            dotted = ".".join(parts)[: -len(".py")]
        if dotted:
            found[dotted] = path
    return found


class Skip(Exception):
    """This test needs something this machine has not got."""


def skip(reason):
    """Stop this test, saying why -- as pytest's own skip when pytest is the
    runner, and as :class:`Skip` under a bare ``python3 tests/x.py``.

    Called from a helper, never from a test body: a test that decides for
    itself whether to run is a test that quietly stops running. One helper
    asks the question once (``kicad_board.py``), so a board test that silently
    *passed* on a machine without KiCad is not a thing that can happen.
    """
    if "pytest" in sys.modules:
        sys.modules["pytest"].skip(reason)
    raise Skip(reason)


def run_module_tests(namespace):
    """Run every ``test_*`` in ``namespace`` (a module's globals) -- what each
    test file's ``__main__`` block calls, so they all report the same way.

    A test that raises :class:`Skip` reports ``skip <name> — <reason>`` and
    the run carries on. A skipped test is announced rather than counted as a
    pass, which is the difference between "not checked here" and "checked".
    """
    for name, fn in sorted(namespace.items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        try:
            fn()
        except Skip as reason:
            print(f"skip {name} — {reason}")
        else:
            print(f"ok {name}")
