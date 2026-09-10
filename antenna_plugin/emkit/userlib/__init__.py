"""The user's own library: named entries they typed once and keep.

Several of the dialog's pickers offer a fixed catalog plus a ``Custom…`` entry
whose numbers are typed by hand -- a metal, a substrate (materials/), and
whatever kinds the product beside this core adds of its own. Typing the same
numbers on the next board is what this
package removes: ``store.UserStore`` keeps named records in the user's config
directory, and ``catalog.SavedCatalog`` is the picker's view of them -- the
built-ins, then the user's own, then the ``Custom…`` sentinel -- with the naming
rules (no shadowing a built-in) and the field rules in one place.

Nothing here knows what an entry *is*: a subclass of ``SavedCatalog`` says which
fields make one, how to build one and what makes one valid, so the same file
format, the same lookup and the same rules serve every kind. Stdlib only -- no
wx, no pcbnew -- and the wx side of it (the Save / Update / Delete buttons) is
just as shared, in ``gui.savedpick``."""
