"""Unit tests for emkit.settings (the flat-YAML form file).

The pages' own snapshot/restore need wx widgets (tests/test_scan_section.py
covers the wizard's rows), so these cover what is pure: the string round-trip
and the page aggregation a save writes. What the file *means* to a run is
tests/test_formparams.py. Loaded through the bare package, which
skips the __init__ that imports pcbnew:  python3 tests/test_settings.py
"""

import pathlib

from bare_package import load

settings = load("emkit.settings")


def test_dump_parse_roundtrip():
    data = {
        "app": "2",
        "freq": "2.45",
        "time": "",  # blank field -> "key:" with no value
        "mur": "true",
        "adv.cell_mm": "0.5",
        "materials.metal0.choice": "Rogers RO4003C",  # internal spaces kept
    }
    assert settings._parse(settings._dump(data)) == data


def test_parse_ignores_comments_and_blanks():
    text = "# a comment\n\nfreq: 5.5\n   \nmodel: 1\n"
    assert settings._parse(text) == {"freq": "5.5", "model": "1"}


def test_parse_keeps_value_after_first_colon():
    # Keys never contain a colon; a value that does must survive intact.
    assert settings._parse("note: a: b\n") == {"note": "a: b"}


def test_load_missing_file_is_empty():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        assert settings.load(pathlib.Path(d) / "nope") == {}


def test_save_then_load():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        # Parent dir doesn't exist yet -- save must create it.
        target = pathlib.Path(d) / "cfg"
        settings.save(target, {"freq": "0.915", "mur": "false"})
        assert settings.load(target) == {"freq": "0.915", "mur": "false"}


class _Page:
    """Just the settings side of a page (gui.pages.base.BookPage's contract)."""

    def __init__(self, data):
        self._data = data
        self.restored = None

    def settings_snapshot(self):
        return dict(self._data)

    def settings_restore(self, data):
        self.restored = data


def test_a_save_writes_every_pages_keys():
    """One file holds the whole window: the simulate view's form and each
    designer's scan rows go in together, so a page saving alone can't drop
    another's keys."""
    pages = [
        _Page({"freq": "2.45"}),
        _Page({"scan.l-monopole.length.min": "20"}),
        _Page({"scan.ifa.length.min": "8"}),
    ]
    assert settings.collect(pages) == {
        "freq": "2.45",
        "scan.l-monopole.length.min": "20",
        "scan.ifa.length.min": "8",
    }


if __name__ == "__main__":
    import sys

    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in fns:
        # Skip the fixture-based cases when run without pytest.
        if fn.__code__.co_argcount:
            print(f"SKIP {name} (needs pytest fixtures)")
            continue
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    sys.exit(1 if failed else 0)
