"""Persist the window's form across launches.

Serialises the shell's widget state to a small YAML file in the board's
``simulation`` folder and restores it when the window opens, so the last-used
application, frequency, speed toggles, Advanced fields, feed-marker sliders,
material picks and each designer's scan rows come back on the next run -- kept
per-project alongside that board's gerbers, config and results. Everything is
stored as flat ``key: value`` string pairs -- no PyYAML dependency (KiCad's
bundled Python may lack it, which is why ``config.py`` hand-writes the runner
YAML too).

The serialization layer (``path``/``load``/``save``) takes the target directory
from the caller, so it stays board-decoupled; ``board_dir`` is the one place
that asks pcbnew where the file goes. The file is best-effort: a missing or
corrupt file just yields an empty dict and the pages open on their built-in
defaults.

The widget side is a two-method contract every page implements
(pages.base.BookPage's no-op default; the form pages override)::

    settings_snapshot() -> dict   the page's persisted keys, flat strings
    settings_restore(data)        set them back (and re-derive dependent UI)

A page just aggregates its sections, which each own the mapping between their
own widgets and the flat dict (``snapshot``/``restore``, also the shared
FormModel's shape -- gui.model). One file holds the whole window, so a save
writes every page's keys together (``save_pages``): a page saving its own would
drop the others'.
"""

from pathlib import Path

_HEADER = (
    "# Antenna Designer saved settings.\n"
    "# Rewritten when the dialog closes or a run starts; safe to delete.\n"
)


def path(directory):
    """Where the settings live -- ``settings.yaml`` inside the board's
    ``simulation`` folder, so each project keeps its own form."""
    return Path(directory) / "settings.yaml"


# --------------------------------------------------------------------------- #
# Flat "key: value" YAML (all values are strings)
# --------------------------------------------------------------------------- #
def _dump(data):
    lines = []
    for key, val in data.items():
        lines.append(f"{key}:" if val == "" else f"{key}: {val}")
    return _HEADER + "\n".join(lines) + "\n"


def _parse(text):
    data = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        data[key.strip()] = val.strip()
    return data


def load(directory):
    """The saved settings dict (string values), or ``{}`` if none/unreadable."""
    try:
        return _parse(path(directory).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def save(directory, data):
    p = path(directory)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump(data), encoding="utf-8")


def board_dir():
    """This board's ``simulation`` folder -- where the per-project settings
    file lives, beside its gerbers, config and results."""
    import pcbnew

    from ..sim import simulate

    return simulate.output_dir(pcbnew.GetBoard())


# --------------------------------------------------------------------------- #
# pages <-> the saved file
# --------------------------------------------------------------------------- #
def collect(pages):
    """Every page's persisted keys in one flat string dict -- what a save
    writes (the pages' key namespaces don't overlap)."""
    data = {}
    for page in pages:
        data.update(page.settings_snapshot())
    return data


def load_into(page):
    """Restore ``page`` from the saved file at launch; a missing or unreadable
    file just leaves its built-in defaults in place. Best-effort: a settings
    file can never keep the window from opening."""
    try:
        data = load(board_dir())
        if data:
            page.settings_restore(data)
    except Exception as exc:
        page.log(f"Could not load saved settings: {exc}")


def save_pages(pages):
    """Write ``pages``' combined form (called when the window closes, when a
    run starts, and when a fresh area marker drops the scan rows); never let a
    save failure interrupt the window."""
    try:
        save(board_dir(), collect(pages))
    except Exception as exc:
        pages[0].log(f"Could not save settings: {exc}")
