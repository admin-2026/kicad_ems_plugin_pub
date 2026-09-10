"""A stand-in solver binary, for the tests that package or install one.

The packager and the sync read every build's header before they will carry it
(``sim.builds.verify``), so a test that stages a package needs files those
checks accept -- but nothing here ever *runs* a solver, and a real one is
megabytes. What is needed is the header and nothing else.

Built from the build record rather than written out as literals, which is the
point: a test that spelled ``\\x7fELF ... \\x3e\\x00`` by hand would be a second
copy of the very fact under test, and it would keep passing after the table it
is meant to be checking had changed underneath it.

A plain function of a ``Build`` and nothing more -- it loads no plugin and
imports nothing -- because both suites need it: a product's (where the plugin
is assembled) and the repository's own (where it is not, and ``bare_package``
cannot answer at all).
"""

# Long enough to carry every field verify() reads -- e_machine ends at byte 20
# -- with room for whatever a later check might want to look at.
LENGTH = 64


def header(build):
    """A file body that passes as *build* and as nothing else.

    The container's first bytes, plus -- for the two Linux builds, which share
    a magic number -- the ELF fields that say which machine it is for.
    """
    body = bytearray(build.magic[0] + bytes(LENGTH))[:LENGTH]
    if build.elf_machine is not None:
        body[4] = 2  # ELFCLASS64
        body[5] = 1  # little-endian, which is what elf_machine reads byte 5 for
        body[18:20] = build.elf_machine.to_bytes(2, "little")
    return bytes(body)


def populate(directory, stem, wanted):
    """Write a stand-in for each build in *wanted* into *directory*.

    Returns ``{build: path}``, so a caller can say which file it expects to be
    chosen without spelling the name a second time.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written = {}
    for build in wanted:
        path = directory / build.filename(stem)
        path.write_bytes(header(build))
        written[build] = path
    return written
