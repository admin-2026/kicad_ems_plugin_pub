"""The board tier: a real ``.kicad_pcb``, loaded by a real pcbnew.

Most of this suite runs anywhere -- ``wx_stub`` and ``fake_pcbnew`` stand in
for what a headless box lacks. A few tests cannot: reading a stackup, plotting
gerbers and resolving a marker are pcbnew doing the work, and a stub that
answered them would be testing the stub.

So those tests come through here, and on a machine with no KiCad they **skip,
once, with the reason**. A board test that silently passed where pcbnew is
absent would be worse than no test at all: it would report a green suite for
the half of the code nobody had run.

    from kicad_board import fixture

    def test_something(tmp_path):
        board = fixture("patch_antenna", into=tmp_path)

``pcbnew`` ships inside KiCad itself -- there is no ``python3-pcbnew`` package
on Debian or Ubuntu -- and it lands in ``/usr/lib/python3/dist-packages``, so
the interpreter that sees it is ``/usr/bin/python3`` and not whatever
virtualenv happens to be first on PATH.

The boards live in ``boards/`` at the top of the checkout, so they are a
directory somebody can open in KiCad and edit. ``tools/assemble.py`` copies it
into every assembled tree, which is why this file looks *up* for it rather than
beside itself: here that is two levels (``emkit/tests/``), in an assembled
checkout one (``tests/``), and neither number is worth spelling twice.
"""

import pathlib
import shutil

from bare_package import skip


def _boards():
    """``boards/`` in the nearest enclosing checkout.

    Not inside the package: these are inputs to a test, never a file an install
    ships. The walk stops at the repository root either way -- an unbounded one
    would happily find some unrelated ``/boards`` on the machine.
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents[:3]:
        if (parent / "boards").is_dir():
            return parent / "boards"
    return here.parent / "boards"  # nothing found: board_path says where it looked


BOARDS = _boards()

_WHY_NO_PCBNEW = (
    "no pcbnew — this needs KiCad's own Python (pcbnew ships inside the "
    "`kicad` package; on Linux that interpreter is /usr/bin/python3, not a "
    "virtualenv's)"
)


def pcbnew():
    """The real ``pcbnew``, or skip.

    Not ``fake_pcbnew``: a test that came through here wants the library, and
    getting the stub instead -- because some earlier import in the same
    process installed it -- would be exactly the silent pass this module
    exists to prevent.
    """
    try:
        import pcbnew as module
    except ImportError:
        skip(_WHY_NO_PCBNEW)
    if not hasattr(module, "GetBuildVersion"):
        skip("pcbnew here is the test stub, not KiCad's own")
    return module


def board_path(name):
    """The fixture board called ``name``, or skip if it is not checked in."""
    found = BOARDS / f"{name}.kicad_pcb"
    if not found.is_file():
        skip(f"no board fixture at {found}")
    return found


def fixture(name, into=None):
    """A fixture board, loaded.

    ``into`` copies it there first, which is what a test that *runs* anything
    wants: the plugin writes its ``simulation/`` folder beside the board, and
    a test must not leave one in the checkout.
    """
    path = board_path(name)
    if into is not None:
        dest = pathlib.Path(into) / path.name
        shutil.copyfile(path, dest)
        path = dest
    loaded = pcbnew().LoadBoard(str(path))
    if loaded is None:
        skip(f"pcbnew could not load {path}")
    return loaded
