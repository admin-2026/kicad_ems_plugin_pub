"""The command line's short name: the file that gets written, and the tick
that writes it (no KiCad, no real config directory).

Two halves, and the seam between them is the whole design: the shim is a file
(agent/shim.py) and the checkbox (gui.sections.cli) keeps no state of its own,
so what is checked here is that the file *is* the setting -- ticking writes it,
unticking removes it, and a box built next to a shim somebody deleted by hand
opens unticked.

Ticking also puts the shortcut's folder on the user's PATH, so this runs on a
home directory of its own: a test that edited the real ``~/.bashrc`` would be
a bug report from whoever ran it. What is checked there is that the block is
fenced, written once however many times it is asked for, and that removing it
leaves the file exactly as it was found -- it is somebody else's file.

The generated script is run on POSIX, where a shebang makes it runnable and
this test's own interpreter can stand in for KiCad's. The Windows spelling is
generated and read rather than run, and the registry half of the PATH entry is
not reachable from here at all -- which is said plainly rather than faked.

    python3 tests/test_agent_shim.py   (or pytest)
"""

import contextlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs the stand-in wx)
from bare_package import PKG, PRODUCT, load, run_module_tests, skip  # noqa: E402

hostpy = load("emkit.agent.hostpy")
shim = load("emkit.agent.shim")
userpath = load("emkit.agent.userpath")
section = load("emkit.gui.sections.cli")
viewers = load("emkit.gui.viewers")

wx = wx_stub.wx

# The box does its writing off the wx thread (a registry broadcast on Windows
# waits on every window on the desktop). Here it is run where it was asked
# for, so what these tests check is the sequence rather than a race; the one
# test that cares about the swap drives it by hand.
section.run_async = lambda work: work()


@contextlib.contextmanager
def _home(nt=False, real_interpreter=False):
    """A config directory *and* a home directory of our own, plus a known
    interpreter to bake in -- this one, which is the only Python this test can
    be sure exists. ``nt`` generates the Windows spelling on whatever this
    machine is."""
    root = tempfile.mkdtemp(prefix="shim_home_")
    real = shim.config_home, shim.interpreter, shim.NAME, hostpy.config_home
    shim.config_home = lambda: root
    hostpy.config_home = lambda: root
    if not real_interpreter:
        shim.interpreter = lambda: sys.executable
    if nt:
        shim.NAME = f"{shim.STEM}.cmd"
    # A home of its own too: ticking the box edits a shell startup file, and a
    # test that edited the *real* one would be a bug report from the person
    # running it.
    home = os.environ.get("HOME")
    os.environ["HOME"] = root
    try:
        yield pathlib.Path(root)
    finally:
        shim.config_home, shim.interpreter, shim.NAME, hostpy.config_home = real
        if home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = home


# --------------------------------------------------------------------------- #
# the file
# --------------------------------------------------------------------------- #
def test_the_shim_is_named_after_the_product():
    """Two products install into one config directory, so the name cannot be
    the core's -- it is the product's, and the si plugin's shim is a different
    file from the antenna plugin's."""
    assert shim.STEM.startswith(PRODUCT.NAME_KEY)
    assert shim.STEM != "ems-agent"


