"""The saved form, turned into a run's parameters.

Two vocabularies meet here, and this is the only place they meet.

A **form** is a flat ``key: value`` string dict: what a section snapshots
(gui.model), what ``settings.yaml`` holds (emkit.settings), and what a caller
hands the command line with ``--settings``. It is spelled the way the window
reads: ``adv.cell_mm`` is a field in a pane, ``no_refine_xy`` is a checkbox
saying what it *skips*, ``materials.metal0.choice`` is a picker on a row.

A run's **parameters** are the config's own keys, typed: ``cell_mm`` a float,
``refine_xy`` a bool, ``metal_layers`` a list of ``{"sigma": ...}``. That is
what ``config.ConfigWriter`` takes and what the runner's YAML says.

**Both frontends translate here.** The window's sections hand their own
snapshot to these functions rather than reading their widgets a second time
(``AdvancedSection.contribute`` and friends), and ``run start`` reads a
settings file and calls the same ones. So the two cannot drift: a form run
from a shell and the same form run from the window are the same run, by
construction rather than by two derivations that have to agree.

Three rules this keeps:

* **Nothing is invented.** A field that is filled in is parsed strictly and
  the error names it; a field left blank is left out, so the config's own
  ``0 = auto`` is what a run gets. What is *missing* from the form falls back
  to ``defaults()`` -- a fresh form, the same one the window opens on -- and
  never to a number nobody chose.
* **A pick is a value, not a caption** (emkit.choices), and one this list no
  longer offers restores as the default rather than as its neighbour.
* **A config key typed into a form is refused by name.** ``cell_mm:`` in a
  settings file would otherwise be silently ignored, and it is the mistake a
  reader of ``pcb.yaml`` will make first (``refuse_config_spellings``).

Pure stdlib -- no wx, no pcbnew: the command line reads this on whatever
Python the caller has (dev_docs/frontend-lazy-loading.md).
"""

from . import choices
from .config import ConfigWriter
from .options import ADV_FIELDS, SPEED_DEFAULT, SPEED_PRESETS

# What a knob left out of a run means, and so what a toggle missing from a
# saved form falls back to: the config's own default (ConfigWriter.DEFAULTS,
# the base table -- these are the keys every flow shares).
CONFIG_DEFAULTS = ConfigWriter.DEFAULTS

# ---------------------------------------------------------------------------
# strings <-> values. The form is strings on both sides of the seam -- a
# widget's and a file's -- so these are shared with the widgets that write
# them (gui.widgets re-exports them).
# ---------------------------------------------------------------------------


def to_float(text, fallback):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return fallback


def bool_str(value):
    """A checkbox state as the flat-dict string 'true'/'false'."""
    return "true" if value else "false"


def parse_bool(text):
    """A flat-dict string back to a bool (anything truthy-looking is True)."""
    return str(text).strip().lower() in ("1", "true", "yes", "on")


# The bool toggles the Advanced pane owns, under the config key each writes.
# Two of them the pane spells the other way round, because a checkbox reads
# better as what it turns *off*, and those two are handled by name below.
_TOGGLES = (
    # Whether the solder mask coating is part of the board being solved. Off
    # by default (CONFIG_DEFAULTS), because the coating is meshed at its own
    # thickness and that is often ten times the wall clock -- so it is a tick
    # to reach for, never one to inherit.
    "include_mask",
    # Whether the run's data is written a second time as bare JSON beside the
    # browser dump. The one output knob a form holds: the .js dump is an
    # assignment and not JSON at all, so a caller that is not a page cannot
    # read a run back without this -- which is why it is on the pane and in
    # the form rather than left to whoever hand-writes a pcb.yaml.
    "output_json",
    "coarse_air",
    "conformal",
    "adaptive",
    "refine_adaptive",
    "feed_snap_to_center",
    "mesh_fit_cell",
    "mesh_nudge",
)

# What the metal model was saved under before it was saved as a value:
# ``model``, holding the caption the picker drew. Read for as long as settings
# files written by an older window are still being opened.
WAS = {choices.COPPER_MODEL.key: "model"}

# Advanced fields the config emits as integers (everything else is a float).
_INT_ADV = {"steps", "threads", "pml_cells", "refine_n"}

# The form's spelling of a config key that is not spelled the same, for the
# one message worth being exact about: a settings file holding `cell_mm` or
# `boundary` is a caller who read pcb.yaml and guessed, and a silently ignored
# key is the worst possible answer to that.
SPELLED = {
    "refine_xy": "no_refine_xy (the form says what it skips)",
    "boundary": "mur",
    "time_ns": "time / time_auto",
}


