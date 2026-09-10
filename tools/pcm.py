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

One package covers every machine. Nothing about PCM requires that --
``platforms`` below could name a single OS -- but nothing about the payload
objects to it either: the solver builds are a few megabytes each, they sit side
by side under ``binaries/``, and the plugin already picks the one for the
machine it is running on (``sim/builds.py``). So the user is never asked a
question they would have to know their own OS to answer.

PCM's ``platforms`` are operating systems and nothing finer, so an architecture
never reaches the metadata: the two Linux builds travel as one "linux". That is
the whole reason the payload carries both rather than the package being cut per
machine -- KiCad could not tell the two apart to offer the right one.

The payload is the staged plugin tree (``make_package.stage_payload``), so this
module holds no opinion about what an install is made of -- only where PCM
expects the pieces and what its metadata has to say:

    metadata.json          this module
    plugins/               the payload's *contents* (__init__.py at the top)
    resources/icon.png     64x64, drawn by tools/icons/tabs.py

On install KiCad extracts ``plugins/`` to
``<3rdparty>/plugins/<identifier with dots replaced by underscores>/`` and
imports that directory as a Python module. Two consequences, both already
true of the payload and both worth not breaking: the package is imported under
a name that is *not* its own (so nothing in it may import itself absolutely --
every import inside the plugin is relative), and it must find its
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

# The 64x64 icon PCM shows beside the package (tools/icons/ draws it;
# `make icon` regenerates it). Not part of the payload: it is the store front,
# not something the installed plugin ever reads -- the plugin's own 24x24
# toolbar glyph travels inside the payload as usual.
ICON_SOURCE = install.PROJECT_ROOT / "packaging" / "pcm" / ICON_NAME

SCHEMA = "https://go.kicad.org/pcm/schemas/v1"

# Everything about *which* product this package is -- its identifier, its name
# and the two descriptions PCM shows -- is the product's own manifest, not this
# module's: what belongs here is the format. See plugins/<name>/product.py.
PRODUCT = install.PRODUCT

# From the schema's enum. It has non-commercial values (CC-BY-NC-*) but none
# for a package that is two licences at once, so this names the plugin source
# and the product's DESCRIPTION_FULL carries the bundled binary's terms -- the
# same split the repository's LICENSE and LICENSE-solver.txt make, both of
# which ship inside the payload (install.bundle_licences).
LICENSE = "MIT"

# The lowest KiCad this package will install into. The plugin is written
# against 9.0 (it loads on older ones and warns), and PCM treats this as a hard
# floor, so it is the same number the README states rather than a wish.
KICAD_MIN_VERSION = "9.0"

# stable / testing / development / deprecated. PCM's default filter shows only
# stable, so anything else is invisible until the user goes looking.
STATUS = "stable"


def project_url() -> str:
    """The published repository, read from the product's own manifest so the
    package and the About page can never name different projects."""
    return PRODUCT.GITHUB_URL


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
        "name": PRODUCT.NAME,
        "description": PRODUCT.DESCRIPTION,
        "description_full": PRODUCT.DESCRIPTION_FULL,
        "identifier": PRODUCT.PCM_ID,
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
    resources.mkdir(exist_ok=True)
    resources.joinpath(ICON_NAME).write_bytes(ICON_SOURCE.read_bytes())

    text = json.dumps(metadata(version, platforms), indent=2, ensure_ascii=False)
    stage_dir.joinpath(METADATA_NAME).write_text(text + "\n", encoding="utf-8")
