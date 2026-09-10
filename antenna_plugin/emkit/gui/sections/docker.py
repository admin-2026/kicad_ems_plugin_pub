"""DockerSection: the About page's container box.

One tick and two buttons over ``sim.container`` and ``emkit.hostprefs`` -- the
same five things the command line's ``docker`` verb offers, through the same
modules, so neither frontend has words of its own for "Docker isn't running".

**Build and Rebuild are one button**, because they are one thing to do and the
probe already knows which: with no image for this release there is nothing to
delete first, and with one there always is. Two buttons meant the user picking
what the last probe had just worked out, and one of them was always wrong.

It sits on the About page for the reason the command-line box does: what it
records is a fact about *this machine*, not about the board in front of you. A
board's settings file travels with the project; "run my solves in a container"
should not.

**The line under the box is the feature.** Every state the probe can report
carries a remedy (sim.container.probe), and this section prints it rather than
composing one: on macOS these are not warnings but the thing standing between a
new user and their first simulation, since no macOS build of the solver ships
and the container is how the product runs there. Which is also why the tick is
drawn ticked and greyed on that OS -- shown, because a box that vanished would
be a mystery, and greyed with ``widgets.enable`` rather than ``Enable(False)``,
which on macOS would swallow the mouse wheel over it and freeze the page
(gui.mac_enable).

**Nothing here happens on the wx thread.** The probe is a process; a build
installs KiCad and is minutes. Both go to a worker and come back through
``wx.CallAfter``, and the buttons give way while one is running -- the same
dance ``sections.cli`` worked out for the shortcut it writes, and ``run_async``
is borrowed from there so a test can drive the sequence without a race.

**The build's own output goes to the page's terminal**, which is why the About
page has one (pages.info, sections.LogSection -- the same section every other
page ends with). The status line under the box says what state things are in;
the log says what the engine is doing, which over four minutes of installing
KiCad is the difference between a build that is working and one that is stuck.

``start_build`` is public because this box is not the only place a build is
asked for: a pre-flight banner reporting "no image built yet" puts the button
on the row, where the user already is, and hands the work here rather than
carrying a second copy of it.
"""

import wx

from ... import hostprefs
from ...sim import container
from ..theme import PAD
from ..widgets import enable, set_tip
from . import banner
from .base import Section
from .cli import run_async
from .guides import open_guide

# The guide this box opens: (button label, help/ file, help-window title). The
# same page the pre-flight banner's "docker-not-ready" row opens, because there
# is one story here and several ways into it.
GUIDE = ("Container guide", "docker.html", "Running the solver in a container")


