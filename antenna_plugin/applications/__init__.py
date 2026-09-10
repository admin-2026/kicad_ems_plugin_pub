"""Application (design-target) catalog: ``db`` is the pure table mapping a
high-level pick (Bluetooth, Wi-Fi, GPS, LoRa, ...) to its antenna spec --
pattern frequency, operating band, desired input impedance and the band's
return-loss / VSWR target -- and the one-line description of a target
(``db.describe``, what a run's verdict table is headed with).

``catalog.Catalog`` is the picker's view of them: the built-in services, then
the targets the user typed and named themselves, then the ``Custom…`` sentinel.
The keeping of those is not this package's business -- the file, the naming
rules and the merged lookup are ``userlib``'s, shared with the saved materials,
and this package only says what a design target is made of. Stdlib only (no wx,
no pcbnew), so it stays unit-testable off KiCad."""
