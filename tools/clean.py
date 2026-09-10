#!/usr/bin/env python3
"""Delete what the other make targets generate.

    python tools/clean.py               # remove them
    python tools/clean.py --dry-run     # list them, remove nothing

Every path this touches is one a target here wrote and .gitignore already
names: the packages `make package` builds (``dist/``), the assembled checkouts
`make <product>-assemble` writes (``build/``), the tool caches, and the
``__pycache__`` directories a test run leaves all over the tree. It is a
convenience, never a correctness step -- assembly empties its own output
directory before writing it (``assemble.assemble``), so no target needs a clean
first.

What it deliberately leaves alone:

* ``binaries/`` -- solver builds are copied in from the simulator's release
  tree (``tools/binary_sync.py``), not built here, and re-fetching them means
  a compile on four machines.
* ``ems/`` and the ``*_pub`` staging clones -- other repositories that happen
  to sit inside this one. A checkout with uncommitted work in it is not
  something a `clean` may decide about. Both are named below *and* caught by
  the general rule the names are an instance of: a directory with a ``.git``
  in it belongs to another repository, and the sweep stops at its edge.
* Anything a user's board directory holds. The plugin writes results beside
  the board (``simulation/``), which is their data and nowhere near here.

One gotcha on a development checkout: ``make <product>-install-cli`` bakes a
path into the shortcut it writes, and with no KiCad install to point at that
path is ``build/<product>/``. Removing ``build/`` therefore breaks the command
line until the next assembly puts it back -- which any ``make <product>-*``
target does.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Generated entries at the checkout's top level, removed whole. Both a
# development tree and an assembled one are cleaned by this list: the assembled
# one simply has no build/ to remove, and the shipped tree's .gitignore names
# the same paths, so nothing here is a fact about which checkout this is.
GENERATED: tuple[str, ...] = (
    "build",  # assembled product checkouts (development tree only)
    "dist",  # the PCM packages `make package` writes
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".docker-image-tag",  # left behind when `make docker-smoke` is interrupted
)

# Directories the __pycache__ sweep below must not descend into, by name at the
# top level: the simulator's own tree, the staging clones tools/publish.py
# mirrors into (the glob), sample data, the two directories of copied-in
# artefacts, and somebody's virtualenv -- ruff.toml excludes much the same set
# for much the same reason.
PRUNE: frozenset[str] = frozenset(
    {"ems", "examples", "binaries", "boards", ".venv", "venv", "env"}
)
PRUNE_GLOB = "*_pub"


# ...and the rule the two lists above are only the spelled-out half of: a
# directory holding a ``.git`` is another repository, and this clean stops at
# its edge whatever it is called. ems/ and the *_pub clones each keep one, so
# either guard alone would cover them today -- both are here because they fail
# differently. A rename (`ems2/`, a second simulator checkout, a clone under
# another name) slips past the names; a tree copied without its .git, or a
# worktree, slips past this. Neither may be cleaned: what is inside is
# somebody else's checkout, possibly with uncommitted work in it, and this
# target has no business deciding anything about it.
def _foreign_checkout(path: Path) -> bool:
    return (path / ".git").exists()


# Compiled Python outside a __pycache__ directory -- rare, but a stale one
# shadows a module that has since been deleted, which is the failure this
# target is reached for in the first place.
STRAY_SUFFIXES = (".pyc", ".pyo")


def _pruned(path: Path, relative: Path) -> bool:
    """Whether the sweep should skip *path* (repo-relative: *relative*)."""
    if relative.name == ".git" or _foreign_checkout(path):
        return True
    if len(relative.parts) > 1:
        return False  # PRUNE names top-level directories only
    name = relative.name
    return name in PRUNE or name in GENERATED or fnmatch.fnmatch(name, PRUNE_GLOB)


def caches(root: Path) -> list[Path]:
    """Every ``__pycache__`` directory and stray ``.pyc`` under *root*.

    Sorted, and a ``__pycache__`` is not descended into: it is removed whole,
    so its contents are not separate findings.
    """
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        here = Path(directory)
        relative = here.relative_to(root)
        keep = []
        for name in sorted(dirnames):
            if name == "__pycache__":
                found.append(here / name)
            elif not _pruned(here / name, relative / name):
                keep.append(name)
        dirnames[:] = keep
        found.extend(
            here / name for name in sorted(filenames) if name.endswith(STRAY_SUFFIXES)
        )
    return found


def targets(root: Path) -> list[Path]:
    """Everything to remove: the generated top level, then the caches."""
    listed = [root / name for name in GENERATED if (root / name).exists()]
    return listed + caches(root)


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would go, remove nothing",
    )
    args = parser.parse_args(argv)

    found = targets(PROJECT_ROOT)
    if not found:
        print("Nothing to clean.")
        return

    failed = 0
    for path in found:
        name = path.relative_to(PROJECT_ROOT).as_posix()
        if args.dry_run:
            print(f"would remove {name}")
            continue
        try:
            remove(path)
        except OSError as exc:
            # One unremovable path (a file open on Windows, a permission) is
            # worth reporting rather than aborting: the rest of the tree can
            # still be cleaned, and the exit code below says something was
            # left behind.
            print(f"could not remove {name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"removed {name}")

    if failed:
        raise SystemExit(f"{failed} path(s) could not be removed")


if __name__ == "__main__":
    main()
