"""Import antenna_plugin modules in a plain Python (no KiCad, no wx).

``antenna_plugin/__init__.py`` imports pcbnew, so the tests can't import the
package the normal way. They assemble a bare package around the real module
tree instead -- every subpackage ``__init__`` is docstring-only, so relative
imports inside it work untouched. This is the one copy of that bootstrap;
each test module does::

    from bare_package import load
    geometry = load("design.geometry")

and stays runnable both under pytest and directly
(``python3 tests/test_geometry.py``).
"""

import importlib
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]

_pkg = types.ModuleType("antenna_plugin")
_pkg.__path__ = [str(ROOT / "antenna_plugin")]
sys.modules.setdefault("antenna_plugin", _pkg)


def load(dotted):
    """A module of the plugin by its path below ``antenna_plugin``."""
    return importlib.import_module(f"antenna_plugin.{dotted}")


def run_module_tests(namespace):
    """Run every ``test_*`` in ``namespace`` (a module's globals) -- what each
    test file's ``__main__`` block calls, so they all report the same way."""
    for name, fn in sorted(namespace.items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
