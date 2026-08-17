#!/usr/bin/env python3
"""Cross-platform lint/format runner for the Antenna Designer plugin.

Wraps ruff (configured by ruff.toml at the repo root) so the Makefile rules
are one-liners that behave the same whether make runs under sh (Linux/macOS/
Git Bash) or cmd.exe -- the `--changed` modes in particular need `git diff`
plus a bit of filtering, which is not portable shell.

    python tools/lint.py lint                  # report findings
    python tools/lint.py fix                   # apply the safe fixes
    python tools/lint.py format                # rewrite files
    python tools/lint.py format-check          # report, rewrite nothing

Scope:
    --changed [BASE]    only .py files that differ from BASE (default HEAD)
    <paths>...          explicit files or directories (default: the plugin,
                        its tools and its tests)

ruff itself is not bundled: `pip install ruff` where you lint.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# What "the plugin" means to the linter: the installed package plus the code
# that builds and tests it. ruff.toml's extend-exclude keeps the simulator
# tree and vendored code out even when a wider path is passed explicitly.
DEFAULT_PATHS = ["antenna_plugin", "tools", "tests"]

# One ruff invocation per action. --fix and the format rewrites are the only
# ones that touch files; keep it that way so `lint` and `format-check` are
# always safe to run (and to gate a commit on).
ACTIONS = {
    "lint": ["check"],
    "fix": ["check", "--fix"],
    "format": ["format"],
    "format-check": ["format", "--check"],
}


def ruff_command() -> list[str]:
    """How to invoke ruff here: the standalone binary, else the module.

    pip installs both a console script and an importable package, but a venv
    that is not on PATH (or a `pip install --user` on Windows) leaves only one
    of the two reachable, so try each before giving up.
    """
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    probe = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "ruff"]
    raise SystemExit(
        "ruff not found -- install it where you lint:\n"
        f"    {Path(sys.executable).name} -m pip install ruff"
    )


def changed_paths(base: str) -> list[str]:
    """The .py files differing from BASE, as repo-relative paths.

    --diff-filter=d drops deletions: a file that is gone cannot be linted,
    and passing it to ruff is an error rather than a no-op.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", base, "--", "*.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"git diff against {base!r} failed:\n{result.stderr.strip()}")
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # Staying under DEFAULT_PATHS keeps a stray script elsewhere in the tree
    # out; ruff.toml's excludes then do the rest of the filtering.
    return [n for n in names if n.split("/", 1)[0] in DEFAULT_PATHS]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=tuple(ACTIONS))
    parser.add_argument(
        "--changed",
        nargs="?",
        const="HEAD",
        metavar="BASE",
        help="only files that differ from BASE (default HEAD)",
    )
    parser.add_argument("paths", nargs="*", help="files or dirs (default: the plugin)")
    args = parser.parse_args(argv)

    if args.changed:
        if args.paths:
            raise SystemExit("--changed and explicit paths are mutually exclusive")
        paths = changed_paths(args.changed)
        if not paths:
            print(f"no changed Python sources vs {args.changed}")
            return
        # Flushed so the list stays above ruff's own output: this print is
        # buffered when stdout is a pipe, the child writes to the fd directly.
        print("\n".join(paths), flush=True)
    else:
        paths = args.paths or DEFAULT_PATHS

    cmd = ruff_command() + ACTIONS[args.action] + paths
    sys.exit(subprocess.run(cmd, cwd=PROJECT_ROOT).returncode)


if __name__ == "__main__":
    main()
