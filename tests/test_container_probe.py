"""Is the container ready, and what does it tell the user (sim.container.probe)?

Driven against a stand-in engine -- a function that answers the way ``docker``
would -- because there is no Docker here and because the failures worth testing
are ones nobody can reproduce on demand anyway: a daemon that is not running, a
socket that refuses this user, an image built by last month's plugin.

What is actually asserted is the *sentence*. Every state has to carry a remedy,
and the remedy has to be this host's -- there is no `docker` group on Windows,
and on macOS these are not warnings but the thing standing between a user and
their first simulation.

    python3 tests/test_container_probe.py   (or pytest)
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

probe = load("emkit.sim.container.probe")
image = load("emkit.sim.container.image")
versions = load("emkit.versions")

ARCH = "arm64"


class Engine:
    """A stand-in ``docker``: canned answers per subcommand, and a record of
    what it was asked."""

    def __init__(self, version=(0, ARCH, ""), labels=None, missing=False):
        self.version = version
        self.labels = labels
        self.missing = missing
        self.asked = []

    def __call__(self, argv, timeout=None):
        self.asked.append(argv)
        if self.missing:
            return None, "", "the docker command was not found"
        if argv[1] == "version":
            return self.version
        if argv[1:3] == ["image", "inspect"]:
            if self.labels is None:
                return 1, "", f"Error: No such image: {argv[3]}"
            return 0, json.dumps(self.labels), ""
        raise AssertionError(f"unexpected command: {argv}")


def _status(monkeypatch_target=None, **kwargs):
    """Ask ``status`` with a stand-in engine; answers (Status, Engine)."""
    engine = Engine(**kwargs)
    saved = probe._run
    probe._run = engine
    try:
        return probe.status(**(monkeypatch_target or {})), engine
    finally:
        probe._run = saved


def _ready_labels(kicad="10.0"):
    return {
        image.VERSION_LABEL: versions.plugin_version(),
        image.KICAD_LABEL: kicad,
    }


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #
def test_no_docker_at_all_says_what_to_install():
    found, _engine = _status({"system": "linux"}, missing=True)
    assert found.state == probe.NO_DOCKER
    assert not found.ready
    assert "Install Docker" in found.remedy


def test_no_remedy_carries_a_url():
    # A remedy is one line in a banner strip, where a URL is neither clickable
    # nor short. What Docker is and where to get it belongs to the guide the
    # row's own Help button opens.
    for kwargs in (
        {"missing": True},  # nothing installed
        {"version": (1, "", "Cannot connect to the Docker daemon")},
        {"version": (1, "", "permission denied while trying to connect")},
        {},  # ready, but no image built
        {"labels": {image.VERSION_LABEL: "0.0.1"}},  # an image from before
    ):
        for system in ("linux", "darwin", "win32"):
            found, _ = _status({"system": system}, **kwargs)
            assert "http" not in found.remedy, (system, kwargs, found.remedy)


def test_the_install_advice_is_this_hosts():
    mac, _ = _status({"system": "darwin"}, missing=True)
    linux, _ = _status({"system": "linux"}, missing=True)
    assert "Docker Desktop" in mac.remedy
    assert "Docker Engine" in linux.remedy


def test_a_daemon_that_is_not_answering_is_not_a_missing_docker():
    # Different failure, different fix: one is an install, the other is a
    # service to start -- and on a Mac it is an application to open.
    found, _ = _status(
        {"system": "linux"}, version=(1, "", "Cannot connect to the Docker daemon")
    )
    assert found.state == probe.NO_DAEMON
    assert "systemctl" in found.remedy

    mac, _ = _status(
        {"system": "darwin"}, version=(1, "", "Cannot connect to the Docker daemon")
    )
    assert "Docker Desktop" in mac.remedy


def test_a_socket_that_refuses_this_user_says_so():
    found, _ = _status(
        {"system": "linux"},
        version=(1, "", "permission denied while trying to connect to the socket"),
    )
    assert found.state == probe.DENIED
    assert "docker` group" in found.remedy


def test_the_group_advice_is_not_given_to_windows():
    # There is no docker group there, and sending somebody to add themselves
    # to one is worse than saying nothing.
    found, _ = _status({"system": "win32"}, version=(1, "", "Access is denied"))
    assert found.state == probe.DENIED
    assert "group" not in found.remedy


# --------------------------------------------------------------------------- #
# the image
# --------------------------------------------------------------------------- #
def test_no_image_yet_is_an_invitation_to_build_one():
    found, engine = _status({"system": "linux"}, labels=None)
    assert found.state == probe.NO_IMAGE
    assert "Build" in found.remedy
    assert image.tag() in found.detail
    # And the engine was asked about *this release's* tag, not a moving one.
    assert engine.asked[-1][3] == image.tag()


def test_an_image_from_an_older_release_is_stale():
    # The state the copied-in source makes necessary: the image carries the
    # plugin's code, so an upgrade leaves last release's code in there.
    found, _ = _status(
        {"system": "linux"},
        labels={image.VERSION_LABEL: "0.0.1", image.KICAD_LABEL: "10.0"},
    )
    assert found.state == probe.STALE
    assert "Rebuild" in found.remedy
    assert "0.0.1" in found.detail


def test_an_image_with_no_version_label_is_stale_too():
    found, _ = _status({"system": "linux"}, labels={image.KICAD_LABEL: "10.0"})
    assert found.state == probe.STALE


def test_an_image_whose_kicad_is_older_than_this_one_is_reported_before_a_run():
    # A board saved by a newer KiCad comes back from an older one's LoadBoard
    # as a bare None. Said here, it is a sentence before the run; unsaid, it is
    # a mystery in the middle of one.
    found, _ = _status(
        {"system": "linux", "kicad_version": (11, 0)}, labels=_ready_labels("10.0")
    )
    assert found.state == probe.KICAD_OLDER
    assert "10.0" in found.detail and "11.0" in found.detail
    assert "Rebuild" in found.remedy


def test_an_image_newer_than_this_kicad_is_fine():
    # One-directional on purpose: a KiCad 10 image reads a KiCad 9 user's
    # boards perfectly, and that is the ordinary state of things.
    found, _ = _status(
        {"system": "linux", "kicad_version": (9, 0)}, labels=_ready_labels("10.0")
    )
    assert found.ready


def test_a_host_with_no_kicad_is_not_compared_against():
    # The command line runs on machines with no KiCad at all. Unknown is not
    # "older", and guessing would refuse a container that works.
    found, _ = _status({"system": "linux"}, labels=_ready_labels("10.0"))
    assert found.ready


# --------------------------------------------------------------------------- #
# ready
# --------------------------------------------------------------------------- #
def test_a_ready_status_names_the_machine_and_the_build_it_will_run():
    found, _ = _status({"system": "darwin"}, labels=_ready_labels())
    assert found.ready
    assert found.arch == ARCH
    # The container's architecture decides the build, not the host's -- this
    # is a Mac, and there is no Mac build at all.
    assert found.build.tag == "linux-aarch64"


def test_the_answer_survives_being_turned_into_data():
    found, _ = _status({"system": "linux"}, labels=_ready_labels())
    payload = found.as_dict()
    assert payload["ready"] is True
    assert payload["image"] == image.tag()
    assert payload["solver"].endswith("linux-aarch64")


def test_the_probe_stops_at_the_first_thing_that_is_wrong():
    # No point reporting a stale image on a machine whose daemon is down: the
    # inspect could not have answered anyway.
    _found, engine = _status({"system": "linux"}, version=(1, "", "cannot connect"))
    assert [argv[1] for argv in engine.asked] == ["version"]


def test_the_engine_is_spawned_without_a_console_window():
    """The About page probes every time it is shown, and on Windows a spawn
    without the flags blinks a terminal at the user (hostos.launch_kwargs)."""
    seen = {}

    class Recorder:
        DEVNULL = None
        SubprocessError = Exception

        @staticmethod
        def run(argv, **kwargs):
            seen.update(kwargs)
            raise OSError("stop here")

    saved_sub, saved_flags = probe.subprocess, probe.hostos.launch_kwargs
    probe.subprocess = Recorder
    Recorder.DEVNULL = saved_sub.DEVNULL
    Recorder.SubprocessError = saved_sub.SubprocessError
    probe.hostos.launch_kwargs = lambda: {"creationflags": 0x08000000}
    try:
        probe._run(["docker", "version"])
    finally:
        probe.subprocess, probe.hostos.launch_kwargs = saved_sub, saved_flags
    assert seen.get("creationflags") == 0x08000000


if __name__ == "__main__":
    run_module_tests(globals())