def test_writing_it_makes_a_runnable_command():
    if os.name == "nt":
        skip("a shebang script is not runnable on Windows")
    with _home():
        path = shim.write()
        assert shim.installed()
        assert os.access(path, os.X_OK), "a shortcut nobody may execute"
        out = subprocess.run(
            [path, "--json", "versions"], capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr
        assert json.loads(out.stdout)["versions"]


def test_it_bakes_in_both_paths_so_neither_has_to_be_typed():
    with _home() as home:
        text = pathlib.Path(shim.write()).read_text(encoding="utf-8")
    assert sys.executable in text, "the interpreter is the point of it"
    assert str(PKG / "emkit" / "run_agent.py") in text, "and so is the install"
    assert str(home) not in text.split("\n")[0], "no path in the shebang"


def test_the_windows_spelling_is_a_cmd_file_that_forwards_its_arguments():
    """Generated on Linux and read, which is as far as this can be checked
    here: what matters is that it is a ``.cmd`` (Windows has no shebang) and
    that it passes the verbs on."""
    with _home(nt=True):
        path = shim.write()
        text = pathlib.Path(path).read_text(encoding="utf-8")
    assert path.endswith(".cmd")
    assert "%*" in text, "a shortcut that dropped its arguments"
    assert "@echo off" in text


def test_removing_it_twice_is_not_an_error():
    """Unticking a box whose file somebody already deleted is the wanted state
    arrived at twice, not a failure to report."""
    with _home():
        shim.write()
        shim.remove()
        shim.remove()
        assert not shim.installed()


def test_refresh_rewrites_an_installed_shim_and_creates_no_other():
    """A KiCad upgrade moves the interpreter; the window rewrites the shim it
    finds. It must never bring back one the user removed -- that is the whole
    reason the file is the setting."""
    with _home():
        shim.write()
        shim.interpreter = lambda: "/opt/kicad-10/bin/python3"
        shim.refresh()
        assert "/opt/kicad-10/bin/python3" in pathlib.Path(shim.path()).read_text()

        shim.remove()
        assert shim.refresh() is None
        assert not shim.installed()


# --------------------------------------------------------------------------- #
# which interpreter gets baked in
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _embedded(home):
    """Stand where the plugin really stands: inside KiCad, whose Python is
    *embedded*, so ``sys.executable`` is the KiCad binary and the interpreter
    is the one shipped beside it."""
    binaries = home / "bin"
    binaries.mkdir(exist_ok=True)
    host = binaries / ("pcbnew.exe" if os.name == "nt" else "pcbnew")
    python = binaries / ("python.exe" if os.name == "nt" else "python3")
    host.write_text("")
    python.write_text("")
    real = sys.executable, sys.base_exec_prefix, getattr(sys, "_base_executable", None)
    sys.executable = str(host)
    sys.base_exec_prefix = str(home / "no-python-here")
    sys._base_executable = str(host)  # what CPython reports for an embedded run
    try:
        yield str(host), str(python)
    finally:
        sys.executable, sys.base_exec_prefix = real[0], real[1]
        if real[2] is None:
            del sys._base_executable
        else:
            sys._base_executable = real[2]


def test_the_interpreter_is_never_the_host_binary():
    """The Windows bug this cost a user: KiCad embeds Python, so inside the
    plugin ``sys.executable`` is pcbnew.exe. Baking that in ran *KiCad* on the
    launcher, and KiCad said the script "does not appear to be a valid KiCad
    project file". The interpreter is the one shipped beside the host."""
    with _home(real_interpreter=True) as home:
        with _embedded(home) as (host, python):
            assert hostpy.this_interpreter() == python
            assert shim.interpreter() == python
            text = pathlib.Path(shim.write()).read_text(encoding="utf-8")
        assert python in text
        assert host not in text, "a shortcut that opens KiCad on its own launcher"


def test_a_recording_of_the_host_binary_is_ignored_and_replaced():
    """The same file is already on disk on the machine that hit this, written
    by the version that had the bug. It has to repair itself: an entry that is
    not an interpreter is no answer, and the next window open records the right
    one over it."""
    with _home(real_interpreter=True) as home:
        with _embedded(home) as (host, python):
            os.makedirs(os.path.dirname(hostpy.path()), exist_ok=True)
            with open(hostpy.path(), "w", encoding="utf-8") as handle:
                json.dump({"python": host, "package": str(home)}, handle)
            assert hostpy.recorded()["python"] == host, "it is on disk"
            assert hostpy.interpreter() is None, "and it is not an answer"

            hostpy.record()
            assert hostpy.interpreter() == python


def test_an_interpreter_that_has_gone_is_no_answer():
    """An uninstalled or upgraded KiCad: the recorded path names nothing."""
    with _home(real_interpreter=True) as home:
        os.makedirs(os.path.dirname(hostpy.path()), exist_ok=True)
        with open(hostpy.path(), "w", encoding="utf-8") as handle:
            json.dump({"python": str(home / "gone" / "python3")}, handle)
        assert hostpy.interpreter() is None


# --------------------------------------------------------------------------- #
# the PATH entry
# --------------------------------------------------------------------------- #
def _profile_of(home):
    """The startup file userpath picks for this test's shell, under the home
    the context manager handed out."""
    return pathlib.Path(userpath.profile())


def test_the_block_is_fenced_and_written_once():
    """Ticking twice (a re-install, a second window) must not stack blocks."""
    if os.name == "nt":
        skip("the POSIX half; Windows keeps PATH in the registry")
    with _home() as home:
        folder = str(home)
        userpath.add(folder, shim.STEM)
        userpath.add(folder, shim.STEM)
        text = _profile_of(home).read_text()
        assert text.count(f">>> {shim.STEM} >>>") == 1
        assert text.count(folder) == 1
        assert userpath.installed(folder, shim.STEM)


def test_removing_it_gives_the_file_back_exactly():
    """It is the user's file. Whatever was in it is still in it, unchanged,
    once the block goes."""
    if os.name == "nt":
        skip("the POSIX half; Windows keeps PATH in the registry")
    with _home() as home:
        before = "export EDITOR=vi\n# something of theirs\n"
        _profile_of(home).write_text(before)
        userpath.add(str(home), shim.STEM)
        assert _profile_of(home).read_text() != before
        userpath.remove(str(home), shim.STEM)
        assert _profile_of(home).read_text() == before
        assert not userpath.installed(str(home), shim.STEM)


def test_it_appends_rather_than_replaces_the_path():
    """An entry that came first could shadow a command the user already had."""
    if os.name == "nt":
        skip("the POSIX half; Windows keeps PATH in the registry")
    with _home() as home:
        userpath.add(str(home), shim.STEM)
        line = next(
            ln
            for ln in _profile_of(home).read_text().splitlines()
            if ln.startswith("export PATH=")
        )
        assert line.index("$PATH") < line.index(str(home))


def test_a_profile_that_is_not_there_yet_is_made():
    if os.name == "nt":
        skip("the POSIX half; Windows keeps PATH in the registry")
    with _home() as home:
        assert not _profile_of(home).exists()
        userpath.add(str(home), shim.STEM)
        assert _profile_of(home).is_file()


# --------------------------------------------------------------------------- #
# the tick
# --------------------------------------------------------------------------- #
class _Viewers:
    """A stand-in ViewerHub: records what was presented, in which slot."""

    def __init__(self):
        self.shown = []

    def present(self, slot, url, title):
        self.shown.append((slot, url, title))
        return True


class _Page:
    """Just what a Section reads off its page -- plus the viewer hub the About
    page borrows for the guide this box opens."""

    def __init__(self):
        self.scroll = object()
        self.viewers = _Viewers()
        self.wrapped = []
        self.logged = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def log(self, text):
        self.logged.append(text)

    def _relayout_scroll(self):
        pass


def _box():
    body = wx.BoxSizer()
    return section.CliSection(_Page(), body)


def test_the_box_opens_on_what_is_on_disk():
    with _home():
        assert _box().check.GetValue() is False
        shim.write()
        assert _box().check.GetValue() is True


def test_ticking_writes_it_and_unticking_takes_it_away():
    with _home():
        box = _box()
        box.check.click(True)
        assert shim.installed()
        assert shim.path() in box._status_label.GetLabel()

        box.check.click(False)
        assert not shim.installed()


def test_ticking_puts_the_folder_on_the_path_and_unticking_takes_it_off():
    if os.name == "nt":
        skip("the POSIX half; Windows keeps PATH in the registry")
    with _home() as home:
        folder = os.path.dirname(shim.path())
        box = _box()
        box.check.click(True)
        assert userpath.installed(folder, shim.STEM)
        assert folder in _profile_of(home).read_text()

        box.check.click(False)
        assert not userpath.installed(folder, shim.STEM)


def test_a_ticked_box_shows_the_command_to_type():
    """The whole point of the shortcut is that it is short, so the box says
    what short looks like -- a real verb, spelled the way the guide spells
    it."""
    with _home():
        box = _box()
        resting = box._status_label.GetLabel()
        example = section.CliSection._EXAMPLE.format(command=shim.STEM)
        assert example.strip() not in resting
        # An invitation, not an inventory: a path nobody has asked for yet is
        # the thing that made this line confusing.
        assert shim.path() not in resting
        assert "agent" in resting

        box.check.click(True)
        shown = box._status_label.GetLabel()
        assert f"{shim.STEM} versions" in shown, "the check that needs no board"
        assert "new terminal" in shown, "the open shell keeps its own PATH"


def test_the_guide_moved_here_and_opens_from_this_box():
    """It used to be a button in the Documentation box; it belongs beside the
    thing it explains."""
    with _home():
        page = _Page()
        body = wx.BoxSizer()
        section.CliSection(page, body)
        button = next(
            w
            for w in _flatten(body)
            if getattr(w, "GetLabel", None) and w.GetLabel() == section.GUIDE[0]
        )
        button.fire("EVT_BUTTON")
    ((slot, url, title),) = page.viewers.shown
    assert slot == viewers.HELP, "a guide never replaces a report"
    assert url.endswith("/cli.html")
    assert title == section.GUIDE[2]


def test_a_path_entry_that_fails_leaves_the_shortcut_and_says_so():
    """The two halves fail apart: a shortcut that was written is worth having
    even when the PATH entry could not be, and it still runs by its full
    path."""
    with _home():
        box = _box()
        real = userpath.add
        userpath.add = _raise
        try:
            box.check.click(True)
        finally:
            userpath.add = real
        assert shim.installed(), "the shortcut is written and stays written"
        assert box.check.GetValue() is True
        shown = box._status_label.GetLabel()
        assert "PATH" in shown and "read-only" in shown


def test_a_write_that_fails_is_said_and_the_tick_goes_back():
    """A box claiming a file it has not got is worse than no box."""
    with _home():
        box = _box()
        real = shim.write
        shim.write = _raise
        try:
            box.check.click(True)
        finally:
            shim.write = real
        assert box.check.GetValue() is False
        assert "could not write" in box._status_label.GetLabel()
        assert "read-only" in box._status_label.GetLabel(), "and why"


def test_refreshing_the_box_picks_up_a_shim_deleted_behind_its_back():
    with _home():
        shim.write()
        box = _box()
        shim.remove()
        box.refresh()
        assert box.check.GetValue() is False


def test_the_spinner_takes_the_ticks_place_until_the_work_is_done():
    """It is not instant, so it does not pretend to be: the tick gives way to
    a running indicator, and comes back -- set from the disk -- at the end."""
    with _home():
        held = []
        section.run_async = held.append
        try:
            box = _box()
            box.check.click(True)
            assert box.check.shown is False, "the tick stands aside"
            assert box.busy.shown is True and box.busy.running is True
            assert "Installing" in box._status_label.GetLabel()
            assert not shim.installed(), "nothing has run yet"

            (work,) = held
            work()
        finally:
            section.run_async = lambda work: work()
    assert box.check.shown is True and box.check.GetValue() is True
    assert box.busy.shown is False and box.busy.running is False
    assert shim.STEM in box._status_label.GetLabel()


def test_the_box_never_claims_to_disable_the_command_line():
    """It installs a name; ``run_agent.py`` is a file in the install and runs
    tick or no tick. A label saying otherwise would be a lie the user finds out
    about later."""
    label = section.CliSection._LABEL.lower()
    assert "shortcut" in label
    assert "enable" not in label and "disable" not in label


def _flatten(sizer):
    """Every widget under ``sizer``, its nested sizers walked through."""
    out = []
    for item in sizer.items:
        if isinstance(item, wx.BoxSizer):  # every stand-in sizer is this class
            out.extend(_flatten(item))
        else:
            out.append(item)
    return out


def _raise(*args, **kwargs):
    raise OSError("read-only file system")


if __name__ == "__main__":
    run_module_tests(globals())
