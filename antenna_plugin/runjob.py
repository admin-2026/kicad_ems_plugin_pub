"""What this product's run needs from its board, and what it makes of a report.

The shared run flow is the same for every plugin built out of this repository
-- read the stackup, plot the gerbers, write the config, mesh, solve, archive
-- and two answers in the middle of it are not:

    ``apply_ports``   the board's markers become the config's ports. One feed
                      marker for an antenna; one per port for an S-parameter
                      sweep.
    ``score``         an archived report, judged. An antenna is designed *for*
                      something -- a band, an impedance, a return loss -- so a
                      plot of |S11| is not yet an answer.

Both used to be methods on the wx Run section, which was the only place a run
could start from. Now there are two frontends and they must not answer
differently, so the answers are here: headless (pcbnew, no wx), reached by a
fixed module name the same way ``config.py`` is
(``emkit.sim.simulate.write_config``). The Run section delegates; the command
line calls the same functions.

``form_params``, ``form_starter`` and ``form_target`` are this product's half
of the *form*: a saved settings file holds one flat dict, and the shared core
translates every key of it but this product's own (``emkit.formparams``). Both
frontends come through here, so a form means one thing whether the window read
it or the command line did.

``form_target`` is the design target a run is scored against, and the form is
the only place it comes from. A product with nothing to judge against answers
``None``, and a report there is reported unjudged rather than half-scored.

``guide_sections``, ``form_options``, ``form_notes`` and ``saved_catalogs`` are
the last four, and the only ones that answer nothing about a run: they are this
product's half of ``<cmd> guide`` -- what it can build, what its form may hold,
what each of its own keys means (and in what unit), and which kinds of entry the
user may save. The core may not name a design or a design target
(``emkit/tests/test_agent_layout.py``), so all of them are reached the same way
everything else product-shaped is -- through this module, by fixed name.
"""

# The frequency the guide's worked example is seeded at. Not a default and
# never used by a run: every relative seed is a multiple of the quarter wave,
# so the millimetres below need *a* frequency to be printed at, and the page
# says which one it picked. Nothing reads it back.
GUIDE_F0_GHZ = 2.45


def _ignore(_text):
    """The default ``note``: do the work and say nothing about it."""


def apply_ports(board, params, note=_ignore):
    """Resolve the placed feed-marker footprint into the run's feed port.

    The box centre and the direction the triangle points (toward the antenna)
    -- the runner infers the trace under that point and severs a one-cell gap
    on the grid, so no marker gerber and no clearance rect is passed. A marker
    the user rotated off a grid axis additionally sets ``rotation_deg``: the
    whole board is rotated in the simulation so the driven trace is
    axis-aligned again.

    A board with no marker leaves ``params`` untouched; refusing that is the
    config writer's, so a run started from anywhere is refused in one set of
    words.
    """
    from .emkit.markers import feed_marker, markergeom

    marker = feed_marker.single_marker(board)  # raises on extras
    if marker is None:
        return params
    params["feed"] = feed_marker.feed_dict(marker)
    note(
        f"feed marker footprint at ({marker['x_mm']}, {marker['y_mm']}) "
        f"gerber mm — dir ({marker['dir_x']}, {marker['dir_y']})"
    )
    rot = markergeom.align_rotation_deg(marker["dir_x"], marker["dir_y"])
    if rot:
        params["rotation_deg"] = rot
        note(
            f"feed runs off-grid; simulating the board rotated {rot:g}° to re-align it"
        )
    return params


def score(dump_path, target):
    """Score the report at ``dump_path`` against ``target`` and leave the
    verdicts beside it, so the report page can say how the antenna measured up
    (``design.run_verdicts``). Returns the payload, or None when there was
    nothing to judge -- no target, no frequency, or a run that stopped before
    its first impedance sweep. An empty verdict table would read like a
    verdict."""
    from .design import run_verdicts

    return run_verdicts.write(dump_path, target)


