#!/usr/bin/env python3
"""Build the redistributable package: the KiCad add-on, and only that.

    python tools/make_package.py                # -> dist/...-pcm.zip
    python tools/make_package.py windows        # the same, carrying the
                                                #   Windows solver alone
    python tools/make_package.py --out-dir /tmp

One archive, for every OS at once. KiCad's own **Plugin and Content Manager**
installs it (*Install from File*), which is why it is the only one worth
building: it asks the user's machine for nothing -- no PowerShell, no shell, no
Python, no administrator rights -- and brings a native uninstall with it. The
scripted installers that used to be built here needed the OS to cooperate and
were dropped; ``pcm.py`` holds the shape of what replaced them.

    <Product>-<ver>-pcm.zip
        metadata.json
        plugins/                 the payload: the plugin, in installed shape
            __init__.py
            ...
            binaries/<solver>-linux-x86_64    \\  every build, side by side;
            binaries/<solver>-linux-aarch64    |  each named for the machine
            binaries/<solver>-windows.exe     /   it is for, and the plugin
                                                  picks its own
        resources/icon.png

``plugins/`` is staged in the shape the plugin has once *installed*, solver
binaries already nested inside it, so installing is a directory copy and
nothing more. Which of those binaries runs is decided at run time by the
plugin itself (``sim/builds.py``), not here -- one package cannot know which
machine it will land on. What ships is a payload, not a procedure.

The list of builds is not this file's either: ``sim/builds.py`` holds it, and
what is left here is one *platform* per OS, since that is the granularity PCM's
metadata can express (it has no way to tell an x86-64 Linux from an AArch64
one). A platform is therefore one or more builds, and Linux is the one with two.

No installer toolchain is involved (no NSIS, no Inno Setup, no dpkg/rpm, no
code signing), so the package builds on any OS -- which matters, because the
plugin is developed on Linux and macOS too. The one thing that cannot be
cross-built is the solver: ``binaries/`` has to already hold every build the
package covers, and the header check below refuses anything else.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import install  # noqa: E402  (path set above; the installer is the source of truth)
import pcm  # noqa: E402  (same path fix; the PCM format's own shape and metadata)
from emptytree import emptied  # noqa: E402  (same path fix)

PROJECT_ROOT = install.PROJECT_ROOT

# The solver builds there are, read out of the plugin rather than listed again
# here: which machines are covered, what each build's file is called and how to
# tell one from another are the run-time answer as much as the build-time one,
# and two copies of it is a package whose binaries the plugin cannot find (see
# emkit/sim/builds.py).
builds = install.load_plugin_module("emkit", "sim", "builds.py")

# The operating systems a package can be narrowed to, which is what PCM's
# metadata names -- see the module docstring. Linux is one platform and two
# builds.
PLATFORMS: tuple[str, ...] = tuple(builds.os_keys())


def requested(target: str | None) -> list:
    """The builds a run carries: one OS's, or -- since the package is for every
    machine, and that is the point of it -- all of them.

    Naming an OS is for a checkout that has only that one built; the package it
    produces says so in its metadata, and PCM then refuses it elsewhere. Which
    OS this runs *on* deliberately doesn't come into it: nothing is built by
    running anything inside the package.

    Only builds that ship. macOS has none -- its solver runs in a container --
    so ``--target macos`` is a package with no binaries in it, which is a
    mistake worth naming rather than staging.
    """
    wanted = builds.for_os(target) if target else list(builds.BUILDS)
    shipped = [build for build in wanted if build.shipped]
    if not shipped:
        raise SystemExit(
            f"No solver build ships for {target}: there is nothing to package. "
            f"A {target} install is served by a package carrying the "
            f"{builds.CONTAINER_OS} builds, which its container runs."
        )
    return shipped


def platforms_of(wanted: list) -> list[str]:
    """The OS names a package carrying *wanted* can be installed on -- what its
    metadata says, one name however many builds it took.

    The plugin's own answer (``sim.builds.platforms_served``), not a count of
    the payload: an OS whose solver runs in a container is served by the Linux
    builds and has none of its own, and a package that failed to name it would
    be refused on every machine running it.
    """
    return builds.platforms_served(wanted)


def binary_name(build) -> str:
    """What *build*'s file is called, for the solver this product drives.

    The stem is the product's (``product.BINARY``); the tail that says which
    machine the file is for is the build's.
    """
    return build.filename(install.PRODUCT.BINARY)


def plugin_version() -> str:
    """``__version__`` read out of the package source.

    Read, not imported: the package ``__init__.py`` imports pcbnew, which only
    exists inside KiCad.
    """
    init = install.SOURCE / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit(f"No __version__ in {init}")


def check_binary(build) -> Path:
    """The bundled solver for *build*, verified to be that machine's.

    Both halves of the check are the plugin's own (``sim.builds.check``): the
    container, which catches a Windows build filed under a Linux name, and --
    on Linux, where two builds share the ELF magic -- the machine in the header,
    which is the only thing that can tell the AArch64 build from the x86-64 one.
    """
    binary = install.BINARIES_DIR / binary_name(build)
    if not binary.is_file():
        raise SystemExit(
            f"{build.label} simulator binary not found: {binary}\n"
            f"Build it for {build.tag} and copy it into "
            f"{install.BINARIES_DIR}, then re-run this."
        )
    problem = builds.check(build, binary)
    if problem:
        raise SystemExit(
            f"{problem}\nIt is probably a build for another machine; the "
            f"{build.label} package needs a {build.tag} one."
        )
    return binary


def make_executable(path: Path) -> None:
    """+x for everyone who can read it -- the mode the archive then carries."""
    mode = path.stat().st_mode
    path.chmod(mode | ((mode & 0o444) >> 2))


def fresh(stage_dir: Path) -> Path:
    """*stage_dir*, emptied -- so a rebuild cannot ship a file that only the
    previous build had a reason to stage.

    Files are what "emptied" means here; a directory that the filesystem
    refuses to remove is written into again (tools/emptytree.py), which is why
    the staging copy below passes ``dirs_exist_ok``.
    """
    return emptied(stage_dir)


def stage_payload(payload: Path, wanted: list) -> None:
    """The installed plugin, staged at *payload*, with each of the solver
    builds in *wanted* nested inside it.

    Normally all of them, since one archive installs on every machine. Choosing
    between the builds is then the plugin's job at run time, not the packager's
    here (``sim/builds.candidates`` offers this machine's own name first, and
    ``sim/simulate._find_exe`` takes the first that is actually there).

    This is the whole of "what an install is made of", kept here rather than
    in ``pcm.py``: where the payload goes and what the metadata says are that
    module's business, what the payload *is* stays this one's.
    """
    binaries_wanted = [check_binary(build) for build in wanted]

    shutil.copytree(
        install.SOURCE,
        payload,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )

    # The plugin's MIT licence and the solver's non-commercial one, staged by
    # the installer's own function so that a package and a `make install` put
    # the same pair of files in the same place.
    install.bundle_licences(payload)

    # Inside the package, not beside it: simulate.locate() looks one level
    # above its own module, so this is where the binary sits post-install --
    # and staging it there is what lets installing be a plain copy.
    binaries = payload / "binaries"
    binaries.mkdir(exist_ok=True)
    for binary in binaries_wanted:
        staged_binary = binaries / binary.name
        shutil.copy2(binary, staged_binary)
        make_executable(staged_binary)


def stage_pcm(stage_dir: Path, wanted: list) -> None:
    """Assemble the KiCad Plugin and Content Manager tree under *stage_dir*,
    carrying every build in *wanted* -- one archive, every machine.

    Only the payload is decided here; where PCM wants it and what its
    metadata says is ``pcm.stage``'s business, which is handed the staging as
    a callable so that this file keeps the one definition of the payload and
    that one keeps the one definition of the format.
    """
    pcm.stage(
        fresh(stage_dir),
        version=plugin_version(),
        # Build.os_key is already spelled the way PCM's schema spells it, and
        # the two Linux builds collapse to the one name it can express.
        platforms=platforms_of(wanted),
        payload=lambda destination: stage_payload(destination, wanted),
    )


def _entries(stage_dir: Path):
    """Every path in the staged tree, sorted, paired with its slash-separated
    name inside the package."""
    for path in sorted(stage_dir.rglob("*")):
        yield path, path.relative_to(stage_dir).as_posix()


def executables_of(wanted: list, payload_dir: str) -> set[str]:
    """What has to unpack runnable: every solver under *payload_dir*. Named
    rather than read off the staged files, because a build on Windows cannot
    express an execute bit on disk at all -- so the archive states the mode
    instead of copying whatever the build host managed."""
    return {f"{payload_dir}/binaries/{binary_name(build)}" for build in wanted}


def make_pcm_zip(stage_dir: Path, zip_path: Path, wanted: list) -> None:
    """Roll the staged tree up into the archive PCM reads.

    No wrapping directory -- metadata.json has to be at the archive root for
    KiCad to find it -- and every file carries the mode it must arrive with.
    The mode is written as a POSIX entry rather than left to the build host,
    which is the only form an extractor can read one back out of: Windows
    ignores it, KiCad's PCM extractor applies it, and that is how the Linux
    solver arrives runnable out of a zip.
    """
    executables = executables_of(wanted, pcm.PLUGINS_DIR)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in _entries(stage_dir):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo.from_file(path, name)
            info.create_system = 3  # Unix; anything else has no mode to read
            info.external_attr = (0o755 if name in executables else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def pcm_name(wanted: list) -> str:
    """What the add-on package is called.

    No OS in the name when it carries every build there is, which is the point
    of it: one file, any machine. No architecture either -- PCM's ``platforms``
    are operating systems, so it has no way to tell two builds of the same OS
    apart, and a name promising otherwise would be the only thing choosing.

    A narrowed package is named for the builds it *carries*, not for the OSes
    it serves -- the two parted company when macOS stopped having a build of
    its own, and this name exists to keep a narrowed build from overwriting the
    real release in ``dist/``. "Which machines was this compiled for" is the
    question a file in a build directory answers; ``metadata.json`` is where
    "where can it be installed" is stated, and it is stated by
    :func:`platforms_of`.
    """
    stem = f"{install.PRODUCT.NAME.replace(' ', '')}-{plugin_version()}"
    if len(wanted) < len(builds.shipped_builds()):
        carried = [key for key in PLATFORMS if any(b.os_key == key for b in wanted)]
        stem += "-" + "-".join(carried)
    return f"{stem}-pcm"


def build_pcm(wanted: list, out_dir: Path) -> Path:
    """Stage and archive the package. Returns the archive."""
    # Every solver before anything is staged: the one archive is *every*
    # machine, so a build missing from binaries/ would otherwise ship as a
    # package that installs where it cannot simulate.
    for build in wanted:
        check_binary(build)

    name = pcm_name(wanted)
    stage_dir = PROJECT_ROOT / "build" / "pcm" / name
    stage_pcm(stage_dir, wanted)

    archive_path = out_dir / f"{name}.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    make_pcm_zip(stage_dir, archive_path, wanted)

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"Staged  {stage_dir}")
    print(f"Package {archive_path}  ({size_mb:.1f} MB)")
    return archive_path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "target",
        nargs="?",
        choices=sorted(PLATFORMS),
        help="Limit the package to one OS's builds (default: every one)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(PROJECT_ROOT / "dist"),
        help="Where to write the archive (default: dist/)",
    )
    args = parser.parse_args(argv)

    build_pcm(requested(args.target), Path(args.out_dir).expanduser())


if __name__ == "__main__":
    main()
