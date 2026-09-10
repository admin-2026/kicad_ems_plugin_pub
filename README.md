# Antenna Designer

![Six views from the plugin: a 3D radiation pattern, the meshed board copper, the pattern over the board, a Smith chart, the efficiency breakdown and the |S11| curve](docs/images/teaser.jpg)

A [KiCad](https://www.kicad.org/) **pcbnew** plugin for designing and
simulating PCB antennas without leaving the board editor.

It adds one button to the PCB toolbar. Behind it:

- **EM simulation** of the board you have open — a bundled FDTD solver meshes
  your real copper, stackup and drills and reports the antenna's radiation
  pattern and impedance (S11).
- **Design wizards** for common topologies — an **L-shaped monopole**, a
  **meandered inverted-F** and a **meandered monopole**. Mark the area the
  antenna may use, sweep its dimensions, and the plugin simulates the
  candidates and ranks them by S11 at your target frequency.

## Install

**Requirements:** KiCad 9.0 or later is recommended. Windows, macOS and Linux
are all supported, on Intel and Apple/ARM machines alike — the one package
below carries a build of the simulator for each, and the plugin runs whichever
belongs to the machine it starts on. In full: Linux x86-64, Linux AArch64,
macOS and Windows.

Download `AntennaDesigner-<ver>-pcm.zip` from the [releases
page](https://github.com/admin-2026/kicad_ems_plugin_pub/releases) — the
[latest
release](https://github.com/admin-2026/kicad_ems_plugin_pub/releases/latest)
is at the top, older versions below it — and let KiCad install it:

**Plugin and Content Manager > Install from File…** → pick the downloaded zip.

Then restart KiCad. An antenna button appears on the top toolbar.

If the manager refuses the file, or the KiCad you want it in isn't the one you
are looking at, the zip can also be unpacked into KiCad's plugin folder by
hand: [docs/manual-install.md](docs/manual-install.md).

## Getting started

Open a board and press the antenna button. The window has a sidebar; each entry is one way to work.

### Simulate the board you have

1. Set the **pattern frequency** you care about, and pick the metal and
   dielectric of each layer if the board's stackup doesn't already say.

   ![Arrows to the antenna toolbar button and the Simulate entry, with the pattern frequency set to 2.45 GHz](docs/images/getting-started-1-feed-marker.jpg)

2. Tell the plugin **where the antenna is fed**. Press **Generate feed marker**
   and click the feed trace — the marker is a line across the trace with a
   triangle pointing toward the antenna.

   ![An arrow to the placed feed marker on the trace, beside the Run section](docs/images/getting-started-2-run.jpg)

3. Press **Generate grid** for a quick look at the mesh your board produces —
   the viewer shows the cell counts and lets you switch the copper, vias and
   air groups on and off.

   ![The FDTD grid viewer: the meshed board in 3D beside its cell groups](docs/images/getting-started-3-grid.jpg)

4. Press **Run simulation** for the full solve. The report opens with the
   radiation pattern, peak directivity and the port match.

   ![The FDTD antenna report: 3D radiation pattern beside the port match](docs/images/getting-started-4-report.jpg)

A full solve can take anywhere from minutes to several hours. The log shows
progress as it goes, and you can **Stop** it early — you still get a report
from what was simulated so far — or take a **Snapshot report** without
stopping. **Show grid** and **Show report** reopen the newest of each without
re-running.

### Design an antenna from scratch

Pick a designer in the sidebar (**L-monopole**, **Inverted-F** or **Meander**):

1. Place the **area marker** — a rectangle showing where the antenna may live,
   with an arrow marking where the feed enters. Size it **on the board**:
   double-click it and drag a corner, like any other KiCad rectangle; drag the
   arrow to feed from another edge. Move (M) and rotate (R) work as usual, and
   an **Angle** field turns it to any angle between KiCad's rotation steps.
2. Choose which dimensions to sweep (the resonant length, track width, and the
   topology's own knobs). Moving a slider previews that candidate on the board.
3. Press **Start scan**. Each candidate is simulated on a copy of your board —
   the board itself is never modified — and the results table ranks them.
4. Press **Generate + place footprint** to put the winner on the board as a
   footprint, saved for reuse.

Scans are saved next to their results, so reopening the plugin days later
brings the table back without re-running the sweep.

### Where things are written

Everything — inputs, configs and results — goes in a `simulation/` folder
beside your board file, inside the KiCad project directory.

## If something goes wrong

- The plugin checks the board before every run and explains what is missing in
  a banner at the top of the window, each problem with its own help page.
- The **About** tab in the sidebar lists the versions of the plugin, the
  simulator, KiCad and Python. That is the list worth quoting in a bug report.
  It also links to the project's source repository and community chat, both
  below.

## Licence

Antenna Designer is two pieces of software under two licences, and the package
carries both files:

- **The plugin** — everything in this repository except the simulator binary —
  is **MIT** licensed ([`LICENSE`](LICENSE)). Use it, change it, ship it.
- **The simulator** (every `binaries/monopole-*` build) is **proprietary and
  free for non-commercial use** ([`LICENSE-solver.txt`](LICENSE-solver.txt)).
  Personal projects, teaching and research are free, and that includes the
  simulation results — you may share the plugin and the solver with anyone, as
  long as you pass them on unchanged and don't charge for them.

Using it to design something you sell — a product, a client's board, paid
consulting — needs a commercial licence. Ask on
[Discord](https://discord.gg/XDY6EE5WA) or open an issue on
[GitHub](https://github.com/admin-2026/kicad_ems_plugin_pub); it's a short
conversation, not a sales funnel.

## Project links

- **Source code:** <https://github.com/admin-2026/kicad_ems_plugin_pub>
- **Examples:** <https://github.com/admin-2026/kicad_ems_plugin_examples> —
  boards to open and simulate.
- **Community chat (Discord):** <https://discord.gg/XDY6EE5WA>

## Running the solver in a container

A simulation can run inside a Docker container that sees only the folder it
writes into and no network — worth having when a script or an AI agent is
driving it rather than you. It is a tick on the plugin's About page, or
`antenna-agent docker on` from a shell, and it is how the solver runs on macOS,
where no native build ships:
[docs/docker.md](docs/docker.md).

## For developers

Building, packaging, the module layout and how to add an antenna topology are
in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
