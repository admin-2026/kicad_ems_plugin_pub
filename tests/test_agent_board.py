"""Why a board would not open, in words, without pcbnew.

``pcbnew.LoadBoard`` returns a bare ``None`` for every way of failing there is
and prints nothing: a path with no file at it, a file that is not a board, and
-- the expensive one -- a board saved by a newer KiCad than the one running.
That last one looks exactly like a broken plugin from the outside, and cost an
afternoon before this existed. So the reason is worked out from the file, and
these are the sentences it comes back with.

Text only: nothing here loads a board, which is what makes it run everywhere
rather than only where KiCad is installed.

    python3 tests/test_agent_board.py   (or pytest)
"""

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

kicad = load("emkit.agent.kicad")
version = load("emkit.kicad.version")

# A board file's first lines, which is all any of this reads.
HEAD = (
    '(kicad_pcb\n\t(version {})\n\t(generator "pcbnew")\n\t(generator_version "{}")\n'
)


def _file(text, name="b.kicad_pcb"):
    path = os.path.join(tempfile.mkdtemp(prefix="agent_board_"), name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def test_a_board_from_a_newer_kicad_says_so_and_says_which():
    """The refusal this is all for. A KiCad 10 board handed to a KiCad 9
    pcbnew is unreadable and unfixable from here, and the only thing that helps
    is knowing *that* -- both versions named, and neither the board nor this
    program blamed for it."""
    path = _file(HEAD.format(20260206, "10.0"))
    said = kicad._unreadable(path, host=(9, 0))
    assert "10.0" in said and "9.0" in said
    assert "Python" in said  # ...and what would read it


def test_a_board_this_kicad_could_have_read_is_not_blamed_on_its_version():
    """The other half: an older board that will not open has something else
    wrong with it, and a version sentence would send the reader after a
    mismatch that is not there."""
    path = _file(HEAD.format(20221018, "6.0"))
    said = kicad._unreadable(path, host=(9, 0))
    assert "6.0" not in said and "saved by" not in said
    assert "could not read a board" in said


def test_a_path_with_no_board_at_it_says_what_is_there_instead():
    empty = tempfile.mkdtemp(prefix="agent_board_none_")
    missing = os.path.join(empty, "nope.kicad_pcb")
    assert "nothing is there" in kicad._unreadable(missing, host=(9, 0))
    # A folder is the near miss worth naming: a board is often referred to by
    # the project directory holding it.
    assert "a folder is there" in kicad._unreadable(empty, host=(9, 0))


def test_a_file_that_is_not_a_board_is_told_which_files_are():
    """The other near miss: a schematic or a project handed to --board. Both
    are in the same folder as the board and neither is what a run is plotted
    from."""
    said = kicad._unreadable(_file("(kicad_sch\n", "b.kicad_sch"), host=(9, 0))
    assert "not a KiCad board" in said and ".kicad_sch" in said


def test_which_kicad_wrote_a_board_is_read_off_its_own_header():
    assert version.board_saved_by(HEAD.format(20260206, "10.0")) == (10, 0)
    assert version.board_saved_by(HEAD.format(20241229, "9.0")) == (9, 0)
    # Before KiCad 7 there is no such header -- and those files a KiCad 9 opens
    # anyway, so "no newer version wrote this" is the true answer.
    assert version.board_saved_by("(kicad_pcb (version 20171130)\n") is None


if __name__ == "__main__":
    run_module_tests(globals())
