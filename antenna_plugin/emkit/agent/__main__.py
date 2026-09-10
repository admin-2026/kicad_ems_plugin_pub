"""The entry point for ``python -m <package>.emkit.agent``.

Everything it does is in ``cli.main`` -- the parser and the ``--json``
contract there, the verbs themselves in ``verbs/``, the line renderings in
``render.py``. This file exists to be the name Python runs and to turn the
result into an exit code.

It is not the *documented* entry point: the Plugin Manager extracts an install
into a directory named after the package identity with the dots replaced by
underscores, which is neither the package's own name nor a legal Python
identifier, so ``python -m`` cannot be relied on to reach it. That is what
``emkit/run_agent.py`` is for. This spelling works in a checkout and is the
convenient one there.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
