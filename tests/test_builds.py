"""Which build of the solver belongs to which machine (emkit.sim.builds).

Three builds ship in one package and the plugin picks one at startup, so every
answer here is one a user's machine depends on and no test machine can check by
running it: the choice is driven with a stated ``sys.platform`` and
``platform.machine()`` rather than with this box's own, which is the only way
the three machines this one is not get tested at all.

Three failures are worth naming, because each produces a plugin that installs
perfectly and dies at the first simulation:

- **the wrong architecture.** Two Linux builds sit side by side under one
  ``binaries/`` and share a magic number, so neither the file name nor the
  first four bytes separate them -- only the machine in the ELF header does.
- **a build for another OS.** Cheaper to catch, and caught at build time
  (:func:`verify`) rather than by launching it.
- **a build for an OS that no longer has one.** macOS ships no solver -- there
  it runs in a container -- while a Mac install still carries the Linux builds
  for that container to mount. So "the machine has no build of its own" and
  "there are builds sitting right there" are both true at once, and anything
  that resolved the tension by handing the Mac an ELF would be an "Exec format
  error" nobody can read.

    python3 tests/test_builds.py   (or pytest)
"""

from bare_package import load

builds = load("emkit.sim.builds")

X86 = builds.LINUX_X86_64
ARM = builds.LINUX_AARCH64
MAC = builds.MACOS
WIN = builds.WINDOWS

STEM = "monopole"  # any stem; the table never names one


# --------------------------------------------------------------------------- #
# the table
# --------------------------------------------------------------------------- #
def test_every_build_is_named_for_the_machine_it_is_for():
    # The tag is in the file name because a name does not travel with its
    # directory: four builds share one binaries/, and an untagged name would be
    # one file for four machine codes.
    assert X86.filename(STEM) == "monopole-linux-x86_64"
    assert ARM.filename(STEM) == "monopole-linux-aarch64"
    assert MAC.filename(STEM) == "monopole-macos"
    assert WIN.filename(STEM) == "monopole-windows.exe"


def test_the_names_are_all_different():
    # The property the tags exist for, stated once over the whole table so a
    # fifth build cannot quietly collide with one of these four.
    names = [build.filename(STEM) for build in builds.BUILDS]
    assert len(set(names)) == len(builds.BUILDS)


def test_an_os_is_one_name_however_many_builds_it_has():
    # What a package's metadata can say. PCM has no way to tell two builds of
    # the same OS apart, so Linux is one platform and two files.
    assert builds.os_keys() == ["linux", "macos", "windows"]
    assert builds.for_os("linux") == [X86, ARM]
    assert builds.for_os("macos") == [MAC]


# --------------------------------------------------------------------------- #
# supported, and shipped
# --------------------------------------------------------------------------- #
def test_macos_is_supported_and_has_no_build():
    # The distinction the table exists to hold. Dropping the row would be the
    # tidier-looking change and would make PCM refuse to install the plugin on
    # every Mac -- where the window, the board and the markers all work.
    assert MAC in builds.BUILDS
    assert MAC not in builds.shipped_builds()
    assert builds.shipped_builds() == [X86, ARM, WIN]
    assert "macos" in builds.os_keys()


def test_a_payload_of_linux_builds_serves_the_os_that_has_none():
    # What the metadata says, and why: a Mac is served by the container, and
    # the container runs the Linux build the package already carries.
    assert builds.platforms_served([X86, ARM, WIN]) == ["linux", "macos", "windows"]
    assert builds.platforms_served([X86]) == ["linux", "macos"]


def test_a_payload_without_a_linux_build_does_not_serve_it():
    # The half that is easy to get wrong by always adding the name: a
    # Windows-only package cannot serve a Mac, because the Mac's container
    # would have nothing to mount.
    assert builds.platforms_served([WIN]) == ["windows"]


def test_a_machine_whose_os_ships_nothing_says_so():
    # Which sentence a caller says when it finds no binary: "reinstall" or
    # "this OS runs the solver in a container".
    assert builds.host_ships("linux", "x86_64")
    assert builds.host_ships("win32", "AMD64")
    assert not builds.host_ships("darwin", "arm64")


def test_a_build_is_found_by_its_tag():
    assert builds.by_tag("linux-aarch64") is ARM
    assert builds.by_tag("linux") is None  # an OS is not a build


# --------------------------------------------------------------------------- #
# choosing one
# --------------------------------------------------------------------------- #
def test_each_machine_gets_its_own_build():
    for system, machine, expected in (
        ("linux", "x86_64", X86),
        ("linux", "aarch64", ARM),
        ("darwin", "arm64", MAC),
        ("darwin", "x86_64", MAC),  # one macOS build; the machine cannot choose
        ("win32", "AMD64", WIN),
        ("win32", "ARM64", WIN),
        ("cygwin", "x86_64", WIN),  # a POSIX layer on Windows is still Windows
    ):
        assert builds.host_build(system, machine) is expected, (system, machine)


def test_the_architecture_decides_between_the_two_linux_builds():
    # The severe one. Both are ELF, both are called <stem>-linux-*, and an
    # x86-64 solver on an AArch64 box is an "Exec format error" -- so the
    # machine, not the OS, has to be what picks.
    assert builds.candidates(STEM, "linux", "aarch64")[0] == "monopole-linux-aarch64"
    assert builds.candidates(STEM, "linux", "x86_64")[0] == "monopole-linux-x86_64"


def test_the_machine_is_read_case_insensitively():
    # The same architecture answers "x86_64" on Linux and "AMD64" on Windows,
    # and Windows' own arm is "ARM64" where Linux says "aarch64".
    assert builds.host_build("linux", "X86_64") is X86
    assert builds.host_build("linux", "ARM64") is ARM


