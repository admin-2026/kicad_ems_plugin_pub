#!/usr/bin/env python3
"""Cross-platform installer for the Antenna Designer pcbnew plugin.

Copies the ``antenna_plugin`` package into KiCad's per-user plugin directory
on Linux, macOS or Windows. Runnable directly (``python tools/install.py
install``) or via the Makefile.

It also bundles the simulator ``monopole`` binary *inside* the installed
package (under ``binaries/``), so the EM Simulation button works from a
detached install. ``simulate.locate()`` finds it there -- one level above
``simulate.py``, the same shape it searches for in the dev checkout. The
plugin depends on nothing else in the repo (in particular nothing in ``ems``);
it generates the runner config itself.

    python tools/install.py install
    python tools/install.py uninstall
    python tools/install.py where        # just print the target directory
    python tools/install.py targets      # every KiCad found, not just the newest

Overrides:
    --kicad-ver 8.0                       # pick a specific KiCad version dir
    --plugin-dir "C:/path/to/plugins"     # bypass detection entirely

This is the checkout's installer. The redistributable packages (Windows, Linux)
do not use it at runtime -- tools/make_package.py stages a payload that needs
only to be copied -- so the two share the build-time answer to "what is an
install made of" without this file having to be present on a user's machine.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_NAME = "antenna_plugin"
SOURCE = PROJECT_ROOT / PLUGIN_NAME

# Simulator binary bundled into the installed package so the run flow is
# self-contained. It lands under <pkg>/binaries/, where simulate.locate()
# probes for it. The directory holds a build per OS (monopole, monopole.exe);
# which one belongs in *this* install is hostos.exe_names' answer, below.
BINARIES_DIR = PROJECT_ROOT / "binaries"
BINARY_STEM = "monopole"

# The licences, copied into the installed package root. Both travel, because
# an install is two licences' worth of software: the plugin is MIT, the solver
# next to it is proprietary and free for non-commercial use only. The second
# one states terms a user is asked to keep, so it has to arrive with the
# binary rather than staying in a repository they may never see.
LICENCE_FILES: tuple[str, ...] = ("LICENSE", "LICENSE-solver.txt")

_VER_RE = re.compile(r"^\d+\.\d+$")


def plugin_base() -> Path:
    """The per-user KiCad directory that holds the version subfolders."""
    home = Path.home()
    if sys.platform.startswith("win"):
        # e.g. C:\Users\me\Documents\KiCad
        docs = os.environ.get("KICAD_DOCUMENTS_DIR")
        return Path(docs) if docs else home / "Documents" / "KiCad"
    if sys.platform == "darwin":
        return home / "Documents" / "KiCad"
    return home / ".local" / "share" / "kicad"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def list_versions(base: Path) -> list[str]:
    """Every KiCad version directory under *base*, oldest first.

    A version directory is KiCad's own per-user data folder for that major, so
    its presence means that KiCad has been installed *and* run at least once.
    """
    if not base.is_dir():
        return []
    return sorted(
        (d.name for d in base.iterdir() if d.is_dir() and _VER_RE.match(d.name)),
        key=_version_key,
    )


def detect_version(base: Path) -> str | None:
    versions = list_versions(base)
    return versions[-1] if versions else None


def plugin_dir_for(base: Path, version: str) -> Path:
    return base / version / "scripting" / "plugins"


def list_targets(base: Path | None = None) -> list[dict]:
    """Each KiCad on this machine as an install target, oldest first.

    ``installed`` reports whether *this* plugin is already in that target, so a
    caller can tell an upgrade from a first install without probing paths of
    its own.
    """
    base = base if base is not None else plugin_base()
    targets = []
    for version in list_versions(base):
        dest_root = plugin_dir_for(base, version)
        targets.append(
            {
                "version": version,
                "plugin_dir": str(dest_root),
                "installed": (dest_root / PLUGIN_NAME).is_dir(),
            }
        )
    return targets


def resolve_plugin_dir(kicad_ver: str | None, plugin_dir: str | None) -> Path:
    if plugin_dir:
        return Path(plugin_dir).expanduser()
    base = plugin_base()
    version = kicad_ver or detect_version(base)
    if not version:
        raise SystemExit(
            f"Could not detect a KiCad version under {base}.\n"
            f"Pass one explicitly, e.g.  --kicad-ver 9.0\n"
            f"or point at the directory:  --plugin-dir <path>"
        )
    if kicad_ver and not (base / version).is_dir():
        # A pinned version that isn't there is almost always a typo or a KiCad
        # that has never been run; say so rather than quietly creating the tree.
        print(
            f"Note: {base / version} does not exist yet -- installing will "
            f"create it.\n"
            f"      Check that KiCad {kicad_ver} is installed and has been "
            f"started once.",
            file=sys.stderr,
        )
    return plugin_dir_for(base, version)


def cmd_install(dest_root: Path) -> None:
    if not SOURCE.is_dir():
        raise SystemExit(f"Source package not found: {SOURCE}")
    dest = dest_root / PLUGIN_NAME
    if dest.exists():
        shutil.rmtree(dest)
    # Skip caches/compiled files so we ship a clean copy.
    shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Installed to {dest}")
    bundle_licences(dest)
    bundle_binary(dest)
    print("Restart pcbnew, or Tools > External Plugins > Refresh Plugins.")


def load_plugin_module(*parts: str):
    """One module of the plugin, loaded straight from its file.

    Importing ``antenna_plugin.anything`` the usual way would run the package
    ``__init__``, which imports pcbnew and so only works inside KiCad. Loading
    by path lets build-time tooling read the plugin's own answer to a question
    -- what the binary is called, where the project lives -- instead of
    keeping a second copy of it that is free to drift.
    """
    name = "_antenna_" + "_".join(parts).removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, SOURCE.joinpath(*parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_exe_names() -> tuple[str, ...]:
    """What this OS's build of the solver may be called, its own convention
    first -- the plugin's own ``sim/hostos.py``.

    Keeps the installer's idea of what the binary is called identical to the
    one ``simulate.locate()`` uses at run time.
    """
    hostos = load_plugin_module("sim", "hostos.py")
    return tuple(hostos.exe_names(BINARY_STEM))


def select_binary() -> Path:
    """The one build of the solver to bundle: this OS's, or the other one when
    that is all there is -- a ``.exe`` is a real find on POSIX, since a
    checkout under WSL runs it through the interop layer."""
    for name in host_exe_names():
        candidate = BINARIES_DIR / name
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"Simulator binary not found: no "
        f"{' or '.join(host_exe_names())} in {BINARIES_DIR}. "
        f"Build it first (e.g. `make -C ems build/monopole`) and copy it "
        f"into {BINARIES_DIR}, then re-run install."
    )


def bundle_licences(dest: Path) -> None:
    """Copy the licences into the installed package at *dest*.

    They live at the repository root -- that is where a reader of the project
    looks for them, and GitHub with them -- so an install has to bring them
    along; a package that carries a proprietary binary and no statement of its
    terms is the one shape this must not take. Called by both installers (here
    and ``make_package.stage_payload``) so that neither can be the one that
    forgets.
    """
    for name in LICENCE_FILES:
        source = PROJECT_ROOT / name
        if not source.is_file():
            raise SystemExit(f"Licence file not found: {source}")
        shutil.copy2(source, dest / name)


def bundle_binary(dest: Path) -> None:
    """Copy this OS's simulator binary into the installed package."""
    binary = select_binary()

    bin_dst = dest / "binaries"
    bin_dst.mkdir(parents=True, exist_ok=True)
    out = bin_dst / binary.name
    shutil.copy2(binary, out)
    os.chmod(out, os.stat(out).st_mode | 0o111)  # keep it executable

    native = host_exe_names()[0]
    note = "" if binary.name == native else f" (no {native} here -- this is not its OS)"
    print(f"  bundled simulator: {binary.name}{note}")


