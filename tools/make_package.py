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

    AntennaDesigner-<ver>-pcm.zip
        metadata.json
        plugins/                 the payload: the plugin, in installed shape
            __init__.py
            ...
            binaries/monopole        the Linux solver \\  both, side by side;
            binaries/monopole.exe    the Windows one  /  the plugin chooses
        resources/icon.png

``plugins/`` is staged in the shape the plugin has once *installed*, solver
binaries already nested inside it, so installing is a directory copy and
nothing more. Which of those binaries runs is decided at run time by the
plugin itself (``sim/hostos.exe_names``), not here -- one package cannot know
which machine it will land on. What ships is a payload, not a procedure.

No installer toolchain is involved (no NSIS, no Inno Setup, no dpkg/rpm, no
code signing), so the package builds on any OS -- which matters, because the
plugin is developed on Linux and macOS too. The one thing that cannot be
cross-built is the solver: ``binaries/`` has to already hold a build for each
OS the package covers, and the magic-number check below refuses anything else.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import install  # noqa: E402  (path set above; the installer is the source of truth)
import pcm  # noqa: E402  (same path fix; the PCM format's own shape and metadata)

PROJECT_ROOT = install.PROJECT_ROOT


@dataclass(frozen=True)
class Platform:
    """Everything that is per-OS about the package: one solver build, and how
    to be sure it really is that OS's.

    ``magic`` is what the binary must start with. A Linux build sitting in
    ``binaries/monopole.exe`` (or the reverse) produces a package that installs
    cleanly and then fails at the first simulation, which is a bad place to
    discover it -- so the check is here, at build time.
    """

    key: str  # "windows"; also how PCM's metadata spells the platform
    binary: str  # the build of the solver this platform contributes
    magic: bytes
    magic_name: str  # how to say "that is the wrong kind of file"


WINDOWS = Platform(
    key="windows",
    binary="monopole.exe",
    magic=b"MZ",
    magic_name="Windows executable",
)

LINUX = Platform(
    key="linux",
    binary="monopole",
    magic=b"\x7fELF",
    magic_name="Linux (ELF) executable",
)

PLATFORMS = {p.key: p for p in (WINDOWS, LINUX)}


def requested(target: str | None) -> list[Platform]:
    """The platforms a run covers: the one named, or -- since the package is
    for all of them, and that is the point of it -- every one.

    Naming one is for a checkout that has only that OS's solver built; the
    package it produces says so in its metadata, and PCM then refuses it
    elsewhere. Which OS this runs *on* deliberately doesn't come into it:
    nothing is built by running anything inside the package.
    """
    return [PLATFORMS[target]] if target else list(PLATFORMS.values())


def plugin_version() -> str:
    """``__version__`` read out of the package source.

    Read, not imported: ``antenna_plugin/__init__.py`` imports pcbnew, which
    only exists inside KiCad.
    """
    init = install.SOURCE / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit(f"No __version__ in {init}")


def check_binary(platform: Platform) -> Path:
    """The bundled solver for *platform*, verified to be that OS's build."""
    binary = install.BINARIES_DIR / platform.binary
    if not binary.is_file():
        raise SystemExit(
            f"{platform.key.capitalize()} simulator binary not found: {binary}\n"
            f"Build it for {platform.key} and copy it into "
            f"{install.BINARIES_DIR}, then re-run this."
        )
    with binary.open("rb") as handle:
        if handle.read(len(platform.magic)) != platform.magic:
            raise SystemExit(
                f"{binary} is not a {platform.magic_name}.\n"
                f"It is probably a build for another OS; the {platform.key} "
                f"package needs a {platform.key} one."
            )
    return binary


def make_executable(path: Path) -> None:
    """+x for everyone who can read it -- the mode the archive then carries."""
    mode = path.stat().st_mode
    path.chmod(mode | ((mode & 0o444) >> 2))


def fresh(stage_dir: Path) -> Path:
    """*stage_dir*, emptied -- so a rebuild cannot ship a file that only the
    previous build had a reason to stage."""
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    return stage_dir


