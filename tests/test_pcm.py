"""Unit tests for tools/pcm.py -- the KiCad Plugin and Content Manager package.

Nothing here runs KiCad, so what is pinned is everything KiCad checks before
it will install the archive, plus the two things it does silently afterwards
that the payload has to survive:

- **it renames the package.** ``plugins/`` is extracted to a directory named
  for the identifier (dots replaced by underscores) and imported under that
  name, so the plugin is *not* called ``antenna_plugin`` once installed. Any
  module of it that imported itself absolutely would fail there while working
  perfectly from the downloadable zip -- a break that only shows up in the
  package nobody rebuilds by hand.
- **it restores the execute bit** from the zip entry, which is the only reason
  a Linux solver can ship in a zip at all.

The metadata rules below are transcribed from the v1 schema
(https://go.kicad.org/pcm/schemas/v1), which is the one KiCad 9 validates
against -- it ships no v2 -- and they are the reason the file is generated
rather than written out by hand.
"""

import ast
import importlib
import json
import pathlib
import re
import sys
import types
import zipfile

import solver_bytes
from tools_module import ROOT, load

install = load("install")
packager = load("make_package")
pcm = load("pcm")

builds = packager.builds
WINDOWS = builds.WINDOWS
LINUX_X86_64 = builds.LINUX_X86_64
LINUX_AARCH64 = builds.LINUX_AARCH64
EVERY = list(builds.BUILDS)

# This product's solver -- off the manifest, since these tests run in every
# assembled product (see emkit/tests/test_install.py); the per-machine names
# come off the build table for the same reason.
STEM = install.PRODUCT.BINARY


def name(build):
    return build.filename(STEM)


# --- from the v1 schema ---------------------------------------------------- #
IDENTIFIER_PATTERN = r"^[a-zA-Z][-a-zA-Z0-9.]{0,98}[a-zA-Z0-9]$"
DESCRIPTION_MAX = 150
STATUSES = {"stable", "testing", "development", "deprecated"}
PLATFORM_NAMES = {"windows", "macos", "linux"}
KICAD_VERSION_PATTERN = r"^\d{1,2}(\.\d{1,2}(\.\d{1,2})?)?$"
REQUIRED = (
    "name",
    "description",
    "description_full",
    "identifier",
    "type",
    "author",
    "license",
    "resources",
    "versions",
)
# The license field is an enum of 90 licence names; a package that declares one
# outside it is refused. Only the ones this project might plausibly use --
# including the non-commercial CC values, which are in the enum and are the
# nearest thing to what this package actually is (see pcm.LICENSE).
LICENSES = {
    "MIT",
    "GPL-2.0",
    "GPL-3.0",
    "Apache-2.0",
    "BSD-3-Clause",
    "CC0-1.0",
    "CC-BY-NC-4.0",
    "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND-4.0",
}


def _load_simulate(path=None):
    """``sim.simulate``, either from the checkout or from a staged tree at
    *path* -- imported under a package named for the directory it sits in,
    which is what KiCad does to a PCM install and what makes the walk in
    ``locate()`` worth testing at all."""
    if path is None:
        from bare_package import load

        return load("emkit.sim.simulate")

    installed = path.parent.parent
    package = types.ModuleType(installed.name)
    package.__path__ = [str(installed)]
    sys.modules[installed.name] = package
    return importlib.import_module(f"{installed.name}.emkit.sim.simulate")


def _staged(tmp_path, monkeypatch, wanted=None):
    """The PCM tree, staged from a binaries/ with every build in it."""
    wanted = EVERY if wanted is None else list(wanted)
    binaries = tmp_path / "binaries"
    solver_bytes.populate(binaries, STEM, builds.BUILDS)
    monkeypatch.setattr(install, "BINARIES_DIR", binaries)

    stage_dir = tmp_path / ("pcm-" + "-".join(build.tag for build in wanted))
    packager.stage_pcm(stage_dir, wanted)
    return stage_dir


def _zipped(tmp_path, monkeypatch, wanted=None):
    """The staged tree, archived -- what a user actually hands to KiCad."""
    stage_dir = _staged(tmp_path, monkeypatch, wanted)
    archive = tmp_path / f"{stage_dir.name}.zip"
    packager.make_pcm_zip(stage_dir, archive, EVERY if wanted is None else list(wanted))
    return zipfile.ZipFile(archive)


