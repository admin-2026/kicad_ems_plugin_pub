"""SavedPicks: the Save as… / Update / Delete trio behind a picker.

Two places in the window let the user keep something they typed: the
Design-target section's application picker (gui.sections.pattern_freq) and
every row of the Advanced pane's material table (materials.ui). The widgets
around them have nothing in common -- one is a column of labelled fields, the
other a dense per-layer grid -- but what the three buttons *do* is the same
thing twice, so it is written once, here, over a ``userlib.SavedCatalog``:

  **Save as…** asks for a name and keeps the typed fields under it. Saving over
  one of the user's own asks first; a name that would shadow a built-in is
  refused by the catalog, and the message is shown as it comes.

  **Update** opens the picked saved entry for editing and turns into **Save
  changes**, which writes the fields back under the same name -- no name to
  type and nothing to confirm, the user having pointed at the entry twice.

  **Delete** forgets one, and leaves the picker on ``Custom…`` holding its
  numbers, so one deleted by mistake can be saved straight back.

Update and Delete show for the user's own entries only: a built-in can be
neither changed nor removed.

The host keeps its own widgets: it hands over the picker and two callbacks --
``read()`` for the typed fields and ``on_change()`` to re-derive its own UI --
and asks ``is_typing()`` whether its fields are live (the ``Custom…`` pick, and
a saved entry being updated: the two states where what is on screen is the
entry rather than a description of one). It also supplies the button factory,
so the buttons are built and placed the host's way and this owns none of the
layout.

Because the three wx dialogs are one method each, a test drives the whole flow
by replacing them -- no window needed (tests/test_target_form.py).
"""

import wx

# The Update button's two labels: it opens the picked saved entry for editing,
# and then finishes the edit it opened.
_EDIT = "Update"
_COMMIT = "Save changes"


