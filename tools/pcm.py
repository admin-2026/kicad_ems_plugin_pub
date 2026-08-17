"""The KiCad Plugin and Content Manager package: its metadata and its shape.

PCM is KiCad's own installer, and the only one this project ships. The user
opens *Plugin and Content Manager > Install from File*, picks the zip, and
KiCad copies the payload into its own plugin directory -- so this route
assumes nothing whatsoever about the machine: no PowerShell (whose absence, or
whose execution policy set by a group policy, is what used to stop the
scripted Windows installer before it drew anything), no cmd, no Python
interpreter, no administrator rights, no SmartScreen prompt over an unsigned
executable. KiCad is already there, by definition, or there would be nothing to
install into. It also gives two things a downloaded archive cannot: an
uninstall button and an update notice, both native.

One package covers every OS. Nothing about PCM requires that -- ``platforms``
below could name a single one -- but nothing about the payload objects to it
either: the solver builds are a few megabytes, they sit side by side under
``binaries/``, and the plugin already picks the one for the machine it is
running on (``sim/hostos.exe_names``). So the user is never asked a question
they would have to know their own OS to answer.

The payload is the staged ``antenna_plugin`` tree
(``make_package.stage_payload``), so this module holds no opinion about what an
install is made of -- only where PCM expects the pieces and what its metadata
has to say:

    metadata.json          this module
    plugins/               the payload's *contents* (__init__.py at the top)
    resources/icon.png     64x64, drawn by tools/icons/tabs.py

On install KiCad extracts ``plugins/`` to
``<3rdparty>/plugins/<identifier with dots replaced by underscores>/`` and
imports that directory as a Python module. Two consequences, both already
true of the payload and both worth not breaking: the package is imported under
a name that is *not* ``antenna_plugin`` (so nothing in it may import itself
absolutely -- every import inside the plugin is relative), and it must find its
own solver binary relative to ``__file__`` rather than by name
(``sim.simulate.locate`` walks its parents, which is why the binary staged
under ``plugins/binaries/`` is found there).

The schema is v1 (https://go.kicad.org/pcm/schemas/v1) because that is what
KiCad 9 validates against -- it ships no v2 schema at all, so a v2-only field
would be refused by the very version this package names as its minimum.
"""

from __future__ import annotations

import json
from pathlib import Path

import install

# Where the archive's three parts go. PCM is strict about this: metadata.json
# sits at the archive *root*, with no wrapping directory around it -- KiCad
# reads the archive itself, so nobody unpacks it into whatever directory they
# happen to be standing in and needs protecting from a scattered tree.
PLUGINS_DIR = "plugins"
RESOURCES_DIR = "resources"
METADATA_NAME = "metadata.json"
ICON_NAME = "icon.png"

# The 64x64 icon PCM shows beside the package (tools/icons/tabs.py draws it;
# `make icon` regenerates it). Not part of the payload: it is the store front,
# not something the installed plugin ever reads -- the plugin's own 24x24
# toolbar glyph travels inside the payload as usual.
ICON_SOURCE = install.PROJECT_ROOT / "packaging" / "pcm" / ICON_NAME

SCHEMA = "https://go.kicad.org/pcm/schemas/v1"

# The package's identity to PCM, and the only string here that must never
# change: it is the install directory, the Python module name the plugin is
# imported under, and how PCM recognises an installed copy as *this* package
# rather than a new one. Reverse-DNS over the published repository
# (links.GITHUB_URL), with the underscores the schema's pattern forbids written
# as dashes. If the repository is ever renamed, this stays as it is.
IDENTIFIER = "com.github.admin-2026.kicad-ems-plugin-pub"

NAME = "Antenna Designer"

# Shown in the package list. The schema caps it at 150 characters.
DESCRIPTION = (
    "Design and simulate PCB antennas without leaving pcbnew: a bundled FDTD "
    "solver, plus wizards for common antenna topologies."
)

# Shown when the package is selected. This is also the only place the package
# can be honest about its licensing: the metadata `license` field below is an
# enum with no value for "part of this is proprietary and non-commercial", so
# the split is spelled out here instead. It is what a user reads *before*
# installing, which is the only notice they get before the binary is on their
# machine -- the terms themselves ride along as LICENSE-solver.txt.
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

# From the schema's enum. It has non-commercial values (CC-BY-NC-*) but none
# for a package that is two licences at once, so this names the plugin source
# and DESCRIPTION_FULL carries the bundled binary's terms -- the same split the
# repository's LICENSE and LICENSE-solver.txt make, both of which ship inside
# the payload (install.bundle_licences).
LICENSE = "MIT"

# The lowest KiCad this package will install into. The plugin is written
# against 9.0 (it loads on older ones and warns), and PCM treats this as a hard
# floor, so it is the same number the README states rather than a wish.
KICAD_MIN_VERSION = "9.0"

# stable / testing / development / deprecated. PCM's default filter shows only
# stable, so anything else is invisible until the user goes looking.
STATUS = "stable"


def project_url() -> str:
    """The published repository, read from the plugin's own ``links`` module
    so the package and the About page can never name different projects."""
    return install.load_plugin_module("links.py").GITHUB_URL


def author() -> dict:
    """Who PCM names as the package's author: the account the repository is
    published under, taken from the URL rather than written out again."""
    url = project_url()
    return {"name": url.rstrip("/").split("/")[-2], "contact": {"web": url}}


def metadata(version: str, platforms: list[str]) -> dict:
    """The ``metadata.json`` for one build of one release.

    Note what is *absent*: the ``download_*`` keys. They describe an archive
    sitting on a server and belong only to the copy submitted to a package
    repository -- inside the archive they describe, they would be a hash of
    something that does not exist yet.
    """
    url = project_url()
    return {
        "$schema": SCHEMA,
        "name": NAME,
        "description": DESCRIPTION,
        "description_full": DESCRIPTION_FULL,
        "identifier": IDENTIFIER,
        "type": "plugin",
        "author": author(),
        "license": LICENSE,
        "resources": {"homepage": url},
        "versions": [
            {
                "version": version,
                "status": STATUS,
                "kicad_version": KICAD_MIN_VERSION,
                # The OSes whose solver build is actually in this archive --
                # normally all of them, since one add-on serves every machine
                # and the plugin picks its own binary at run time. Stating them
                # is what makes PCM refuse the package on an OS whose solver
                # was left out, instead of installing something that would fail
                # at the first simulation.
                "platforms": platforms,
            }
        ],
    }


def stage(stage_dir: Path, *, version: str, platforms: list[str], payload) -> None:
    """Assemble the PCM archive tree under *stage_dir*.

    *payload* is called with the directory the plugin's contents belong in;
    what it puts there is ``make_package``'s business, not this module's.
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    payload(stage_dir / PLUGINS_DIR)

    if not ICON_SOURCE.is_file():
        raise SystemExit(
            f"PCM icon not found: {ICON_SOURCE}\nRegenerate it with `make icon`."
        )
    resources = stage_dir / RESOURCES_DIR
    resources.mkdir()
    resources.joinpath(ICON_NAME).write_bytes(ICON_SOURCE.read_bytes())

    text = json.dumps(metadata(version, platforms), indent=2, ensure_ascii=False)
    stage_dir.joinpath(METADATA_NAME).write_text(text + "\n", encoding="utf-8")
