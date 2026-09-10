"""Unit tests for tools/install.py -- the *checkout's* installer, the one
behind ``make install``, which copies the plugin straight into a KiCad on this
machine.

Loaded by path: the tools are scripts, not an importable package.

What it shares with the redistributable package is the answer to "what is an
install made of", which is why make_package borrows this module's constants
and is checked here for the parts that are not about the package's own
format. The format itself -- the KiCad add-on, the only thing shipped -- is
tests/test_pcm.py.
"""

import os
import pathlib
import shutil
import sys

import solver_bytes
from tools_module import load

install = load("install")
packager = load("make_package")

builds = packager.builds
WINDOWS = builds.WINDOWS
LINUX_X86_64 = builds.LINUX_X86_64
LINUX_AARCH64 = builds.LINUX_AARCH64
MACOS = builds.MACOS

# This product's solver stem. Read off the manifest, not spelled out: these
# tests run in every assembled product, and which binary a plugin drives is
# exactly the thing that differs between two of them. The per-machine names
# come off the build table for the same reason.
STEM = install.PRODUCT.BINARY


def name(build):
    return build.filename(STEM)


def _kicad_tree(base, versions):
    for version in versions:
        (base / version / "scripting" / "plugins").mkdir(parents=True)
    return base


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #
def test_versions_sort_numerically_not_lexically(tmp_path):
    _kicad_tree(tmp_path, ["8.0", "9.0", "10.0"])
    # "10.0" sorts before "9.0" as text; the newest KiCad is 10.0.
    assert install.list_versions(tmp_path) == ["8.0", "9.0", "10.0"]
    assert install.detect_version(tmp_path) == "10.0"


def test_non_version_directories_are_ignored(tmp_path):
    _kicad_tree(tmp_path, ["9.0"])
    (tmp_path / "templates").mkdir()
    (tmp_path / "9").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    assert install.list_versions(tmp_path) == ["9.0"]


def test_missing_base_detects_nothing(tmp_path):
    assert install.list_versions(tmp_path / "nope") == []
    assert install.detect_version(tmp_path / "nope") is None


def test_targets_report_each_kicad_and_whether_installed(tmp_path):
    _kicad_tree(tmp_path, ["9.0", "10.0"])
    (tmp_path / "9.0" / "scripting" / "plugins" / install.PRODUCT.PACKAGE).mkdir()

    targets = install.list_targets(tmp_path)

    assert [t["version"] for t in targets] == ["9.0", "10.0"]
    assert targets[0]["installed"] is True
    assert targets[1]["installed"] is False
    assert targets[0]["plugin_dir"] == str(tmp_path / "9.0" / "scripting" / "plugins")


def test_targets_of_a_machine_without_kicad_is_empty(tmp_path):
    assert install.list_targets(tmp_path) == []


# --------------------------------------------------------------------------- #
# where an install lands
# --------------------------------------------------------------------------- #
def test_windows_documents_dir_is_overridable(monkeypatch, tmp_path):
    # Documents is not always under the profile -- OneDrive moves it -- so the
    # detected base has to be overridable.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("KICAD_DOCUMENTS_DIR", str(tmp_path / "OneDrive" / "KiCad"))
    assert install.plugin_base() == tmp_path / "OneDrive" / "KiCad"


