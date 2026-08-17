# Antenna Designer — KiCad pcbnew plugin (developer guide)

For what the plugin is and how to install and use it, see
[README.md](../README.md). This document is the developer's view: the tree, how
each piece works, and how to build, package, lint and release it.

Adds an antenna button to the PCB editor toolbar. Pressing it opens a small
native dialog (plain wxPython — no HTML GUI, no local server): a one-click
**EM simulation** that meshes and solves the open board with the FDTD runner,
with a live log. The only embedded HTML viewer is the results window, which
shows a run's `pcb_grid.js` / `pcb_data.js` dumps through the bundled viewer.

```
.
├── Makefile                 # thin, OS-aware wrapper around the installer
├── antenna_plugin/          # the plugin package (this is what gets installed)
│   ├── __init__.py          # registers the action plugin with pcbnew
│   ├── action_plugin.py     # toolbar button definition + Run()
│   ├── gui/                 # native wx dialog, run/marker logic, wizard UI
│   ├── sim/                 # stackup -> gerbers -> config.py YAML (no ems
│   │                        #   dep) -> monopole.exe, then archive its dumps
│   ├── kicad/               # pcbnew shims: point compat, version note, stackup
│   ├── markers/             # feed + area marker footprints and their decoding
│   ├── design/              # L-shape engine: geometry, scan plan/run, preview
│   ├── update/              # launch-time "newer version?" check + its strip
│   ├── materials/           # per-layer material catalog (db) + picker UI (ui)
│   ├── assets/              # palette.css / help_theme.css (light, linked by
│   │                        #   the help guides)
│   ├── assets/icons/        # scan-parameter illustrations (one per knob)
│   ├── help/                # pre-flight problem help pages + the About
│   │                        #   tab's settings reference (settings.html)
│   ├── viewer/              # the static app that draws a run's dumps (the
│   │                        #   simulator's front end, three.js and all)
│   └── icon.png             # 26×26 antenna toolbar icon
├── packaging/               # what the redistributable package ships with
│   └── pcm/                 # icon.png (64×64), the KiCad add-on's store front
└── tools/
    ├── install.py           # cross-platform install/uninstall logic
    ├── make_package.py      # builds the KiCad add-on package
    ├── pcm.py               # the KiCad add-on package: metadata + tree shape
    ├── make_icon.py         # regenerates every bundled PNG (needs Pillow)
    └── icons/               # how they are drawn: engine, shapes, tabs, scan
```

## How it works

- `action_plugin.py` subclasses `pcbnew.ActionPlugin` and sets
  `show_toolbar_button = True` with `icon.png`, so KiCad draws the button.
- On click, `Run()` opens `gui/`'s `AntennaDialog` — native wx widgets: the
  simulation form (pattern frequency, copper model, the feed-marker generator),
  a Run section carrying the knobs of the pass itself (simulation time, Auto
  ground/source) and the run button, a one-line resonant-length hint, and a
  monospace log.
- Running a simulation also shows the filename, footprint/net counts,
  thickness and board size read from `pcbnew.GetBoard()`.
- The solver's output streams into the log; lines are batched through a single
  pending `wx.CallAfter`, so a fast-printing solver can't flood the event
  queue and freeze the editor.
- Results open in `ResultDialog`, a `wx.html2.WebView` window — the only HTML
  view in the plugin, and the OS browser is never opened.

## Run an EM simulation

The dialog drives `binaries/monopole.exe` from the live board.
Pressing **Run simulation** (`sim/simulate.py`):

1. **Reads the physical stackup** from the saved `.kicad_pcb` — every copper
   foil's thickness and every dielectric gap's thickness, εr and loss tangent.
   Nothing is defaulted: a missing value blocks the run in the pre-flight
   banner (with a help page) instead of being invented.
2. **Plots gerbers** (copper stack, edge cuts and the solder paste — the paste
   apertures are how the solver identifies pads for its ground detection) plus
   separate PTH/NPTH Excellon drills, returning the resolved paths by role.
   The feed is not a gerber: the plugin resolves the marker to a point +
   direction and writes it into the config.
3. **Writes the YAML config** in-process (`sim/config.py`, a self-contained port of
   the runner schema — the plugin depends on nothing in `ems`), seeding it with
   the measured thicknesses and the dialog's frequency, copper model,
   simulation time and feed.
