"""The wx the plugins share: the look, the controls, and the windows around
them.

Nothing here decides what a plugin's window *contains* -- that is the plugin's
own ``gui`` package, which builds its pages out of these.

Modules:
    theme   — the look: the spacing scale, the type scale and the frame every
              section is built into
    widgets — small shared wx helpers and fixed control widths
    gtk_wheel — the GTK scroll-wheel guard the sliders and spins are bound
              through
    icons   — the bundled PNGs (tab icons, scan and marker drawings) as
              bitmaps, looked up in the plugin first and here second
    model   — FormModel, the datastore behind the fields more than one page
              shows
    options — static choice tables and the speed/accuracy presets
    savedpick — the "saved picks" dropdown behaviour the catalogs share
    settings— save/restore a window's pages to a YAML file across launches
    board   — pcbnew queries (board facts, copper layer names)
    editor  — the PCB editor frame: finding it, and closing the plugin window
              with it
    place   — clipboard + simulated-paste cursor placement for markers
    activelayer — switching the PCB editor's active layer from the plugin
    reveal  — taking the PCB editor to a board item (a placed marker)
    viewer  — ResultDialog, the embedded HTML viewer
    viewers — ViewerHub, the named viewer windows a page shows its pages in
    pages/  — BookPage, the scrolled-form base every page is built on
    sections/ — the form sections that are not about one kind of simulation
"""
