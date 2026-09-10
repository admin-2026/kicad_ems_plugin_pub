# Running the solver in a Docker container

The solver is not what this is about: it is this project's own program, and
starting it directly is the ordinary way to use the plugin. What the container
is for is the *driver* — an **AI agent** working through this command line, or
a script or CI job doing the same. Then nobody is choosing each run, and an
agent that is confidently wrong is wrong on whatever it can reach. So a run can
instead happen inside a container that sees **one directory and no network**:
the boundary is drawn round the agent's work, not round the solve.

On **macOS this is not optional**: no macOS build of the solver ships, so every
simulation there runs in the container. On Linux and Windows it is a tick,
off by default.

The window has the same controls in **About › Docker**, and its *Container
guide* button opens the same explanation as a help page. This file is the
command-line half, and the reference for what is actually in the image.

## What you need

| | |
| --- | --- |
| macOS, Windows | [Docker Desktop](https://docs.docker.com/get-started/get-docker/) |
| Linux | Docker Engine, and your user in the `docker` group |

`antenna-agent docker status` reports which of those is missing, if any, and
what to do about it — the same sentence the window shows and the same one a
refused run carries.

## Build it, once

```sh
antenna-agent docker build      # minutes: it installs KiCad inside the image
antenna-agent docker on         # every run on this machine from now on
```

`docker on` is a preference about *this machine*, kept beside your saved
materials (`~/.config/kicad-antenna-designer/machine.json`) rather than beside
a board — an answer that is only true of one laptop has no business travelling
with a project. It is the same setting the About page's tick writes, and either
can change it. For one run without changing that:

```sh
antenna-agent run start --board b.kicad_pcb --docker      # or --no-docker
```

**Rebuild after every plugin update.** The plugin's own code is copied into the
image, so an upgraded install asks for an image tag that does not exist yet:

```sh
antenna-agent docker rebuild
```

`docker status` reports that as `stale` before you hit it. It also reports
`kicad_older` — the KiCad inside the image predating the one you run — which
matters because an older KiCad cannot open a board a newer one saved.

## What is in the image

`antenna-workbench:<plugin version>`, built from
`antenna_plugin/emkit/sim/container/Dockerfile`:

* **Ubuntu 24.04** with the KiCad project's own PPA, and **KiCad 10** from it
  (`--no-install-recommends`, so none of the symbol/footprint/3D libraries this
  plugin has no use for — about 100 MB of KiCad rather than several GB);
* **this plugin**, copied in whole at `/opt/plugin`, with `emkit/` nested
  inside it;
* **the solver builds**, at `/opt/plugin/binaries`;
* **both licences**, at `/opt/plugin/LICENSE` and
  `/opt/plugin/LICENSE-solver.txt` — the image holds the code and the binary,
  so it holds the terms they are used under; a build with either one missing
  is refused;
* **the command line**, as `antenna-agent` on `PATH`.

We ship the recipe, never an image. Two reasons, and both matter: the image
carries a proprietary, non-commercial-only solver (`LICENSE-solver.txt`), so it
is not ours to publish and **not yours to push**; and it carries the plugin's
own code, so an image is only ever right for the release that built it.

## Working inside it

Because KiCad and the command line are in there, the image is somewhere to
work, not only somewhere to solve. Mount a project directory at `/work`:

```sh
# one verb
docker run --rm -v "$PWD:/work" antenna-workbench:0.2.0 versions

# a whole run, from outside
docker run --rm -v "$PWD:/work" antenna-workbench:0.2.0 \
    run start --board /work/board.kicad_pcb

# a shell, to look round
docker run --rm -it -v "$PWD:/work" antenna-workbench:0.2.0 bash
```

The entrypoint hands anything that is not a program to `antenna-agent`, so
`versions` and `run start` above are this plugin's verbs, while `bash` is
bash. A run started by the *window* is the same image with the solver named
directly.

## What a run can see

| | | |
| --- | --- | --- |
| the board's `simulation/` folder | `/work` | read-write |
| the plugin's solver builds | `/opt/solver` | read-only |

Nothing else: no home directory, no board file outside that folder, and
`--network none`. The container is named per run, given the caller's uid on
Linux (so results are yours, not root's), and removed when the run ends.

**Stop and Snapshot still work.** They travel through a control file inside the
run folder rather than through the operating system, so a containerised run is
as interruptible as a native one. Closing the window still ends the run: the
container is killed by name, because killing the `docker run` client would
leave the solver stepping.

## Things that go wrong

**"Docker is not installed", but it works in your terminal** — a window opened
from the Dock or the Start menu inherits a much shorter `PATH` than a login
shell builds. The plugin looks in the places the installers use as well as on
that `PATH`, so this should not happen; if it does, your engine is somewhere
of its own and a symlink into `/usr/local/bin` fixes it for good.

**A build that stops on `docker-credential-desktop: executable file not found`**
— the same `PATH` one level down. Docker runs helper programs of its own and
looks for them on the path it is handed; they sit beside the client, which is
where the plugin points it, so a helper you keep elsewhere wants the same
symlink into `/usr/local/bin`.

**"permission denied while trying to connect to the socket"** (Linux) — add
yourself to the `docker` group and log in again. A new terminal alone does not
pick it up.

**A project outside Docker Desktop's file sharing** (macOS, Windows) — Desktop
only mounts directories you have listed in its settings. Add the project's
parent there.

**A run that fits natively but not in the container** — Docker Desktop runs a
VM with a memory limit of its own, and the solver sizes its mesh against what
it can see. Raise the VM's memory in Desktop's settings; `mesh_budget_gb` in
the form is measured against the same number.

**A board this container cannot read** — `docker status` says `kicad_older`.
Rebuild the image.

## What this does not do

It does not run *KiCad* in a container: the editor, the board and this window
stay on your machine. It does not use the network, publish anything, or change
what the simulation computes — the same board through the same solver gives the
same numbers, container or not.
