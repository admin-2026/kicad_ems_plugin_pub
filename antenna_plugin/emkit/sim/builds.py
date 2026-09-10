"""Which build of the bundled solver belongs to which machine.

The solver is a compiled program, so an install carries one file per machine it
may be started on. This module is the list of them. What each build is called,
whose machine it is for, and how to tell one from another by its first bytes
are one table here because four separate places need the same answer, and any
two of them disagreeing is a plugin that installs cleanly and then fails at the
first simulation:

    sim/simulate.py        which file a run launches (``_find_exe``)
    tools/install.py       which builds ``make install`` bundles
    tools/make_package.py  which builds a release carries, and the header check
    tools/binary_sync.py   which builds are copied out of the simulator's tree

**Supported and shipped are different questions, and this table answers both.**
There are four builds, and one of them -- macOS -- is no longer produced: on
that OS the solver runs inside a container, which is Linux, so what a Mac
actually launches is the Linux build for the container's architecture. The
macOS entry stays in the table because macOS is still an operating system this
plugin *supports* (the window, the board, the markers all run there, and a
package that stopped saying so would be refused by the Plugin and Content
Manager on every Mac) -- it is marked ``shipped=False``, and everything that
walks the payload walks :func:`shipped_builds` instead. ``os_keys`` is the
supported list and deliberately still names macOS.

**The tag is in the file name.** The simulator's own build writes
``<stem>-<tag><exe>`` -- ``monopole-linux-aarch64``, ``monopole-windows.exe``
-- and the plugin keeps that name rather than renaming on the way in. A name
does not travel with its directory: copy two machines' builds into one
``binaries/`` under an untagged name and it is one file name for two machine
codes, whichever landed last being the one that runs (or, worse, fails to).
Tagged, a file found on a user's machine says what it is.

**Only Linux is told apart by architecture.** Two ELF builds sit side by side
there, and picking the wrong one is an "Exec format error" at the first
simulation -- so the machine is part of choosing (:func:`host_build`) and part
of the header check (:func:`verify`). Windows ships one build, which is then
*the* build for that OS whatever it was compiled for; it does not ask, and this
table does not pretend to know. The architecture matters a second time for the
container (:func:`container_build`), where it is the *daemon's* answer and not
this machine's -- Docker Desktop on an Apple Silicon Mac runs arm64 images.

Nothing here names a product or a solver: the stem every function takes is
``product.BINARY``, which is the caller's business.
"""

import platform
import sys
from dataclasses import dataclass
from typing import Optional

# How much of an executable :func:`verify` needs to see. 64 bytes covers every
# field read below with room to spare, and reading a fixed slice means a
# truncated file is a complaint rather than an exception.
HEADER_BYTES = 64

# e_machine: which machine an ELF file is for. Two bytes at offset 18 of the
# header, in the file's own byte order (byte 5 says which). Read because ELF
# alone cannot separate the two Linux builds -- the magic is identical. Mach-O
# and PE carry the same fact and are not asked for it: one build ships for each
# of those OSes, so there is no second file to confuse it with.
ELF_MACHINE_OFFSET = 18
EM_X86_64 = 0x3E
EM_AARCH64 = 0xB7
ELF_MACHINE_NAMES = {EM_X86_64: "x86-64", EM_AARCH64: "AArch64"}


