"""The About page's Docker box (gui.sections.docker), on the wx stand-in.

What is worth holding onto here is not the layout -- it is that the box never
invents a sentence and never blocks the window:

* **the words are the probe's.** Every state carries a remedy, per state and
  per OS (sim.container.probe), and this section prints it. Two frontends
  phrasing "Docker isn't running" differently is the thing that split answer
  was designed to prevent.
* **the tick reflects what is saved**, not what was clicked -- and on an OS
  with no native solver it is drawn ticked and *greyed*, never disabled, since
  a wx-disabled control on macOS swallows the wheel and freezes the page it
  sits on.
* **nothing slow runs on the wx thread.** The probe is a process and a build is
  minutes; both go through the ``run_async`` seam, which a test replaces so
  what is checked is the sequence and not a race.

    python3 tests/test_docker_section.py   (or pytest)
"""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: F401,E402  (installs the stand-in wx)
from bare_package import load, run_module_tests  # noqa: E402

container = load("emkit.sim.container")
hostprefs = load("emkit.hostprefs")
clibox = load("emkit.gui.sections.cli")
dockerbox = load("emkit.gui.sections.docker")
infopage = load("emkit.gui.pages.info")

wx = wx_stub.wx


class _Page:
    """Just what a Section reads off its page."""

    def __init__(self):
        self.scroll = object()
        self.wrapped = []
        self.logged = []

    def register_wrap(self, label):
        self.wrapped.append(label)

    def log(self, text):
        self.logged.append(text)

    def _relayout_scroll(self):
        pass


def _now(work):
    """The ``run_async`` seam, run here and now: the sequence without a race."""
    work()


# What this file stands in for, and puts back. These modules are shared -- one
# suite, one process -- so a stub left behind is a failure in test_hostprefs or
# test_launch: somewhere else, for a reason that is not there. Which is why the
# harness is a context manager and every test uses it as one.
_STUBBED = (
    (
        lambda: hostprefs,
        ("path", "save", "saved_choice", "docker_forced", "use_docker"),
    ),
    (lambda: container, ("status", "image_build", "image_remove")),
    (lambda: dockerbox, ("run_async", "enable")),
    (lambda: clibox, ("run_async",)),
)


@contextlib.contextmanager
def _section(status=None, saved=None, forced=False, tmp_path=None):
    """A built section, with the engine and the preferences stood in for."""
    kept = [
        (module(), name, getattr(module(), name))
        for module, names in _STUBBED
        for name in names
    ]
    try:
        clibox.run_async = _now
        dockerbox.run_async = _now
        if tmp_path is not None:
            hostprefs.path = lambda: str(tmp_path / "machine.json")
        hostprefs.saved_choice = lambda: saved
        hostprefs.docker_forced = lambda system=None: forced
        hostprefs.use_docker = lambda *a, **k: forced or bool(saved)
        container.status = lambda **kwargs: (
            status
            or container.Status(
                container.READY, "antenna-workbench:0.0.0 is ready", "", arch="amd64"
            )
        )
        yield dockerbox.DockerSection(_Page(), wx.BoxSizer())
    finally:
        for module, name, original in kept:
            setattr(module, name, original)


