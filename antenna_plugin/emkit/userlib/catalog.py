"""SavedCatalog: the built-ins, the user's own, and the Custom sentinel.

One object answers everything a picker of a given kind needs -- what the
choices are, what a pick means, whether it is the user's (and so may be changed
or removed), and what happens when they save one. A saved entry is built by the
same code the built-ins are, so nothing downstream can tell where it came from.

What a kind must say for itself (the subclass contract):

  ``FILENAME``   the file its saved entries live in (``store.UserStore``)
  ``FIELDS``     the fields an entry is made of, in record order; they are read
                 off an entry by name, so an entry's attributes must match
  ``NOUN``       what one of them is called in a message ("metal")
  ``CUSTOM``     the sentinel pick whose fields are typed rather than picked
  ``builtin_names()``  the fixed catalog's labels, in picker order
  ``builtin(name)``    one of them, or ``None``
  ``build(name, values)``  an entry from a name and its fields
  ``check(values)``    raise ``ValueError`` saying what to type when ``values``
                       don't make an entry

``check`` is the one rule that serves three callers at once: it refuses a save,
it is what a hand-typed ``Custom…`` pick is validated against, and it drops a
record from a file somebody hand-edited into nonsense. So a kind can't end up
judging the same numbers differently depending on where they came from.

Pure stdlib -- the dialog turns the ``ValueError`` raised here into the message
it shows (gui.savedpick).
"""

from .store import NAME, UserStore


def _number(value):
    """A stored field as a float, or ``None`` when it is absent or not a number
    -- a hand-edited file can hold anything."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SavedCatalog:
    FILENAME = None
    FIELDS = ()
    NOUN = "entry"
    CUSTOM = "Custom…"

    def __init__(self, store=None):
        self.store = UserStore(self.FILENAME) if store is None else store

    # --- what a kind says for itself ------------------------------------------
    def builtin_names(self):
        raise NotImplementedError

    def builtin(self, name):
        raise NotImplementedError

    def build(self, name, values):
        raise NotImplementedError

    def check(self, values):
        """Raise ``ValueError`` when ``values`` (a dict of ``FIELDS``) don't
        make an entry. The default kind demands nothing."""

    def fields_of(self, entry):
        """``entry``'s fields as a record dict. Read off the entry by the names
        in ``FIELDS`` -- an entry stores what it was built with (or derives it,
        as a design target's bandwidth is derived from its band edges), so this
        is what goes back to the file, never the raw typed values."""
        return {f: getattr(entry, f, None) for f in self.FIELDS}

    # --- what the picker shows ------------------------------------------------
    def choices(self):
        """Picker labels: the built-ins, then the user's saved entries, then
        the Custom sentinel last."""
        return list(self.builtin_names()) + self.saved_names() + [self.CUSTOM]

    def saved(self):
        """Every usable saved entry, in file order. A record the kind's own
        ``check`` refuses is skipped rather than offered: a picker entry that
        can't answer what it is would be worse than one fewer."""
        entries = [self._entry(record) for record in self.store.load()]
        return [entry for entry in entries if entry is not None]

    def saved_names(self):
        return [entry.name for entry in self.saved()]

    def get(self, name):
        """The picked entry -- built-in or saved -- or ``None`` for the Custom
        sentinel and for a label neither half knows (both meaning: the
        hand-typed fields are the entry). A kind whose built-in list has a
        sentinel of its own ("From board stackup") answers ``None`` for it
        too, which is that sentinel's meaning."""
        return self.builtin(name) or self.get_saved(name)

    def get_saved(self, name):
        for entry in self.saved():
            if entry.name == name:
                return entry
        return None

    def pick(self, name, values, label):
        """What a form's pick stands for: the built-in or saved entry called
        ``name``, or -- on the Custom sentinel -- one built from ``values``,
        the fields typed beside the picker.

        ``None`` where the pick means "leave the board's own numbers" (a kind
        whose built-in list has a sentinel of its own). Anything that is not an
        entry raises ``ValueError`` naming ``label`` -- the layer, or whatever
        the caller calls this pick -- because a pick that stands for nothing
        must not quietly become the first thing in the list.

        Both frontends resolve a pick through here: a material row does it from
        its widgets (materials.ui) and ``formparams`` from a saved form, so a
        run started either way means the same by the same word.
        """
        if name != self.CUSTOM:
            entry = self.get(name)
            if entry is None and name not in self.builtin_names():
                raise ValueError(
                    f"{label}: '{name}' is no longer a saved {self.NOUN} — pick another"
                )
            return entry
        try:
            self.check(values)
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from None
        return self.build(self.CUSTOM, values)

    def is_user(self, name):
        """Whether ``name`` is one of the user's saved entries -- the ones that
        can be updated and deleted."""
        return self.get_saved(name) is not None

    # --- saving ---------------------------------------------------------------
    def validate_name(self, name):
        """The name an entry may be saved under, stripped. Raises
        ``ValueError`` naming the problem when it can't be used: a saved entry
        that shadowed a built-in would leave the picker with two entries
        meaning different things, and a settings file could no longer say which
        one was picked."""
        name = (name or "").strip()
        if not name:
            raise ValueError(f"Give the {self.NOUN} a name.")
        if name == self.CUSTOM or name in self.builtin_names():
            raise ValueError(f"'{name}' is a built-in {self.NOUN} — pick another name.")
        return name

    def save(self, name, **values):
        """Save ``values`` under ``name`` and return the entry, replacing a
        saved one of the same name. Fields the kind doesn't know are dropped
        and ones it leaves free stay free -- shown, not judged, never
        defaulted."""
        name = self.validate_name(name)
        values = {f: values.get(f) for f in self.FIELDS}
        self.check(values)
        entry = self.build(name, values)
        record = {NAME: name}
        record.update(self.fields_of(entry))
        self.store.save(record)
        return entry

    def delete(self, name):
        """Forget the saved entry called ``name``; ``True`` when there was one
        (a built-in is never touched)."""
        return self.store.delete(name)

    # --- records --------------------------------------------------------------
    def _entry(self, record):
        """One stored record as an entry, or ``None`` when it isn't one."""
        values = {f: _number(record.get(f)) for f in self.FIELDS}
        try:
            self.check(values)
        except ValueError:
            return None
        return self.build(str(record[NAME]).strip(), values)
