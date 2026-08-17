"""Application (design-target) catalog: ``db`` is the pure table mapping a
high-level pick (Bluetooth, Wi-Fi, GPS, LoRa, ...) to its antenna spec --
pattern frequency, operating band, desired input impedance and the band's
return-loss / VSWR target. Self-contained and optional (stdlib only, no wx or
pcbnew): deleting this package leaves the dialog on a free frequency field."""