# --------------------------------------------------------------------------- #
# the whole form
# --------------------------------------------------------------------------- #
def params(form):
    """Every run parameter ``form`` describes, in the config's vocabulary.

    Raises ``RuntimeError`` naming the field for anything filled in that is not
    a value, and ``ValueError`` naming the layer for a material pick that
    stands for nothing -- the same refusals, in the same words, whichever
    frontend asked. What is left out is left out: the config's ``0 = auto``
    answers for a blank field, and a copper layer with no metal is refused by
    the config writer rather than given one here.
    """
    from .. import runjob

    refuse_config_spellings(form)
    out = {"feed_layer": form.get("feed_layer", "")}
    # In the window's own order (gui.sections.run.collect_run_params): the
    # product's form, then the Advanced pane, then the pass. It matters where
    # a flow's own field and an Advanced one write the same config key -- a
    # sweep's top-of-band and `adv.fmax_ghz` -- and there the pane wins,
    # because that is the field a user typed *last resort* into.
    runjob.form_params(form, out)  # the product's own half of the form
    advanced(form, out)
    pass_knobs(form, out)
    return out


def defaults():
    """A fresh form's shared half: what the window opens on, and what a key
    missing from a saved form means.

    Derived rather than written down -- the speed slider's default stop for the
    toggles it drives, the config's own defaults for the toggles it does not,
    each closed list's default, and a blank for every Advanced field, which is
    the config's auto. So the starter file, the fallback and the window's
    opening state are one answer.
    """
    preset = SPEED_PRESETS[SPEED_DEFAULT]
    data = {
        "coarse_air": bool_str(preset.coarse_air),
        "no_refine_xy": bool_str(not preset.refine_xy),
        "mur": bool_str(preset.boundary == "mur"),
        "conformal": bool_str(preset.conformal),
        "adaptive": bool_str(preset.adaptive),
        "copper_cells": str(preset.copper_cells),
        "time_auto": bool_str(not CONFIG_DEFAULTS["time_ns"]),
        "time": "",
        "auto_ground": bool_str(CONFIG_DEFAULTS["auto_ground"]),
        "feed_layer": "",
    }
    for name in _TOGGLES:
        data.setdefault(name, bool_str(CONFIG_DEFAULTS[name]))
    for pick in choices.SHARED:
        data[pick.key] = pick.default
    for key, _label, _hint in ADV_FIELDS:
        data["adv." + key] = ""
    return data


def starter(copper_layers=(), substrate_count=1):
    """A whole fresh form for a board with these layers: the shared defaults,
    the product's own fields, and one material row per copper foil and per
    dielectric gap, each on the pick a fresh picker shows.

    What ``settings init`` writes. Deliberately incomplete where the plugin has
    nothing to say: a target frequency is blank, because there is no default
    frequency for a board and inventing one is the single thing that must never
    happen at this seam. A run refuses it by name until it is filled in.
    """
    from .. import runjob

    data = defaults()
    data["feed_layer"] = copper_layers[0] if copper_layers else ""
    data.update(runjob.form_starter())
    data.update(_material_starter(len(copper_layers), substrate_count))
    return data


def _material_starter(metal_count, substrate_count):
    from .materials.catalog import MaskCatalog, MetalCatalog, SubstrateCatalog

    data = {}
    rows = [(f"metal{i}", MetalCatalog) for i in range(metal_count)]
    rows += [(f"sub{i}", SubstrateCatalog) for i in range(substrate_count)]
    rows += [("mask", MaskCatalog)]
    for prefix, kind in rows:
        catalog = kind()
        # The first choice a picker offers: copper for a foil, and the "from
        # board stackup" sentinel for a laminate and for the coating -- which
        # is the pick that takes the board's own numbers rather than one this
        # side chose.
        data[f"materials.{prefix}.choice"] = catalog.choices()[0]
        for field in catalog.FIELDS:
            data[f"materials.{prefix}.{_state_key(field)}"] = ""
    return data


# --------------------------------------------------------------------------- #
# the halves
# --------------------------------------------------------------------------- #
def advanced(form, params):
    """The Advanced pane's half: the closed lists, the six speed/quality
    toggles the slider drives and the five it does not, the per-layer
    materials, and every numeric field that has been filled in."""
    params.update(picked(form))
    params.update(
        {
            "refine_xy": not _flag(form, "no_refine_xy"),
            "boundary": "mur" if _flag(form, "mur") else "pml",
            "copper_cells": _copper_cells(form),
        }
    )
    for name in _TOGGLES:
        params[name] = _flag(form, name)
    materials(form, params)
    for key, label, _hint in ADV_FIELDS:
        text = _read(form, "adv." + key).strip()
        if text:
            value = adv_value(key, label, text)
            if key == "port_resistance":
                _agrees_on_impedance(label, value, params.get(key))
            params[key] = value
    return params


