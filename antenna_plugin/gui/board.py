"""pcbnew board queries for the GUI.

Everything that reads the open board lives here, keeping the other gui
modules (options, widgets, log, viewer) pcbnew-free.
"""

import pcbnew


def board_info():
    """Read a few facts from the currently open board for the GUI to show."""
    board = pcbnew.GetBoard()
    if board is None:
        return {"ok": False, "error": "No board is open"}
    try:
        bbox = board.GetBoundingBox()
        thickness = board.GetDesignSettings().GetBoardThickness()
        return {
            "ok": True,
            "file": board.GetFileName() or "(unsaved board)",
            "footprints": sum(1 for _ in board.GetFootprints()),
            "nets": int(board.GetNetInfo().GetNetCount()),
            "thickness_mm": round(pcbnew.ToMM(thickness), 3),
            "size_mm": [
                round(pcbnew.ToMM(bbox.GetWidth()), 2),
                round(pcbnew.ToMM(bbox.GetHeight()), 2),
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def board_edge_span_mm():
    """The board outline's extent as ``(x_span_mm, y_span_mm)`` -- the widest
    and deepest the board itself is -- or None when no board is open or it has
    no Edge.Cuts outline yet.

    "No outline" is the degenerate edge bounding box the pre-flight's
    no-outline blocker tests for (``sim.simulate._outline_missing``): with
    nothing drawn on Edge.Cuts pcbnew answers an empty box. The area section
    caps its width/height sliders at this, so the marked antenna area can't be
    dragged bigger than the board it has to fit on; without an outline there is
    nothing to cap against and its own range stands.
    """
    board = pcbnew.GetBoard()
    if board is None:
        return None
    try:
        bbox = board.GetBoardEdgesBoundingBox()
        span = (pcbnew.ToMM(bbox.GetWidth()), pcbnew.ToMM(bbox.GetHeight()))
    except Exception:
        return None  # an older/odd binding: no cap rather than a broken page
    return span if span[0] > 0 and span[1] > 0 else None


def board_layer_names():
    """``(copper_layer_suffixes, dielectric_gap_count)`` for the open board,
    used to build one material row per layer. Falls back to a 2-layer board
    when nothing is open."""
    board = pcbnew.GetBoard()
    if board is None:
        return ["F_Cu", "B_Cu"], 1
    try:
        from ..sim import simulate

        copper = [suffix for suffix, _ in simulate.copper_layers(board)]
    except Exception:
        copper = ["F_Cu", "B_Cu"]
    return copper, max(1, len(copper) - 1)


def make_material_selector(parent, on_change):
    """Build the optional per-layer material picker, or None if the feature's
    package (materials/) was removed -- the plugin then runs without material
    selection, using config's copper/FR-4 defaults."""
    try:
        from ..materials.ui import MaterialSelector
    except ImportError:
        return None
    return MaterialSelector(parent, board_layer_names(), on_change)