@dataclass(frozen=True)
class Build:
    """One compiled solver: whose machine it is for, and what it looks like."""

    tag: str  # what the name ends in: "linux-x86_64", "windows"
    os_key: str  # "linux" / "macos" / "windows" -- also how PCM spells it
    label: str  # how to say it to a person
    platforms: tuple  # the ``sys.platform`` spellings of this OS
    machines: tuple  # ``platform.machine()`` spellings; () = any machine
    suffix: str  # what this OS calls an executable
    magic: tuple  # the file's first bytes, any one of them
    magic_name: str  # how to say "that is the wrong kind of file"
    elf_machine: Optional[int] = None  # e_machine, when the file is ELF
    shipped: bool = True  # is this build produced and carried in a package?

    def filename(self, stem):
        """What this build of the solver *stem* is called."""
        return f"{stem}-{self.tag}{self.suffix}"

    def runs_on(self, os_key):
        """Whether a machine running *os_key* could launch this build.

        Its own OS, always -- and one crossing, which is the reason
        :func:`order` has a tail at all: a Windows ``.exe`` on Linux, where a
        checkout under WSL runs it through the interop layer and it is a real
        answer. Nothing else crosses. An ELF handed to macOS is an "Exec format
        error" and never a find, which matters now that no macOS build ships:
        without this the two Linux builds sitting in every install would be
        what a Mac reached for.
        """
        return self.os_key == os_key or (self.os_key == "windows" and os_key == "linux")


# The x86-64 Linux build. ``machines`` is every spelling of that architecture a
# Python might report, lower-cased before it is compared -- the same
# architecture answers "x86_64" on Linux and "AMD64" on Windows, and a machine
# nobody listed simply finds no build rather than being handed a wrong one.
LINUX_X86_64 = Build(
    tag="linux-x86_64",
    os_key="linux",
    label="Linux (x86-64)",
    platforms=("linux",),
    machines=("x86_64", "amd64"),
    suffix="",
    magic=(b"\x7fELF",),
    magic_name="Linux (ELF) executable",
    elf_machine=EM_X86_64,
)

LINUX_AARCH64 = Build(
    tag="linux-aarch64",
    os_key="linux",
    label="Linux (AArch64)",
    platforms=("linux",),
    machines=("aarch64", "arm64"),
    suffix="",
    magic=(b"\x7fELF",),
    magic_name="Linux (ELF) executable",
    elf_machine=EM_AARCH64,
)

# The macOS build, which is no longer produced (``shipped=False``): on macOS
# the solver runs inside a container, and a container is Linux. The entry stays
# because macOS is still a supported operating system -- ``os_keys`` is what a
# package's metadata says, and dropping the row would make PCM refuse to
# install this plugin on a Mac, where everything but the solve still runs.
#
# It also stays because the *shape* of a macOS build is still worth knowing: a
# maintainer who drops one into ``binaries/`` by hand, or an install pointed at
# one through the environment, gets it checked rather than guessed at. No
# ``machines``: there was one build, so there was nothing to choose between --
# and the four magics are the ones a Mach-O file can start with, a 64-bit image
# in either byte order and a universal ("fat") archive in either.
MACOS = Build(
    tag="macos",
    os_key="macos",
    label="macOS",
    platforms=("darwin",),
    machines=(),
    suffix="",
    magic=(
        b"\xcf\xfa\xed\xfe",  # 64-bit Mach-O, little-endian
        b"\xfe\xed\xfa\xcf",  # ... and big-endian
        b"\xca\xfe\xba\xbe",  # a universal ("fat") archive of them
        b"\xbe\xba\xfe\xca",  # ... byte-swapped
    ),
    magic_name="macOS (Mach-O) executable",
    shipped=False,
)

# ``platforms`` covers the POSIX-emulation spellings as well as win32: a Python
# built for Cygwin or MSYS is running on Windows and wants the Windows build.
WINDOWS = Build(
    tag="windows",
    os_key="windows",
    label="Windows",
    platforms=("win", "cygwin", "msys"),
    machines=(),
    suffix=".exe",
    magic=(b"MZ",),
    magic_name="Windows executable",
)

# Every build there is, in release order. The order matters twice: it is the
# order a package's metadata lists its platforms in, and the order the fallback
# in :func:`order` walks after this machine's own build.
BUILDS = (LINUX_X86_64, LINUX_AARCH64, MACOS, WINDOWS)


# --------------------------------------------------------------------------- #
# the table, read
# --------------------------------------------------------------------------- #
def by_tag(tag):
    """The build named *tag*, or None."""
    for build in BUILDS:
        if build.tag == tag:
            return build
    return None


