"""KiCad-version advisory.

The plugin's board/marker/footprint modules are written against KiCad 9
scripting behaviour; older hosts don't raise, they misbehave silently. That is
worth *saying* at launch, but it is not ours to forbid: a user who wants the
plugin on the KiCad they have gets it, with a warning. So this module only
ever produces a message -- nothing here blocks.
"""

import re

# The oldest KiCad this plugin is written against. Older hosts are warned
# about, not refused.
SUPPORTED_KICAD_VERSION = (9, 0)


def _parse_major_minor(build_version):
    match = re.match(r"(\d+)\.(\d+)", build_version)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


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
            f"Antenna Designer is written for KiCad "
            f"{supported_kicad_version_str()} or later (detected "
            f"{version[0]}.{version[1]}). It will open, but board, marker and "
            f"footprint operations may misbehave on this host."
        )
    return None