class SavedPicks:
    def __init__(
        self,
        parent,
        choice,
        catalog,
        *,
        read,
        on_change,
        button,
        on_edit=None,
        log=None,
    ):
        self.parent = parent  # the window the dialogs are shown over
        self.choice = choice
        self.catalog = catalog
        self._read = read  # () -> the typed fields, as the catalog takes them
        self._on_change = on_change  # () -> host re-derives its own UI
        self._on_edit = on_edit  # () -> an edit just opened (the host may focus)
        self._log = log
        # The saved entry whose fields are open for editing, or None. Held by
        # name rather than as a flag so it can never outlive the pick it
        # belongs to -- see is_editing.
        self._editing = None
        self.save_btn = button("Save as…", self._on_save)
        self.update_btn = button(_EDIT, self._on_update)
        self.delete_btn = button("Delete", self._on_delete)

    # --- state ----------------------------------------------------------------
    def name(self):
        """The current pick's label."""
        return self.choice.GetStringSelection()

    def entry(self):
        """The picked entry, or ``None`` when the pick is the Custom sentinel
        (or a kind's own sentinel) -- meaning the typed fields are the entry."""
        return self.catalog.get(self.name())

    def is_custom(self):
        return self.name() == self.catalog.CUSTOM

    def is_saved(self):
        """Whether the pick is one of the user's own -- the ones with an Update
        and a Delete."""
        return self.catalog.is_user(self.name())

    def is_editing(self):
        """Whether the picked saved entry is open for editing (Update). Tied to
        the pick, so a pick that moved on has ended the edit whether or not
        anything remembered to say so."""
        return self._editing is not None and self._editing == self.name()

    def is_typing(self):
        """Whether the host's fields are the entry right now -- 'Custom…', or a
        saved entry being updated. The host shows or enables them by this, and
        it is also the one state in which typing must not snap the pick away."""
        return self.is_custom() or self.is_editing()

    # --- the picker -----------------------------------------------------------
    def on_pick(self):
        """The host's picker fired: any edit in flight is over, since the fields
        are about to hold the new pick's numbers instead."""
        self._editing = None

    def refresh_choices(self, select=None):
        """Rebuild the picker from the catalog -- the saved entries are a file
        this window's other pages and other sessions also write, so the list is
        re-read rather than remembered. Keeps the current pick (or takes
        ``select``); a pick that no longer exists falls back to 'Custom…',
        leaving the fields it filled in place rather than silently standing for
        something else."""
        want = select or self.name()
        self.choice.Clear()
        for label in self.catalog.choices():
            self.choice.Append(label)
        if want and self.choice.FindString(want) != wx.NOT_FOUND:
            self.choice.SetStringSelection(want)
        else:
            self.choice.SetStringSelection(self.catalog.CUSTOM)

    def restore_pick(self, name):
        """Set the picker to the ``name`` a settings file remembered: rebuild
        the choices first (it may be an entry saved after this picker was
        built -- on another page of this window, or in the session that wrote
        the file), and fall back to 'Custom…' when it names an entry that no
        longer exists. The fields restored beside it are then what that entry
        was, instead of whichever pick the picker happened to be on. A blank
        name leaves the pick alone.

        The host still restores its own fields; this is only the pick."""
        self.on_pick()  # the restored fields are not somebody's edit
        self.refresh_choices()
        if name and self.choice.FindString(name) == wx.NOT_FOUND:
            name = self.catalog.CUSTOM
        if name:
            self.choice.SetStringSelection(name)

    def sync_buttons(self):
        """Show the buttons this pick has and say which half of its job Update
        is on. Called from the host's own re-derive, which is what arranges the
        fields beside them."""
        self.save_btn.Show(self.is_typing())
        saved = self.is_saved()
        self.update_btn.SetLabel(_COMMIT if self.is_editing() else _EDIT)
        self.update_btn.Show(saved)
        self.delete_btn.Show(saved)

    # --- the flows ------------------------------------------------------------
    def _on_save(self, event=None):
        name = self.ask_name()
        if name is not None:
            self.save_as(name)

    def save_as(self, name):
        """Save the typed fields under ``name`` and pick it; True when saved.
        Asks first when the name is one of the user's own -- Save as… under a
        name already taken means replacing it, which nobody said out loud
        (Update did, so it doesn't ask)."""
        name = (name or "").strip()
        if self.catalog.is_user(name) and not self.confirm(
            f"'{name}' is already saved. Replace it?", f"Replace {self.catalog.NOUN}"
        ):
            return False
        return self._store(name, "Saved")

    def _on_update(self, event=None):
        """**Update**, then **Save changes**: the two clicks of one edit. The
        first opens the picked entry's fields (already holding its numbers, so
        there is something to correct rather than something to retype); the
        second writes what is in them back under the same name."""
        if not self.is_saved():
            return
        if self.is_editing():
            self.commit_edit()
            return
        self._editing = self.name()
        self._on_change()
        if self._on_edit is not None:
            self._on_edit()  # the fields just came live, to be typed in

    def commit_edit(self):
        """Write the edited fields back to the entry being edited and close the
        edit; True when they were saved. Nothing is asked and nothing renamed --
        it is the entry the user picked and pressed Update on. A field the
        catalog refuses leaves the edit open, message shown and numbers still
        there to fix."""
        if not self.is_editing():
            return False
        return self._store(self._editing, "Updated")

    def _on_delete(self, event=None):
        name = self.name()
        if not self.catalog.is_user(name):
            return
        if not self.confirm(
            f"Delete the saved {self.catalog.NOUN} '{name}'?", "Delete"
        ):
            return
        try:
            self.catalog.delete(name)
        except OSError as exc:
            self.error(f"Could not delete the {self.catalog.NOUN}: {exc}")
            return
        self._editing = None  # deleted mid-edit: there is nothing to write to
        self.refresh_choices(select=self.catalog.CUSTOM)
        self._on_change()
        self.log(f"Deleted {self.catalog.NOUN} '{name}'")

    def _store(self, name, verb):
        """The one way an entry reaches the file (Save as… and Save changes are
        the same write under different names): save it, end any edit, and leave
        the picker on it -- so what was just written is now the pick. False,
        with the message shown, when the catalog or the disk refused it."""
        try:
            entry = self.catalog.save(name, **self._read())
        except ValueError as exc:
            self.error(str(exc))
            return False
        except OSError as exc:
            self.error(f"Could not save the {self.catalog.NOUN}: {exc}")
            return False
        self._editing = None
        self.refresh_choices(select=entry.name)
        self._on_change()
        self.log(f"{verb} {self.catalog.NOUN} '{entry.name}' — {entry.spec_line}")
        return True

    # --- the three dialogs (one method each: a test answers them) -------------
    def ask_name(self, default=""):
        """Ask for the name to save under; None when the user cancelled."""
        dialog = wx.TextEntryDialog(
            self.parent,
            f"Name for this {self.catalog.NOUN}:",
            f"Save {self.catalog.NOUN}",
            default,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            return dialog.GetValue()
        finally:
            dialog.Destroy()

    def confirm(self, message, title):
        return wx.MessageBox(message, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES

    def error(self, message):
        wx.MessageBox(message, self.catalog.NOUN.capitalize(), wx.OK | wx.ICON_ERROR)

    def log(self, text):
        if self._log is not None:
            self._log(text)
