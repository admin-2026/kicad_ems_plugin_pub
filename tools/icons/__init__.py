"""Generated artwork for the plugin, split by what it draws for.

    draw.py     the engine: supersampled canvas, stencil layers, primitives
    shapes.py   the shared vocabulary: the board, the antennas, the markers,
                dimension marks
    tabs.py     the toolbar glyph and the window's sidebar tab icons
    scan.py     one illustration per scan parameter of a design
    markers.py  one picture per marker footprint a button places

``tools/make_icon.py`` is the entry point (``make icon``); nothing here ships
in the plugin package -- only the PNGs it writes into it do.
"""
