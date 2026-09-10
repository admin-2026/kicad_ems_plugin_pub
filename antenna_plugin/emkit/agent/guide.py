"""Assembling the briefing ``guide`` prints.

The one page a caller with no context reads before its first verb. Four
sources, none of them written for it:

    guide.md                 the shared preamble -- the command, the loop, the
                             rules, the folder beside the board
    formparams / choices     the settings file's vocabulary: every key a form
                             holds and every value a pick may take, read off
                             the tables both frontends translate through
    userlib catalogs         the open lists: every name a picker offers, the
                             built-in table and the user's own file alike,
                             with the numbers each name stands for
    verbs.VERBS              the verb table, generated, so it cannot drift
                             from the parser
    this install's own paths where to go for detail the page does not hold
    runjob                   what only the product can say: its own sections,
                             what its own form keys mean and in which unit,
                             and which kinds of entry it lets the user save

Separate from ``verbs/guide.py`` because a verb does not compute, and putting
four sources in order is computing. The verb maps an argv to one call here.

**Nothing here restates a verb's docstring.** Argparse already prints those,
in full, under ``<verb> --help``, and a page that copied them would be a
second copy of the manual with nobody watching the two. The table below is a
name, a line and a pointer at the real thing.

**The preamble is a file, not a string literal.** It is prose, it is edited as
prose, and ``tools/assemble.py`` copies ``emkit/`` wholesale so it ships with
no staging step. Its product placeholders are substituted *here*, at print
time, rather than at assemble time the way a help page's are -- a help page is
shown as the file it is, with no render step, and this command line **is** the
render step, so the file keeps its tokens and cannot be staged stale.
"""

import os

from . import render

# Beside this module, and read on every ``guide``: a page is printed once and
# the file is small, so there is nothing here worth caching.
PREAMBLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guide.md")

# The install this is running out of: this file -> agent/ -> emkit/ -> the
# package. The one root the map below is written against, and it is true by
# construction on whatever machine it prints on rather than being a path
# anybody wrote down.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The map: where to go for the detail this page does not hold, as paths under
# ROOT. Deliberately short and deliberately opinionated -- a directory listing
# invites an agent to read the whole tree, and the two places that actually
# answer questions are a verb's docstring and (through the product's own
# sections) a design's.
CODE_MAP = (
    ("emkit/agent/verbs", "one module per verb; its docstring is that verb's manual"),
    ("emkit/sim", "what the verbs call: drive the solver, read what it wrote"),
    (
        "emkit/config.py",
        "every run knob the settings file sets, what it does and what 0 means",
    ),
    ("emkit/help/cli.html", "the same ground as this page, written for a human"),
)


def page():
    """The whole briefing as one string."""
    out = []
    for title, body in sections():
        out.append(f"## {title}\n\n{body}" if title else body)
    return "\n\n".join(out)


def sections():
    """``(title, body)`` pairs in reading order. A title of ``""`` is a body
    that carries its own headings, which is the preamble and nothing else.

    Sections are how the headings stay consistent across four sources; they
    are not a wire format. ``--json`` hands back the rendered page, so nothing
    downstream parses this and nothing has to keep it stable.
    """
    return (
        ("", preamble()),
        ("The settings file, key by key", form_keys()),
        ("What a picked value may be", form_options()),
        ("What a picked name stands for", catalog_entries()),
        ("The verbs", verb_table()),
        ("Where this plugin's code is", code_map()),
    ) + product_sections()


def preamble():
    """``guide.md`` with this product's facts written into it."""
    with open(PREAMBLE, encoding="utf-8") as page_file:
        text = page_file.read()
    for token, value in _substitutions():
        text = text.replace(token, value)
    return text.strip()


def _substitutions():
    """What the preamble's placeholders stand for on this install.

    The same ``{{token}}`` convention ``tools/assemble.py`` uses on the help
    pages, on purpose, so a reader of either file recognises the other's --
    but substituted here rather than there, because this is a render step and
    a help page is not.
    """
    from ... import product
    from ..sim import simulate
    from . import shim

    return (
        ("{{product}}", product.NAME),
        ("{{command}}", shim.STEM),
        # The shortcut as a path and the interpreter baked into it: what a
        # shell that cannot find the *name* still has (a POSIX shell on
        # Windows, where PATH is registered for cmd and the extension is
        # .cmd). Neither asks anything of the machine it prints on.
        ("{{shim}}", shim.path()),
        ("{{python}}", shim.interpreter()),
        ("{{launcher}}", shim.LAUNCHER),
        ("{{dump}}", simulate.DUMPS[simulate.REPORT]),
    )


