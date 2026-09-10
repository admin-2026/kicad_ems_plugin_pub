# {{product}} — the whole briefing

This plugin runs an electromagnetic simulation of a PCB. It has two frontends
over one set of code: a window inside KiCad, and this command line. Same board,
same folder beside it, same answers, and — this is the part to hold on to — the
same **settings file**. A run is a board plus a form, the form is one flat YAML
file, and both frontends read it through the same translation.

Two things worth reading twice: *The settings file* and *A run costs minutes*,
both below.

## The command

    {{command}} versions

If that name is not found, nothing is broken: it is an optional shortcut the
plugin's About page writes, and it is a file, here:

    {{shim}}

**A name not found is often the shell, not the install.** The About page puts
that folder on the user's own PATH, and on Windows that is the account's
environment — which `cmd` and PowerShell read, while a POSIX shell there (Git
Bash, MSYS, WSL) either does not see it or will not look for a `.cmd` under a
bare name. `which` answering nothing in one shell proves nothing about
another. Type the full path above instead (`cmd //c "<that path>" versions`
from Git Bash, since `.cmd` is cmd's to run), or skip the shortcut entirely:
the long spelling needs no PATH and is exactly this install:

    {{python}} {{launcher}} versions

**Do not install a Python for this.** Reading a board needs `pcbnew`, which
exists only in the interpreter KiCad ships; a Python installed alongside has
none of it and takes over `python` on PATH. The launcher above re-execs into
the interpreter the plugin recorded the last time its window opened, so there
is no table of paths to learn.

## The loop

    {{command}} guide                                    # this page
    {{command}} versions                                 # is the chain sane
    {{command}} preflight     --board <board.kicad_pcb>  # would a run be refused
    {{command}} settings init --board <board.kicad_pcb>  # a form, if there is none
    cp <project>/simulation/settings.yaml my.yaml        # ...then edit the copy
    {{command}} run start     --board <board.kicad_pcb> --settings my.yaml --grid-only
    {{command}} run start     --board <board.kicad_pcb> --settings my.yaml
    {{command}} run status    --board <board.kicad_pcb>  # poll this one
    {{command}} run log       --board <board.kicad_pcb> --since <offset>
    {{command}} run log       --board <board.kicad_pcb> --severity warning
    {{command}} results show  --board <board.kicad_pcb>  # numbers and a verdict
    {{command}} results show  --board <board.kicad_pcb> --job <id>  # ...an older run

Every verb but `guide`, `versions` and `docker` takes `--board <path>`. It reads
that file; there is no handle on whatever board KiCad has open.

`--json` goes **before** the verb (`{{command}} --json run status …`) and every
verb honours it — usage errors included, so a caller parsing stdout never has
to also watch stderr to find out it failed.

`--help` works at every level and is the real reference: `{{command}} --help`
lists the verbs, `{{command}} run --help` the things `run` does, and
`{{command}} run start --help` every option that one takes. Nothing on this
page replaces it.

## Running the solver in a container

A run is otherwise a native process with your rights: it reads and writes
anything you can. When something other than a person is driving — which is what
this page is for — a solver confined to one mounted directory, with no network,
is the better default:

    {{command}} docker status                            # ready? if not, why
    {{command}} docker build                             # minutes: it installs KiCad
    {{command}} docker on                                # every run from now on
    {{command}} run start --board <board.kicad_pcb> --docker    # or just this one

The image holds KiCad, this plugin, this command line and the solver, so it is
also somewhere to work: mount a project at `/work` and every verb above is
there. **Rebuild it after a plugin update** (`docker rebuild`) — the plugin's
own code is copied inside, so an upgraded install asks for an image tag that
does not exist yet, and `docker status` says so.

A run that wants a container it cannot have is refused with the reason and the
fix, never quietly run outside one. On macOS there is no outside: no macOS
build of the solver ships, so `docker off` is refused there and every run goes
through the container.

## A run costs minutes

Everything above except the two `run start` lines costs milliseconds. A solve
is minutes — 429 s for a small board on a coarse mesh, measured. So reason
about a board for free, and spend a run deliberately.

`run start` therefore never waits. It answers a **job id** — the timestamp
naming the folder that run writes into — and leaves the solver going. Poll
`run status`. `run log --since <offset>` returns the offset to pass next time,
because the solver's output is a flood.

**That id is the only handle there is.** `run status`, `run log`, `run sample`,
`run stop` and `results show` all take the same `--job <id>`, and it is also
the name of the folder under `simulation/results/` holding everything that run
produced — its numbers, its state and its log. Nothing asks for a path to a
dump. Without `--job` each of them means the newest run of that board.

**The solver's own warnings are in that flood, and they are not pre-flight's.**
`preflight` reads the *board* — an outline, a stackup, a marker — and answers
before a solver has been launched. The ground check, the lattice and the copper
around the port are the solver's, decided a minute into a run pre-flight has
already called clean. It prints what it finds with a stable id:

    WARNING [GND-004]: port 1: the feed direction points toward +x ...

so "No problems with the board itself" and a ground warning are both true about
one run. **`run log --severity warning` is that log without the flood** — every
warning and error the run printed, `--severity note` for the mesher's remarks
too, `--severity error` for refusals alone. You do not have to ask, though:
every `run log` ends with what the run has warned about *anywhere* in its log,
not just in the stretch you happened to read, because a warning printed at
meshing time is one a poller reads past exactly once.

**`--grid-only` is the cheap half of that run, and it is in the loop above for
a reason.** A run meshes the board and then steps the fields; the meshing is
the short part, and it is where the solver says what it made of the board —
the cell it settled on, the lattice it built, and every ground warning, all of
which are printed before the first field step. `run start --grid-only` stops
there. Same job id, same `run status`, same `run log`; it writes the grid dump
and no report, so read it with `run log` rather than `results show`. Doing it
first turns "the board was wrong" from minutes into moments — and the mesh it
previews is exactly the one the solve would use.

## The settings file — read it, copy it, edit the copy

**A run is built from a form**, and the form is a flat `key: value` YAML file
beside the board:

    <project>/simulation/settings.yaml

That file is the window's. It rewrites it whenever it closes and whenever it
starts a run, so an edit made there lives until the next time somebody opens
the plugin — which is not long enough to be worth debugging. **Copy it, edit
the copy, and run the copy:**

    cp <project>/simulation/settings.yaml my.yaml
    <edit my.yaml>
    {{command}} run start --board <board.kicad_pcb> --settings my.yaml

`--settings` takes any path. Without it a run reads the board's own file, which
is the right thing when the point is to run what the window is set to.

**If there is no such file**, the window has never been open on that board.
Write a starter and fill in what it leaves blank:

    {{command}} settings init --board <board.kicad_pcb>
    {{command}} settings init --board <board.kicad_pcb> --out my.yaml

It writes the toggles, the picks and one material row per copper layer and per
dielectric gap *of that board*, and it leaves blank everything this plugin has
no business choosing — a target frequency, above all. It refuses to overwrite a
file that is already there. What it wrote a run would still refuse is printed
with it, so there is no guessing about which blank matters.

Every key that file may hold, what a fresh form has in it, and what each picked
value may be, are two sections further down this page. Two rules about editing
one:

- **A blank value means the automatic one.** Every `adv.*` field is a runner
  knob whose 0 is derived from the board and the band — leave it blank unless
  you have a reason, and the reason is usually in `emkit/config.py`, where each
  knob says what its auto resolves to.
- **Do not spell a key the way `pcb.yaml` spells it.** The form is the window's
  vocabulary (`adv.cell_mm`, `no_refine_xy`, `freq`); the config is the
  runner's (`cell_mm`, `refine_xy`, `fpattern_ghz`). A config key in a settings
  file is *refused by name* rather than quietly ignored, and the message says
  how the form spells it.

## Four things worth knowing before you get them wrong

- **Nothing is defaulted.** A missing input is a refusal that names what to
  set. There is no fallback frequency, substrate, impedance or port. If a verb
  refuses, the message names the thing to fix — read it rather than guessing a
  plausible number, because a plausible number is exactly what this plugin
  will not supply for you.
- **`run stop` is not throw-away.** `stop` and `sample` are both requests the
  solver picks up on its next step: stopping writes the report for the record
  so far, and sampling writes one and keeps stepping. Because the channel is a
  file and not a signal, both reach a run whoever started it — this shell,
  another one, the window, or a session that has since closed.
- **The board is read as last saved.** An unsaved edit in KiCad is invisible
  here. Zone fills are read as stored and nothing refills them.
- **One run per board.** A second `run start` on a board that already has one
  going is *refused*, naming the live job: the two would write one config,
  overwrite each other's dumps and share one stop request. A run alongside a
  *different* board's run is fine.

## The board's project folder

Everything for one board lives beside it. Nothing here is yours to edit except
the board and a copy of the settings file:

| path | what it is |
|---|---|
| `<project>/<board>.kicad_pcb` | the board, read as last saved |
| `<project>/simulation/settings.yaml` | the form a run is built from — yours to copy, the window's to rewrite (see above) |
| `<project>/simulation/pcb.yaml` | the runner's config, rewritten every run — never edit |
| `<project>/simulation/results/<stamp>/` | one run, whole. `{{dump}}` is its numbers, `job.json` its state, `run.log` what the solver printed. The stamp is the job id |
| `<project>/simulation/running/` | one lock file per live run, visible across processes |

Everything under `simulation/` is generated output and can be deleted whole.
The generated footprint library sits *beside* it, because that one is yours.
