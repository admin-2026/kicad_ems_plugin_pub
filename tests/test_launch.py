"""How a solve is started (sim.launch), and how it is stopped again.

The seam between "which command line" and "run it and read its output". Three
things are worth pinning here, and each of them fails invisibly if it is wrong:

* **the container's command line is the same run.** The yaml is named as the
  container sees it and the run directory is the working directory, which is
  what makes every relative path in the config resolve identically inside and
  out. Get it wrong and the run dies on its first read, inside a container,
  where the message is somebody else's log.
* **a string is still a launcher.** This seam went in under working code -- a
  wizard scan, a test harness -- and none of that should have had to learn
  about containers to keep working.
* **choosing between them is not a wx-thread question.** It probes the engine,
  and a Docker Desktop still waking up answers slowly; asked from a button's
  handler, that is a window frozen between the click and the run.
* **a container run is not killed by killing what we are holding.** The handle
  is the engine's client. Kill it alone and the container steps on with nobody
  watching, holding a lock on the run folder.

    python3 tests/test_launch.py   (or pytest)
"""

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, modules, run_module_tests  # noqa: E402

launch = load("emkit.sim.launch")
runcontrol = load("emkit.sim.runcontrol")
container = load("emkit.sim.container")
hostprefs = load("emkit.hostprefs")
product = load("product")

TAG = "antenna-workbench:9.9.9"


def _docker_launcher(arch="amd64"):
    return launch.Launcher(
        f"/opt/solver/{product.BINARY}-linux-x86_64", tag=TAG, arch=arch
    )


# --------------------------------------------------------------------------- #
# the command line
# --------------------------------------------------------------------------- #
def test_a_native_run_is_what_it_always_was(tmp_path):
    yaml = tmp_path / "pcb.yaml"
    argv, cwd, name = launch.Launcher("/bin/solver").command(
        str(yaml), grid_only=True, control=str(tmp_path / "run.ctl")
    )
    assert argv == [
        "/bin/solver",
        str(yaml),
        "--grid-only",
        "--control",
        str(tmp_path / "run.ctl"),
    ]
    assert cwd == str(tmp_path)  # the yaml's own folder, as the config expects
    assert name is None  # nothing to ask an engine about


def test_a_path_is_accepted_wherever_a_launcher_goes():
    # The wizard's scan and the test harness hold a path and always have.
    assert launch.of("/bin/solver").exe == "/bin/solver"
    assert not launch.of("/bin/solver").docker
    made = launch.Launcher("/bin/solver")
    assert launch.of(made) is made


def test_a_container_run_names_the_yaml_as_the_container_sees_it(tmp_path):
    yaml = tmp_path / "pcb.yaml"
    argv, cwd, name = _docker_launcher().command(str(yaml))
    assert argv[0] == "docker"
    assert argv[-1] == "/work/pcb.yaml"
    assert cwd == str(tmp_path)
    assert name and name.startswith(f"{product.NAME_KEY}-run-")


def test_the_control_file_is_named_inside_the_container_too(tmp_path):
    # Stop and Snapshot are lines appended to this file on the *host*; the
    # solver polls it from inside, so the path it is given has to be the
    # mounted one. An untranslated /tmp/... is a control channel that silently
    # never delivers -- the run would simply refuse to stop.
    yaml = tmp_path / "pcb.yaml"
    argv, _cwd, _name = _docker_launcher().command(
        str(yaml), control=str(tmp_path / "run.ctl")
    )
    assert argv[argv.index("--control") + 1] == "/work/run.ctl"


def test_a_scan_candidate_mounts_the_folder_its_gerbers_are_in(tmp_path):
    # A scan plots one set of gerbers into the scan folder and writes a config
    # per candidate below it, so every candidate's config says
    # ../gerbers/...gbr. Mount only the candidate's own folder and that path is
    # above the mount: the solver dies on "cannot open ../gerbers/..." before
    # it meshes anything, for every design, on every machine that runs in a
    # container. So the scan folder is mounted and the candidate's directory is
    # the cwd inside it.
    cand = tmp_path / "cand-00"
    cand.mkdir()
    argv, _cwd, _name = _docker_launcher().command(
        str(cand / "pcb.yaml"), mount=tmp_path
    )
    mounts = [argv[i + 1] for i, word in enumerate(argv) if word == "-v"]
    assert f"{tmp_path}:/work" in mounts
    assert argv[argv.index("-w") + 1] == "/work/cand-00"
    assert argv[-1] == "/work/cand-00/pcb.yaml"


def test_flags_are_left_alone(tmp_path):
    argv, _cwd, _name = _docker_launcher().command(
        str(tmp_path / "pcb.yaml"), grid_only=True
    )
    assert "--grid-only" in argv


def test_a_second_run_of_a_board_is_not_refused_by_a_leftover_cidfile(tmp_path):
    # The run directory is a board's, not a run's, so a --cidfile in it is
    # written once and refuses (125) every run after. The container name, which
    # carries the run's stamp, is what a kill uses anyway.
    argv, _cwd, name = _docker_launcher().command(str(tmp_path / "pcb.yaml"))
    assert "--cidfile" not in argv
    assert name and argv[argv.index("--name") + 1] == name