def test_windows_documents_dir_defaults_under_the_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("KICAD_DOCUMENTS_DIR", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    assert install.plugin_base() == tmp_path / "Documents" / "KiCad"


def test_a_named_version_wins_over_detection(tmp_path, monkeypatch):
    _kicad_tree(tmp_path, ["9.0", "10.0"])
    monkeypatch.setattr(install, "plugin_base", lambda: tmp_path)
    # `make install KICAD_VER=9.0` names a version, not a path.
    resolved = install.resolve_plugin_dir("9.0", None)
    assert resolved == tmp_path / "9.0" / "scripting" / "plugins"


def test_an_explicit_directory_skips_detection(tmp_path):
    resolved = install.resolve_plugin_dir(None, str(tmp_path / "somewhere"))
    assert resolved == tmp_path / "somewhere"


# --------------------------------------------------------------------------- #
# which solver gets bundled
# --------------------------------------------------------------------------- #
def test_the_bundled_binary_names_come_from_the_plugin_itself():
    # Not a second copy of the convention: the installer asks sim/builds.py,
    # the same module simulate.locate() asks at run time -- so the name it
    # bundles under and the name the plugin then reaches for cannot differ.
    names = install.host_build_names()
    assert set(names) <= {name(build) for build in builds.BUILDS}
    assert names[0] == name(builds.host_build())


def test_every_shipped_build_is_bundled(tmp_path, monkeypatch):
    # Not just this machine's, and that is the container's doing: a run may
    # happen natively or inside a Linux container whose architecture is the
    # daemon's, so an install that carried one build would leave the container
    # with nothing to mount.
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    solver_bytes.populate(tmp_path, STEM, builds.BUILDS)
    assert install.select_binaries() == [
        tmp_path / name(build) for build in builds.shipped_builds()
    ]


def test_a_build_that_is_not_in_the_checkout_is_skipped(tmp_path, monkeypatch):
    # A developer with one build compiled can still install; what they get is
    # what is there.
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    solver_bytes.populate(tmp_path, STEM, [WINDOWS])
    assert install.select_binaries() == [tmp_path / name(WINDOWS)]


def test_the_retired_build_is_not_bundled_even_when_it_is_there(tmp_path, monkeypatch):
    # macOS ships no solver: a leftover file under binaries/ is not a reason to
    # start carrying one again.
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    solver_bytes.populate(tmp_path, STEM, [MACOS, WINDOWS])
    assert install.select_binaries() == [tmp_path / name(WINDOWS)]


def test_installing_without_any_build_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    try:
        install.select_binaries()
        raise AssertionError("expected a refusal")
    except SystemExit as exit_error:
        # The machine's own build is the one to go and fetch, so it is the one
        # the message names.
        assert install.host_build_names()[0] in str(exit_error)


def test_bundling_copies_runnable_binaries(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    solver_bytes.populate(binaries, STEM, builds.BUILDS)
    monkeypatch.setattr(install, "BINARIES_DIR", binaries)

    dest = tmp_path / "installed"
    dest.mkdir()
    install.bundle_binary(dest)

    staged = sorted(p.name for p in (dest / "binaries").iterdir())
    assert staged == sorted(name(build) for build in builds.shipped_builds())
    for build in builds.shipped_builds():
        assert (dest / "binaries" / name(build)).stat().st_mode & 0o111


# --------------------------------------------------------------------------- #
# what the packager takes from here
#
# The package's own shape is tests/test_pcm.py. What is left below is the part
# that would be just as true of any format: which solver build goes in, and
# where the version comes from.
# --------------------------------------------------------------------------- #
def _binaries_dir(tmp_path, monkeypatch, wanted=None):
    """A stand-in binaries/ holding this product's builds, named off the build
    table rather than spelled out: the core's tests run in every assembled
    product, and which solver it drives is the manifest's answer
    (product.BINARY)."""
    binaries = tmp_path / "bin"
    solver_bytes.populate(binaries, STEM, builds.BUILDS if wanted is None else wanted)
    monkeypatch.setattr(install, "BINARIES_DIR", binaries)
    return binaries


def test_a_bare_run_covers_every_shipped_build(tmp_path, monkeypatch):
    # One package for every machine is the point of it, so that is what naming
    # nothing means -- and it must not depend on which OS the build runs on.
    assert packager.requested(None) == builds.shipped_builds()
    # An OS is what can be named, and Linux is one name for two builds.
    assert packager.requested("linux") == [LINUX_X86_64, LINUX_AARCH64]
    monkeypatch.setattr(packager.sys, "platform", "darwin")
    assert packager.requested(None) == builds.shipped_builds()


def test_narrowing_to_an_os_with_no_build_is_refused(tmp_path, monkeypatch):
    # A macOS package would carry no binaries at all. What serves a Mac is a
    # package with the Linux builds in it, which its container runs.
    try:
        packager.requested("macos")
        raise AssertionError("expected a refusal")
    except SystemExit as exit_error:
        assert "macos" in str(exit_error)


def test_the_metadata_names_an_os_however_many_builds_it_took(tmp_path, monkeypatch):
    # PCM's platforms are operating systems and nothing finer, so the two Linux
    # builds have to collapse to one name -- and to exactly one, not two.
    assert packager.platforms_of(builds.shipped_builds()) == [
        "linux",
        "macos",
        "windows",
    ]
    assert packager.platforms_of([LINUX_X86_64, LINUX_AARCH64]) == ["linux", "macos"]
    assert packager.platforms_of([WINDOWS]) == ["windows"]


def test_the_metadata_still_names_the_os_that_has_no_build():
    # The trap this whole split exists for: derive the platforms from the
    # payload's builds and a package stops declaring macOS, at which point PCM
    # refuses to install the plugin on every Mac -- where everything but the
    # solve runs.
    assert "macos" in packager.platforms_of(builds.shipped_builds())
    assert MACOS not in packager.requested(None)


def test_a_missing_build_stops_the_run_before_anything_is_staged(tmp_path, monkeypatch):
    # One archive is every machine, so a missing build must stop it rather
    # than ship a package that installs where it cannot simulate.
    _binaries_dir(tmp_path, monkeypatch, [LINUX_X86_64])
    staged = []
    monkeypatch.setattr(packager, "stage_pcm", lambda d, ps: staged.append(d))

    try:
        packager.main(["--out-dir", str(tmp_path / "dist")])
        raise AssertionError("expected a refusal")
    except SystemExit as exit_error:
        assert name(LINUX_AARCH64) in str(exit_error)
    assert staged == []


def test_a_wrong_os_binary_is_refused(tmp_path, monkeypatch):
    # A build for another OS would install fine and fail at the first
    # simulation, so the package build has to catch it.
    binaries = _binaries_dir(tmp_path, monkeypatch, [])
    for build, impostor in ((WINDOWS, MACOS), (MACOS, WINDOWS)):
        (binaries / name(build)).write_bytes(solver_bytes.header(impostor))
        try:
            packager.check_binary(build)
            raise AssertionError(f"expected a refusal for {build.tag}")
        except SystemExit as exit_error:
            assert build.magic_name in str(exit_error)


def test_the_wrong_linux_build_is_refused_too(tmp_path, monkeypatch):
    # The one a magic number cannot catch, and the reason the check reads the
    # ELF header: both Linux builds start with \x7fELF, so an AArch64 solver
    # filed as the x86-64 one would package silently and be an "Exec format
    # error" on the first user's machine.
    binaries = _binaries_dir(tmp_path, monkeypatch, [])
    (binaries / name(LINUX_X86_64)).write_bytes(solver_bytes.header(LINUX_AARCH64))
    try:
        packager.check_binary(LINUX_X86_64)
        raise AssertionError("expected a refusal")
    except SystemExit as exit_error:
        assert "AArch64" in str(exit_error)


def test_a_missing_binary_is_refused(tmp_path, monkeypatch):
    _binaries_dir(tmp_path, monkeypatch, [])
    for build in builds.BUILDS:
        try:
            packager.check_binary(build)
            raise AssertionError(f"expected a refusal for {build.tag}")
        except SystemExit as exit_error:
            assert "not found" in str(exit_error)


def test_each_build_takes_its_own_machines_binary(tmp_path, monkeypatch):
    binaries = _binaries_dir(tmp_path, monkeypatch)
    for build in builds.BUILDS:
        assert packager.check_binary(build) == binaries / name(build)


def test_the_plugin_version_is_read_not_imported():
    # antenna_plugin/__init__.py imports pcbnew, so the packager must not
    # import it to learn the version.
    assert packager.plugin_version().count(".") == 2


# --------------------------------------------------------------------------- #
# The command line's shortcut points at an install, which is a copy, and a
# copy can be older than the checkout that made it. _newest_py is how that is
# noticed -- and it only works because every copy on the way is copy2's.
# --------------------------------------------------------------------------- #
def _tree(root, mtime):
    root.mkdir(parents=True)
    module = root / "thing.py"
    module.write_text("x = 1\n")
    os.utime(module, (mtime, mtime))
    return root


def test_a_checkout_edited_since_the_install_reads_newer(tmp_path):
    installed = _tree(tmp_path / "installed", 1_000_000)
    checkout = _tree(tmp_path / "checkout", 2_000_000)
    assert install._newest_py(checkout) > install._newest_py(installed)


def test_a_fresh_install_reads_the_same_age_as_its_checkout(tmp_path):
    checkout = _tree(tmp_path / "checkout", 2_000_000)
    installed = tmp_path / "installed"
    shutil.copytree(checkout, installed)
    assert install._newest_py(installed) == install._newest_py(checkout)


def test_a_tree_with_no_python_in_it_is_the_oldest_thing_there_is(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert install._newest_py(empty) == 0.0
