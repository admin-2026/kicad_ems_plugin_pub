"""The About page's version facts (antenna_plugin.versions), off KiCad.

The module's contract is that it always answers: every probe reports UNKNOWN
rather than raising, whatever the host is missing (here: pcbnew, the package
__init__), and ``entries`` hands a UI a complete list of label/value rows --
every one of them a string, and every one of them free to read, which is what
lets a page draw the table on the thread it was built on.

    python3 tests/test_versions.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

versions = load("emkit.versions")


def test_entries_are_label_value_pairs():
    rows = versions.entries()
    assert rows, "the About page would show an empty table"
    for label, value in rows:
        assert isinstance(label, str) and label
        assert isinstance(value, str) and value


def test_nothing_in_the_table_costs_a_process():
    """The whole list is free to read. It was not: the solver's version used
    to be a callable a caller had to resolve off its UI thread, which on a
    machine whose solver runs in a container would be a container start."""
    assert not [label for label, value in versions.entries() if callable(value)]


def test_the_solver_version_is_the_one_this_release_declares():
    """Declared in the manifest beside the solver's name, not read off the
    binary -- and it is the same string the packager and the sync check."""
    product = load("product")
    assert versions.solver_version() == product.BINARY_VERSION
    assert dict(versions.entries())["Simulator"] == product.BINARY_VERSION


def test_probes_answer_without_a_host():
    """No pcbnew, no wx, no runnable binary here: every fact still answers."""
    for probe in (
        versions.plugin_version,
        versions.kicad_version,
        versions.python_version,
        versions.wx_version,
        versions.solver_version,
    ):
        assert isinstance(probe(), str) and probe()


def test_no_row_is_a_path():
    """Versions only: where a file sits says nothing about what is running,
    and a path is the one value long enough to stretch the table."""
    for label, value in versions.entries():
        assert "/" not in value and "\\" not in value, label


def test_config_schema_is_the_one_the_plugin_writes():
    """The About page must quote the schema the runner YAML actually carries,
    not a copy of it."""
    config = load("config")
    assert versions.config_schema_version() == config.CONFIG_VERSION


if __name__ == "__main__":
    run_module_tests(globals())
