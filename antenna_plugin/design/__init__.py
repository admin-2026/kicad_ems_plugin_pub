"""The antenna design engine: topologies, and the machinery every one shares.

No wx and no pcbnew at import time, so the whole engine is unit-testable off
KiCad. It is split so that adding an antenna topology means writing ONE module
against the design contract and listing it in ``registry``:

    base        the AntennaDesign contract -- params (with their seeds),
                solve(), capacity_mm() -- and what a design gets for free
    registry    the designs the plugin ships; everything else looks them up here
    lmonopole   the L-shaped monopole (stem + arm)
    ifa         the meandered inverted-F (short pin + tapped feed + folded arm)
    meander     the meandered monopole (one pin, a wire that turns back and
                forth away from the feed edge)

    geometry    the shared planar work: centerline Paths -> a Geometry, its
                copper rectangles, the off-grid rotation, the gerber splice and
                the runner's feed dict
    fit         whether the candidate still fits the marked area, and the
                warning (with the length the area does hold) when it doesn't
    sizing      the frequency-aware sizing: lambda/4, the candidate ladder,
                linear sweeps, the 1/L refinement
    measure     what a finished run measured (resonance, S11, bandwidth, Z)
    scoring     how that compares with the application's desired spec
    footprints  the winning geometry as a .kicad_mod, and onto the board

    wizard_scan the scan driver: plans and runs a sweep of one parameter of
                one design, headless
    scan_views  the view manifests a finished scan writes, so the shipped
                viewer steps through every candidate from one page
    scan_store  a finished scan's rows + the spec they were measured under,
                kept in its folder so a later session can place from them

Candidates are previewed by drawing them on the board inside the area marker,
as a footprint of their own (gui.sections.scan + markers.preview); the GUI
reads designs through ``registry`` and knows nothing about any particular one.
"""