def form_target(form):
    """The design target ``form`` is aiming at, as an ``Application``: the
    application picked on it (a built-in service or one the user saved), or --
    on the ``Custom…`` sentinel -- one synthesized from the frequency /
    bandwidth / impedance fields beside the picker.

    One place, because there is one target. The form already says what the
    antenna is for; a run scored against anything else would be a run judged
    by something the board's own form does not say.

    Resolved the way every other pick on a form is (``SavedCatalog.pick``), so
    an application this install no longer has raises ``ValueError`` naming it
    rather than quietly becoming the first entry in the list.
    """
    from .applications.catalog import Catalog
    from .emkit.formparams import to_float

    catalog = Catalog()
    return catalog.pick(
        form.get("app", catalog.CUSTOM),
        {
            "f0_ghz": to_float(form.get("freq"), None),
            "bandwidth_mhz": to_float(form.get("bandwidth"), None),
            "impedance_ohm": to_float(form.get("impedance"), None),
            # Blank leaves it free -- shown, not judged, never defaulted -- and
            # a free one is also what decides the threshold the match bandwidth
            # is measured at (``design.measure``), so it is a field and not a
            # constant: a target specified at 15 dB is not met by a 10 dB band.
            "return_loss_db": to_float(form.get("return_loss"), None),
        },
        "Application",
    )


def form_starter():
    """This product's own keys in a fresh form: the design target, and the
    three fields a hand-typed one is typed into.

    All three are **blank**, and that is the point of them: there is no default
    frequency for an antenna, so a starter settings file says what to fill in
    rather than filling it in. ``form_params`` refuses a run until it is.
    """
    from .applications.catalog import Catalog

    return {
        "app": Catalog().CUSTOM,
        "freq": "",
        "bandwidth": "",
        "impedance": "",
        "return_loss": "",
    }


def form_notes():
    """What this product's own keys are, and the unit each is in -- the note
    ``<cmd> guide`` prints beside them.

    A number in a settings file is worth nothing without its unit, and these
    four names do not carry one: ``freq: 2.44`` is gigahertz and
    ``bandwidth: 100`` is megahertz, and nothing but this says so to a caller
    who has never seen the window's labels. The picked key beside them
    (``app``) is described by its own list (``form_options``).

    Here rather than in the core because ``freq`` is a different frequency in
    every flow that has one: an antenna computes a pattern at it, a sweep
    analyses at it.
    """
    return {
        # All four are read on the Custom… target only: a named application
        # carries its own frequency, band, impedance and return loss, which is
        # what picking it is for (``form_params``).
        "freq": (
            "the frequency the radiation pattern is computed at, in GHz (Custom… only)"
        ),
        "bandwidth": "the band the target spans, in MHz (Custom… only)",
        "impedance": (
            "the impedance the target is matched to — and the one the feed "
            "port is driven through, so also what S11 is measured against — "
            "in Ω (Custom… only)"
        ),
        "return_loss": (
            "the return loss the match is judged against — and the depth the "
            "bandwidth is measured at — in dB (Custom… only; blank leaves the "
            "match shown but not judged, and the bandwidth read at 10 dB)"
        ),
    }