def _metadata(tmp_path, monkeypatch, wanted=None):
    stage_dir = _staged(tmp_path, monkeypatch, wanted)
    return json.loads((stage_dir / "metadata.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# archive shape
# --------------------------------------------------------------------------- #
def test_the_three_parts_sit_at_the_archive_root(tmp_path, monkeypatch):
    # PCM reads the archive itself: a wrapping directory of the kind the
    # downloadable zip uses would hide metadata.json and the package would be
    # refused as not a package at all.
    names = _zipped(tmp_path, monkeypatch).namelist()
    assert "metadata.json" in names
    assert "resources/icon.png" in names
    assert "plugins/__init__.py" in names
    assert {name.split("/")[0] for name in names} == {
        "metadata.json",
        "plugins",
        "resources",
    }


def test_the_payload_is_unwrapped_inside_plugins(tmp_path, monkeypatch):
    # KiCad imports the extracted directory itself, so the plugin's top-level
    # modules have to be directly inside plugins/ -- nesting the package one
    # deeper would install something with no __init__.py to import.
    plugins = _staged(tmp_path, monkeypatch) / "plugins"
    assert (plugins / "__init__.py").is_file()
    assert (plugins / "action_plugin.py").is_file()
    assert not (plugins / install.PRODUCT.PACKAGE).exists()


def test_every_machines_solver_is_bundled_where_the_plugin_looks_for_it(
    tmp_path, monkeypatch
):
    # One archive installs on every machine, so it has to carry every machine's
    # build -- side by side under the payload root, which is where
    # simulate.locate() walks to and where sim.builds then chooses between them.
    binaries = _staged(tmp_path, monkeypatch) / "plugins" / "binaries"
    assert sorted(p.name for p in binaries.iterdir()) == sorted(
        name(build) for build in EVERY
    )


def test_both_licences_travel_with_the_solver(tmp_path, monkeypatch):
    # The package is MIT plugin plus proprietary, non-commercial solver. The
    # terms the user is asked to keep have to be *in* the thing they install,
    # next to the binary they restrict -- not only in a repository they may
    # never open.
    plugins = _staged(tmp_path, monkeypatch) / "plugins"
    for name in install.LICENCE_FILES:
        staged = plugins / name
        assert staged.is_file(), name
        assert staged.read_bytes() == (ROOT / name).read_bytes()
    terms = (plugins / "LICENSE-solver.txt").read_text(encoding="utf-8").lower()
    assert "non-commercial" in terms


def test_the_package_says_the_solver_is_not_free_for_commercial_use(
    tmp_path, monkeypatch
):
    # description_full is the only licensing PCM shows before the download, so
    # the one term that can surprise somebody has to be legible there. The
    # `license` field cannot say it: the enum has no value for a package that
    # is two licences at once.
    data = _metadata(tmp_path, monkeypatch)
    full = data["description_full"].lower()
    assert "non-commercial" in full
    assert "license-solver.txt" in full


def test_narrowing_the_build_narrows_the_payload(tmp_path, monkeypatch):
    # `make_package.py windows` is a package for Windows alone: it says so in
    # its metadata, and it must not carry a solver it does not declare.
    stage_dir = _staged(tmp_path, monkeypatch, [WINDOWS])
    binaries = stage_dir / "plugins" / "binaries"
    assert [p.name for p in binaries.iterdir()] == [name(WINDOWS)]

    data = json.loads((stage_dir / "metadata.json").read_text(encoding="utf-8"))
    assert data["versions"][0]["platforms"] == ["windows"]


def test_narrowing_to_linux_still_carries_both_of_its_builds(tmp_path, monkeypatch):
    # An OS is the finest thing PCM's metadata can say, so a Linux package is
    # offered to x86-64 and AArch64 machines alike and has to carry both -- one
    # name in the metadata, two files in the payload.
    stage_dir = _staged(tmp_path, monkeypatch, packager.requested("linux"))
    binaries = stage_dir / "plugins" / "binaries"
    assert sorted(p.name for p in binaries.iterdir()) == sorted(
        [name(LINUX_X86_64), name(LINUX_AARCH64)]
    )

    # And it is offered to macOS as well, which has no build of its own: what
    # a Mac installs it for is the container, and the container runs one of
    # these two.
    data = json.loads((stage_dir / "metadata.json").read_text(encoding="utf-8"))
    assert data["versions"][0]["platforms"] == ["linux", "macos"]


def test_the_zip_carries_the_execute_bit_for_every_solver(tmp_path, monkeypatch):
    # The whole reason a Linux build can ship as a zip: KiCad's extractor
    # applies the entry's mode. Without it the solver installs unrunnable and
    # fails at the first simulation.
    archive = _zipped(tmp_path, monkeypatch)
    for build in EVERY:
        solver = archive.getinfo(f"plugins/binaries/{name(build)}")
        assert solver.create_system == 3, "a mode is only readable off a Unix entry"
        assert solver.external_attr >> 16 & 0o111 == 0o111

    plain = archive.getinfo("plugins/__init__.py")
    assert plain.external_attr >> 16 & 0o111 == 0


def test_the_icon_is_the_size_pcm_asks_for(tmp_path, monkeypatch):
    # PCM specifies 64x64. Read out of the PNG header rather than with Pillow,
    # which is a build-time dependency the tests don't have to share.
    header = pcm.ICON_SOURCE.read_bytes()
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    assert (width, height) == (64, 64)


# --------------------------------------------------------------------------- #
# metadata
# --------------------------------------------------------------------------- #
def test_the_metadata_has_every_required_field(tmp_path, monkeypatch):
    data = _metadata(tmp_path, monkeypatch)
    for key in REQUIRED:
        assert key in data, key
    assert data["type"] == "plugin"
    assert data["license"] in LICENSES
    assert len(data["description"]) <= DESCRIPTION_MAX
    assert re.match(IDENTIFIER_PATTERN, data["identifier"])


def test_the_version_entry_matches_the_schema(tmp_path, monkeypatch):
    data = _metadata(tmp_path, monkeypatch)
    assert len(data["versions"]) == 1
    version = data["versions"][0]
    assert version["version"] == packager.plugin_version()
    assert version["status"] in STATUSES
    assert re.match(KICAD_VERSION_PATTERN, version["kicad_version"])
    # The archive declares exactly the OSes whose solver is inside it, so PCM
    # refuses it anywhere it could not simulate.
    assert version["platforms"] == packager.platforms_of(EVERY)
    assert set(version["platforms"]) <= PLATFORM_NAMES


def test_the_metadata_in_the_archive_claims_no_download(tmp_path, monkeypatch):
    # The download_* keys describe an archive sitting on a server. Inside the
    # archive they describe, they would be a hash of something that does not
    # exist yet -- the spec says they belong only to the repository's copy.
    data = _metadata(tmp_path, monkeypatch)
    assert not [key for key in data["versions"][0] if key.startswith("download_")]
    assert "install_size" not in data["versions"][0]


def test_the_project_is_named_once(tmp_path, monkeypatch):
    # Both the package's metadata and the About page's link read the same
    # manifest, so they can never point at different projects.
    links = install.load_plugin_module("emkit", "links.py")
    data = _metadata(tmp_path, monkeypatch)
    assert data["resources"]["homepage"] == links.GITHUB_URL
    assert data["author"]["contact"]["web"] == links.GITHUB_URL


def test_the_identifier_survives_kicads_rename(tmp_path, monkeypatch):
    # KiCad extracts to a directory named for the identifier with dots turned
    # into underscores, then imports it. Dots would make Python read the name
    # as a submodule path, so what is left has to be a name importlib can
    # actually import.
    installed = pcm.PRODUCT.PCM_ID.replace(".", "_")
    assert "." not in installed
    assert installed.isascii() and " " not in installed
    assert installed[0].isalpha()


# --------------------------------------------------------------------------- #
# the invariant the rename depends on
# --------------------------------------------------------------------------- #
def _self_imports(path):
    """Absolute imports of the plugin by name, found in *path*'s source."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == install.PRODUCT.PACKAGE:
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which is what this asks for.
            if node.level == 0 and node.module:
                if node.module.split(".")[0] == install.PRODUCT.PACKAGE:
                    yield node.module


def test_the_plugin_never_imports_itself_by_name():
    # Installed by PCM the package is called com_github_..., not
    # antenna_plugin, so an absolute self-import would raise ImportError there
    # while working from every other install route.
    offenders = {}
    for path in sorted(install.SOURCE.rglob("*.py")):
        found = sorted(set(_self_imports(path)))
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert offenders == {}, f"use a relative import instead: {offenders}"


def test_the_payload_matches_what_the_checkout_installs(tmp_path, monkeypatch):
    # The two ways the plugin reaches a KiCad -- this package, and `make
    # install` from a checkout (tools/install.py) -- have to put the same tree
    # there. They may differ in the directory's name, never in what the plugin
    # itself is. They no longer differ in the binaries either: both carry every
    # shipped build, because any host may run its solver in a container and the
    # container's build is not the host's.
    packaged = _staged(tmp_path, monkeypatch, packager.requested(None)) / "plugins"

    dest_root = tmp_path / "kicad-plugins"
    dest_root.mkdir()
    install.cmd_install(dest_root)
    installed = dest_root / install.PRODUCT.PACKAGE

    def tree(root):
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    assert tree(packaged) == tree(installed)


def test_no_python_and_no_installer_script_ship_in_the_package(tmp_path, monkeypatch):
    # PCM's whole point here is that the user's machine is not asked for
    # anything: KiCad does the copying, so nothing in the archive is meant to
    # be run *to install it*.
    #
    # The container's entrypoint is the one script that ships, and it is the
    # exception that proves the rule: it never runs on the user's machine at
    # all. It is copied into an image at `docker build` and executed inside a
    # container, which is exactly why it is excused here by name rather than by
    # loosening the check -- the next .sh to appear in a payload should still
    # have to argue for itself.
    names = _zipped(tmp_path, monkeypatch).namelist()
    scripts = [n for n in names if n.endswith((".ps1", ".bat", ".sh"))]
    assert scripts == ["plugins/emkit/sim/container/entrypoint.sh"]
    assert not [n for n in names if pathlib.PurePosixPath(n).name == "install.py"]


def test_the_container_recipe_ships(tmp_path, monkeypatch):
    # A feature whose recipe did not ship fails only on the user's machine, and
    # invisibly here: the Dockerfile and the entrypoint are not .py files, so
    # nothing else about the payload would notice their absence.
    names = _zipped(tmp_path, monkeypatch).namelist()
    for wanted in (
        "plugins/emkit/sim/container/Dockerfile",
        "plugins/emkit/sim/container/entrypoint.sh",
    ):
        assert wanted in names


# --------------------------------------------------------------------------- #
# choosing between the bundled solvers
# --------------------------------------------------------------------------- #
def test_the_package_is_named_for_covering_everything(tmp_path, monkeypatch):
    # No OS in the name when it carries them all -- that is the whole point of
    # one add-on. A narrowed build says which, so it can't overwrite the real
    # release in dist/.
    version = packager.plugin_version()
    stem = install.PRODUCT.NAME.replace(" ", "")
    assert packager.pcm_name(EVERY) == f"{stem}-{version}-pcm"
    assert packager.pcm_name([WINDOWS]) == f"{stem}-{version}-windows-pcm"
    # An architecture never reaches the name, for the same reason it never
    # reaches the metadata: PCM cannot act on one.
    assert packager.pcm_name([LINUX_AARCH64]) == f"{stem}-{version}-linux-pcm"


def test_the_plugin_picks_its_own_machines_build_from_the_four(tmp_path, monkeypatch):
    # The one thing the fat package moves onto the plugin: with every build
    # sitting under binaries/, it has to reach for its own -- and the two Linux
    # ones make that an architecture question, not just an OS one. Launching
    # the wrong build is an OSError at the first simulation, long after the
    # install looked fine.
    simulate = _load_simulate()
    payload = _staged(tmp_path, monkeypatch) / "plugins"

    for system, machine, build in (
        ("win32", "AMD64", WINDOWS),
        ("linux", "x86_64", LINUX_X86_64),
        ("linux", "aarch64", LINUX_AARCH64),
        ("darwin", "arm64", builds.MACOS),
    ):
        monkeypatch.setattr(builds.sys, "platform", system)
        monkeypatch.setattr(builds.platform, "machine", lambda m=machine: m)
        assert simulate._find_exe(payload).name == name(build)


def test_another_machines_build_still_answers_when_it_is_the_only_one(
    tmp_path, monkeypatch
):
    # The narrowed package, or a checkout under WSL: only the .exe is there,
    # and on POSIX that is still a real find (the interop layer runs it), so
    # the fallback must not be lost to the choice above.
    simulate = _load_simulate()
    payload = _staged(tmp_path, monkeypatch, [WINDOWS]) / "plugins"

    monkeypatch.setattr(builds.sys, "platform", "linux")
    monkeypatch.setattr(builds.platform, "machine", lambda: "x86_64")
    assert simulate._find_exe(payload).name == name(WINDOWS)


def test_locate_finds_the_solver_from_inside_the_installed_package(
    tmp_path, monkeypatch
):
    # End to end, the way KiCad leaves it: locate() walks up from the module's
    # own file, so the binary is found under whatever name the package was
    # installed as -- which for PCM is never "antenna_plugin".
    payload = _staged(tmp_path, monkeypatch) / "plugins"
    installed = tmp_path / "3rdparty" / "plugins" / pcm.PRODUCT.PCM_ID.replace(".", "_")
    installed.parent.mkdir(parents=True, exist_ok=True)
    payload.rename(installed)

    simulate = _load_simulate(installed / "sim" / "simulate.py")
    monkeypatch.delenv("ANTENNA_SIM_ROOT", raising=False)
    exe, root = simulate.locate()
    assert pathlib.Path(root) == installed
    assert pathlib.Path(exe).parent == installed / "binaries"
