"""Load a script out of ``tools/`` as a module.

The build-time tools are scripts, not an importable package, so the tests load
them by path -- the same bootstrap ``bare_package`` is for the plugin itself.
They also import *each other* by bare name (``make_package`` imports
``install`` as its source of truth for what an install is made of, and ``pcm``
for the shape of the KiCad package), so each module is registered under that
name as it loads, and loaded once::

    from tools_module import load
    packager = load("make_package")
"""

import importlib.util
import pathlib
import sys


def _root():
    """The checkout these tests belong to: the nearest parent holding tools/.

    Not ``parents[1]``: this file is one of the shared harness, and it is read
    from three places -- ``emkit/tests/`` in the development checkout, the
    merged ``tests/`` of an assembled tree, and the repository's own ``tests/``
    beside it.
    """
    for candidate in pathlib.Path(__file__).resolve().parents:
        if (candidate / "tools" / "install.py").is_file():
            return candidate
    raise RuntimeError(f"No tools/install.py above {__file__}")


ROOT = _root()
TOOLS = ROOT / "tools"

_loaded = {}


def load(name):
    """The tools script *name* (without ``.py``), executed once per session."""
    if name not in _loaded:
        spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        _loaded[name] = module
        sys.modules.setdefault(name, module)  # for the imports between them
        spec.loader.exec_module(module)
    return _loaded[name]