def cmd_uninstall(dest_root: Path) -> None:
    dest = dest_root / PLUGIN_NAME
    if dest.exists():
        shutil.rmtree(dest)
        print(f"Removed {dest}")
    else:
        print(f"Nothing to remove at {dest}")


def cmd_targets() -> None:
    """List every KiCad found, so a caller can choose among them."""
    base = plugin_base()
    targets = list_targets(base)
    if not targets:
        print(f"No KiCad version directories under {base}")
        return
    for target in targets:
        state = "installed" if target["installed"] else "not installed"
        print(f"{target['version']:<6} {target['plugin_dir']}  [{state}]")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "uninstall", "where", "targets"))
    parser.add_argument("--kicad-ver", help="KiCad version dir, e.g. 9.0")
    parser.add_argument("--plugin-dir", help="Target plugins dir (skips detection)")
    args = parser.parse_args(argv)

    # `targets` surveys the machine rather than acting on one directory, so it
    # runs before the resolution that would fail when nothing is detected.
    if args.action == "targets":
        cmd_targets()
        return

    dest_root = resolve_plugin_dir(args.kicad_ver, args.plugin_dir)

    if args.action == "where":
        print(dest_root / PLUGIN_NAME)
    elif args.action == "install":
        cmd_install(dest_root)
    else:
        cmd_uninstall(dest_root)


if __name__ == "__main__":
    main()