def _agrees_on_impedance(label, value, already):
    """Refuse a Port resistance that contradicts the impedance the flow's own
    half of the form already said this run is for.

    The pane wins where the two halves overlap -- it is the last-resort field
    (see ``params``) -- and for a sweep's top-of-band that is right, because
    exciting above the band is a real thing to want. This one is not like that.
    The resistance is what the solver normalizes the S11 and VSWR it writes to,
    and the verdict table reads those columns back and labels them with the
    *target's* impedance: letting the pane win quietly would print a curve
    against a reference it was never computed against. So a number that
    disagrees is refused naming both.

    ``inf``/``none`` is not a disagreement about a number -- it is an ideal
    current source rather than a resistor, which is the reason this field is
    still writable at all -- so it is allowed to win. Spelled the way
    ``adv_value`` spells it, and not as "whatever ``float()`` refuses":
    ``float("inf")`` is a number, and comparing it would refuse the one
    override this field is for.
    """
    if already is None or str(value).strip().lower() in ("inf", "none"):
        return
    typed, said = to_float(value, None), to_float(already, None)
    if typed is None or said is None or typed == said:
        return
    raise RuntimeError(
        f"{label}: '{value}' is not the impedance this form is designed for "
        f"({said:g} Ω). Leave the Advanced field blank to take that, or change "
        f"the impedance this form is built for so the two agree."
    )


def pass_knobs(form, params):
    """The knobs of the pass itself: how long to step for, and whether the
    solver may find the board's ground (or source) reference for itself."""
    if _flag(form, "time_auto"):
        time_ns = 0.0  # 0 = run until the port rings down
    else:
        time_ns = to_float(_read(form, "time"), None)
        if time_ns is None or time_ns <= 0:
            raise RuntimeError(
                "Simulation time: enter a positive number of ns, or set "
                "time_auto (ring-down)"
            )
    params["time_ns"] = time_ns
    params["auto_ground"] = _flag(form, "auto_ground")
    return params


def materials(form, params):
    """The per-layer picks as the ordered ``metal_layers`` (each
    ``{"sigma": ...}``) and ``substrate_layers`` (each ``{"eps": ...,
    "loss_tangent": ...}``, or ``None`` for "from board stackup"), plus the
    coating's ``mask_material``.

    One entry per row the form holds, in row order, which is the order the
    config walks the stackup in. A row that is not there is not a layer with a
    default: the lists come up short and the config writer refuses the layer by
    name (config._apply_overrides).
    """
    try:
        from .materials.catalog import MaskCatalog, MetalCatalog, SubstrateCatalog
    except ImportError:
        return params  # the materials package was removed from this install
    metal = MetalCatalog()
    params["metal_layers"] = [
        _sigma(_material(form, f"metal{i}", metal))
        for i in range(_row_count(form, "metal"))
    ]
    substrate = SubstrateCatalog()
    params["substrate_layers"] = [
        _constants(_material(form, f"sub{i}", substrate))
        for i in range(_row_count(form, "sub"))
    ]
    params["mask_material"] = _constants(_material(form, "mask", MaskCatalog()))
    return params


def mask_params(form):
    """What the pre-flight needs to judge the coating: whether it is included
    and the material the form supplies for it, read without parsing every other
    field on the pane (which raises)."""
    from .materials.catalog import MaskCatalog

    out = {"include_mask": _flag(form, "include_mask")}
    try:
        out["mask_material"] = _constants(_material(form, "mask", MaskCatalog()))
    except ValueError as exc:
        # A Custom pick whose fields are not a material yet is exactly the
        # "properties not set" the banner is for, so it travels as the reason
        # there is no material rather than as a broken check.
        out["mask_material_error"] = str(exc)
    return out


# --------------------------------------------------------------------------- #
# the picks
# --------------------------------------------------------------------------- #
def picked(form):
    """Every shared closed list's *value* under the config key it writes. A
    caption an older window saved, and a value this list no longer offers, both
    resolve the way the picker resolves them (choices.Choices.index)."""
    return {
        pick.key: pick.value(pick.index(_pick_text(form, pick)))
        for pick in choices.SHARED
    }


def _pick_text(form, pick):
    return form.get(pick.key) or form.get(WAS.get(pick.key, ""), "")


