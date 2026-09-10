"""Preferences about this machine (emkit.hostprefs), and the order they answer
in.

The one that matters is ``use_docker``, because it is read by two frontends
that never see each other: a tick on the About page writes it, and a
``run start`` in some agent's shell reads it. Four sources can answer and they
have to be tried most-specific first, or a flag on the command line loses to a
file somebody ticked last month.

The macOS floor is the interesting case and it is tested on this machine by
saying which machine to answer for -- the same trick ``sim.builds`` and
``sim.hostos`` already use, and the only way the OS this box is not gets tested
at all.

    python3 tests/test_hostprefs.py   (or pytest)
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

hostprefs = load("emkit.hostprefs")

LINUX, MAC = "linux", "darwin"

# The real ``path``, kept because the helpers below replace it: these tests run
# under pytest and under the bare runner at the foot of the file, and only one
# of those has a fixture that would put it back.
REAL_PATH = hostprefs.path


def _saved(tmp_path, value):
    """Put a preferences file where hostprefs will read it."""
    target = tmp_path / "machine.json"
    target.write_text(json.dumps({"docker": value}), encoding="utf-8")
    hostprefs.path = lambda: str(target)
    return target


def _no_file(tmp_path):
    hostprefs.path = lambda: str(tmp_path / "nothing" / "machine.json")


# --------------------------------------------------------------------------- #
# the order
# --------------------------------------------------------------------------- #
def test_off_by_default(tmp_path):
    # A feature that silently rerouted every existing user's runs through a
    # container they have not built is not a courtesy.
    _no_file(tmp_path)
    assert hostprefs.use_docker(system=LINUX, environ={}) is False


def test_the_saved_tick_is_read(tmp_path):
    _saved(tmp_path, True)
    assert hostprefs.use_docker(system=LINUX, environ={}) is True


def test_the_environment_beats_the_saved_tick(tmp_path):
    _saved(tmp_path, True)
    off = {hostprefs.DOCKER_ENV: "0"}
    assert hostprefs.use_docker(system=LINUX, environ=off) is False


def test_an_explicit_flag_beats_the_environment(tmp_path):
    _saved(tmp_path, False)
    environ = {hostprefs.DOCKER_ENV: "0"}
    assert hostprefs.use_docker(True, environ=environ, system=LINUX) is True
    assert hostprefs.use_docker(False, environ={}, system=LINUX) is False


def test_the_environment_variable_is_this_products(tmp_path):
    # Two plugins on one machine are two solvers, two images and two answers.
    product = load("product")
    assert hostprefs.DOCKER_ENV.startswith(product.NAME_KEY.upper())


def test_a_word_the_variable_cannot_mean_is_not_an_answer(tmp_path):
    # It must not read as "off": that is the one interpretation that would
    # send a run out of the container somebody asked for.
    _saved(tmp_path, True)
    assert hostprefs.use_docker(system=LINUX, environ={hostprefs.DOCKER_ENV: "maybe"})
    assert hostprefs.env_choice({hostprefs.DOCKER_ENV: "maybe"}) is None


def test_every_spelling_of_yes_and_no(tmp_path):
    for word in ("1", "true", "YES", " on "):
        assert hostprefs.env_choice({hostprefs.DOCKER_ENV: word}) is True
    for word in ("0", "false", "NO", " off "):
        assert hostprefs.env_choice({hostprefs.DOCKER_ENV: word}) is False


# --------------------------------------------------------------------------- #
# the floor
# --------------------------------------------------------------------------- #
def test_macos_runs_in_a_container_whatever_anything_says(tmp_path):
    # Not a preference being overridden: no macOS build of the solver ships,
    # so there is no native path for a preference to choose.
    _saved(tmp_path, False)
    assert hostprefs.docker_forced(MAC)
    assert hostprefs.use_docker(system=MAC, environ={hostprefs.DOCKER_ENV: "0"})
    assert hostprefs.use_docker(False, environ={}, system=MAC) is True


def test_a_refused_flag_is_said_out_loud(tmp_path):
    # A flag quietly ignored is worse than one refused: the caller asked for
    # something this OS cannot give and should hear it.
    said = hostprefs.refused(False, system=MAC)
    assert said and "container" in said
    assert hostprefs.refused(False, system=LINUX) is None
    assert hostprefs.refused(True, system=MAC) is None


def test_linux_and_windows_still_choose(tmp_path):
    _no_file(tmp_path)
    for system in (LINUX, "win32"):
        assert not hostprefs.docker_forced(system)
        assert hostprefs.use_docker(system=system, environ={}) is False


# --------------------------------------------------------------------------- #
# the file
# --------------------------------------------------------------------------- #
def test_a_broken_file_is_nothing_saved(tmp_path):
    target = tmp_path / "machine.json"
    target.write_text("{not json", encoding="utf-8")
    hostprefs.path = lambda: str(target)
    # Read on the way to opening a window and on the way to starting a run;
    # neither is a place to fail over a stray byte.
    assert hostprefs.load() == {}
    assert hostprefs.saved_choice() is None
    assert hostprefs.use_docker(system=LINUX, environ={}) is False


def test_a_missing_file_is_nothing_saved(tmp_path):
    _no_file(tmp_path)
    assert hostprefs.load() == {}


def test_saving_round_trips(tmp_path):
    target = tmp_path / "sub" / "machine.json"
    hostprefs.path = lambda: str(target)
    hostprefs.save(hostprefs.DOCKER, True)
    assert hostprefs.saved_choice() is True
    hostprefs.save(hostprefs.DOCKER, False)
    assert hostprefs.saved_choice() is False
    assert json.loads(target.read_text(encoding="utf-8")) == {"docker": False}


def test_a_key_nobody_has_heard_of_is_refused(tmp_path):
    hostprefs.path = lambda: str(tmp_path / "machine.json")
    try:
        hostprefs.save("colour", "blue")
        raise AssertionError("expected a refusal")
    except ValueError:
        pass


def test_the_file_sits_with_the_users_other_saved_things():
    # Not beside a board: an answer that is only true of this laptop has no
    # business travelling with a project.
    hostprefs.path = REAL_PATH  # the helpers above point it at a tmpdir
    store = load("emkit.userlib.store")
    assert str(store.config_home()) in hostprefs.path()
    assert store.DIR_NAME in hostprefs.path()


if __name__ == "__main__":
    run_module_tests(globals())
