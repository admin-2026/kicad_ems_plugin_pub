#!/usr/bin/env python3
"""Cross-platform installer for this checkout's pcbnew plugin.

Copies the plugin package -- the one directory here holding a ``product.py``,
see ``package_dir`` -- into KiCad's per-user plugin directory on Linux, macOS
or Windows. Runnable directly (``python tools/install.py install``) or via the
Makefile.

It also bundles the simulator binary the product names *inside* the installed
package (under ``binaries/``), so the EM Simulation button works from a
detached install. ``simulate.locate()`` finds it there -- one level above
``simulate.py``, the same shape it searches for in the dev checkout. The
plugin depends on nothing else in the repo (in particular nothing in ``ems``);
it generates the runner config itself.

    python tools/install.py install
    python tools/install.py uninstall
    python tools/install.py where        # just print the target directory
    python tools/install.py targets      # every KiCad found, not just the newest
    python tools/install.py install-cli  # the command line's one-word shortcut

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
import importlib
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def package_dir(root: Path) -> Path:
    """The one directory in *root* that is a plugin: the one holding a
    ``product.py``.

    A checkout that installs is a checkout of *one* product -- either this
    repository's public mirror, or a tree ``tools/assemble.py`` wrote -- so
    there is exactly one, and asking the tree beats keeping its name written
    down here as well. Anything else is an error: none means this is the
    development checkout, where the plugin is assembled out of ``emkit/`` and
    ``plugins/<name>/`` rather than sitting ready to copy.
    """
    found = sorted(path.parent for path in root.glob("*/product.py"))
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit(
            f"No plugin package in {root}: nothing here holds a product.py.\n"
            f"In the development checkout the package is assembled first --\n"
            f"  make <product>-install      (see Makefile.local)"
        )
    raise SystemExit(
        "More than one plugin package here: "
        + ", ".join(path.name for path in found)
        + "\nAn install is one product; assemble each into its own tree."
    )


SOURCE = package_dir(PROJECT_ROOT)


# The name the plugin's modules are imported under here. Not the package's own
# (PRODUCT.PACKAGE): importing that would run its ``__init__``, which imports
# pcbnew and so only works inside KiCad. A bare package around the same
# directory has no ``__init__`` to run, and every module below it keeps working
# -- the plugin's imports are all relative, which is what makes this possible.
BARE_NAME = "_plugin_package"


def load_plugin_module(*parts: str, root: Path | None = None):
    """One module of the plugin, loaded without running its package ``__init__``.

    Lets build-time tooling read the plugin's own answer to a question -- what
    the binary is called, where the project lives -- instead of keeping a
    second copy of it that is free to drift.

    ``root`` names which copy to read, and defaults to this checkout's. An
    *installed* one is worth naming when the module answers with its own path
    (``agent/shim.py`` bakes in the launcher beside it), so each copy gets a
    bare package of its own rather than the first one seen standing in for all.
    """
    root = SOURCE if root is None else root
    name = _BARE_NAMES.get(root)
    if name is None:
        name = BARE_NAME if root == SOURCE else f"{BARE_NAME}_{len(_BARE_NAMES)}"
        package = types.ModuleType(name)
        package.__path__ = [str(root)]
        sys.modules[name] = package
        _BARE_NAMES[root] = name
    dotted = ".".join(parts).removesuffix(".py")
    return importlib.import_module(f"{name}.{dotted}")


_BARE_NAMES: dict[Path, str] = {}


# The product's own manifest: its name, its solver, its repository. Every
# per-product string the build-time tools need comes from here, so that adding
# a second plugin does not mean editing them (see plugins/<name>/product.py).
PRODUCT = load_plugin_module("product.py")

# Simulator binary bundled into the installed package so the run flow is
# self-contained. It lands under <pkg>/binaries/, where simulate.locate()
# probes for it. The directory holds a build per machine, each under the name
# that says which (monopole-linux-x86_64, monopole-windows.exe, ...); which one
# belongs in *this* install is sim/builds.py's answer, below.
#
# In an assembled tree it is already this product's solver and nothing else;
# in the development checkout the builds are one directory per solver stem
# (binaries/<stem>/), and assembly flattens the one the product names.
BINARIES_DIR = PROJECT_ROOT / "binaries"
if (BINARIES_DIR / PRODUCT.BINARY).is_dir():
    BINARIES_DIR = BINARIES_DIR / PRODUCT.BINARY

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
                "installed": (dest_root / PRODUCT.PACKAGE).is_dir(),
            }
        )
    return targets


def resolve_plugin_dir(
    kicad_ver: str | None, plugin_dir: str | None, required: bool = True
) -> Path | None:
    """KiCad's plugin directory for this machine.

    ``required=False`` answers ``None`` where the strict form gives up: a
    caller that has somewhere else to go (``cli_package``) rather than a
    message to print.
    """
    if plugin_dir:
        return Path(plugin_dir).expanduser()
    base = plugin_base()
    version = kicad_ver or detect_version(base)
    if not version:
        if not required:
            return None
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
    dest = dest_root / PRODUCT.PACKAGE
    if dest.exists():
        shutil.rmtree(dest)
    # Skip caches/compiled files so we ship a clean copy.
    shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Installed to {dest}")
    bundle_licences(dest)
    bundle_binary(dest)
    print("Restart pcbnew, or Tools > External Plugins > Refresh Plugins.")


def host_build_names() -> tuple[str, ...]:
    """Every build of this product's solver by name, the one for this machine
    first -- the plugin's own ``sim/builds.py``.

    Keeps the installer's idea of what the binary is called identical to the
    one ``simulate.locate()`` uses at run time, architecture included.
    """
    builds = load_plugin_module("emkit", "sim", "builds.py")
    return tuple(builds.candidates(PRODUCT.BINARY))


def select_binaries() -> list[Path]:
    """The builds of the solver to bundle: every one that ships and is there.

    Not just this machine's, and that changed with the container. A run may
    happen natively (this machine's build) or inside a container (a Linux
    build, for the *daemon's* architecture -- which on an Apple Silicon Mac is
    AArch64 and on Docker Desktop for Windows is x86-64, neither of them a fact
    about the host). Bundling one build would leave the container with nothing
    to mount on exactly the OS that has no other way to solve.

    So an install carries what a package carries, which also means the two
    installers no longer disagree about what an install is. A build that is
    missing from the checkout is skipped rather than fatal -- a developer with
    one build compiled can still install -- but carrying none is not an
    install anyone can simulate from.
    """
    builds = load_plugin_module("emkit", "sim", "builds.py")
    found = []
    for build in builds.shipped_builds():
        candidate = BINARIES_DIR / build.filename(PRODUCT.BINARY)
        if candidate.is_file():
            found.append(candidate)
    if not found:
        wanted = host_build_names() or [
            build.filename(PRODUCT.BINARY) for build in builds.shipped_builds()
        ]
        raise SystemExit(
            f"Simulator binary not found: no {wanted[0]} in {BINARIES_DIR} "
            f"(nor any other build).\n"
            f"Build it first (`make -C ems build_all_release`) and copy it "
            f"into {BINARIES_DIR}, then re-run install."
        )
    return found


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
    """Copy the simulator builds into the installed package."""
    binaries = select_binaries()

    bin_dst = dest / "binaries"
    bin_dst.mkdir(parents=True, exist_ok=True)
    for binary in binaries:
        out = bin_dst / binary.name
        shutil.copy2(binary, out)
        os.chmod(out, os.stat(out).st_mode | 0o111)  # keep it executable

    # Which of them this machine would launch itself, said plainly: on macOS
    # that is none of them, and a line reading "bundled 3 builds" with no word
    # about which one runs here would be the wrong kind of reassuring.
    names = [binary.name for binary in binaries]
    native = host_build_names()
    if native and native[0] in names:
        note = f"this machine runs {native[0]}"
    elif native:
        note = f"none of them is this machine's ({native[0]})"
    else:
        note = "this machine has no native build; its solver runs in a container"
    print(f"  bundled simulator: {', '.join(names)} -- {note}")


def cli_package(kicad_ver: str | None, plugin_dir: str | None) -> Path:
    """Which copy of the package the shortcut should run: the one installed in
    KiCad's plugin directory, else this checkout's own.

    The shim bakes in the path of the package it is written from, so the copy
    that outlives everything is the right one to name -- an install, where
    there is one. There is not always: a headless box has ``kicad-cli`` and no
    per-user KiCad directory at all (nothing has ever opened a window to create
    it), and a checkout is a complete plugin, solver included. So the command
    line is installable there too, pointed at the tree it was run from.
    """
    dest_root = resolve_plugin_dir(kicad_ver, plugin_dir, required=False)
    if dest_root is None:
        return SOURCE
    dest = dest_root / PRODUCT.PACKAGE
    return dest if dest.is_dir() else SOURCE


def _newest_py(root: Path) -> float:
    """The most recent ``.py`` mtime under *root*.

    Every copy on the way here is ``copytree``'s, which is ``copy2``, so an
    installed file carries the mtime of the file it came from: comparing two
    trees this way compares how old their *code* is, not when somebody last
    copied it.
    """
    return max((p.stat().st_mtime for p in root.rglob("*.py")), default=0.0)


def cmd_install_cli(package: Path) -> None:
    """Write the command line's one-word shortcut for *package*, and put its
    folder on the user's PATH.

    The same two steps the About page's tick does (``gui/sections/cli.py``),
    from a shell instead of from inside KiCad -- and through the same two
    modules, so there is one answer to what a shim is and where PATH is kept.

    Nothing here removes it: the tick in the window is the off switch (it reads
    the file, not a setting of its own), and the shim says in its own comment
    header that deleting it by hand is the other one.
    """
    shim = load_plugin_module("emkit", "agent", "shim.py", root=package)
    userpath = load_plugin_module("emkit", "agent", "userpath.py", root=package)

    target = shim.write()
    print(f"Wrote {target}")
    which = "the install" if package != SOURCE else "this checkout (no install found)"
    print(f"  runs: {package}  -- {which}")
    # An install outlives a checkout, which is why it is the copy named above --
    # but it is also a copy, and a checkout that has moved on since leaves the
    # shortcut running code the person who just built it has never seen. Nothing
    # here can install (a headless box has nowhere to install *to*, and that is
    # the case this fallback exists for), so say it instead of wiring it quietly.
    if package != SOURCE and _newest_py(SOURCE) > _newest_py(package):
        print(
            "  STALE: that install is older than this checkout, so the shortcut\n"
            "         would run code you have not built. `make install` first,\n"
            "         then this again."
        )
    folder = os.path.dirname(target)
    userpath.add(folder, shim.STEM)
    print(f"  PATH: added {folder} in {userpath.where()}")
    # Which Python got baked in, and whether it is one that can read a board.
    # Asked of the interpreter itself rather than of hostpy's recording: a
    # headless box has no window to have recorded anything and its
    # ``/usr/bin/python3`` may well have pcbnew, so "not recorded" is not the
    # question -- "no pcbnew" is, and it is the one the board verbs will fail on.
    baked = shim.interpreter()
    if _has_pcbnew(baked):
        print(f"  Python: {baked}")
    else:
        print(
            f"  Python: {baked} -- no pcbnew there, so the board verbs will say so.\n"
            "          Open the plugin's window once (it records KiCad's own) and "
            "re-run this,\n"
            "          or re-run with PYTHON=<the interpreter that has pcbnew>."
        )
    print(f"Open a new terminal (this one keeps its own PATH), then: {shim.STEM} guide")


def _has_pcbnew(python: str) -> bool:
    """Can *python* import pcbnew? Asked by running it, which is the only
    answer worth having -- a path that looks like KiCad's proves nothing."""
    try:
        done = subprocess.run(
            [python, "-c", "import pcbnew"], capture_output=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def cmd_uninstall(dest_root: Path) -> None:
    dest = dest_root / PRODUCT.PACKAGE
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
    parser.add_argument(
        "action", choices=("install", "uninstall", "where", "targets", "install-cli")
    )
    parser.add_argument("--kicad-ver", help="KiCad version dir, e.g. 9.0")
    parser.add_argument("--plugin-dir", help="Target plugins dir (skips detection)")
    args = parser.parse_args(argv)

    # Neither of these acts on KiCad's plugin directory -- `targets` surveys
    # the machine, and `install-cli` writes a shortcut that can point at this
    # checkout -- so both run before the resolution that gives up when there is
    # no KiCad directory to find.
    if args.action == "targets":
        cmd_targets()
        return
    if args.action == "install-cli":
        cmd_install_cli(cli_package(args.kicad_ver, args.plugin_dir))
        return

    dest_root = resolve_plugin_dir(args.kicad_ver, args.plugin_dir)

    if args.action == "where":
        print(dest_root / PRODUCT.PACKAGE)
    elif args.action == "install":
        cmd_install(dest_root)
    else:
        cmd_uninstall(dest_root)


if __name__ == "__main__":
    main()