def for_os(os_key):
    """Every build for the operating system *os_key*, in release order."""
    return [build for build in BUILDS if build.os_key == os_key]


def shipped_builds():
    """Every build that is actually produced and carried, in release order.

    What a package holds, what the sync copies and what a header check walks.
    Not what a package *supports* -- see :func:`os_keys`.
    """
    return [build for build in BUILDS if build.shipped]


# A container is Linux whatever the host is, so an OS with no build of its own
# is served by the Linux ones. Named here because :func:`platforms_served` is
# the only place that reasoning is applied and it has to be applied *by name*
# -- "the OS whose solver runs elsewhere" is not something a magic number or a
# file name can say.
CONTAINER_OS = "linux"


def platforms_served(carried):
    """The operating systems a payload holding *carried* can be installed on.

    Not the same list as the builds in it, and this is where the two part. An
    OS with a build of its own is served by carrying that build. An OS with no
    build at all -- macOS -- is served by the *container's* build, which is
    Linux: so a package carrying the Linux builds can be installed on a Mac,
    and one narrowed to Windows cannot, because the Mac's container would have
    nothing to mount.

    This is what a package's metadata says, and getting it wrong is not a
    subtle failure: an omitted OS is a Plugin and Content Manager that refuses
    to install the plugin there at all, on a machine where everything except
    the solve runs perfectly.
    """
    keys = {build.os_key for build in carried}
    served = []
    for key in os_keys():
        if key in keys:
            served.append(key)
        elif not any(build.shipped for build in for_os(key)) and CONTAINER_OS in keys:
            served.append(key)
    return served


def os_keys():
    """Every operating system covered, in release order and without repeats.

    Linux contributes two builds and one name: an OS is what a package's
    metadata can say (PCM has no way to tell two builds of the same OS apart),
    while a build is what actually runs. macOS is on this list and contributes
    no build at all -- the plugin runs there and its solver runs in a
    container, and a package that failed to name the OS would not install.
    """
    seen = []
    for build in BUILDS:
        if build.os_key not in seen:
            seen.append(build.os_key)
    return seen


# --------------------------------------------------------------------------- #
# this machine
# --------------------------------------------------------------------------- #
def host_os(system=None):
    """This machine's ``os_key``, or None on an OS nothing is built for.

    ``system`` overrides what is asked (tests, and the packager driving the
    branch this machine is not); it is a ``sys.platform`` string.
    """
    key = sys.platform if system is None else system
    for build in BUILDS:
        if key.startswith(build.platforms):
            return build.os_key
    return None


def host_build(system=None, machine=None):
    """The build this machine runs, or None when no build claims it.

    None is not the same question the OS gate used to ask -- there is a build
    for every OS now. It means an *architecture* nothing was compiled for (a
    RISC-V box, a 32-bit Linux), which is a real answer and not a refusal: the
    caller still has :func:`order` to fall back through.
    """
    key = host_os(system)
    if key is None:
        return None
    word = (platform.machine() if machine is None else machine).lower()
    for build in for_os(key):
        # No ``machines`` means the OS ships one build and it is that machine's
        # by definition -- see MACOS.
        if not build.machines or word in build.machines:
            return build
    return None


def host_ships(system=None, machine=None):
    """Whether a build of the solver ships for this machine at all.

    False on macOS, where the answer is not "something went wrong" but "the
    solver runs in a container here". A caller that finds no binary asks this
    to know which sentence to say.
    """
    return any(build.shipped for build in order(system, machine))