def form_params(form, params):
    """This product's half of a form, as run parameters: the pattern
    frequency, parsed strictly and named when it doesn't parse.

    The shared half -- the Advanced pane, the materials, the pass knobs -- is
    ``emkit.formparams``; this is what only an antenna has. Both frontends come
    through here (the wx Design-target section over its own snapshot, the
    command line over a settings file), so a form means one thing whoever read
    it.

    **A named application is the frequency.** The design target beside the
    field (``app``) is not itself a run parameter -- the solver is handed a
    geometry and a frequency, never a purpose -- but a picked one carries the
    frequency it is designed at, and that is the frequency the run solves at.
    The window says this by filling the field from the pick and then hiding it
    (``gui.sections.pattern_freq``): there the field is not the target either.
    Reading the field instead would leave the two halves of one form free to
    disagree -- solving at the typed 2.44 GHz while ``form_target`` judges the
    result against the pick's 2.45 GHz, which is one curve read at two points
    and no warning that it happened.

    So the field is read on ``Custom…`` -- where it *is* the target -- and
    beside a named pick it may only agree, or be blank. A number that does not
    is refused naming both, rather than one of them quietly winning.
    """
    from .applications.catalog import Catalog
    from .emkit.formparams import to_float

    text = form.get("freq", "")
    typed = to_float(text, None)
    catalog = Catalog()
    picked = catalog.get(form.get("app", catalog.CUSTOM))
    if picked is not None:
        # Compared as the window prints it into the field, so a form the window
        # wrote can never disagree with itself over the last digit of a float.
        spelled = f"{picked.f0_ghz:g}"
        if text.strip() and (typed is None or f"{typed:g}" != spelled):
            raise RuntimeError(
                f"Pattern frequency: '{text}' is not what the picked "
                f"Application says ({picked.name} is designed at {spelled} "
                f"GHz). A named application carries its own frequency — leave "
                f"the field blank, or pick '{catalog.CUSTOM}' to type your own."
            )
        params["fpattern_ghz"] = picked.f0_ghz
    elif typed is None or typed <= 0:
        raise RuntimeError(
            f"Pattern frequency: '{text}' is not a positive number (GHz)"
        )
    else:
        params["fpattern_ghz"] = typed
    _port_resistance(form, params)
    return params


def _port_resistance(form, params):
    """The resistance the feed port is driven through -- the design target's
    impedance, for the same reason the pattern frequency is the target's
    frequency.

    **It is not only what drives the port.** The solver normalizes the ``S11``
    and ``VSWR`` columns it writes to this resistance (it is the dump's
    ``geometry.zref``), and the verdict table reads those columns straight out
    of the dump (``design.measure``). Return loss, VSWR and the -10 dB
    bandwidth are therefore all measured against it, while the line over them
    names the *target's* impedance -- so a target scored at one and a port
    driven at another is one curve labelled with a reference it was never
    computed against, and nothing in the report says so.

    A target may leave its impedance free -- ``applications.catalog.check``
    requires a frequency and nothing else, and a free field is shown rather
    than judged. Then there is nothing here to take, and the Advanced field is
    the other place it can be said; ``formparams.advanced`` writes it after
    this, so leaving the key out is how it gets its turn. With neither, the run
    is refused rather than driven at a number this plugin picked for the user.
    """
    ohms = form_target(form).impedance_ohm
    if ohms:
        # As text, which is the shape the Advanced field writes and the shape
        # the config writer passes straight through -- the runner also takes
        # "inf" there, so the key has never been a float and must not become
        # one on only one of the two paths that fill it.
        params["port_resistance"] = f"{ohms:g}"
    elif not str(form.get("adv.port_resistance") or "").strip():
        raise RuntimeError(
            "Impedance: the design target names none, so there is nothing to "
            "drive the feed port at — and S11 has no reference to be measured "
            "against. Give the target an impedance (Ω), or fill in Advanced > "
            "Feed port > Port resistance."
        )


def form_options():
    """This product's closed lists, as ``emkit.choices.Choices`` -- the values
    a settings file may hold for them, which ``<cmd> guide`` prints.

    One -- the design target the form is built around. Its values are the
    catalog's, built-ins and the user's own saved targets, read at the moment
    of asking the way the picker reads them, so a target saved in the window is
    offered here as soon as it is saved. Each is captioned with the spec line
    the window shows under the picker (the band, the impedance, the return
    loss), because a caller reading a bare name has no way to know what picking
    it would aim the run at.

    The sentinel is in the list and captioned as what it means: it is a legal
    saved value, and one a caller will see in a settings file.
    """
    from .applications.catalog import Catalog
    from .emkit.choices import Choices

    catalog = Catalog()
    options = []
    for name in catalog.choices():
        entry = catalog.get(name)  # None for the sentinel: the fields are it
        options.append((name, entry.spec_line if entry else _TYPED_TARGET))
    return (
        Choices(
            key="app",
            label="Application",
            what=(
                "What the antenna is for. The pick carries the frequency a "
                "run is solved at and the band, impedance and return loss it "
                "is scored against — all four, so the frequency/bandwidth/"
                "impedance keys beside it are read on 'Custom…' only."
            ),
            options=tuple(options),
            default=catalog.CUSTOM,
        ),
    )


