"""A fake KiCad board, for the tests that exercise the plugin's board half.

``wx_stub`` installs an empty ``pcbnew`` module so the plugin imports off KiCad;
this fills it in far enough to place a marker and read one back: points,
graphics, footprints, groups and a board, plus the enum names and unit
conversions the marker code asks ``pcbnew`` for.

It is one module object for the whole test run, and the modules under test bound
it at import time — so it has to be *mutated* rather than replaced, which is
what ``with_kicad`` does (and undoes) around each call into the plugin.

Shared rather than copied per test file: the marker code has one idea of what a
board offers, and two divergent fakes of it would be two different KiCads to be
wrong about.
"""

import sys

import wx_stub  # noqa: F401  (installs the empty wx / pcbnew this fills in)

pcbnew = sys.modules["pcbnew"]  # wx_stub put it there


class Pt:
    """A VECTOR2I: internal units, integer."""

    def __init__(self, x=0, y=0):
        self.x, self.y = int(x), int(y)


class Box:
    """A bounding box in internal units, as pcbnew answers one."""

    def __init__(self, x_mm, y_mm, w_mm, h_mm):
        self._v = [int(v * 1e6) for v in (x_mm, y_mm, w_mm, h_mm)]

    def GetX(self):
        return self._v[0]

    def GetY(self):
        return self._v[1]

    def GetWidth(self):
        return self._v[2]

    def GetHeight(self):
        return self._v[3]


class Shape:
    """A stand-in for a board PCB_SHAPE (and for a footprint's own graphic,
    which is the same class from KiCad 8 on): the setters the plugin writes and
    the getters it reads back, plus a count of how often the geometry was
    written (a repin must not touch the rectangle the user dragged)."""

    _next_uuid = 0

    def __init__(self, parent=None):
        self.parent = parent
        Shape._next_uuid += 1
        self.m_Uuid = f"{Shape._next_uuid:04d}"
        self.shape = None
        self.points = []
        self.start, self.end = Pt(), Pt()
        self.layer = None
        self.width = None
        self.filled = None
        self.writes = 0

    def SetShape(self, shape):
        self.shape = shape

    def GetShape(self):
        return self.shape

    # -- the polygon form, which a turned marker's outline takes
    def SetPolyPoints(self, points):
        self.points = list(points)
        self.writes += 1

    def GetPolyShape(self):
        return PolySet(self.points)

    def set_poly_mm(self, corners):
        """What a vertex drag leaves behind: fresh corners, nothing else."""
        self.points = [Pt(x * 1e6, y * 1e6) for (x, y) in corners]

    def SetStart(self, pt):
        self.start = pt
        self.writes += 1

    def SetEnd(self, pt):
        self.end = pt

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def SetLayer(self, layer):
        self.layer = layer

    def GetLayer(self):
        return self.layer

    def SetWidth(self, width):
        self.width = width

    def SetFilled(self, filled):
        self.filled = filled

    # -- what a drag in the editor does to a placed shape
    def drag_to(self, seg_mm):
        (x0, y0), (x1, y1) = seg_mm
        self.start = Pt(x0 * 1e6, y0 * 1e6)
        self.end = Pt(x1 * 1e6, y1 * 1e6)

    def points_mm(self):
        return (
            (self.start.x / 1e6, self.start.y / 1e6),
            (self.end.x / 1e6, self.end.y / 1e6),
        )


class Text:
    """A footprint's reference/value field: only ever hidden."""

    def SetVisible(self, visible):
        self.visible = visible


class LibId:
    def __init__(self, name):
        self.name = name

    def GetLibItemName(self):
        return self.name


