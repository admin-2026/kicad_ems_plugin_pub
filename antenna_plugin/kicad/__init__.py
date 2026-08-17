"""KiCad/pcbnew interop shims: point-type compat, version advisory, stackup
reader. Everything that talks to the pcbnew API but isn't a marker footprint
lives here; pcbnew is imported lazily so the pure helpers stay testable."""
