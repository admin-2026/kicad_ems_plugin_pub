"""Per-layer material selection: ``db`` is the pure metal/substrate catalog,
``catalog`` the picker's view of it (the built-in table plus the materials the
user saved themselves -- ``userlib``'s file and rules, the same ones behind a
saved design target), and ``ui`` the wx per-layer picker table. Self-contained,
but the only source of each layer's conductivity/loss -- config invents none, so
with this package removed a run is blocked until a metal and substrate are
supplied some other way."""
