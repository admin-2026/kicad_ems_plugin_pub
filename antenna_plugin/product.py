"""What this plugin *is*, as data: the one place a product name is written.

The shared core (``emkit/``) is the same code in every plugin built out of this
repository, so nothing in it may spell "Antenna Designer", "monopole" or the
repository the releases come from. It reads them here instead, relatively
(``from ..product import NAME``), and this module is the only file that
changes when a second product is assembled out of the same core.

The build-time tools read it too, by path -- ``install.load_plugin_module``,
because importing the package the normal way runs ``__init__``, which imports
pcbnew and so only works inside KiCad. That is the whole reason this module
imports nothing: it has to be readable outside KiCad, by a script, with no
plugin around it.
"""

# The directory under ``plugins/`` this product's own code lives in, and the
# stem of its make targets (``make antenna-install``). Never seen at run time.
NAME_KEY = "antenna"

# What an install is called on disk, and so the Python module name KiCad
# imports the plugin under from a checkout install. (A PCM install is imported
# under PCM_ID with the dots replaced by underscores instead -- which is why
# nothing inside the package may import itself by name.)
PACKAGE = "antenna_plugin"

# The product, as a human reads it: the toolbar button, the window title, the
# name PCM lists the package under.
NAME = "Antenna Designer"

# The pcbnew "External Plugins" submenu this product's button files under.
CATEGORY = "Antenna"

# The package's identity to PCM, and the only string here that must never
# change: it is the install directory, the Python module name a PCM install is
# imported under, and how PCM recognises an installed copy as *this* package
# rather than a new one. Reverse-DNS over the published repository, with the
# underscores the schema's pattern forbids written as dashes. If the
# repository is ever renamed, this stays as it is.
PCM_ID = "com.github.admin-2026.kicad-ems-plugin-pub"

# The folder of our own below the user's config home (``%APPDATA%`` on Windows,
# ``~/.config`` elsewhere): where the entries the user saves from a picker live,
# and the command-line shortcut beside them (``userlib.store``, ``agent.shim``).
# Named for the product rather than the package because these are user
# documents -- they outlive an uninstall and the user may go looking for them --
# and, like PCM_ID, it must never change: renaming it hides every target and
# material somebody saved.
CONFIG_DIR = "kicad-antenna-designer"

# The solver this product drives -- the stem of it. ``binaries/<BINARY>/`` in
# the repository, flattened to ``binaries/`` inside an install, where every
# machine's build sits side by side under a name that says which
# (``monopole-linux-aarch64``); ``sim.simulate.locate`` picks this machine's
# out of them (``sim.builds``).
BINARY = "monopole"

# Which version of it this release carries. Declared rather than asked of the
# binary: running a program to read one line is a process spawn, and inside a
# container it is a container start -- far too slow for a page that opens on a
# click, to answer a question this file already knows. Nothing mixes versions
# across components (the plugin, its solver and the config schema they speak
# move together), so a declaration cannot be more wrong than a probe is slow.
# ``tools/binary_sync.py`` checks it against the build it copies, which is the
# one moment a machine can actually ask.
BINARY_VERSION = "1.28.1"

# The two dumps a run writes, without their extension: the results the report
# page draws, and the lattice ``--grid-only`` produces on its own.
DUMPS = ("pcb_data", "pcb_grid")

# The viewer page that draws the first of those (emkit/viewer/). The grid's is
# grid.html for every flow -- a lattice is a lattice.
REPORT_PAGE = "report.html"

# The 24x24 toolbar glyph, beside this module in the installed package.
ICON = "icon.png"

# The public repository this product is published from, as "owner/repo". It is
# where ``tools/publish.py`` mirrors to, where the update check looks for a
# release (``update.github``) and what the About page links to
# (``links.GITHUB_URL``) -- one fact, not three.
REPO = "admin-2026/kicad_ems_plugin_pub"

# The same repository as a browsable address: what the About page links to
# and what the package's metadata names as its homepage.
GITHUB_URL = f"https://github.com/{REPO}"

# The staging checkout of that repository, beside this one.
PUB_DIR = "kicad_ems_plugin_pub"

# PCM's store front. The short line is shown in the package list (the schema
# caps it at 150 characters); the long one when the package is selected, and
# it is also the only place the package can be honest about its licensing --
# metadata's `license` field is an enum with no value for "part of this is
# proprietary and non-commercial", so the split is spelled out here.
DESCRIPTION = (
    "Design and simulate PCB antennas without leaving pcbnew: a bundled FDTD "
    "solver, plus wizards for common antenna topologies."
)

DESCRIPTION_FULL = """\
Antenna Designer adds one button to the pcbnew toolbar.

EM simulation of the board you have open: a bundled FDTD solver meshes your \
real copper, stackup and drills, and reports the antenna's radiation pattern \
and impedance (S11).

Design wizards for common topologies -- an L-shaped monopole and a meandered \
inverted-F. Mark the area the antenna may use, sweep its dimensions, and the \
plugin simulates the candidates and ranks them by S11 at your target \
frequency.

Licensing: the plugin's Python source is MIT. The simulator binary bundled \
with it is proprietary and free for NON-COMMERCIAL USE ONLY -- personal, \
educational and research work, including the simulation results it produces. \
Designing a product you sell with it needs a separate commercial licence; ask \
through the project's repository or chat. Full terms in LICENSE-solver.txt \
inside the package."""
