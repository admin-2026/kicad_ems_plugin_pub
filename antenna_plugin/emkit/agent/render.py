"""Turning a payload into lines, for the reader who did not ask for JSON.

Everything here is a *view*, and it is the only part of the command line that
is a matter of taste. It lives apart from the verbs for that reason: a verb
should be its question and its answer, and how the answer looks on a terminal
should be somebody else's problem.

What is here is the shapes several verbs share. A rendering that depends on
what the payload *means* -- a verdict's glyph, a job's phase -- belongs with
the verb that produced it, because that verb is the thing that knows. The rule
is one of ownership, not of file size: a helper here must make sense to a
caller who has not read the verb.

Nothing here judges, computes or reorders. A renderer that has to work
something out has been handed the wrong payload, and the fix is in the verb.
"""


def kv(payload, keys=None):
    """``key: value`` per entry, in the payload's own order (``keys`` narrows
    and reorders). The plainest thing a flat answer can look like."""
    items = payload.items() if keys is None else ((k, payload[k]) for k in keys)
    return [f"{key}: {value}" for key, value in items]


def columns(items, *specs):
    """Left-aligned columns from ``(width, key)`` pairs, then the rest of the
    line. A width of 0 means "as wide as it comes" -- the last column, which
    has nothing to line up against."""
    out = []
    for row in items:
        cells = [
            f"{row[key]:<{width}}" if width else str(row[key]) for width, key in specs
        ]
        out.append(" ".join(cells).rstrip())
    return out