4. **Runs `binaries/monopole.exe`** twice: `--grid-only` first (`pcb_grid.js`,
   the mesh), then the full solve (`pcb_data.js`, every series it measured).
   The solver writes data and nothing else; what draws it is the bundled
   viewer, in an embedded results WebView inside KiCad — the OS browser is
   never opened. Progress and the binary's captured
   output stream into the log; the two runs happen on a worker thread so the
   editor stays responsive. **Generate grid** does the first of the two on its
   own — same board preparation and config, no solve — for a quick look at the
   mesh a board produces before paying for a full run.

### Stopping early, and snapshotting a running solve

The solve is the long part of a run (a real board can take several hours), and
the solver is interruptible, so the buttons follow what the run is doing:

- **Stop** — the Run button during the solve — asks the solver to end the run
  early and *still write its report*, from the data simulated so far. The
  report is archived and opened like any other. The button then reads
  **Stopping** and is disabled until the report lands: the run is already
  ending, and there is no press that would throw the report away.
- **Snapshot report** asks a running solve for a report from the data simulated
  so far *without* stopping it ("is this converging on anything?"). The solve
  keeps stepping; each snapshot overwrites this run's report, so *the* report is
  always the newest, longest record of it. Writing one takes as long as a
  normal report, so the button reads **Snapshotting** and is disabled until that
  report lands.
- Every report says what it covers — the equivalent simulated time (ns)
  against the planned length, and the ring-down level reached — in the run log,
  in the status line and in the result window's title. A report written from a
  2 ns record must never read like a converged 20 ns one.

During the meshing pass there are no results to write, so the button reads
**Cancel** and stops the run outright. Details:
[dev_docs/interruptible-runs.md](../dev_docs/interruptible-runs.md).

The pages are `antenna_plugin/viewer/`, the simulator's own front end shipped
as a verbatim copy (`docs/viewer.md`, in this checkout, records where each file
came from — keeping the copy in step is a job for a tree that has `ems/` beside
it). `simulate.install_viewer` puts one copy in the board's `simulation/viewer/`
and the Results box opens a page in it pointed at what to draw
(`report.html?d=../results/<stamp>/pcb_data.js`). The folder is copied as it
stands, so it carries only what a page loads. Everything
loads through classic `<script src>` tags — three.js included, vendored as one
non-module bundle — because a Chromium-based WebView gives a `file://` page an
opaque origin and CORS-blocks every ES-module fetch from it. That constraint is
why there is no import map and nothing to inline. three.js is r160, MIT.

`install.py` bundles the `monopole` binary *into* the installed package, so a
detached install resolves the simulator with no extra setup. The plugin finds
it by searching upward from itself (bundled install and dev checkouts), or via
the `ANTENNA_SIM_ROOT` environment variable. All inputs and outputs (gerbers,
the config, and the run results) are kept in a `simulation/` folder beside the
board file, under the KiCad project directory. Give the feed with the
generated **feed marker** footprint (see below), or as a small circle drawn
on a `User.*` layer.

## Feed marker

The always-visible **Feed marker** box generates the marker footprint: a line
laid across the
feed trace and, above it, a triangle pointing toward the antenna, whose tip
marks the feed point and points the way to the antenna. The **Feed width**
slider sets the line's drawn length, the **Feed marker layer** picker in
**Advanced** chooses which `User.N` layer holds it (only User layers
are allowed), and **Generate feed marker** puts it on the cursor — click the
feed line to place it (clipboard + simulated paste; falls back to a manual
`Ctrl+V` hint or a drop at the board center when the platform can't simulate
the keystroke). Moving the slider or the layer pick reshapes the placed marker
in place, and a status line under the button tracks the marker: its
target layer before placement, the placement prompt after Generate, and its
location and layer once placed. At run time the plugin decodes the placed
footprint into the feed point and its direction, which is all the runner takes:
it severs the gap itself, on the simulation grid
(`markers/feed_marker.py`, unit-tested off KiCad by `tests/test_feed_marker.py`).
Full details: [dev_docs/feed-marker.md](../dev_docs/feed-marker.md).

## Antenna design wizards

Each **designer** tab in the window's sidebar opens a guided designer for one
antenna topology:

- **L-shaped monopole** — a quarter-wave monopole bent once: a *stem* straight
  in from the feed, then an *arm* along the roomier side.
- **Meandered inverted-F** — a quarter-wave radiator folded over its own ground
  plane: a *short pin* to the pour, a *feed pin* tapped a little along from it,
  and an arm that meanders to fit. It packs a quarter wave into a fraction of
  the board, and the tap is a match knob a monopole doesn't have.

