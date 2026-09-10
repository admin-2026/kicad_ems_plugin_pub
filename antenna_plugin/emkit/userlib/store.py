"""Where the user's saved entries live between sessions.

One JSON file per kind of entry (``metals.json``, ``substrates.json``, and
whatever the product beside this core saves), each a list of records with a
``name``::

    [{"name": "House laminate", "eps": 3.9, "tan_d": 0.017}]

They are the *user's* entries, not a project's, so the files live in the user's
config directory rather than beside a board -- unlike ``emkit.settings``, which
keeps the per-project half of the form. JSON because it is stdlib (the runner
YAML and the settings file are hand-written only because PyYAML may be missing
under KiCad's Python).

This layer knows nothing about what a record means: it holds dicts keyed by
name, and ``catalog.SavedCatalog`` turns them into whatever kind they are.
Reading is best-effort -- a missing, unreadable or corrupt file yields no
records, so a broken file can never keep a picker from opening. Writing is not:
saving is something the user asked for, so a failure raises and the dialog says
so.

Pure stdlib: no wx, no pcbnew, and testable off KiCad with a temporary
directory. The one import that is not stdlib is the product's manifest, which
imports nothing itself.
"""

import json
import os
from pathlib import Path

# The directory of our own the files sit in below the user's config home. The
# product's, off its manifest: two plugins built out of this core each keep
# their user's entries in a folder of their own, and the core may not spell
# either name (``emkit/__init__.py``). ``agent.shim`` writes the command-line
# shortcut into the same folder, which is why this is the one name for it.
from ...product import CONFIG_DIR as DIR_NAME

# The field every record is identified by.
NAME = "name"


def config_home():
    """The user's configuration directory -- ``%APPDATA%`` on Windows, else
    ``$XDG_CONFIG_HOME`` (``~/.config`` when it isn't set)."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


class UserStore:
    """The named records of one kind, backed by a JSON file.

    Nothing is cached: every call reads the file. Each holds a handful of
    records and is read when a picker is built or restored, while the window
    that wrote it may be another page of this dialog (or another KiCad
    session) -- so the cheap read is also the one that can't go stale.

    ``directory`` is the folder the file lives in; the default is the user's
    own (``config_home()/DIR_NAME``), and the tests pass a temporary one."""

    def __init__(self, filename, directory=None):
        self.filename = filename
        self.directory = (
            Path(directory) if directory is not None else config_home() / DIR_NAME
        )

    @property
    def path(self):
        return self.directory / self.filename

    # --- reading --------------------------------------------------------------
    def load(self):
        """Every named record, in the order the file lists them; ``[]`` when
        there is no file, it can't be read, or it holds nothing usable."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        return [
            r for r in raw if isinstance(r, dict) and str(r.get(NAME) or "").strip()
        ]

    def get(self, name):
        """The record called ``name``, or ``None``."""
        for record in self.load():
            if record[NAME] == name:
                return record
        return None

    # --- writing --------------------------------------------------------------
    def save(self, record):
        """Add ``record``, replacing one of the same name in place (so re-saving
        an entry keeps its position in the picker)."""
        records = self.load()
        for i, saved in enumerate(records):
            if saved[NAME] == record[NAME]:
                records[i] = record
                break
        else:
            records.append(record)
        self._write(records)
        return record

    def delete(self, name):
        """Drop the record called ``name``; ``True`` when there was one."""
        records = self.load()
        kept = [r for r in records if r[NAME] != name]
        if len(kept) == len(records):
            return False
        self._write(kept)
        return True

    def _write(self, records):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
