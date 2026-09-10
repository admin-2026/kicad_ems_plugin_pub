#!/usr/bin/env python3
"""Empty a generated directory, on filesystems that let you and on ones that
do not quite.

Every build step here starts by throwing away what the previous one wrote --
``tools/assemble.py`` empties ``build/<product>/``, ``tools/make_package.py``
empties the staging tree under ``dist/``. A tree that kept whatever was there
before could ship a module that has since been deleted, and finding that out
from a user's install is the whole reason the emptying is a build step.

``shutil.rmtree`` is the obvious way to do it and it is not enough. A checkout
inside a synced folder -- Docker Desktop's virtiofs over a macOS
``~/Library/CloudStorage`` mount, Synology Drive or Dropbox underneath it --
hands back directories that ``readdir`` reports as empty and ``rmdir`` still
refuses with ``ENOTEMPTY``: the provider is holding entries the guest never
sees. Nothing is wrong with the *build* when that happens, but the build dies,
on a directory it was about to regenerate from scratch anyway.

So this separates the two halves of "emptied". Files must go, because a stale
file is what would be shipped. Directories are structure: one that refuses to
be removed is left standing and written into again, which is why every
``copytree`` onto a tree this function returns passes ``dirs_exist_ok=True``.
A file that survives is still fatal, and named.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# How many survivors to name before the message is just noise.
SHOWN = 10


def emptied(tree: Path) -> Path:
    """*tree* with no file left in it, created if it was not there at all.

    Returns the directory, so it reads as one step at the call site::

        dest = emptied(build_dir(product))
    """
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True, exist_ok=True)

    left = sorted(path for path in tree.rglob("*") if path.is_file())
    if left:
        listed = "\n".join(f"  {path}" for path in left[:SHOWN])
        more = f"\n  ...and {len(left) - SHOWN} more" if len(left) > SHOWN else ""
        raise SystemExit(
            f"Could not empty {tree} -- these files are still there:\n"
            f"{listed}{more}\n"
            f"Something is holding them open, or they are not yours to remove. "
            f"Delete the directory by hand and re-run."
        )
    return tree