class DockerSection(Section):
    _TITLE = "Docker"
    _LABEL = "Run the solver inside a Docker container"
    _TIP = (
        "Run solves in a container that can see only the folder this board's "
        "simulation writes into, and no network. A fact about this machine, "
        "not about this board — a command line or an agent on this machine "
        "gets the same answer"
    )
    _FORCED = (
        "On this operating system the solver only runs in a container: no "
        "native build of it ships here."
    )
    _BUILD = "Build image"
    _REBUILD = "Rebuild image"
    _BUILD_TIP = (
        "Build the image this machine runs solves in: KiCad, this plugin and "
        "the solver. Minutes, and a few hundred megabytes"
    )
    _REBUILD_TIP = (
        "Delete the image and build it again — what a plugin upgrade needs, "
        "since this plugin's own code is copied inside it"
    )
    _OFF = (
        "Tick to run solves in a container: the solver then sees one folder "
        "and no network."
    )
    _WORKING = "Checking Docker…"
    _RECIPE = "The image is built from {path} — edit it and press Rebuild image."
    _BUILDING = "Building the image — this installs KiCad, so it takes minutes."
    _BUILT = "✓ Built {image}."
    _FAILED = "✗ The build failed. The last line was: {line}"
    _SAVE_FAILED = "✗ could not save the setting: {error}"

    def __init__(self, page, body):
        super().__init__(page)
        self._status = None  # the last probe's answer
        self._busy = False
        self._done = None  # what to tell when a build somebody else asked for ends
        self._recipe_said = False  # the log opens with where the Dockerfile is
        self._build(body)

    # --- construction ---------------------------------------------------------
    def _build(self, body):
        box = self.box(self._TITLE)
        self.check = wx.CheckBox(self.scroll, label=self._LABEL)
        self.check.Bind(wx.EVT_CHECKBOX, self._toggle)
        set_tip(self.check, self._TIP)
        box.Add(self.check, 0, wx.BOTTOM, PAD)

        row = wx.BoxSizer(wx.HORIZONTAL)
        label, _file, _title = GUIDE
        set_tip(
            self.row_button(row, label, self._open_guide),
            "What the container is for, how to set it up, and what each "
            "message below means",
        )
        self.build_button = self.row_button(row, self._BUILD, self._on_build)
        set_tip(self.build_button, self._BUILD_TIP)
        box.Add(row, 0, wx.EXPAND)

        self._status_label = self.wrap_label(self.scroll, self._OFF, mute=True)
        box.Add(self._status_label, 0, wx.EXPAND | wx.TOP, PAD)
        self._show_preference()
        self.add_to_body(body, box)

    # --- what the page calls --------------------------------------------------
    def refresh(self):
        """The About page came up: re-read the preference, and ask the engine
        where it stands.

        Asked every time rather than once per window, because every answer here
        can change while the plugin is open -- Docker Desktop is started, an
        image is built in another terminal -- and this is a box a user opens
        *because* they are doing one of those things.
        """
        self._show_preference()
        self._say_recipe()
        if self._busy:
            return
        self._set_busy(True, self._WORKING)
        run_async(self._probe)

    def _say_recipe(self):
        """Open this page's log with the Dockerfile's path on this machine.

        The guide can say what the file is *called* and cannot say where it is:
        it is a static page displayed out of the install tree, and the install
        tree is wherever KiCad put it -- a different answer per machine, per
        KiCad version and per install route. This is the window's own answer,
        printed once, in the one control on the page a path can be selected and
        copied out of.
        """
        if self._recipe_said:
            return
        self._recipe_said = True
        self.log(self._RECIPE.format(path=container.image.dockerfile()))

    # --- the guide ------------------------------------------------------------
    def _open_guide(self, event=None):
        label, filename, title = GUIDE
        if not open_guide(self, label, filename, title):
            return  # the shared path already said it is missing
        self.refresh()  # the line went back to being about the guide

    # --- the tick -------------------------------------------------------------
    def _toggle(self, event=None):
        """Remember the answer for this machine. Writing it is a small file, so
        it happens here; what it means for a run is decided at run time by
        whoever starts one."""
        wanted = self.check.GetValue()
        # Whatever the other pages' banners were told about this machine is now
        # wrong in one direction or the other, and they are not about to ask
        # again on their own -- a banner asks when its page is shown.
        banner.recheck_container()
        try:
            hostprefs.save(hostprefs.DOCKER, wanted)
        except OSError as exc:
            # The box goes back to what is actually saved: a tick that did not
            # persist must not look as though it did.
            self._show_preference()
            self._say(self._SAVE_FAILED.format(error=exc))
            return
        self.refresh()

    def _show_preference(self):
        """Put the tick in step with what is saved -- or with the OS, where
        there is nothing to choose."""
        forced = hostprefs.docker_forced()
        self.check.SetValue(hostprefs.use_docker())
        # Greyed, never disabled: a wx-disabled control on macOS swallows the
        # wheel and freezes the page it is on, and macOS is the one OS where
        # this box is always greyed (memory: mac-disabled-scroll).
        enable(self.check, not forced)

    # --- the button -----------------------------------------------------------
    def _on_build(self, event=None):
        self.start_build(rebuild=self._has_image())

    def _has_image(self):
        """Is there an image for this release to delete first? Every state past
        NO_IMAGE has one; the states before it are the engine itself failing,
        where "build" is the honest offer -- a removal would fail the same way
        the probe just did."""
        return self._status is not None and self._status.state in (
            container.STALE,
            container.KICAD_OLDER,
            container.READY,
        )

    def _show_button(self):
        """Build or Rebuild, per the last probe. The label is the whole of the
        difference: pressing it means "make the image right", and what that
        takes is the probe's answer rather than the user's guess."""
        rebuild = self._has_image()
        self.build_button.SetLabel(self._REBUILD if rebuild else self._BUILD)
        set_tip(self.build_button, self._REBUILD_TIP if rebuild else self._BUILD_TIP)

    def start_build(self, rebuild=False, on_done=None):
        """Build (or rebuild) the image. Answers whether it started.

        Public because this box is not the only place a build is asked for: a
        pre-flight banner reporting "no image built yet" offers the button
        where the user is standing, and asks *this* section to do the work
        rather than growing a second copy of it -- so there is one build in the
        window, one place its output is printed, and one thing that knows a
        second one must not start on top of it (False, which the caller says in
        its own words).

        ``on_done`` is called on the wx thread with ``(ok, last_line)`` when it
        finishes, for a caller with a row to redraw.
        """
        if self._busy:
            return False
        self._done = on_done
        self._set_busy(True, self._BUILDING)
        self.log(self._BUILDING)
        run_async(lambda: self._build_image(rebuild))
        return True

    # --- the worker -----------------------------------------------------------
    def _probe(self):
        """Worker: ask the engine where it stands. No widget is touched here."""
        try:
            found = container.status(kicad_version=_kicad_version())
        except Exception as exc:  # a probe must never take the page down
            found = container.Status(container.NO_DOCKER, str(exc), "")
        wx.CallAfter(self._probed, found)

    def _build_image(self, rebuild):
        """Worker: build (or rebuild) the image, printing its output into this
        page's terminal as it arrives.

        Into the log and not onto the status line: the output is thousands of
        lines, the line under the box holds one, and a build that is installing
        KiCad looks exactly like a build that is wedged if all you can see is
        the newest word. ``LogCtrl.log`` is thread-safe and batched, so the
        lines go straight in from here.
        """
        lines = []

        def note(line):
            lines.append(line)
            self.log(line)

        try:
            if rebuild:
                container.image_remove(on_line=note)
            ok = container.image_build(on_line=note)
        except Exception as exc:
            ok, lines = False, [str(exc)]
        wx.CallAfter(self._built, ok, lines[-1] if lines else "")

    # --- back on the wx thread ------------------------------------------------
    def _probed(self, found):
        self._status = found
        self._show_button()
        self._set_busy(False)
        self._say(self._sentence(found))

    def _built(self, ok, last_line):
        self._set_busy(False)
        # The image is there now (or the attempt is over): the banners must not
        # go on showing "no image" at the user who just built one.
        banner.recheck_container()
        done, self._done = self._done, None
        if done is not None:
            done(ok, last_line)  # the row that asked for this build
        if not ok:
            self._say(self._FAILED.format(line=last_line))
            self.log(self._FAILED.format(line=last_line))
            return
        self._say(self._BUILT.format(image=container.image.tag()))
        self.log(self._BUILT.format(image=container.image.tag()))
        self.refresh()  # and say what the engine makes of it now

    def _set_busy(self, busy, text=""):
        """The button off while something is running, and a word about what --
        a build takes minutes, and the one thing that must not happen is a
        second one started on top of it.

        The tick stays as it is: the preference is not what is busy, and a box
        that flickered every time a probe ran would be a box nobody trusts.
        """
        self._busy = busy
        enable(self.build_button, not busy)
        if text:
            self._say(text)

    def _say(self, text):
        try:
            self._set_status(text)
            self._relayout()
        except RuntimeError:
            pass  # the page went away with the window

    # --- the words ------------------------------------------------------------
    def _sentence(self, found):
        """What the box says: what the probe saw, then what to do about it.

        Neither half is written here. The remedy is per state and per OS and
        belongs with the state (sim.container.probe), so that the window, the
        command line and a refused run all say the same thing.
        """
        parts = []
        if hostprefs.docker_forced():
            parts.append(self._FORCED)
        elif not hostprefs.use_docker():
            parts.append(self._OFF)
        if found.ready:
            parts.append(f"✓ {found.detail}.")
            if found.build:
                parts.append(
                    f"Solves run the {found.build.label} build "
                    f"in a {found.arch} container."
                )
        else:
            parts.append(f"✗ {found.detail}.")
            if found.remedy:
                parts.append(found.remedy)
        return " ".join(part for part in parts if part)


def _kicad_version():
    """The host KiCad's ``(major, minor)``, or None off KiCad.

    Read here rather than in the probe: it is a pcbnew question, and the probe
    is one of the modules that has to stay runnable from a shell.
    """
    try:
        from ...kicad.version import get_kicad_version

        return get_kicad_version()
    except Exception:
        return None