def _said(section):
    return section._status_label.GetLabel()


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #
def test_a_failure_is_reported_with_its_remedy(tmp_path):
    # The whole point of the split answer: this section shows the sentence the
    # probe wrote, so the window, the command line and a refused run agree.
    status = container.Status(
        container.NO_DAEMON, "Cannot connect to the Docker daemon", "Start Docker."
    )
    with _section(status, saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        assert "Cannot connect to the Docker daemon" in _said(section)
        assert "Start Docker." in _said(section)


def test_a_ready_container_says_which_build_it_will_run(tmp_path):
    with _section(saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        said = _said(section)
        assert "✓" in said and "amd64" in said


def test_a_stale_image_is_reported_as_something_to_rebuild(tmp_path):
    # The state the copied-in plugin code makes necessary.
    status = container.Status(
        container.STALE, "built by an older release", "Rebuild the image."
    )
    with _section(status, saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        assert "Rebuild the image." in _said(section)


def test_an_os_with_no_native_solver_says_why_the_box_cannot_be_unticked(tmp_path):
    with _section(forced=True, tmp_path=tmp_path) as section:
        section.refresh()
        assert "only runs in a container" in _said(section)


# --------------------------------------------------------------------------- #
# the tick
# --------------------------------------------------------------------------- #
def test_the_tick_shows_what_is_saved(tmp_path):
    with _section(saved=True, tmp_path=tmp_path) as section:
        assert section.check.GetValue() is True
    with _section(saved=False, tmp_path=tmp_path) as section:
        assert section.check.GetValue() is False


def test_ticking_writes_the_preference(tmp_path):
    written = []
    with _section(saved=False, tmp_path=tmp_path) as section:
        hostprefs.save = lambda key, value: written.append((key, value))
        section.check.SetValue(True)
        section._toggle()
        assert written == [(hostprefs.DOCKER, True)]


def test_a_preference_that_could_not_be_saved_is_said_and_not_shown(tmp_path):
    # A tick that did not persist must not look as though it did.
    def refuse(key, value):
        raise OSError("read-only file system")

    with _section(saved=False, tmp_path=tmp_path) as section:
        hostprefs.save = refuse
        section.check.SetValue(True)
        section._toggle()
        assert section.check.GetValue() is False
        assert "could not save" in _said(section)


def test_the_tick_is_shown_ticked_where_there_is_no_choice(tmp_path):
    # Shown, not hidden: a box that vanished on one OS would be a mystery, and
    # this is the OS where the container is how the product runs.
    with _section(forced=True, tmp_path=tmp_path) as section:
        assert section.check.GetValue() is True


def test_nothing_here_is_greyed_by_disabling_it(tmp_path):
    # On macOS a wx-disabled control swallows the wheel outright -- the notch
    # reaches neither wx nor the scroll view -- so the page freezes wherever
    # the pointer rests on it. widgets.enable is the way round that, and this
    # box is greyed on exactly that OS, so it has to be the one used.
    greyed = []
    with _section(forced=True, tmp_path=tmp_path) as section:
        dockerbox.enable = lambda ctrl, flag=True: greyed.append((ctrl, flag)) or ctrl
        section.refresh()
        assert (section.check, False) in greyed
        # What `enable` then does is the platform's business and is checked
        # where it lives (test_mac_enable): off macOS it is `Enable` and
        # nothing more, which is why the assertion here is about the route and
        # not about the flag that comes out the other end.


# --------------------------------------------------------------------------- #
# building
# --------------------------------------------------------------------------- #
def test_building_streams_and_then_reports(tmp_path):
    with _section(saved=True, tmp_path=tmp_path) as section:
        container.image_build = lambda on_line=None: (on_line("Step 1/8"), True)[1]
        section._on_build()
        assert "is ready" in _said(section)  # it re-probes when the build lands


def test_the_one_button_says_build_until_there_is_an_image_to_rebuild(tmp_path):
    # One button, because the probe already knows which of the two it is: with
    # no image there is nothing to delete first, with one there always is.
    status = container.Status(container.NO_IMAGE, "no image", "Build the image.")
    with _section(status, saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        assert section.build_button.GetLabel() == dockerbox.DockerSection._BUILD
    status = container.Status(container.STALE, "older release", "Rebuild it.")
    with _section(status, saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        assert section.build_button.GetLabel() == dockerbox.DockerSection._REBUILD


def test_pressing_it_with_an_image_there_removes_it_first(tmp_path):
    # Otherwise "rebuild" is a cache hit on the layer that was wrong.
    order = []
    with _section(saved=True, tmp_path=tmp_path) as section:
        section.refresh()  # a ready image: the button is Rebuild now
        container.image_remove = lambda on_line=None: order.append("remove")
        container.image_build = lambda on_line=None: order.append("build") or True
        section._on_build()
        assert order == ["remove", "build"]


def test_pressing_it_with_no_image_only_builds(tmp_path):
    status = container.Status(container.NO_IMAGE, "no image", "Build the image.")
    order = []
    with _section(status, saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        container.image_remove = lambda on_line=None: order.append("remove")
        container.image_build = lambda on_line=None: order.append("build") or True
        section._on_build()
        assert order == ["build"], "there was nothing there to delete"


def test_the_log_opens_with_where_the_dockerfile_is(tmp_path):
    # The guide can name the file and cannot say where it is -- a static page,
    # displayed out of an install tree that is wherever KiCad put it. So the
    # window answers, once, in the one control on the page a path can be
    # selected out of.
    with _section(saved=True, tmp_path=tmp_path) as section:
        section.refresh()
        first = section.page.logged[0]
        assert first.endswith("Dockerfile — edit it and press Rebuild image.")
        assert container.image.dockerfile() in first

        section.refresh()  # the About page is opened again, and again
        assert section.page.logged.count(first) == 1, "the log is not a chorus"


def test_the_engines_output_goes_to_the_pages_terminal(tmp_path):
    # Not to the one-line status: a build installs KiCad and takes minutes, and
    # one that is working looks exactly like one that is wedged if all you can
    # see is the newest word. This is why the About page has a log at all.
    with _section(saved=True, tmp_path=tmp_path) as section:
        container.image_build = lambda on_line=None: (
            on_line("Step 1/8"),
            on_line("Step 2/8"),
            True,
        )[-1]
        section._on_build()
        assert "Step 1/8" in section.page.logged
        assert "Step 2/8" in section.page.logged
        assert "Step 2/8" not in _said(section), "the status line is not a console"


def test_a_build_can_be_started_from_elsewhere_and_reports_back(tmp_path):
    # The pre-flight banner's "no image built yet" row offers the button where
    # the user is standing and hands the work here, so there is one build in
    # the window and one place its output is printed.
    told = []
    with _section(saved=True, tmp_path=tmp_path) as section:
        container.image_build = lambda on_line=None: True
        assert section.start_build(on_done=lambda *args: told.append(args)) is True
        assert told == [(True, "")]


def test_a_second_build_is_refused_rather_than_stacked(tmp_path):
    # The caller says so in its own words; what must not happen is two builds
    # of one image at once because two pages both show the row.
    with _section(saved=True, tmp_path=tmp_path) as section:
        started = []

        def slow(on_line=None):
            started.append(section.start_build())  # while the first one runs
            return True

        container.image_build = slow
        section._on_build()
        assert started == [False]


def test_a_failed_build_shows_the_last_line_it_printed(tmp_path):
    def failing(on_line=None):
        on_line("E: Unable to locate package kicad")
        return False

    with _section(saved=True, tmp_path=tmp_path) as section:
        container.image_build = failing
        section._on_build()
        assert "Unable to locate package kicad" in _said(section)


def test_the_button_is_off_while_a_build_is_running(tmp_path):
    seen = []
    with _section(saved=True, tmp_path=tmp_path) as section:

        def slow(on_line=None):
            seen.append(section.build_button.enabled)
            return True

        container.image_build = slow
        section._on_build()
        assert seen == [False], "a second build could be started while one runs"
        assert section.build_button.enabled


def test_the_about_page_carries_the_terminal_this_box_prints_into():
    # The box logs through its page (Section.log -> BookPage.log -> log_ctrl),
    # which on a page with no log section goes nowhere at all -- silently. So
    # the wiring is asserted rather than assumed: this is the one page in the
    # window that grew a log because of this feature.
    page = infopage.InfoPage(None)
    assert page.log_ctrl is not None
    assert page.log_ctrl is page.log_section.ctrl
    page.log("Step 1/8")  # the route the build's output takes


def test_a_probe_that_raises_does_not_take_the_page_down(tmp_path):
    def explode(**kwargs):
        raise RuntimeError("something odd")

    with _section(saved=True, tmp_path=tmp_path) as section:
        container.status = explode
        section.refresh()
        assert "something odd" in _said(section)


if __name__ == "__main__":
    run_module_tests(globals())