def saved_kinds():
    """Every kind of entry this install lets the user save: the shared pane's
    materials, then whatever the product keeps a picker of its own for.

    The same arrangement as ``choices.pickers()``, and for the same reason --
    the core ships the code for kinds a given product never offers, so *which*
    of them a page may name is the product's answer and is asked for through
    ``runjob``. A flow whose only saved entries are materials answers ``()``.
    """
    from ... import runjob
    from ..materials.catalog import MaskCatalog, MetalCatalog, SubstrateCatalog

    return (MetalCatalog, SubstrateCatalog, MaskCatalog) + tuple(
        runjob.saved_catalogs()
    )


# What a row that is the user's own is flagged with. A column rather than a
# suffix, and only there when a kind has any: the question it answers is which
# of these names is in the file above the table, and on a fresh install the
# answer is none of them.
SAVED = "(saved)"


def catalog_entries():
    """Every name a picker offers, and the numbers behind it.

    The open lists, as against ``form_options()``'s closed ones: a pick here is
    a *name* looked up in a catalog that the user may add to, so what the legal
    values are is a question about this machine and cannot be a table in a
    module. Printed rather than pointed at because the alternative is what a
    caller had before -- a settings file holding `FR-4` and nothing anywhere
    saying what else it would have taken, or what that one means.

    Off the catalogs themselves -- the file name, the noun, the fields and the
    rule are each kind's own (``userlib.catalog``) -- and off ``saved_kinds()``
    for which ones there are, so a kind added tomorrow is on this page the day
    it lands and nothing here can go stale.
    """
    from ..userlib.store import NAME

    lines = [
        "A form holds a *name* (`materials.sub1.choice: FR-4`), and this is the\n"
        "table that name is looked up in. Each kind is a built-in list plus\n"
        "whatever the user saved from that picker, and the saved half is a JSON\n"
        "file of *theirs* rather than a project's, so one copy serves every board\n"
        f"on this machine. The rows marked `{SAVED}` are the ones in the file:",
        "",
    ]
    for kind in saved_kinds():
        lines += _catalog_block(kind())
        lines.append("")
    lines.append(
        "The window writes those files and no verb here does -- a missing one is\n"
        f"a user who has saved none of that kind. They are plain JSON (a `{NAME}`\n"
        "and the fields above it, per record) and can be read and edited without\n"
        "the window. A record that does not meet the rule beside its kind is\n"
        "skipped when the file is read, and skipped silently: an edit that never\n"
        "showed up in a picker is an edit that broke the rule."
    )
    return "\n".join(lines)


def _catalog_block(catalog):
    """One kind as its own little table: the file, the rule a record is held
    to, then a row per name -- the built-ins, the user's own, and the sentinel
    whose fields are typed rather than picked, in the order the picker shows
    them (``SavedCatalog.choices``).

    The header row's cells are the field names, so a number under one is read
    off the line above it rather than labelled twice on every row -- which is
    what keeps a four-field kind's rows inside a terminal.
    """
    saved = set(catalog.saved_names())
    rows = [
        (name, name in saved) + _stands_for(catalog, name) for name in catalog.choices()
    ]
    name_w = max([len(catalog.NOUN) + 1] + [len(row[0]) for row in rows])
    mark_w = len(SAVED) if saved else 0
    field_w = [
        max([len(field)] + [len(row[2][i]) for row in rows if row[2]])
        for i, field in enumerate(catalog.FIELDS)
    ]

    def line(name, mark, cells, note):
        left = f"{name:<{name_w}}"
        if mark_w:
            left += "  " + f"{mark:<{mark_w}}"
        right = (
            note
            if cells is None
            else "  ".join(f"{cell:>{width}}" for cell, width in zip(cells, field_w))
        )
        return ("      " + left + "  " + right).rstrip()

    return [
        "  " + str(catalog.store.path),
        "      to count as one: " + _rule(catalog),
        line(catalog.NOUN + ":", "", list(catalog.FIELDS), ""),
    ] + [
        line(name, SAVED if is_saved else "", cells, note)
        for name, is_saved, cells, note in rows
    ]


