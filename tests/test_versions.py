"""The About page's version facts (antenna_plugin.versions), off KiCad.

The module's contract is that it always answers: every probe reports UNKNOWN
rather than raising, whatever the host is missing (here: pcbnew, the package
__init__, a runnable solver binary), and ``entries`` hands a UI a complete
list of label/value rows -- with the slow probes still deferred, since running
them on a wx thread is what this shape exists to prevent.

    python3 tests/test_versions.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

versions = load("versions")


def test_entries_are_label_value_pairs():
    rows = versions.entries()
    assert rows, "the About page would show an empty table"
    for label, value in rows:
        assert isinstance(label, str) and label
        assert isinstance(value, str) or callable(value)


def test_the_slow_probe_is_deferred():
    """Exactly the facts that cost a process spawn come back as callables --
    a UI shows PENDING for those and resolves them off its main thread."""
    deferred = [label for label, value in versions.entries() if callable(value)]
    assert deferred == ["Simulator"]


def test_resolve_yields_only_strings():
    rows = versions.resolve(versions.entries())
    assert all(isinstance(value, str) for _, value in rows)
    # ... and leaves the labels (and their order) alone.
    assert [label for label, _ in rows] == [label for label, _ in versions.entries()]


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
    for label, value in versions.resolve(versions.entries()):
        assert "/" not in value and "\\" not in value, label


def test_version_word_takes_the_last_word_of_the_first_line():
    assert versions._version_word("monopole 1.4.0\n") == "1.4.0"
    assert versions._version_word("\n\nmonopole 1.4.0\nmore\n") == "1.4.0"
    assert versions._version_word("") == ""
    assert versions._version_word(None) == ""


def test_config_schema_is_the_one_the_plugin_writes():
    """The About page must quote the schema the runner YAML actually carries,
    not a copy of it."""
    config = load("sim.config")
    assert versions.config_schema_version() == config.CONFIG_VERSION


if __name__ == "__main__":
    run_module_tests(globals())