def stage_payload(payload: Path, platforms: list[Platform]) -> None:
    """The installed plugin, staged at *payload*, with a solver build for each
    of *platforms* nested inside it.

    Normally all of them, since one archive installs on every OS. Choosing
    between the builds is then the plugin's job at run time, not the packager's
    here (``sim/hostos.exe_names`` offers the running OS's own name first, and
    ``sim/simulate._find_exe`` takes the first that is actually there).

    This is the whole of "what an install is made of", kept here rather than
    in ``pcm.py``: where the payload goes and what the metadata says are that
    module's business, what the payload *is* stays this one's.
    """
    binaries_wanted = [check_binary(platform) for platform in platforms]

    shutil.copytree(
        install.SOURCE,
        payload,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # The plugin's MIT licence and the solver's non-commercial one, staged by
    # the installer's own function so that a package and a `make install` put
    # the same pair of files in the same place.
    install.bundle_licences(payload)

    # Inside the package, not beside it: simulate.locate() looks one level
    # above its own module, so this is where the binary sits post-install --
    # and staging it there is what lets installing be a plain copy.
    binaries = payload / "binaries"
    binaries.mkdir()
    for binary in binaries_wanted:
        staged_binary = binaries / binary.name
        shutil.copy2(binary, staged_binary)
        make_executable(staged_binary)


def stage_pcm(stage_dir: Path, platforms: list[Platform]) -> None:
    """Assemble the KiCad Plugin and Content Manager tree under *stage_dir*,
    covering every one of *platforms* -- one archive, every OS.

    Only the payload is decided here; where PCM wants it and what its
    metadata says is ``pcm.stage``'s business, which is handed the staging as
    a callable so that this file keeps the one definition of the payload and
    that one keeps the one definition of the format.
    """
    pcm.stage(
        fresh(stage_dir),
        version=plugin_version(),
        # Platform.key is already spelled the way PCM's schema spells it.
        platforms=[platform.key for platform in platforms],
        payload=lambda destination: stage_payload(destination, platforms),
    )


def _entries(stage_dir: Path):
    """Every path in the staged tree, sorted, paired with its slash-separated
    name inside the package."""
    for path in sorted(stage_dir.rglob("*")):
        yield path, path.relative_to(stage_dir).as_posix()


def executables_of(platforms: list[Platform], payload_dir: str) -> set[str]:
    """What has to unpack runnable: every solver under *payload_dir*. Named
    rather than read off the staged files, because a build on Windows cannot
    express an execute bit on disk at all -- so the archive states the mode
    instead of copying whatever the build host managed."""
    return {f"{payload_dir}/binaries/{p.binary}" for p in platforms}


def make_pcm_zip(stage_dir: Path, zip_path: Path, platforms: list[Platform]) -> None:
    """Roll the staged tree up into the archive PCM reads.

    No wrapping directory -- metadata.json has to be at the archive root for
    KiCad to find it -- and every file carries the mode it must arrive with.
    The mode is written as a POSIX entry rather than left to the build host,
    which is the only form an extractor can read one back out of: Windows
    ignores it, KiCad's PCM extractor applies it, and that is how the Linux
    solver arrives runnable out of a zip.
    """
    executables = executables_of(platforms, pcm.PLUGINS_DIR)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in _entries(stage_dir):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo.from_file(path, name)
            info.create_system = 3  # Unix; anything else has no mode to read
            info.external_attr = (0o755 if name in executables else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def pcm_name(platforms: list[Platform]) -> str:
    """What the add-on package is called.

    No OS in the name when it covers them all, which is the point of it: one
    file, any machine. No architecture either -- PCM's ``platforms`` are
    operating systems, so it has no way to tell two builds of the same OS
    apart, and a name promising otherwise would be the only thing choosing.
    """
    stem = f"AntennaDesigner-{plugin_version()}"
    if len(platforms) < len(PLATFORMS):
        stem += "-" + "-".join(platform.key for platform in platforms)
    return f"{stem}-pcm"


def build_pcm(platforms: list[Platform], out_dir: Path) -> Path:
    """Stage and archive the package. Returns the archive."""
    # Every solver before anything is staged: the one archive is *all* the
    # platforms, so a build missing from binaries/ would otherwise ship as a
    # package that installs on an OS it cannot simulate on.
    for platform in platforms:
        check_binary(platform)

    name = pcm_name(platforms)
    stage_dir = PROJECT_ROOT / "build" / "pcm" / name
    stage_pcm(stage_dir, platforms)

    archive_path = out_dir / f"{name}.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    make_pcm_zip(stage_dir, archive_path, platforms)

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
        help="Limit the package to one OS's solver (default: every one)",
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
