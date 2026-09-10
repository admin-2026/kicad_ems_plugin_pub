"""The command line's entry point, and the one promise it makes.

**A caller who asks for JSON gets JSON, whatever happens** -- including when
the arguments themselves are wrong, which argparse would otherwise report as
English on a stream that caller is not reading. And it survives a Plugin
Manager install, whose directory name is neither the package's own nor a legal
Python identifier: the launcher names no package at all.

``versions`` is the smoke test for the whole surface, because it needs no
board and so runs on a machine with no KiCad state at all.

    python3 tests/test_agent_cli.py   (or pytest)
"""

import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import PKG, load, run_module_tests  # noqa: E402
from clirun import run as _run  # noqa: E402  (one command, streams captured)

cli = load("emkit.agent.cli")
shim = load("emkit.agent.shim")
verbs = load("emkit.agent.verbs")
versions = load("emkit.versions")

LAUNCHER = PKG / "emkit" / "run_agent.py"


# --------------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------------- #
def test_versions_has_every_row_the_about_page_has():
    code, out, _ = _run(["--json", "versions"])
    assert code == 0
    rows = json.loads(out)["versions"]
    assert [r["label"] for r in rows] == [label for label, _ in versions.entries()]


def test_every_version_row_is_answered():
    # Nothing here costs a process any more -- the solver's version is
    # declared by the release rather than read off the binary -- so a caller
    # gets the whole table on the first ask, with no flag to discover.
    code, out, _ = _run(["--json", "versions"])
    assert code == 0
    rows = json.loads(out)["versions"]
    assert rows and all(isinstance(r["value"], str) and r["value"] for r in rows)


def test_versions_reads_as_lines_without_json():
    code, out, _ = _run(["versions"])
    assert code == 0
    assert versions.PLUGIN_LABEL in out


# --------------------------------------------------------------------------- #
# the --json promise
# --------------------------------------------------------------------------- #
def test_an_unknown_verb_answers_in_json_on_stdout():
    code, out, err = _run(["--json", "nosuchverb"])
    assert code == 2
    payload = json.loads(out)
    assert payload["ok"] is False and payload["error"]
    assert payload["usage"]
    assert err == ""  # a caller parsing stdout must not have to watch stderr


def test_a_missing_board_answers_in_json_on_stdout():
    code, out, _ = _run(["--json", "preflight"])
    assert code == 2
    assert json.loads(out)["ok"] is False


def test_a_verbs_own_failure_is_its_own_message():
    code, out, _ = _run(["--json", "preflight", "--board", "/nowhere/none.kicad_pcb"])
    assert code == 1
    assert json.loads(out)["ok"] is False


def test_without_json_a_usage_error_is_a_sentence_on_stderr():
    code, out, err = _run(["nosuchverb"])
    assert code == 2
    assert out == ""
    assert err.startswith("error: ")


def test_every_verb_honours_json():
    """Walked off the verb table rather than a list here, so a verb added
    tomorrow is covered the day it lands."""
    for verb in verbs.VERBS:
        code, out, err = _run(["--json", verb.NAME])
        # Either it answered, or it refused -- but in JSON on stdout, and
        # never as English on a stream nobody is reading.
        assert code in (0, 1, 2), verb.NAME
        assert json.loads(out) is not None, verb.NAME
        assert err == "", verb.NAME


def test_a_wrong_flag_on_a_topic_answers_in_json_too():
    """The promise at the depth a caller actually fumbles at. Every topic is
    its own parser now, so the flag has to be inherited all the way down --
    the level that notices a bad argument is the level that has to answer in
    JSON."""
    code, out, err = _run(["--json", "run", "start", "--nope"])
    assert code == 2
    assert json.loads(out)["ok"] is False
    assert err == ""


# --------------------------------------------------------------------------- #
# --help
# --------------------------------------------------------------------------- #
def test_the_usage_lines_name_the_command_and_not_the_launcher():
    """A usage line is copied. Argparse would spell it ``run_agent.py``, the
    file inside the install, which is a command nobody can type without also
    naming KiCad's Python -- and which is not what the guide teaches or what
    every failure's pointer already says."""
    _code, _out, err = _run(["nosuchverb"])
    assert f"usage: {shim.STEM}" in err
    assert "run_agent.py" not in err


def test_a_topic_prints_its_own_help_and_only_its_own_flags():
    """The complaint this answers: ``run start --help`` used to print the
    whole verb's manual and every flag any of its topics takes -- including
    ``--since``, which start ignores, and which a reader has no way of knowing
    it ignores."""
    code, out, _err = _run(["run", "start", "--help"])
    assert code == 0
    assert f"usage: {shim.STEM} run start" in out
    assert "--settings" in out and "--grid-only" in out
    assert "--since" not in out and "--severity" not in out
    # ...and the flags really are somewhere: they are the log's.
    _code, log, _err = _run(["run", "log", "--help"])
    assert "--since" in log and "--severity" in log
    assert "--settings" not in log and "--grid-only" not in log


def test_every_verb_and_topic_answers_help():
    """Walked off the verb table, so a verb or topic added tomorrow is covered
    the day it lands. A page, not an exit status: a parser built wrong is far
    likelier to print nothing than to fail."""
    for verb in verbs.VERBS:
        for argv in [[verb.NAME]] + [
            [verb.NAME, t] for t in getattr(verb, "TOPICS", ())
        ]:
            code, out, _err = _run(argv + ["--help"])
            assert code == 0, argv
            assert f"usage: {shim.STEM} {verb.NAME}" in out, argv


def test_a_console_that_cannot_spell_the_glyphs_does_not_raise():
    """The Windows failure, reproduced on Linux: stdout to a *pipe* is
    encoded with the locale codec, and cp1252 cannot carry ✓ ✗ ⚠ Ω ·. It
    works in an interactive console and breaks under capture, which is the
    agent's only mode."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    real = sys.stdout
    sys.stdout = stream
    try:
        cli.main(["versions"])
        cli.fail("no design target called 'Wi-Fi ✓' — Ω · ⚠", as_json=False)
    finally:
        sys.stdout = real
    stream.flush()


# --------------------------------------------------------------------------- #
# the launcher
# --------------------------------------------------------------------------- #
def test_the_launcher_answers_from_a_checkout():
    out = subprocess.run(
        [sys.executable, str(LAUNCHER), "--json", "versions"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["versions"]


def test_the_launcher_works_from_a_directory_named_like_a_pcm_install():
    """The regression that would otherwise only ever be found by a user. PCM
    extracts the payload to a directory named after the package identity with
    the dots replaced by underscores -- which is not the package's name and is
    not a legal Python identifier, so nothing may reach the package by name."""
    root = tempfile.mkdtemp(prefix="pcm_install_")
    installed = pathlib.Path(root) / "com_github_admin-2026_kicad-ems-plugin-pub"
    shutil.copytree(PKG, installed, ignore=shutil.ignore_patterns("__pycache__"))
    launcher = str(installed / "emkit" / "run_agent.py")
    out = subprocess.run(
        [sys.executable, launcher, "--json", "versions"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["versions"]


if __name__ == "__main__":
    run_module_tests(globals())