def _stands_for(catalog, name):
    """``(cells, note)`` for one pick: either its fields as text, or -- for a
    pick that stands for no record -- what it means instead.

    Two picks stand for no record, and ``SavedCatalog.pick`` is where both are
    defined: the ``Custom…`` sentinel, whose fields are typed into the form
    beside it, and a built-in that resolves to ``None``, which is a kind whose
    list leads with a sentinel meaning *keep what the board itself says*.
    """
    entry = None if name == catalog.CUSTOM else catalog.get(name)
    if entry is None:
        if name == catalog.CUSTOM:
            return (None, f"the fields typed beside the picker are the {catalog.NOUN}")
        return (None, "whatever the board itself says")
    record = catalog.fields_of(entry)
    return ([_number_text(record[field]) for field in catalog.FIELDS], "")


def _rule(catalog):
    """What a record must hold to be one, in the kind's own words.

    Asked by handing ``check`` a record with nothing in it, which is what a
    file missing the field would yield: the message it raises is written to
    say what to type (``userlib.catalog``), and it is the same rule that
    refuses a save and drops a hand-edited record -- so printing it here can
    never describe a rule the file is not actually held to.
    """
    try:
        catalog.check({field: None for field in catalog.FIELDS})
    except ValueError as exc:
        return str(exc)
    return f"nothing in particular -- any record is a {catalog.NOUN}"


