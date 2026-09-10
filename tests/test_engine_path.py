"""Finding the container engine from a process that is not a shell
(sim.container.enginepath).

This is the fix for a bug report that reads like a contradiction: "Docker is
installed, `docker version` answers in my terminal, and the plugin says the
docker command was not found." Both are true. KiCad is started from the Dock or
the Start menu, and a GUI process inherits launchd's or the session's PATH, not
the one a login shell builds -- on macOS that is `/usr/bin:/bin:/usr/sbin:/sbin`
and Docker Desktop's client is in none of those.

So what is checked here is that PATH is asked first (it is the right answer
whenever it has one, and it is the only answer a user can influence), that the
installers' own locations are tried after it, and that a machine with genuinely
no Docker still gets the bare name back -- because the spawn's own
FileNotFoundError is what turns into "install Docker", and inventing a path
would turn it into something less useful.

The second half is the environment (``environ``), which is the same bug one
level down. `docker` runs a credential helper and a CLI plugin to do its work,
and looks for them on the PATH we hand it -- so a build started from a window
died with `"docker-credential-desktop": executable file not found in $PATH`
long after the client itself had been found. The helpers sit beside the client,
so what is asserted below is that its directory and the installers' are on the
PATH the engine is given, that the user's own PATH stays in front of them, and
that nothing else about the environment is invented.

    python3 tests/test_engine_path.py   (or pytest)
"""

import contextlib
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

enginepath = load("emkit.sim.container.enginepath")


@contextlib.contextmanager
def _machine(on_path=None, folders=()):
    """A machine where PATH answers *on_path* (or nothing) and the installers'
    locations are *folders* -- module state, so it is put back."""
    kept = (shutil.which, enginepath._FOLDERS)
    shutil.which = lambda name: on_path
    enginepath._FOLDERS = {key: tuple(folders) for key in ("macos", "linux", "windows")}
    try:
        yield
    finally:
        shutil.which, enginepath._FOLDERS = kept


def _executable(path):
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_path_is_asked_first():
    # Whatever a user has arranged wins: an alias to a rootless daemon, a
    # wrapper, a second engine. This module only exists for the case where
    # PATH has no answer at all.
    with _machine(on_path="/somewhere/of/their/own/docker"):
        assert enginepath.find() == "/somewhere/of/their/own/docker"


def test_the_installers_own_location_is_tried_when_path_has_none(tmp_path):
    _executable(tmp_path / "docker")
    with _machine(folders=[str(tmp_path)]):
        assert enginepath.find(system="darwin") == str(tmp_path / "docker")


def test_a_folder_without_it_is_passed_over(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _executable(tmp_path / "docker")
    with _machine(folders=[str(empty), str(tmp_path)]):
        assert enginepath.find(system="darwin") == str(tmp_path / "docker")


def test_a_file_that_cannot_be_run_is_not_the_engine(tmp_path):
    # A directory named docker/, or a Desktop install half removed.
    (tmp_path / "docker").mkdir()
    with _machine(folders=[str(tmp_path)]):
        assert enginepath.find(system="darwin") == "docker"


def test_a_machine_with_no_docker_gets_the_bare_name_back():
    # And so the spawn fails with FileNotFoundError, which the probe turns
    # into "install Docker" -- the right message on that machine.
    with _machine():
        assert enginepath.find(system="linux") == "docker"


def test_the_home_directory_is_expanded(tmp_path):
    # Docker Desktop 4.x offers a per-user install (~/.docker/bin) that touches
    # no system directory, and a literal "~" reaches nothing.
    home = tmp_path / "home"
    (home / ".docker" / "bin").mkdir(parents=True)
    _executable(home / ".docker" / "bin" / "docker")
    kept = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        with _machine(folders=["~/.docker/bin"]):
            assert enginepath.find(system="darwin") == str(
                home / ".docker" / "bin" / "docker"
            )
    finally:
        if kept is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = kept


def test_only_the_first_word_of_a_command_is_touched():
    # The rest is the command line the guide prints and the tests assert; this
    # step is about where the program is, and nothing else.
    with _machine(on_path="/usr/local/bin/docker"):
        assert enginepath.resolved(["docker", "image", "rm", "x-workbench:1"]) == [
            "/usr/local/bin/docker",
            "image",
            "rm",
            "x-workbench:1",
        ]


def test_an_empty_command_is_left_alone():
    with _machine():
        assert enginepath.resolved([]) == []


# --------------------------------------------------------------------------- #
# the environment the engine is started in
# --------------------------------------------------------------------------- #
def test_the_clients_own_directory_is_on_the_path_it_is_given():
    # The bug this exists for: `docker` was found at its full path and then
    # could not find `docker-credential-desktop`, which is its neighbour.
    with _machine(on_path="/usr/local/bin/docker"):
        found = enginepath.search_path(env={"PATH": "/usr/bin"}, system="darwin")
    assert "/usr/local/bin" in found.split(os.pathsep)


def test_the_installers_locations_are_on_it_too(tmp_path):
    # The client can come off PATH while a helper it needs did not, so the
    # known folders go on whether or not that is where the client was found.
    with _machine(on_path="/usr/local/bin/docker", folders=[str(tmp_path)]):
        found = enginepath.search_path(env={"PATH": "/usr/bin"}, system="darwin")
    assert str(tmp_path) in found.split(os.pathsep)


def test_the_users_own_path_stays_in_front():
    # Whatever they arranged wins, here as in `find`: a helper of theirs must
    # not be shadowed by one of Docker Desktop's.
    with _machine(on_path="/usr/local/bin/docker"):
        found = enginepath.search_path(env={"PATH": "/theirs"}, system="darwin")
    assert found.split(os.pathsep)[0] == "/theirs"


def test_a_folder_already_there_is_not_repeated():
    with _machine(on_path="/usr/local/bin/docker"):
        found = enginepath.search_path(env={"PATH": "/usr/local/bin"}, system="darwin")
    assert found.split(os.pathsep).count("/usr/local/bin") == 1


def test_an_empty_path_is_not_an_empty_entry():
    # An empty element in PATH means "the current directory" on every platform
    # that reads one, which is not what a process with no PATH meant.
    with _machine(on_path="/usr/local/bin/docker"):
        found = enginepath.search_path(env={}, system="darwin")
    assert "" not in found.split(os.pathsep)
    assert found.split(os.pathsep)[0] == "/usr/local/bin"


def test_everything_else_in_the_environment_survives():
    # DOCKER_HOST is how a rootless or remote daemon is reached and
    # DOCKER_CONFIG is where the login lives: an environment built from scratch
    # would take a working setup away from the user who arranged it.
    with _machine(on_path="/usr/local/bin/docker"):
        made = enginepath.environ(
            env={"PATH": "/usr/bin", "DOCKER_HOST": "ssh://box", "HOME": "/home/x"},
            system="darwin",
        )
    assert made["DOCKER_HOST"] == "ssh://box"
    assert made["HOME"] == "/home/x"
    assert made["PATH"].startswith("/usr/bin" + os.pathsep)


def test_a_bare_name_contributes_no_directory():
    # find() answers "docker" on a machine with none, and os.path.dirname of
    # that is "" -- which must not reach PATH as the current directory.
    with _machine():
        found = enginepath.search_path(env={"PATH": "/usr/bin"}, system="linux")
    assert found == "/usr/bin"


if __name__ == "__main__":
    run_module_tests(globals())