def test_a_container_run_is_started_with_a_path_the_engines_helpers_are_on():
    # The engine is a program that runs other programs -- a credential helper,
    # a CLI plugin -- and finds them on the PATH we hand it, which from a window
    # KiCad opened is launchd's (container.enginepath). A native run inherits
    # ours untouched, which is what None means to Popen.
    assert launch.Launcher("/bin/solver").env is None
    made = _docker_launcher().env
    assert made is not None and made["PATH"]


def test_a_launcher_says_what_it_is_about_to_run():
    assert "/bin/solver" in launch.Launcher("/bin/solver").label
    said = _docker_launcher().label
    assert TAG in said and "amd64" in said


# --------------------------------------------------------------------------- #
# choosing between them
# --------------------------------------------------------------------------- #
class _Probe:
    """A stand-in for container.status."""

    def __init__(self, status):
        self.status = status
        self.asked = 0

    def __call__(self, engine="docker", system=None, kicad_version=None):
        self.asked += 1
        return self.status


def _prepared(status, **kwargs):
    saved = container.status
    container.status = _Probe(status)
    try:
        return launch.prepare(**kwargs)
    finally:
        container.status = saved


def test_a_run_is_native_when_nothing_asks_for_a_container(tmp_path):
    hostprefs.path = lambda: str(tmp_path / "nothing.json")
    launcher = launch.prepare(explicit=False)
    assert not launcher.docker


def test_an_asked_for_container_that_is_not_ready_refuses_with_the_remedy():
    # It must not quietly fall back to a native run: a confinement that does
    # not confine is worse than a run that did not start -- and on macOS there
    # is nothing to fall back to.
    status = container.Status(
        container.NO_IMAGE, "no image antenna-workbench:9.9.9", "Build the image."
    )
    try:
        _prepared(status, explicit=True)
        raise AssertionError("expected a refusal")
    except launch.LaunchError as refusal:
        assert "Build the image." in str(refusal)
        assert refusal.status is status  # a banner can offer the button


def test_a_ready_container_launches_the_build_for_its_architecture():
    status = container.Status(container.READY, "ready", "", arch="arm64")
    launcher = _prepared(status, explicit=True)
    assert launcher.docker
    assert launcher.exe.endswith(f"{product.BINARY}-linux-aarch64")
    assert launcher.exe.startswith(container.cmd.SOLVER_DIR)


# --------------------------------------------------------------------------- #
# stopping one
# --------------------------------------------------------------------------- #
class _Proc:
    """Enough of a Popen to be killed."""

    def __init__(self, container_name=None):
        self.killed = False
        self._alive = True
        if container_name:
            self.container_name = container_name

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self.killed = True
        self._alive = False


def _killed_with(proc):
    """Kill *proc*, answering which containers the engine was asked to end.

    The engine call itself is replaced rather than the subprocess module: what
    is being checked here is that ``kill`` *notices* it is holding a client and
    reaches for the engine at all. What it says to the engine is one argv, and
    that is pinned where every other argv is (test_container_cmd).
    """
    asked = []
    saved = runcontrol._kill_container
    runcontrol._kill_container = asked.append
    try:
        runcontrol.kill(proc)
    finally:
        runcontrol._kill_container = saved
    return asked


def test_a_native_run_is_killed_by_killing_it():
    proc = _Proc()
    assert _killed_with(proc) == []
    assert proc.killed


def test_a_container_run_is_ended_through_the_engine():
    # Killing the client alone leaves the container stepping: the fields carry
    # on, the run folder stays claimed, and nothing is watching it.
    proc = _Proc(container_name="antenna-run-1")
    assert _killed_with(proc) == ["antenna-run-1"]
    assert proc.killed  # and the client too, as the belt to that brace


def test_a_run_that_already_ended_is_not_killed_twice():
    proc = _Proc(container_name="antenna-run-1")
    proc._alive = False
    assert _killed_with(proc) == []


# --------------------------------------------------------------------------- #
# where it may be asked from
# --------------------------------------------------------------------------- #
def _prepare_callers(path):
    """The enclosing function of every ``launch.prepare(...)`` in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "prepare"
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id == "launch"
            ):
                found.append(node.name)
    return found


def test_the_window_never_asks_how_a_run_starts_on_the_wx_thread():
    """``prepare`` probes the container engine -- two subprocesses, and a
    Docker Desktop that is waking up takes seconds over them. Asked from a
    button's handler that is a frozen window between the click and the run, so
    every GUI module asks from its worker thread (``_worker``) instead."""
    for dotted, path in sorted(modules().items()):
        if "gui" not in dotted.split("."):
            continue
        for caller in _prepare_callers(path):
            assert caller == "_worker", f"{dotted}.{caller} prepares on the wx thread"


if __name__ == "__main__":
    run_module_tests(globals())