def _number_text(value):
    """One stored field for a table cell. ``%g``, so a conductivity and a loss
    tangent are both a few characters wide; a field the user left free says so
    rather than printing as a zero it is not."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "free"


# The core's own typed keys, said in words because their names do not say it.
# **A number is worth nothing without its unit**: `time: 12` is twelve of
# something, and a reader who has never seen the window has no way to find out
# which. Every `adv.` field carries its unit in its own name (`_mm`, `_ghz`,
# `_gb`) and its label besides, and a bool is a bool -- so what is left is
# these three, plus the one bool that is not just a bool: what it turns on is a
# *file*, and a caller with no window is the reader that file is for.
SHARED_NOTES = {
    "time": "how long to step for, in ns (read only when time_auto is false)",
    "copper_cells": "cells across the driven copper, a whole number from 1 to 5",
    "feed_layer": "the copper layer the feed sits on, a KiCad layer name (F.Cu)",
    "output_json": (
        "also write the run's numbers as bare JSON beside the browser dump — "
        "turn this on to read a run back with anything but the report page"
    ),
}


def key_notes():
    """What each form key *is*, keyed by the key: the note printed beside it.

    Assembled rather than written, so the three sources that already know
    cannot drift from the page. The Advanced fields carry the label and hint
    their own pane draws (``options.ADV_FIELDS``), a picked key carries its
    list's label -- the values themselves are the next section -- and the
    product's own keys are the product's to describe (``runjob.form_notes``),
    since ``freq`` means a different frequency in each flow that has one.

    A key with nothing here prints without a note, which is the right answer
    for a bool: its name is the whole of what it is.
    """
    from ... import runjob
    from .. import choices
    from ..options import ADV_FIELDS

    notes = dict(SHARED_NOTES)
    for key, label, hint in ADV_FIELDS:
        notes["adv." + key] = f"{label} — {hint}" if hint else label
    for pick in choices.pickers():
        notes[pick.key] = pick.label
    notes.update(runjob.form_notes())
    return notes


def form_keys():
    """Every key a saved form holds, with what a fresh one has in it and what
    it is.

    Off ``formparams`` -- the table both frontends translate through -- so a
    knob added to the window is on this page the day it lands, and the value
    printed beside each key is literally what ``settings init`` would write.

    The material rows are described rather than listed: how many there are is a
    property of the board, not of the plugin.
    """
    from ... import runjob
    from .. import formparams
    from ..materials.catalog import MaskCatalog, MetalCatalog, SubstrateCatalog

    form = dict(formparams.defaults())
    form.update(runjob.form_starter())
    lines = [
        "A form is flat: one `key: value` per line, `#` comments ignored, no\n"
        "nesting anywhere. A blank value means the runner's own automatic one\n"
        "-- which is what every `adv.` field is for -- and a bool is\n"
        "`true`/`false`. These are the keys, with what a fresh form holds and,\n"
        "after the `#`, what the key is and the unit it is in:",
        "",
    ]
    lines += _key_lines(form)
    lines += [
        "",
        "Plus one block per layer of the board being simulated, in board order\n"
        "-- a copper foil's metal, a dielectric gap's laminate, and the coating.\n"
        "The `.choice` is a name from the catalogs below; the fields beside it\n"
        "are read only when it is `" + MetalCatalog.CUSTOM + "`:",
        "",
    ]
    for prefix, kind in (
        ("metal<i>", MetalCatalog),
        ("sub<i>", SubstrateCatalog),
        ("mask", MaskCatalog),
    ):
        keys = ", ".join(
            f"materials.{prefix}.{formparams._state_key(field)}"
            for field in kind.FIELDS
        )
        lines.append(f"  materials.{prefix}.choice — the {kind.NOUN} on that row")
        lines.append(f"      {keys}")
    lines += [
        "",
        "`settings init` writes all of that for a board, so the rows match its\n"
        "stackup without anybody counting layers.",
        "",
        "**Do not spell a key the way `pcb.yaml` spells it.** A form is the\n"
        "window's vocabulary and the config is the runner's; where they differ,\n"
        "the config key is refused by name rather than quietly ignored:",
        "",
    ]
    spelled = dict(formparams.SPELLED)
    for key, _label, _hint in formparams.ADV_FIELDS:
        spelled[key] = "adv." + key
    lines += [f"  {key} → {right}" for key, right in sorted(spelled.items())]
    return "\n".join(lines)


def _key_lines(form):
    """The key list itself: ``key: value``, aligned, with each key's note
    behind a ``#`` -- which is a comment in the very file being described, so
    a line of this page can be pasted into one and stay legal."""
    notes = key_notes()
    pairs = [
        (f"{key}: {value}".rstrip(), notes.get(key, ""))
        for key, value in sorted(form.items())
    ]
    width = max(len(text) for text, _note in pairs)
    return [
        f"  {text:<{width}}  # {note}" if note else f"  {text}" for text, note in pairs
    ]


def form_options():
    """Every closed list this install has: the key it is saved under, what
    picking one does, its values and where a fresh form starts.

    Off ``choices.pickers()`` -- the same table the window builds its pickers
    from, plus whatever the product adds -- so the list printed here is the
    list the pane offers and neither can drift from the other. Without it a
    value like `copper_model: sibc` says nothing about what else it could have
    been, and the vocabulary would live in a wx picker where nothing but the
    window could read it.
    """
    from .. import choices

    out = []
    for pick in choices.pickers():
        out.append(f"{pick.key} — {pick.label}: {pick.what}")
        for value, note in pick.options:
            line = f"{value} — {note}" if note else value
            # Whether it is the one a fresh form starts on, said in words
            # rather than marked with a glyph: "the default" is a fact about
            # the list and reads as one.
            out.append(f"  {line}  (default)" if value == pick.default else f"  {line}")
        out.append("")
    return "\n".join(out).rstrip()


def verb_table():
    """Every verb the parser offers, off the same tuple the parser builds
    from. Generated rather than written, so a verb added tomorrow is on this
    page the day it lands."""
    from . import shim, verbs

    rows = []
    for verb in verbs.VERBS:
        topics = getattr(verb, "TOPICS", ())
        if len(topics) == 1:
            # One topic is not a choice, so the pair is the verb's real name.
            rows.append({"verb": f"{verb.NAME} {topics[0]}", "what": verb.HELP})
            continue
        rows.append({"verb": verb.NAME, "what": verb.HELP})
        if topics:
            # Spelled out rather than listed as bare topics: what a caller
            # types is the pair, and one line of HELP for five of them said
            # the same thing five times.
            spelled = "  ".join(f"{verb.NAME} {topic}" for topic in topics)
            rows.append({"verb": "", "what": spelled})
    return "\n".join(
        render.columns(rows, (16, "verb"), (0, "what"))
        + [
            "",
            f"`{shim.STEM} <verb> --help` is that verb's own manual, in full.\n"
            "It is longer than the line above, and it is the thing to read\n"
            "before using a verb you have not used before.",
        ]
    )


def code_map():
    """Where this install's code is, resolved rather than written down.

    Absolute, because the point is that a reader can open one -- and this is
    the *installed* copy, which is a shipped artifact rather than a checkout:
    a file here is worth reading and is never worth editing.
    """
    lines = [
        "This plugin is Python, and it is right here. Two places answer\n"
        "questions this page does not: a verb's own module, and -- below,\n"
        "through the product's own sections -- what it can build.",
        "",
    ]
    for name, what in CODE_MAP:
        lines.append("  " + os.path.join(ROOT, *name.split("/")))
        lines.append(f"      {what}")
    return "\n".join(lines)


def product_sections():
    """What only this product can say: its designs, its markers, its own code.

    Through ``runjob`` by fixed module name, the way every other
    product-shaped answer is reached, because nothing under ``emkit/`` may
    name a design. A product with nothing to add answers ``()``.
    """
    from ... import runjob

    return tuple(runjob.guide_sections())
