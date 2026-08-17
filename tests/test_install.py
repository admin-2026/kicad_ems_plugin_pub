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
import sys

from tools_module import load

install = load("install")
packager = load("make_package")

WINDOWS = packager.WINDOWS
LINUX = packager.LINUX

# Enough of each build for the header check; the packager never runs them.
FAKE_EXE = b"MZ\x90\x00"
FAKE_ELF = b"\x7fELF\x02\x01\x01" + bytes(11) + b"\x3e\x00"  # e_machine = x86-64


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
    (tmp_path / "9.0" / "scripting" / "plugins" / install.PLUGIN_NAME).mkdir()

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
def test_the_bundled_binary_names_come_from_the_plugin_itself(monkeypatch):
    # Not a second copy of the convention: the installer asks sim/hostos.py,
    # the same module simulate.locate() asks at run time.
    names = install.host_exe_names()
    assert set(names) == {"monopole", "monopole.exe"}
    assert names[0] == ("monopole.exe" if os.name == "nt" else "monopole")


def test_this_os_build_is_the_one_bundled(tmp_path, monkeypatch):
    # binaries/ holds a build per OS. Installing has to take this machine's,
    # not whichever sorts first.
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    monkeypatch.setattr(install, "host_exe_names", lambda: ("monopole", "monopole.exe"))
    (tmp_path / "monopole").write_bytes(FAKE_ELF)
    (tmp_path / "monopole.exe").write_bytes(FAKE_EXE)
    assert install.select_binary() == tmp_path / "monopole"


def test_the_other_os_build_is_bundled_when_it_is_the_only_one(tmp_path, monkeypatch):
    # A .exe is a real find on POSIX -- under WSL it runs through the interop
    # layer -- so the second name is a fallback, not a refusal.
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    monkeypatch.setattr(install, "host_exe_names", lambda: ("monopole", "monopole.exe"))
    (tmp_path / "monopole.exe").write_bytes(FAKE_EXE)
    assert install.select_binary() == tmp_path / "monopole.exe"


def test_installing_without_any_build_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "BINARIES_DIR", tmp_path)
    try:
        install.select_binary()
        raise AssertionError("expected a refusal")
    except SystemExit as exit_error:
        assert "not found" in str(exit_error)


def test_bundling_copies_exactly_one_runnable_binary(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "monopole").write_bytes(FAKE_ELF)
    (binaries / "monopole.exe").write_bytes(FAKE_EXE)
    monkeypatch.setattr(install, "BINARIES_DIR", binaries)
    monkeypatch.setattr(install, "host_exe_names", lambda: ("monopole", "monopole.exe"))

    dest = tmp_path / "installed"
    dest.mkdir()
    install.bundle_binary(dest)

    staged = sorted(p.name for p in (dest / "binaries").iterdir())
    assert staged == ["monopole"]  # the other OS's build is dead weight
    assert (dest / "binaries" / "monopole").stat().st_mode & 0o111


# --------------------------------------------------------------------------- #
# what the packager takes from here
#
# The package's own shape is tests/test_pcm.py. What is left below is the part
# that would be just as true of any format: which solver build goes in, and
# where the version comes from.
# --------------------------------------------------------------------------- #
def _binaries_dir(tmp_path, monkeypatch, **builds):
    """A stand-in binaries/ holding the named builds."""
    binaries = tmp_path / "bin"
    binaries.mkdir(exist_ok=True)
    for name, content in builds.items():
        (binaries / name.replace("_exe", ".exe")).write_bytes(content)
    monkeypatch.setattr(install, "BINARIES_DIR", binaries)
    return binaries


def test_a_bare_run_covers_every_platform(tmp_path, monkeypatch):
    # One package for all of them is the point of it, so that is what naming
    # nothing means -- and it must not depend on which OS the build runs on.
    assert packager.requested(None) == [WINDOWS, LINUX]
    assert packager.requested("linux") == [LINUX]
    monkeypatch.setattr(packager.sys, "platform", "darwin")
    assert packager.requested(None) == [WINDOWS, LINUX]


def test_a_missing_build_stops_the_run_before_anything_is_staged(tmp_path, monkeypatch):
    # One archive is every platform, so a missing build must stop it rather
    # than ship a package that installs where it cannot simulate.
    _binaries_dir(tmp_path, monkeypatch, monopole=FAKE_ELF)
    staged = []
    monkeypatch.setattr(packager, "stage_pcm", lambda d, ps: staged.append(d))

    try:
        packager.main(["--out-dir", str(tmp_path / "dist")])
        raise AssertionError("expected a refusal")
    except SystemExit as exit_error:
        assert "monopole.exe" in str(exit_error)
    assert staged == []


def test_a_wrong_os_binary_is_refused(tmp_path, monkeypatch):
    # A build for the other OS would install fine and fail at the first
    # simulation, so the package build has to catch it.
    _binaries_dir(tmp_path, monkeypatch, monopole=FAKE_EXE, monopole_exe=FAKE_ELF)
    for platform in (WINDOWS, LINUX):
        try:
            packager.check_binary(platform)
            raise AssertionError(f"expected a refusal for {platform.key}")
        except SystemExit as exit_error:
            assert platform.magic_name in str(exit_error)


def test_a_missing_binary_is_refused(tmp_path, monkeypatch):
    _binaries_dir(tmp_path, monkeypatch)
    for platform in (WINDOWS, LINUX):
        try:
            packager.check_binary(platform)
            raise AssertionError(f"expected a refusal for {platform.key}")
        except SystemExit as exit_error:
            assert "not found" in str(exit_error)


def test_each_platform_takes_its_own_os_build(tmp_path, monkeypatch):
    binaries = _binaries_dir(
        tmp_path, monkeypatch, monopole=FAKE_ELF, monopole_exe=FAKE_EXE
    )
    assert packager.check_binary(WINDOWS) == binaries / "monopole.exe"
    assert packager.check_binary(LINUX) == binaries / "monopole"


def test_the_plugin_version_is_read_not_imported():
    # antenna_plugin/__init__.py imports pcbnew, so the packager must not
    # import it to learn the version.
    assert packager.plugin_version().count(".") == 2