def preset_index(form):
    """The speed/accuracy stop this form's toggles are, or ``None`` (custom --
    also the outcome for an unparseable cells-across-driven-copper value, since
    no preset can match it)."""
    copper_cells = to_float(_read(form, "copper_cells"), None)
    if copper_cells is not None and copper_cells == int(copper_cells):
        copper_cells = int(copper_cells)
    state = (
        _flag(form, "coarse_air"),
        not _flag(form, "no_refine_xy"),
        "mur" if _flag(form, "mur") else "pml",
        _flag(form, "conformal"),
        _flag(form, "adaptive"),
        copper_cells,
    )
    for i, preset in enumerate(SPEED_PRESETS):
        if state == preset.toggles:
            return i
    return None


# --------------------------------------------------------------------------- #
# the fields
# --------------------------------------------------------------------------- #
def adv_value(key, label, text):
    """One filled-in Advanced field, parsed strictly. Raises naming the field's
    label instead of letting config's float()/int() coercion fail with a bare
    'invalid literal' message."""
    if key == "port_resistance":
        # passed through as a string: the runner also accepts "inf"/"none"
        # (ideal current source)
        if text.lower() in ("inf", "none") or to_float(text, None) is not None:
            return text
        raise RuntimeError(f"{label}: '{text}' is not a number (or inf/none)")
    num = to_float(text, None)
    if num is None:
        raise RuntimeError(f"{label}: '{text}' is not a number")
    if key in _INT_ADV:
        if num < 0 or num != int(num):  # accepts 1e4-style whole numbers
            raise RuntimeError(f"{label}: '{text}' is not a whole number")
        return int(num)
    # Every numeric Advanced field is a size, a frequency, a memory ceiling or
    # a radius: none of them has a meaning below zero, and the runner's
    # reaction to a negative is uneven (a config error for min_raster_mm, a
    # silent fall back to the auto budget for mesh_budget_gb). Catch it here,
    # naming the field, rather than mid-run or not at all.
    if num < 0:
        raise RuntimeError(f"{label}: '{text}' is negative")
    return num


def _copper_cells(form):
    text = _read(form, "copper_cells")
    value = to_float(text, None)
    if value is None or value != int(value) or not 1 <= value <= 5:
        raise RuntimeError(
            f"Cells across driven copper: '{text}' is not a whole number from 1 to 5"
        )
    return int(value)


def _read(form, key):
    """``key`` as the form spells it, or what a fresh form has -- which is what
    the window would show for a key its settings file never held."""
    value = form.get(key)
    return defaults().get(key, "") if value is None else value


def _flag(form, key):
    return parse_bool(_read(form, key))


def refuse_config_spellings(form):
    """Refuse a config key typed into a form, naming the form's spelling.

    A caller who has read ``pcb.yaml`` will write ``cell_mm:`` into a settings
    file, and every key here would otherwise be quietly ignored -- a run at the
    automatic cell, reported as the run that was asked for. The keys a form and
    the config genuinely share (``copper_model``, ``mesh_nudge``, ...) are not
    in this table and pass straight through.
    """
    spelled = dict(SPELLED)
    for key, _label, _hint in ADV_FIELDS:
        spelled[key] = "adv." + key
    wrong = [(key, spelled[key]) for key in sorted(form) if key in spelled]
    if wrong:
        raise RuntimeError(
            "these are config keys, not form keys — a settings file spells "
            "them differently:\n"
            + "\n".join(f"  {key} → {right}" for key, right in wrong)
        )


# --------------------------------------------------------------------------- #
# the material rows
# --------------------------------------------------------------------------- #
# The form spells the loss tangent without the underscore the record uses (it
# was a field named after the symbol on the pane, `tanδ`), and that is the only
# place the two differ.
_STATE_KEY = {"tan_d": "tand"}


def _state_key(field):
    return _STATE_KEY.get(field, field)


def _row_count(form, prefix):
    """How many rows of a kind the form holds: ``metal0``, ``metal1``, ... up
    to the first one that is not there."""
    count = 0
    while f"materials.{prefix}{count}.choice" in form:
        count += 1
    return count


def _material(form, prefix, catalog):
    """One row's material: what its pick names, or one built from the fields
    typed beside it. ``None`` where the pick is the board's own numbers, and a
    ValueError naming the row where it is nothing at all."""
    name = form.get(f"materials.{prefix}.choice", "")
    values = {
        field: to_float(form.get(f"materials.{prefix}.{_state_key(field)}"), None)
        for field in catalog.FIELDS
    }
    return catalog.pick(name, values, prefix)


def _sigma(material):
    return None if material is None else {"sigma": material.sigma}


def _constants(material):
    if material is None:
        return None
    return {"eps": material.eps, "loss_tangent": material.tan_d}