# What the sentinel pick means, said as a caption rather than as a name: the
# three fields under the picker are the target, instead of describing one.
_TYPED_TARGET = "the frequency, bandwidth and impedance below are the target"


def saved_catalogs():
    """The kinds of saved entry this product offers beyond the shared
    materials: the design target, which only an antenna has.

    The core carries every catalog's *code* -- one copy, nested in every
    plugin -- so shipping a kind and offering it are two different things, and
    this is where the second one is said. Without it ``<cmd> guide`` told a
    signal-integrity user where their design targets were kept, of which there
    are none.
    """
    from .applications.catalog import Catalog

    return (Catalog,)


def guide_sections():
    """This product's half of ``<cmd> guide``: ``(title, body)`` pairs, in
    reading order.

    One section per registered topology, iterated rather than listed, so a
    fourth design is guided by the line it already adds to ``design/registry``
    -- and one section before them on what a design *is* here, because the
    command line cannot draw one and an agent otherwise learns three
    topologies it has no way to place.
    """
    from .design import registry

    sections = [
        ("Designing an antenna, if the board has none yet", _DESIGNING),
        ("Where this product's own code is", _code_map()),
    ]
    for design in registry.DESIGNS:
        sections.append((f"Design: {design.name}", design.guide(GUIDE_F0_GHZ)))
    return tuple(sections)


_DESIGNING = """\
**A run simulates whatever antenna the board already has.** The copper can be
drawn by hand, imported, bought as a module footprint or generated by one of
the designs below -- the solver reads plotted gerbers and knows nothing about
where the shape came from. All a board needs to be simulated is a feed marker
saying which point is driven and which way the antenna runs from it, and
`preflight` names anything else that is missing.

The designs are a *convenience for a board that has no antenna yet*, not a
catalog of what can be simulated. A design is a topology: the shape the copper
is drawn in. Laying one out happens in the plugin's window, not here -- the
command line reads boards and runs the solver, it does not draw on a board.
That flow, so that the numbers a run reports have somewhere to come from:

  1. Mark the area the antenna may use. The wizard places an *area marker*
     (a rectangle plus an arrow footprint, dragged in KiCad) saying where the
     copper may go and which edge the feed enters from.
  2. Pick a topology and a target frequency. Every knob below is seeded from
     the quarter wave at that frequency.
  3. Scan. The wizard sweeps the resonant length -- and whatever else is
     asked -- solving each candidate and scoring it against the target. This
     is many solver runs and is the expensive part.
  4. Place the winner's footprint. It is generated: the radiator is the pad,
     so it carries a net, and pad 1 is always the feed.
  5. Simulate the whole board. That is what `run start` does here, and what
     `results show` reads back.

Steps 1-4 need the window, and a board that arrived with its antenna already
on it skips them entirely. Either way an agent's leverage from a shell is step
5: check the board, run it, read the verdict."""


def _code_map():
    """Where this product's own modules are, resolved off this file so the
    paths are true wherever the plugin was installed. Read-only pointers: the
    install is the shipped artifact, and the place to *change* any of it is
    the repository these were assembled from."""
    import os

    root = os.path.dirname(os.path.abspath(__file__))
    rows = [
        ("design/", "one module per topology; its docstring is the explanation"),
        ("design/registry.py", "the list of them"),
        ("markers/", "the area and feed markers a board carries"),
        ("config.py", "the runner YAML a run writes, key by key"),
        ("runjob.py", "this file: the answers the shared run flow asks a product for"),
    ]
    lines = ["The topologies and the config writer are this product's own:", ""]
    for name, what in rows:
        lines.append(f"  {os.path.join(root, name)}")
        lines.append(f"      {what}")
    return "\n".join(lines)
