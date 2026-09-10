"""The closed lists a form picks from, written once for both frontends.

A knob whose value comes from a fixed set is three things at once: a picker in
the window, a key in the saved settings, and a word in the runner's config.
They used to be spelled differently in each -- the window saved the *caption*
it happened to draw (``model: sibc — skin-effect loss``) under a key of its own,
while the run that caption started wrote ``copper_model: sibc``. One knob, two
vocabularies, and neither file said what the other would accept, which is what
made a saved form unreadable to anything that had not first read the wx section
that wrote it.

So a closed list is a :class:`Choices` here, and it carries everything either
side needs: the key it is saved under (the config key, where the runner takes
one), the label the window draws, one line saying what picking one does, the
values with a note each, and the one a fresh form starts on. Three readers, no
second copy:

    gui.sections.advanced   draws the picker, and saves the *value*
    formparams              resolves a saved form's pick into a run parameter
    agent.guide             prints the vocabulary, for a caller editing a
                            settings file with no window to open
    <product>.runjob        contributes the product's own (``form_options``)

Pure stdlib -- no wx, no pcbnew -- because the command line reads it on
whatever Python the caller has (dev_docs/frontend-lazy-loading.md).
"""

from typing import NamedTuple


class Choices(NamedTuple):
    """One closed list: what it is called, what it may be, where it starts."""

    # What a saved form calls it -- and, for a knob the runner takes, the
    # config key it writes. One name across the settings file, the run
    # parameters and pcb.yaml, so a caller that has read one has read all three.
    key: str
    label: str  # what the window calls it
    what: str  # one line: what picking one of these does
    options: tuple  # ``(value, note)`` per entry; a note may be ""
    default: str  # the value a fresh form starts on

    def values(self):
        return tuple(value for value, _note in self.options)

    def labels(self):
        """What a picker shows: the value, then its note after an em dash. The
        value leads because it is the name the config, the log and the solver's
        messages use -- the note is a gloss on it, not a name for it."""
        return [f"{value} — {note}" if note else value for value, note in self.options]

    def index(self, text):
        """Where ``text`` sits in this list, for a picker to select.

        Matched against the values *and* against the labels, because a settings
        file written before the value was the saved thing holds the caption the
        picker drew. Anything else -- a blank, or a value this list no longer
        offers -- answers the default's index rather than its neighbour's: a
        pick that has gone away must not silently become another one.
        """
        for position, (value, label) in enumerate(zip(self.values(), self.labels())):
            if text in (value, label):
                return position
        return self.values().index(self.default)

    def value(self, position):
        """The value at ``position``: what a picker's selection saves and what
        the run writes. Out of range -- wx answers -1 for no selection at all
        -- is the default."""
        if 0 <= position < len(self.options):
            return self.options[position][0]
        return self.default


COPPER_MODEL = Choices(
    key="copper_model",
    label="Metal model",
    what="How a conductor is represented in the FDTD grid.",
    options=(
        ("sheet", "fast, lossless"),
        ("sibc", "skin-effect loss"),
        ("slab", "volumetric foil"),
    ),
    # Not the config default (that one is `sheet`): a form always writes this
    # key, so what the picker starts on is the only default a run ever sees.
    default="sibc",
)

GROUND_CHECK = Choices(
    key="ground_check",
    label="Ground check",
    what="What a port with no DC path to ground does to a run.",
    options=(
        ("strict", "stop the run"),
        ("warn", "run, and say so"),
        ("off", "do not look"),
    ),
    default="strict",
)

# The closed lists every product has, because the shared Advanced pane draws
# them. A product's own are reached through its runjob (see ``pickers``).
SHARED = (COPPER_MODEL, GROUND_CHECK)


def pickers():
    """Every closed list this install offers: the shared ones, then whatever
    the product adds.

    Through ``runjob`` by fixed module name, the way every other
    product-shaped answer is reached -- nothing here may know what a product
    picks from. A product with no list of its own answers ``()``.
    """
    from .. import runjob

    return SHARED + tuple(runjob.form_options())