The flow is the same either way. Mark where the antenna may live with the
**area marker** — a footprint the wizard drops on the board, a rectangle with a
feed triangle on one edge pointing inward. The wizard's sliders reshape it live
(width, height, feed position along its edge), its **Advanced** pane picks the
`User.N` layer it is drawn on; KiCad's own tools move it
anywhere and rotate it to feed from another side, at any angle. Then pick which
of the design's geometry parameters to sweep — the resonant length, the track
width, and whatever else the topology has (the monopole's stem; the
inverted-F's height and feed-to-short tap) — with the others fixed, and moving
the slider previews the candidate on the board. Push it past what the area
holds — any of the parameters, not just the length — and the antenna is still
drawn, on the area marker's own User layer instead of on copper: it hangs out
of the rectangle by exactly what is missing, so you can see how much too big it
is and which way to drag. The status line says why, quoting the longest
resonant length that area *does* hold, and the preview goes back onto copper by
itself once it fits again. **Start scan**
simulates them
(each spliced into a *copy* of the plotted gerbers, the board untouched),
ranking them by S11 at the target frequency. A length sweep with blank bounds
runs automatically around the quarter-wave estimate and adds one refined length
interpolated from the measured resonances; the other parameters sweep between
the bounds you give. **Generate grids** is the same sweep meshed and not
solved — the simulate view's **Generate grid** across every candidate — for
checking the meshes a sweep produces before paying for it.
**Generate + place footprint** turns the winning row into
a real footprint (a pad per connection — the feed, and for the inverted-F its
ground pin — with the radiator carried by the feed pad as its custom shape, so
the copper has a net and DRC lets a track reach the pads; an inverted-F, whose
two pins are one piece of copper, also declares them a net tie) placed exactly where it was simulated,
and writes the `.kicad_mod` to `<project>/antenna.pretty/` (beside the
`simulation/` folder, not inside it) for reuse. Its chooser also offers a second table with a single row — the
shape the scan parameters describe *right now*, the one previewed on the
marker — so a geometry you already know you want can be placed with no scan
behind it: same copper, dashes instead of verdicts, and a status line saying
nothing was simulated. A finished scan is also written down beside its runs
(`scan.json`), so reopening the plugin days later fills the candidates table
again from disk — placing a different candidate never means paying for the
sweep twice, and the chooser and status line name the saved scan (and the area
it was run in) so it is clear which board the numbers describe.

The scan inherits the dialog's materials/mesh/speed settings. A design is one
module against one contract (`antenna_plugin/design/base.py`) — the wizard
page, the scan driver and the scan's view manifests know nothing about any
particular antenna — and the geometry, marker decoding and scan logic are pure and
unit-tested off KiCad (`tests/test_geometry.py`, `tests/test_lmonopole.py`,
`tests/test_ifa.py`, `tests/test_designs.py`, `tests/test_area_marker.py`,
`tests/test_wizard_scan.py`). Full details, including how to add a design:
[dev_docs/antenna-wizard.md](../dev_docs/antenna-wizard.md).

## Materials

The **Advanced** pane holds every runner knob that isn't on the main form, in
one box per function: **Materials**, **Optimizations** (what the Speed /
accuracy slider drives), **Mesh**, **Feature refinement**, **Frequencies and
run**, **Feed port**, **Ground** (the ground check, the Auto ground/source
radius and the raster they read the copper on — whether that search runs at all
is the Run / Scan section's own tick), and **Markers** — the `User.N` layer this
page's marker footprint is drawn on (the simulate view's feed marker, a
designer's area marker; each page picks its own). A blank numeric field means
the default, shown greyed in the box.

The **Materials** box has a per-layer table: one
metal picker for every copper layer (copper by default, or aluminium, silver,
gold, …) and one dielectric picker for every substrate gap (the board's own
stackup by default, or FR-4, PTFE, a Rogers laminate, …). A metal contributes
its bulk conductivity; a substrate contributes its permittivity and, from its
loss tangent, an effective conductivity at the pattern frequency. Each picker
also offers **Custom…**, which reveals fields for a hand-typed conductivity
(metals) or εr + loss tangent (dielectrics). The layer rows reflect the board
as of when the dialog was opened, so reopen it after changing the stackup. The
catalog lives in a `Materials` class in `materials/db.py`.

The feature is self-contained and optional. `materials/db.py` (the pure
catalog) and `materials/ui.py` (the per-layer table) only *emit* two ordered
override lists — `metal_layers` and `substrate_layers` — that
`config._apply_overrides` lays onto the board-read stackup entry by entry,
falling back to the scalar `copper_sigma` / `substrate_sigma` /
`substrate_eps` defaults for any layer a list doesn't cover. The GUI loads
the block through a guarded import and injects the board's layer list
(keeping `materials/ui.py` KiCad-free), so deleting the `materials/` package
drops material selection cleanly and the plugin keeps running on the
copper/FR-4 defaults (`config.DEFAULTS`). The pure modules are unit-tested off
KiCad (`python3 tests/test_materials.py`, `tests/test_config_overrides.py`).

## About tab

The last tab in the sidebar (a chat bubble, pinned to its foot) opens with a
**Project links** box: the source repository
([GitHub](https://github.com/admin-2026/kicad_ems_plugin_pub)) and the
community chat ([Discord](https://discord.gg/XDY6EE5WA)). Both live in
`antenna_plugin/links.py` (the list the section renders, the same relation
`versions.py` has to the version table below it), and the GitHub one names the
same repository as `update.github.REPO` — `tests/test_update.py` checks the
pair against each other. A link added there before its destination is published
is written under `example.com` (`links.PLACEHOLDER_HOST`), and the section then
says so on that row's tooltip and in a line under the box, so nobody follows a
dead link expecting it to work. Both links are built with `gui.widgets.hyperlink`,
which is also the update strip's Download link — a real `wx.adv.HyperlinkCtrl`
where the host's wx has one, else a button that opens the browser through wx.

Under it, a **Documentation** box: one button per bundled guide that is worth
reading on its own rather than when something goes wrong — today the **Settings
reference** (`antenna_plugin/help/settings.html`), every knob of the window with
what it changes and its default. The list is `gui/sections/guides.py`'s
`GUIDES`, so adding one is a line there plus the HTML file; opening it takes the
shared path every guide takes (`gui.viewers.show_guide` → the `HELP` viewer
slot), the same one a pre-flight banner's Help button uses, so the two land in
one window. The About tab has no run log, so a guide missing from the install is
said on the box's own status line. `tests/test_guides.py` reads the field labels
out of `gui/options.py` and fails if the reference has fallen behind a knob
added to the Advanced pane.

Under it is the version table: the plugin, the bundled simulator (asked of the
binary with `--version`, off the UI thread), the runner-config schema the two
agree on, and the KiCad / Python / wxPython underneath. That is the list worth
quoting when something misbehaves — versions only, no paths. The facts live in
`antenna_plugin/versions.py` (pure, unit-tested by `tests/test_versions.py`);
anything it can't establish reads `unknown` rather than being invented. The
plugin's own row also carries what the launch-time update check found, when it
found anything (`0.1.0 — 0.2.0 available`; see below).

## Update check

When the window opens it asks, in the background, whether a newer release
exists. If one does, a strip appears across the top of the window naming both
versions with a link to the release page and a ✕ to put it away for the
session; the About tab's plugin row says the same thing. Anything else — up to
date, no network, a proxy, a rate limit — shows nothing at all and leaves one
line in the run log.

It cannot get in the way, by construction: the request runs on a daemon thread,
`update.checker.check` answers an `Outcome` instead of raising (every failure
included), and nothing in the plugin waits on the result or is gated by it.

The feature is a folder of its own, `antenna_plugin/update/`, layered so all of
it but the strip is testable without wx or a network (`tests/test_update.py`,
`tests/test_update_strip.py`):

| module | what it is |
| --- | --- |
| `model.py` | `Release` / `Outcome` — the answer as plain data |
| `version.py` | comparing two version strings (pure; `v` tags, pre-releases, build metadata) |
| `github.py` | the release source: the API URL, one capped/timed-out GET, payload → `Release` |
| `checker.py` | the policy — `check` / `check_async`, the source injected |
| `strip.py` | `UpdateStrip`, the only module here that knows what a window is |

The shell's whole share of it is building the strip and calling `start()`
(`gui/shell.py`). The source is an argument, so pointing the check at something
other than GitHub releases (a JSON manifest on the product website, say) is a
new module beside `github.py` — nothing else changes.

Two settings, both read from the environment KiCad launches from:

| variable | effect |
| --- | --- |
| `ANTENNA_UPDATE_CHECK=0` | switch the check off; no request is made |
| `ANTENNA_UPDATE_REPO=owner/repo` | check that repository instead of the built-in one |

`REPO` in `antenna_plugin/update/github.py` is the `owner/repo` the releases
are published from — `admin-2026/kicad_ems_plugin_pub`, the same repository
`links.GITHUB_URL` offers on the About page; move the project and both lines
change together. Left empty it would mean "no update source": the checker then
makes no request at all rather than guessing a URL.

## Install

Installs on Linux, macOS and Windows — though only the first two can simulate,
see [Requirements](#requirements). With `make`:

```sh
make install       # copies antenna_plugin/ + bundles the simulator binary
make uninstall     # removes it
make where         # print the target directory without touching anything
```

KiCad 9 and KiCad 10 each keep their own plugin directory, and the targets
above follow whichever version directory is newest. When both are installed,
name the one you mean:

```sh
make install KICAD_VER=9.0    # ~/.local/share/kicad/9.0/scripting/plugins
make install KICAD_VER=10.0   # ~/.local/share/kicad/10.0/scripting/plugins
```

`uninstall`, `reinstall` and `where` take `KICAD_VER` the same way. Installing
to both is fine — they are separate copies of the package, each with its own
bundled binary.

No `make`? Call the installer directly (same on every OS):

```sh
python tools/install.py install      # or: py -3 tools/install.py install
python tools/install.py uninstall
python tools/install.py targets      # every KiCad found, not just the newest
```

`install` also copies the simulator into the installed package so the EM
Simulation button works out of the box (build the binary first if it's
missing). `binaries/` holds a build per OS — `monopole` and `monopole.exe` —
and the install takes *this* machine's, asking the plugin's own
`sim/hostos.py` which that is rather than keeping a second copy of the naming
convention. The other OS's build is left behind; only when there is no native
one does the install fall back to it (a `.exe` runs under WSL). The plugin
generates the runner config itself, so nothing from `ems/` is copied or needed
at runtime.

The installer auto-detects the newest KiCad version and the per-OS user
plugin directory:

| OS      | Detected location                                            |
| ------- | ------------------------------------------------------------ |
| Linux   | `~/.local/share/kicad/<ver>/scripting/plugins`               |
| macOS   | `~/Documents/KiCad/<ver>/scripting/plugins`                  |
| Windows | `%USERPROFILE%\Documents\KiCad\<ver>\scripting\plugins`      |

Override when detection guesses wrong:

```sh
make install KICAD_VER=8.0
make install PLUGIN_DIR="C:/Users/me/Documents/KiCad/9.0/scripting/plugins"
```

> On native Windows the Makefile uses the `py -3` launcher; under Git Bash /
> MSYS2 / WSL it works the same. Set `PYTHON=python` to force a specific
> interpreter.

After installing, restart pcbnew, or use
**Tools → External Plugins → Refresh Plugins**. The antenna button appears on
the top toolbar (and under **Tools → External Plugins**).

### The redistributable package

Everything above assumes a checkout. For someone who just wants the plugin,
`tools/make_package.py` builds the KiCad add-on — one archive, every OS:

```sh
make package                          # -> dist/AntennaDesigner-<ver>-pcm.zip
python tools/make_package.py windows  # the same, carrying the Windows solver
                                      #   alone (a checkout with one build)
```

KiCad's own **Plugin and Content Manager** installs it (*Install from File*),
which is why it is the only format built. It asks the user's machine for
nothing — no PowerShell, no shell, no Python, no administrator rights, no
SmartScreen prompt over an unsigned executable — because KiCad is already
running, or there would be nothing to install into. It also brings a native
uninstall and update notice. What it cannot do is install into several KiCads
at once: it installs into the one it is running in.

(This replaced a pair of scripted installers, a `.zip` with `install.ps1` and a
`.tar.gz` with `install.sh`. They needed the OS to cooperate and it often
didn't: a group policy setting the PowerShell execution policy overrides the
`-ExecutionPolicy Bypass` a launcher asks for, and some Windows images have no
PowerShell at all.)

```
metadata.json          generated by tools/pcm.py
plugins/               the payload's *contents* (__init__.py at the top)
    binaries/monopole      the Linux solver \  both, side by side; the
    binaries/monopole.exe  the Windows one  /  plugin picks at run time
    LICENSE                the plugin's MIT licence      \  copied from the
    LICENSE-solver.txt     the solver's, non-commercial  /  repo root
resources/icon.png     64×64, drawn by tools/icons/tabs.py
```

The package needs nothing installed beforehand — not even Python. The staged
`plugins/` is in the shape the plugin has once *installed*, solver binaries
already nested inside it, so applying it is a directory copy. That keeps "what
an install is made of" in one place and at build time (`stage_payload()`,
alongside the `install.py` it borrows its constants from) instead of restating
it in a script, where it would be a second definition free to drift. What ships
is a payload, not a procedure.

`make package` checks that every solver build is present *before* staging
anything: one archive is all the platforms, so a missing build would otherwise
ship as a package that installs where it cannot simulate. Which OS the build
runs on has no bearing on what it produces — no NSIS, no Inno Setup, no
dpkg/rpm, no signing toolchain, so a release is cut from the same machine the
plugin is developed on. What it cannot cross-build is the solver, so
`binaries/` has to hold each build already, and anything whose header says
otherwise is refused (`MZ` for Windows, `\x7fELF` for Linux).

What it cannot express is **architecture**: PCM's `platforms` are operating
systems, so the Linux build inside is whatever `binaries/monopole` was, and an
arm64 machine would install a package it cannot simulate with. A second Linux
architecture would need a second identifier, which is a different package
rather than a variant of this one.

Five things about it are load-bearing, and each has a test in
`tests/test_pcm.py`:

- **The plugin chooses its own binary.** Both builds ship, so the choice is
  made at run time rather than by the packager. The pair is pinned in both
  directions: `.exe` on Windows, ELF on POSIX, and the other one still
  answering when it is the only build present (a checkout under WSL, or a
  narrowed package).
- **KiCad renames the package.** `plugins/` is extracted to
  `<3rdparty>/plugins/<identifier with dots as underscores>/` and imported
  under *that* name, so the installed plugin is not called `antenna_plugin`.
  Every import inside the package must therefore stay relative; an absolute
  self-import would work from a checkout install and fail only here.
- **The zip states its modes.** KiCad's extractor applies the entry's execute
  bit, so the Linux solver can ship in a zip at all — `make_pcm_zip()` writes
  POSIX entries rather than trusting the build host, which on Windows cannot
  express an execute bit at all.
- **The metadata carries no `download_*` keys.** They describe an archive
  sitting on a server and belong only to the copy submitted to a package
  repository — inside the archive they describe they would be a hash of
  something that does not exist yet.
- **Both licences travel with the binary.** The solver is proprietary and
  non-commercial; terms that live only in a repository bind nobody who
  installed a zip, so `install.bundle_licences()` copies `LICENSE` and
  `LICENSE-solver.txt` into the payload — one function, called by the packager
  and by `make install`, so neither can be the one that forgets.

The schema is v1, because that is what KiCad 9 validates against (it ships no
v2). Its `license` field is an enum of 90 licence names; it does have the
non-commercial CC values, but none for a package that is two licences at once,
so it names the plugin source's licence (`MIT`) and `description_full` states
the bundled solver's terms. That also means this package suits *Install from
File* rather than the official KiCad addon repository, which takes freely
redistributable content only.

| file | what it is |
| ---- | ---------- |
| `packaging/pcm/icon.png` | the 64×64 PCM shows the package as |
| `tools/pcm.py` | the add-on's metadata and tree shape |
| `tools/make_package.py` | the per-OS table, staging and archiving |

`tools/install.py` is the *checkout's* installer (the `make` targets above) and
is deliberately not part of the package. It is the second thing that has to
agree on what an install is made of, which `tests/test_pcm.py` checks by
comparing the two trees.

## Lint and format

Both are [ruff](https://docs.astral.sh/ruff/), configured by `ruff.toml` at the
repo root (so an editor picks up the same rules) and driven by `tools/lint.py`:

```sh
make lint            # findings
make lint/fix        # apply the safe ones -- review the diff
make format          # rewrite files
make format-check    # report instead of rewriting
```

Scope a run with `PATHS=antenna_plugin/gui`, or take only what you changed:

```sh
make lint/changed                    # vs the last commit
make format/changed LINT_BASE=master # everything a branch touched
```

The tree predates the formatter and is hand-wrapped a little narrower than its
88 columns, so a bare `make format` rewrites nearly every file — prefer
`format/changed` unless you mean to make that change on its own. The lint
targets ignore `ems/`, which has its own (`make -C ems lint`).

## Page styling — shared with the website

The plugin renders a few HTML pages, and one stylesheet in it is **shared with
the product homepage**:

| file | what it is | who uses it |
| --- | --- | --- |
| `antenna_plugin/assets/palette.css` | the Ultraviolet palette: every colour and typeface token, and nothing else | **the help guides *and* the website homepage** |
| `antenna_plugin/assets/help_theme.css` | prose rules for the pre-flight guides, on those tokens | `antenna_plugin/help/*.html` |
| `antenna_plugin/viewer/css/theme.css` | the viewer's own dark theme (tokens, stat tiles, toggle rows, the run switcher) | the shipped viewer's pages, and kept identical to the simulator's copy |

`palette.css` lives inside the plugin package because the installed package has
to run on its own files (the guides link it as `../assets/palette.css`, and are
displayed from the install tree so that link resolves). The homepage is not
tracked here — a draft lives in `examples/` when there is one — so **this copy
is the reference**: the site links it from a checkout, or carries it verbatim.

**Keeping the two in sync is a rule, not a nicety.** The sheet carries a
`Version: MAJOR.MINOR.PATCH` in its header, and that version is the handle:
bump PATCH when a value is retuned, MINOR when a token is added, MAJOR when one
is renamed or removed — a major breaks every rule referring to it on *both*
sides, so grep the plugin and the site before you make one. A copy that has
drifted is a bug: replace it wholesale rather than merging by hand, in whichever
direction the version says is older. Only the tokens are shared — layout rules
stay on their own side, and the plugin's system-font fallbacks stay in the
tokens because its pages render offline, with no Google Fonts.

## Licensing

The project is two licences, because it is two pieces of software:

| what | licence | file |
| --- | --- | --- |
| the plugin — this repository, minus the binary | MIT | `LICENSE` |
| the solver — `binaries/monopole(.exe)` | proprietary, free for non-commercial use | `LICENSE-solver.txt` |
| `antenna_plugin/viewer/vendor/three.js` | MIT (three.js r160) | its own notice |

The solver's licence covers **what the solver is used for**, not just who runs
it: results may not feed a product, service or contract that is paid for.
Personal, educational and research work is free; commercial use is a separate
written agreement, asked for through the repository or the Discord in
`antenna_plugin/links.py`.

Two consequences for anyone touching the build:

- **Both files ship inside every install.** `install.bundle_licences()` is the
  one definition of that, called from `cmd_install()` and from
  `make_package.stage_payload()`; `LICENCE_FILES` names them. A licence that
  only exists in the repository does not reach someone who installed a zip.
- **`tools/pcm.py` declares `MIT` on purpose.** PCM's enum cannot say "MIT
  plugin plus non-commercial binary", so the field names the source's licence
  and `DESCRIPTION_FULL` carries the solver's terms — that description is the
  only licensing a user sees *before* installing. Do not "correct" the field
  to something outside the enum: the package would be refused at install time.

Nothing here is legal advice; `LICENSE-solver.txt` is the operative text.

## Requirements

- Linux (x86-64) or Windows for *simulating*: `binaries/` carries a build of
  the solver for each. **macOS is not supported yet** — the plugin itself runs
  there (KiCad, wx, the drawing half of it all work), but there is no macOS
  solver to bundle, so a run is refused before it starts with a message that
  says exactly that. The refusal is one small module,
  `antenna_plugin/sim/os_support.py`, deliberately built to be deleted in one
  commit: `git grep os_support` is the whole removal list (two callers, one
  test file), plus `PLATFORMS` in `tools/make_package.py`, which decides whose
  builds a release package carries and therefore which systems KiCad's Plugin
  and Content Manager offers it on.
- KiCad 9.0+ recommended: the board, marker and footprint code is written
  against KiCad 9 scripting behaviour. Older hosts are not blocked — the
  plugin installs into whichever version directory you name, and on launch it
  logs a warning and opens anyway (`antenna_plugin/kicad/version.py`).
- The main dialog is plain wxPython and needs nothing extra; the results
  window uses `wx.html2.WebView` (WebKitGTK on Linux,
  WKWebView on macOS, Edge WebView2 on Windows). If a build has no WebView
  backend, the run still completes and the log prints the result file paths
  to open manually.
- Pillow — only needed to *regenerate* the icons (`make icon`), not to run it.
- ruff — only needed to lint or format (`pip install ruff`), not to run it.