class Footprint:
    """A stand-in for a FOOTPRINT: what the markers build one with, and what a
    move does to it — ``SetPosition`` carries every graphic along, which is the
    whole reason the area marker's feed arrow is one."""

    _next_uuid = 0

    def __init__(self, board=None):
        self.board = board
        Footprint._next_uuid += 1
        self.m_Uuid = f"fp{Footprint._next_uuid:04d}"
        self.items = []
        self.pos = Pt()
        self.orientation = 0.0
        self.fpid = LibId("")
        self.removed = []
        self.thisown = True

    # -- what _build_footprint writes
    def SetFPID(self, fpid):
        self.fpid = fpid

    def GetFPID(self):
        return self.fpid

    def SetReference(self, text):
        self.reference = text

    def SetValue(self, text):
        self.value = text

    def Reference(self):
        return Text()

    def Value(self):
        return Text()

    def SetAttributes(self, attrs):
        self.attributes = attrs

    def Add(self, item):
        self.items.append(item)

    def Remove(self, item):
        self.items.remove(item)
        self.removed.append(item)

    def GraphicalItems(self):
        return list(self.items)

    # -- moving it
    def SetPosition(self, pt):
        dx, dy = pt.x - self.pos.x, pt.y - self.pos.y
        self.pos = pt
        for item in self.items:  # FOOTPRINT::SetPosition carries the shapes
            item.start = Pt(item.start.x + dx, item.start.y + dy)
            item.end = Pt(item.end.x + dx, item.end.y + dy)

    def GetPosition(self):
        return self.pos

    def SetOrientationDegrees(self, degrees):
        self.orientation = float(degrees)

    def GetOrientationDegrees(self):
        return self.orientation

    def drag_by(self, dx_mm, dy_mm):
        """The user dragging a footprint across the board: it and every shape
        on it move together, which is all KiCad lets them do."""
        self.SetPosition(Pt(self.pos.x + dx_mm * 1e6, self.pos.y + dy_mm * 1e6))


class Chain:
    """A SHAPE_LINE_CHAIN, as boardshapes reads one."""

    def __init__(self, points):
        self.points = points

    def PointCount(self):
        return len(self.points)

    def CPoint(self, i):
        return self.points[i]


class PolySet:
    def __init__(self, points):
        self.points = points

    def Outline(self, _i):
        return Chain(self.points)


class Group:
    def __init__(self, parent=None):
        self.parent = parent
        self.name = ""
        self.items = []

    def SetName(self, name):
        self.name = name

    def GetName(self):
        return self.name

    def AddItem(self, item):
        self.items.append(item)

    def GetItems(self):
        # Unordered, as PCB_GROUP::GetItems is: the plugin must not depend on
        # the order things went in (boardshapes.group_items sorts them).
        return list(reversed(self.items))


class Board:
    def __init__(self, outline=(0.0, 0.0, 60.0, 40.0)):
        self.items = []
        self.footprints = []
        self.outline = Box(*outline)

    def Add(self, item):
        (self.footprints if isinstance(item, Footprint) else self.items).append(item)

    def Remove(self, item):
        (self.footprints if isinstance(item, Footprint) else self.items).remove(item)

    def Groups(self):
        return [i for i in self.items if isinstance(i, Group)]

    def GetFootprints(self):
        return list(self.footprints)

    def GetBoardEdgesBoundingBox(self):
        return self.outline

    def GetBoundingBox(self):
        return self.outline

    def IsLayerEnabled(self, layer_id):
        return layer_id is not None


# What the plugin looks up on the pcbnew module itself.
KICAD = {
    "FromMM": staticmethod(lambda mm: int(round(mm * 1e6))),
    "ToMM": staticmethod(lambda iu: iu / 1e6),
    "VECTOR2I": Pt,
    "BOARD": Board,
    "PCB_SHAPE": Shape,
    "PCB_GROUP": Group,
    "FOOTPRINT": Footprint,
    "LIB_ID": staticmethod(lambda lib, name: LibId(name)),
    "SHAPE_T_SEGMENT": 0,
    "SHAPE_T_RECT": 1,
    "SHAPE_T_CIRCLE": 2,
    "SHAPE_T_ARC": 3,
    "SHAPE_T_POLYGON": 4,
}
KICAD.update({f"User_{n}": 50 + n for n in range(1, 10)})

USER_1, USER_2 = 51, 52  # the layer ids this fake gives User.1 and User.2


def with_kicad(board, fn):
    """Run ``fn`` with the shared pcbnew stub wearing enough KiCad to place and
    read a marker on ``board``, and put the stub back afterwards (see the module
    docstring on why it is mutated in place)."""
    saved = {name: getattr(pcbnew, name, KeyError) for name in KICAD}
    saved["GetBoard"] = getattr(pcbnew, "GetBoard", KeyError)
    for name, value in KICAD.items():
        setattr(pcbnew, name, value.__func__ if hasattr(value, "__func__") else value)
    pcbnew.GetBoard = lambda: board
    try:
        return fn()
    finally:
        for name, value in saved.items():
            if value is KeyError:
                delattr(pcbnew, name)
            else:
                setattr(pcbnew, name, value)
