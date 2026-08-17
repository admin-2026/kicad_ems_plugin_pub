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

    Only the layers the simulation models come back (see ``_layer_entry``):
    the copper foils and dielectric gaps it meshes, plus the geometry-only
    silk/paste overlays, which carry a name and nothing else.

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


# Geometry-only overlays, by the substring KiCad puts in the layer's `type`
# ("Top Silk Screen", "Bottom Solder Paste", ...). They are never meshed, so
# only their name and their position in the stack (which side they belong to)
# are read -- see simulate.collect_stackup.
_OVERLAY_TYPES = {"Silk Screen": "silk", "Solder Paste": "paste"}


def _layer_entry(node):
    """Normalize one ["layer", name, props...] node; None for entries the
    simulation doesn't model (the solder mask -- nothing in the runner reads
    it since the pad signal moved to the solder paste, see
    simulate._AUX_LAYERS). A bare ``addsublayer`` token starts the next
    sublayer of a dielectric; ``(thickness X locked)`` carries an extra token
    that is simply ignored."""
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
            return {"kind": kind, "name": name}
    return None