def test_a_machine_nothing_was_built_for_gets_no_build():
    # Not a refusal and not a wrong answer: 32-bit Linux and RISC-V are real
    # machines with no solver, and handing one an x86-64 ELF would be worse
    # than finding nothing.
    assert builds.host_build("linux", "riscv64") is None
    assert builds.host_os("linux") == "linux"


def test_an_os_nothing_was_built_for_is_no_os():
    assert builds.host_os("aix") is None
    assert builds.host_build("aix", "ppc64") is None


def test_this_machines_build_comes_first_and_the_rest_follow():
    # The tail is a deliberate fallback: a checkout or a narrowed package may
    # hold only one build, and finding another machine's beats reporting no
    # binary at all -- under WSL a .exe genuinely runs. Same OS before other
    # OSes, since that is the likelier of the two to work.
    assert builds.order("linux", "x86_64") == [X86, ARM, WIN]


def test_the_fallback_never_offers_a_build_that_cannot_run():
    # The one crossing that works is a .exe under WSL. An ELF on macOS is an
    # "Exec format error", so a Mac -- which carries the Linux builds for its
    # container -- is offered nothing to launch itself, which is the truth.
    assert builds.order("darwin", "arm64") == [MAC]
    assert X86.runs_on("linux") and WIN.runs_on("linux")
    assert not X86.runs_on("macos")
    assert not MAC.runs_on("linux")


def test_a_machine_with_none_of_its_own_is_still_offered_its_os_and_wsl():
    order = builds.order("linux", "riscv64")
    assert order == [X86, ARM, WIN]  # its own OS's first, even unusable


def test_the_default_is_this_machine():
    assert builds.host_build() is builds.host_build(None, None)
    assert builds.candidates(STEM)[0] == builds.order()[0].filename(STEM)


# --------------------------------------------------------------------------- #
# the machine inside a container
# --------------------------------------------------------------------------- #
def test_the_container_runs_a_linux_build_whatever_the_host_is():
    # The daemon's architecture, not this machine's: Docker Desktop on an
    # Apple Silicon Mac runs arm64 images, and the host there has no build at
    # all for host_build to have answered with.
    assert builds.container_build("amd64") is X86
    assert builds.container_build("arm64") is ARM


def test_the_container_arch_is_read_in_either_vocabulary():
    # Go's spellings (what `docker version` answers) and the kernel's (what
    # `uname -m` inside the container answers) are different words.
    assert builds.container_build("x86_64") is X86
    assert builds.container_build("aarch64") is ARM
    assert builds.container_build(" ARM64 ") is ARM


def test_a_container_architecture_nothing_is_built_for_gets_no_build():
    # A sentence for the caller to say, not a build to guess at.
    assert builds.container_build("riscv64") is None
    assert builds.container_build("") is None
    assert builds.container_build(None) is None


# --------------------------------------------------------------------------- #
# is this file really that build?
# --------------------------------------------------------------------------- #
def _elf(machine, endian=1):
    body = bytearray(b"\x7fELF" + bytes(60))
    body[4] = 2
    body[5] = endian
    body[18:20] = machine.to_bytes(2, "little" if endian == 1 else "big")
    return bytes(body)


def test_a_build_passes_as_itself():
    assert builds.verify(X86, _elf(builds.EM_X86_64)) is None
    assert builds.verify(ARM, _elf(builds.EM_AARCH64)) is None
    assert builds.verify(WIN, b"MZ\x90\x00") is None
    assert builds.verify(MAC, b"\xcf\xfa\xed\xfe" + bytes(16)) is None


def test_a_universal_macos_binary_is_still_a_macos_binary():
    # A build made for both Apple architectures is a fat archive with its own
    # magic; refusing it would refuse the most portable build there is.
    assert builds.verify(MAC, b"\xca\xfe\xba\xbe" + bytes(16)) is None


def test_a_big_endian_elf_is_read_in_its_own_byte_order():
    # e_machine is two bytes in the file's order, and byte 5 is what says
    # which. Read little-endian regardless, an AArch64 build would answer
    # 0xb700 and be refused as some unknown machine.
    assert builds.verify(ARM, _elf(builds.EM_AARCH64, endian=2)) is None


def test_the_wrong_os_build_is_caught():
    assert "Windows executable" in builds.verify(WIN, _elf(builds.EM_X86_64))
    assert "Linux (ELF) executable" in builds.verify(X86, b"MZ\x90\x00")


def test_the_wrong_linux_build_is_caught():
    # The whole reason the header is read past its magic number.
    assert "AArch64" in builds.verify(X86, _elf(builds.EM_AARCH64))
    assert "x86-64" in builds.verify(ARM, _elf(builds.EM_X86_64))


def test_a_machine_the_table_cannot_name_is_still_refused():
    # An ELF for something nobody listed is not this build, and saying which
    # number it was beats saying nothing.
    complaint = builds.verify(X86, _elf(0x28))  # ARM (32-bit)
    assert "0x28" in complaint


def test_a_truncated_file_is_a_complaint_and_not_an_exception():
    assert builds.verify(X86, b"\x7fELF") is not None
    assert builds.verify(X86, b"") is not None


def test_a_checked_file_names_itself(tmp_path):
    # What the packager and the sync print: the complaint has to say which
    # file, since both are looking at a directory full of them.
    good = tmp_path / X86.filename(STEM)
    good.write_bytes(_elf(builds.EM_X86_64))
    assert builds.check(X86, good) is None

    bad = tmp_path / ARM.filename(STEM)
    bad.write_bytes(_elf(builds.EM_X86_64))
    assert str(bad) in builds.check(ARM, bad)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            with tempfile.TemporaryDirectory() as directory:
                fn(Path(directory)) if fn.__code__.co_argcount else fn()
            print(f"ok {name}")
