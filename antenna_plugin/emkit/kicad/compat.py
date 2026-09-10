"""pcbnew API shims shared across modules.

KiCad 7 moved point types from wxPoint to VECTOR2I; every module that builds
a pcbnew point goes through ``vec2`` so the version fallback lives in one
place. pcbnew is imported lazily, keeping the callers' pure helpers
unit-testable off KiCad.
"""


def vec2(x_iu=0, y_iu=0):
    """A pcbnew point in internal units: VECTOR2I on KiCad 7+, wxPoint on 6."""
    import pcbnew

    if hasattr(pcbnew, "VECTOR2I"):
        return pcbnew.VECTOR2I(int(x_iu), int(y_iu))
    return pcbnew.wxPoint(int(x_iu), int(y_iu))
