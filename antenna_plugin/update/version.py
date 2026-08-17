"""Comparing two version strings, and nothing else.

The plugin's versions are dotted numbers ("0.1.0"), and GitHub publishes them
as tags, which conventionally wear a "v" ("v0.2.0"). So this parses a leading
"v", any number of dotted integers, and the two suffixes semver allows: a
pre-release ("0.2.0-rc1") and build metadata ("0.2.0+3f2a1c").

The comparison is deliberately coarse where semver is fussy:

* missing components are zero, so "0.2" and "0.2.0" are the same version;
* build metadata is ignored, as semver says it must be;
* a pre-release sorts *below* the release it leads to ("0.2.0-rc1" < "0.2.0"),
  but two pre-releases of the same version compare equal -- ranking "rc2"
  against "beta" is guesswork, and the only pre-release that can turn up here
  is one the user installed themselves (the source never offers one).

Anything that doesn't parse -- an empty string, "unknown", a date, a name --
answers None and can only ever produce "not newer": an install whose version
we can't read is never nagged about an update we can't be sure it needs.
"""


def parse(text):
    """``text`` as ``(numbers, rank)`` -- the dotted integers as a tuple and 0
    for a pre-release / 1 for a final release -- or None if it isn't a version.
    The two are ordered together, which is what puts "0.2.0-rc1" below
    "0.2.0"."""
    if not isinstance(text, str):
        return None
    core = text.strip()
    if core[:1] in ("v", "V"):
        core = core[1:]
    core = core.split("+", 1)[0]  # build metadata: not part of the ordering
    core, _, pre = core.partition("-")
    parts = core.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts), 0 if pre else 1


def is_newer(candidate, current):
    """Is ``candidate`` a later version than ``current``? False whenever either
    side can't be read, so an unreadable version is never reported as out of
    date (see the module docstring)."""
    left, right = parse(candidate), parse(current)
    if left is None or right is None:
        return False
    return _padded(left, right) > _padded(right, left)


def _padded(one, other):
    """``one`` with its number tuple zero-padded to ``other``'s length, so
    "0.2" and "0.2.0" compare as the same version."""
    numbers, rank = one
    width = max(len(numbers), len(other[0]))
    return numbers + (0,) * (width - len(numbers)), rank
