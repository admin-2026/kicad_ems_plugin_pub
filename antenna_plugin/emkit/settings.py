"""The saved form: one flat YAML file per board, both frontends' input.

Serialises the shell's widget state to a small YAML file in the board's
``simulation`` folder and restores it when the window opens, so the last-used
application, frequency, speed toggles, Advanced fields, feed-marker sliders,
material picks and each designer's scan rows come back on the next run -- kept
per-project alongside that board's gerbers, config and results. Everything is
stored as flat ``key: value`` string pairs -- no PyYAML dependency (KiCad's
bundled Python may lack it, which is why ``config.py`` hand-writes the runner
YAML too).

**And it is what a run is made of.** ``formparams`` turns this dict into the
run's parameters, so ``run start`` reads this file -- the board's own, or
another one handed to it with ``--settings`` -- and the window reads its live
widgets through the same translation. One vocabulary, two frontends; the file
is the seam and it can be written by hand (``settings init`` writes a starter).

The keys are the form's own, and the value of a *picked* one is the word the
config takes rather than the caption the widget drew beside it (emkit.choices);
``guide`` prints the whole vocabulary, so this file can be read and edited by
something that has never seen the window.

The serialization layer (``path``/``load``/``save``/``read``) takes the target
from the caller, so it stays board-decoupled; ``board_dir`` is the one place
that asks pcbnew where the file goes. ``load`` is best-effort -- a missing or
corrupt file just yields an empty dict and the pages open on their built-in
defaults -- while ``read`` is for a file a caller *named* and so says why it
could not be read.

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

from .. import product

_HEADER = (
    f"# {product.NAME} saved settings -- the form a run is built from.\n"
    "# The window rewrites THIS file whenever it closes or starts a run, so\n"
    "# edit a copy and run that (`run start --settings <copy>`) instead.\n"
    "# Every key, and what a picked value may be: `guide`.\n"
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


def read(file_path):
    """The form saved in ``file_path``, raising RuntimeError naming the file.

    The named-file half of ``load``: a caller that pointed at a settings file
    (``run start --settings``) is told why that one could not be read, rather
    than being handed the empty dict a missing file means to the window."""
    try:
        data = _parse(Path(file_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"cannot read the settings file {file_path}: {exc}") from exc
    if not data:
        raise RuntimeError(f"{file_path} holds no settings: it is empty")
    return data


def write(file_path, data):
    """Write ``data`` as the flat form file at ``file_path``."""
    target = Path(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump(data), encoding="utf-8")
    return str(target)


def save(directory, data):
    write(path(directory), data)


def board_dir():
    """This board's ``simulation`` folder -- where the per-project settings
    file lives, beside its gerbers, config and results."""
    import pcbnew

    from .sim import simulate

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
