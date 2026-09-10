"""KiCad-version advisory.

The plugin's board/marker/footprint modules are written against KiCad 9
scripting behaviour; older hosts don't raise, they misbehave silently. That is
worth *saying* at launch, but it is not ours to forbid: a user who wants the
plugin on the KiCad they have gets it, with a warning. So this module only
ever produces a message -- nothing here blocks.
"""

import re

from ... import product

# The oldest KiCad this plugin is written against. Older hosts are warned
# about, not refused.
SUPPORTED_KICAD_VERSION = (9, 0)


# What a board file says about the KiCad that wrote it, in its own first
# lines: `(generator_version "10.0")`, since KiCad 7.
_GENERATOR_VERSION = re.compile(r'\(generator_version\s+"([^"]+)"')


def _parse_major_minor(build_version):
    match = re.match(r"(\d+)\.(\d+)", build_version)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def board_saved_by(head):
    """(major, minor) of the KiCad that wrote a board file, off the first
    kilobytes of it, or None when it says nothing about that.

    Read from the text rather than asked of pcbnew, because the question is
    only ever asked when pcbnew has *refused* the file: a board saved by a
    newer KiCad comes back from ``LoadBoard`` as a bare None, and this is what
    turns that into a sentence. Boards written before KiCad 7 carry no such
    header -- and a KiCad 9 opens those anyway, so None is the right answer to
    "which newer version wrote this".
    """
    match = _GENERATOR_VERSION.search(head)
    return _parse_major_minor(match.group(1)) if match else None


def get_kicad_version():
    """(major, minor) of the running KiCad host, or None if undetectable."""
    import pcbnew

    return _parse_major_minor(pcbnew.GetBuildVersion())


def supported_kicad_version_str():
    return "{}.{}".format(*SUPPORTED_KICAD_VERSION)


def kicad_version_warning():
    """Advisory string if the host is older than the supported KiCad, else None.

    Returns None when the version can't be determined at all, rather than
    warning about an unrecognised build string. Callers show the text and
    carry on -- an old host is a caveat, not a refusal.
    """
    version = get_kicad_version()
    if version is None:
        return None
    if version < SUPPORTED_KICAD_VERSION:
        return (
            f"{product.NAME} is written for KiCad "
            f"{supported_kicad_version_str()} or later (detected "
            f"{version[0]}.{version[1]}). It will open, but board, marker and "
            f"footprint operations may misbehave on this host."
        )
    return None
