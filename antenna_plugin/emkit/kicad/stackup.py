"""Parse the physical stackup out of a saved .kicad_pcb board file.

Some KiCad builds ship an incomplete swig binding for the stackup manager --
``GetStackupDescriptor()`` comes back as an opaque SwigPyObject with no
``GetList()`` -- so the plugin reads the same data from the board file
itself: the ``(stackup ...)`` block KiCad writes inside ``(setup ...)`` once
Board Setup > Physical Stackup has been configured. The caller
(``simulate.collect_stackup``) is responsible for the file being current;
``gui.on_run`` prompts the user to save when the in-memory board differs
from disk.

Stdlib only, no pcbnew: a tiny s-expression reader scoped to just the
stackup block, so it stays unit-testable off KiCad.
"""

import re

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+')


def read_stackup(pcb_path):
    """The ordered ``(layer ...)`` entries of the file's stackup block, top
    to bottom, normalized to dicts:

      {"kind": "copper",     "name", "thickness_mm"}
      {"kind": "dielectric", "name", "sublayers": [(mm, eps, loss_tangent), ...]}
      {"kind": "silk",       "name"}
      {"kind": "paste",      "name"}
      {"kind": "mask",       "name", "thickness_mm"?, "eps"?, "loss_tangent"?}

    Only the layers the simulation models come back (see ``_layer_entry``):
    the copper foils and dielectric gaps it meshes, plus the silk/paste/mask
    overlays. The first two are geometry only and carry a name and nothing
    else; the solder mask is a coating with a thickness and a permittivity of
    its own, which KiCad's stackup states and a run that simulates it meshes
    it with (each optional -- an unset one comes back missing, and it is the
    caller that decides whether it needed one).

    A dielectric's KiCad sublayers (a gap built from prepreg + core plies)
    come through individually for the caller to merge, each as an
    ``(mm, eps, loss_tangent)`` triple. Missing numbers come back as None --
    the caller decides how hard to fail. Returns None when
    the file has no stackup block at all (Physical Stackup never
    configured).
    """
    block = stackup_text(pcb_path)
    if block is None:
        return None
    entries = []
    for node in _parse(block)[1:]:
        if isinstance(node, list) and node[:1] == ["layer"] and len(node) > 1:
            entry = _layer_entry(node)
            if entry:
                entries.append(entry)
    return entries


def stackup_text(pcb_path):
    """The file's raw ``(stackup ...)`` block, or None when absent. Besides
    feeding read_stackup, this is what ``simulate.board_needs_save`` compares
    between the on-disk file and a temp save of the live board -- only the
    stackup is read from disk (gerbers are plotted from the live board), so
    only a stackup difference means stale data."""
    with open(pcb_path, encoding="utf-8") as f:
        return _stackup_block(f.read())


def _stackup_block(text):
    """The balanced "(stackup ...)" substring of the board file, quote-aware
    (a ')' inside a quoted material name must not close the block)."""
    m = re.search(r"\(stackup[\s(]", text)
    if not m:
        return None
    depth, in_str, i = 0, False, m.start()
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[m.start() : i + 1]
        i += 1
    return None


def _parse(text):
    """One balanced s-expression -> nested lists of atoms (strings)."""
    tokens = _TOKEN.findall(text)
    pos = 0

    def node():
        nonlocal pos
        pos += 1  # consume '('
        out = []
        while tokens[pos] != ")":
            if tokens[pos] == "(":
                out.append(node())
            else:
                out.append(_atom(tokens[pos]))
                pos += 1
        pos += 1  # consume ')'
        return out

    return node()


def _atom(tok):
    if tok.startswith('"'):
        return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return tok


# The overlays, by the substring KiCad puts in the layer's `type` ("Top Silk
# Screen", "Bottom Solder Paste", "Top Solder Mask", ...). Their name and their
# position in the stack (which side they belong to) are always read -- see
# simulate.collect_stackup -- plus, for the solder mask, the thickness and
# permittivity that make the coating a dielectric a run can mesh.
_OVERLAY_TYPES = {
    "Silk Screen": "silk",
    "Solder Paste": "paste",
    "Solder Mask": "mask",
}

# The constants an overlay entry carries when the board states them, by the
# name this module answers them under and the property KiCad writes. Only the
# solder mask has any (silk and paste have neither in KiCad's stackup), so
# nothing here has to branch on which overlay it is looking at.
_OVERLAY_PROPS = (
    ("thickness_mm", "thickness"),
    ("eps", "epsilon_r"),
    ("loss_tangent", "loss_tangent"),
)


def _layer_entry(node):
    """Normalize one ["layer", name, props...] node; None for entries the
    simulation models nothing of (the user layers, the adhesive). A bare
    ``addsublayer`` token starts the next sublayer of a dielectric;
    ``(thickness X locked)`` carries an extra token that is simply ignored."""
    name = node[1]
    ltype = ""
    subs = [{}]
    for prop in node[2:]:
        if prop == "addsublayer" or prop == ["addsublayer"]:
            subs.append({})
        elif isinstance(prop, list) and len(prop) >= 2:
            key, val = prop[0], prop[1]
            if key == "type":
                ltype = val
            elif key in ("thickness", "epsilon_r", "loss_tangent"):
                try:
                    subs[-1][key] = float(val)
                except ValueError:
                    pass
    first = subs[0]
    if ltype == "copper":
        return {"kind": "copper", "name": name, "thickness_mm": first.get("thickness")}
    if ltype in ("core", "prepreg"):
        return {
            "kind": "dielectric",
            "name": name,
            "sublayers": [
                (s.get("thickness"), s.get("epsilon_r"), s.get("loss_tangent"))
                for s in subs
            ],
        }
    for fragment, kind in _OVERLAY_TYPES.items():
        if fragment in ltype:
            entry = {"kind": kind, "name": name}
            for key, prop in _OVERLAY_PROPS:
                if first.get(prop) is not None:
                    entry[key] = first[prop]
            return entry
    return None