def order(system=None, machine=None):
    """Every build this machine could launch, best first: its own, then the
    rest of its OS's, then another OS's that would still run here.

    The tail is a fallback and it is deliberate. A checkout or a narrowed
    package may hold only one build, and a build for another machine is worth
    *finding*: under WSL a Windows ``.exe`` runs through the interop layer and
    is a real answer, and "this is not its OS" (which is what the callers then
    say) beats "no simulator binary found" -- the second sends a user looking
    for a file that is sitting right there.

    What it must not do is offer a build that *cannot* run here
    (:meth:`Build.runs_on`). That was harmless while every OS had a build of
    its own and is not any more: a Mac install carries the two Linux builds so
    that its container has something to mount, and a fallback that reached for
    one would turn "no macOS build ships" into an "Exec format error" with no
    hint of why. On macOS this returns nothing at all, which is the true
    answer to "what can this machine launch itself".
    """
    host = host_build(system, machine)
    key = host_os(system)
    rest = [build for build in BUILDS if build is not host and build.runs_on(key)]
    same_os = [build for build in rest if build.os_key == key]
    others = [build for build in rest if build.os_key != key]
    return ([host] if host else []) + same_os + others


def candidates(stem, system=None, machine=None):
    """The file names to look for, best first -- :func:`order` by name."""
    return [build.filename(stem) for build in order(system, machine)]


# --------------------------------------------------------------------------- #
# the machine inside a container
# --------------------------------------------------------------------------- #
# What a container engine calls an architecture (``docker version --format
# {{.Server.Arch}}``, which answers in Go's vocabulary), mapped onto the build
# that runs there. Go's spellings and the kernel's are not the same words for
# the same machines, which is the whole reason this mapping is written down;
# the kernel's own spellings are accepted too, since a caller may have asked
# ``uname`` inside the container instead.
CONTAINER_ARCHES = {
    "amd64": LINUX_X86_64,
    "x86_64": LINUX_X86_64,
    "arm64": LINUX_AARCH64,
    "aarch64": LINUX_AARCH64,
}


def container_build(arch):
    """The build that runs inside a Linux container on *arch*, or None.

    A container is Linux whatever the host is, so this deliberately does not
    ask :func:`host_build`: on macOS the host has no build at all, and on an
    Apple Silicon Mac the answer is the AArch64 one -- neither of which the
    host's own architecture would have told us. None means an architecture
    nothing is built for, which is a sentence for the caller to say and not a
    build to guess at.
    """
    return CONTAINER_ARCHES.get((arch or "").strip().lower())


# --------------------------------------------------------------------------- #
# is this file really that build?
# --------------------------------------------------------------------------- #
def read_header(path):
    """The first :data:`HEADER_BYTES` of *path* -- what :func:`verify` reads."""
    with open(path, "rb") as handle:
        return handle.read(HEADER_BYTES)


def elf_machine(header):
    """The machine an ELF *header* names, as an ``e_machine`` number; None
    when the header is too short to carry one."""
    end = ELF_MACHINE_OFFSET + 2
    if len(header) < end:
        return None
    order_ = "little" if header[5] == 1 else "big"
    return int.from_bytes(header[ELF_MACHINE_OFFSET:end], order_)


def verify(build, header):
    """What is wrong with *header* for *build*, as one phrase -- or None.

    Checked at build time (the packager, the sync) rather than at run time,
    because both failures it catches produce a package that installs perfectly
    and fails at the first simulation, which is a bad place to find out: a
    Windows build filed under the Linux name, or -- the one a magic number
    cannot see -- an AArch64 ELF filed as the x86-64 one.
    """
    if not any(header.startswith(magic) for magic in build.magic):
        return f"not a {build.magic_name}"
    if build.elf_machine is None:
        return None
    found = elf_machine(header)
    if found is None:
        return "an ELF header too short to say which machine it is for"
    if found != build.elf_machine:
        named = ELF_MACHINE_NAMES.get(found, f"machine {found:#x}")
        return f"an ELF for {named}, not {build.label}"
    return None


def check(build, path):
    """*path*'s complaint as :func:`verify` would put it, naming the file, or
    None when the file is the build it claims to be."""
    problem = verify(build, read_header(path))
    return None if problem is None else f"{path} is {problem}."
