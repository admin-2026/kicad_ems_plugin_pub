"""The command lines the plugin gives a container engine (sim.container.cmd,
.image, .runtime).

There is no Docker on this machine and there is none in CI, which is exactly
why these three modules were split out of the part that runs things: what is
checked here is the *argument list*, which is where the failures that would
otherwise be found on a user's machine live -- a mount pointing at the wrong
directory, a path that was never translated, a ``--user`` on the OS that must
not have one, an image tag that does not change when the release does.

    python3 tests/test_container_cmd.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import load, run_module_tests  # noqa: E402

cmd = load("emkit.sim.container.cmd")
image = load("emkit.sim.container.image")
runtime = load("emkit.sim.container.runtime")
builds = load("emkit.sim.builds")
product = load("product")
versions = load("emkit.versions")

TAG = "product-workbench:1.2.3"


def licensed(package):
    """*package* with both licence files inside it, the way an install has
    them. Every staging test needs them, because a context without them is
    refused -- see test_a_context_without_the_licences_is_refused."""
    package.mkdir(parents=True, exist_ok=True)
    for name in image.LICENCE_FILES:
        (package / name).write_text(f"{name} text", encoding="utf-8")
    return package


# --------------------------------------------------------------------------- #
# the probes
# --------------------------------------------------------------------------- #
def test_the_engine_is_asked_its_architecture_not_this_machines():
    # One call answers three questions -- is docker there, is the daemon up,
    # and which architecture will its containers be -- and the third is the
    # one that cannot be guessed from the host: an Apple Silicon Mac has no
    # build of its own and runs arm64 containers.
    assert cmd.version_argv() == ["docker", "version", "--format", "{{.Server.Arch}}"]


def test_an_image_is_asked_for_its_labels():
    argv = cmd.inspect_argv(TAG)
    assert argv[:4] == ["docker", "image", "inspect", TAG]
    assert cmd.LABEL_FORMAT in argv


def test_a_build_records_what_it_was_built_from():
    argv = cmd.build_argv(TAG, "/ctx", labels=(("a", "1"), ("b", "2")))
    assert argv[:4] == ["docker", "build", "-t", TAG]
    assert "--label" in argv and "a=1" in argv and "b=2" in argv
    assert argv[-1] == "/ctx"  # the context is the last word, as docker wants


def test_a_rebuild_removes_the_image_first():
    # Otherwise "rebuild" is a cache hit on the layer that was wrong.
    assert cmd.remove_argv(TAG) == ["docker", "image", "rm", TAG]


def test_a_run_is_killed_by_name():
    # The whole reason a container run carries a name: Popen.kill() reaches
    # the `docker run` client, which is not the thing stepping the fields.
    assert cmd.kill_argv("antenna-run-1") == ["docker", "kill", "antenna-run-1"]


# --------------------------------------------------------------------------- #
# one run
# --------------------------------------------------------------------------- #
def _run_argv(**kwargs):
    return cmd.run_argv(TAG, "/opt/solver/monopole-linux-x86_64", **kwargs)


def test_a_run_is_confined_and_leaves_nothing_behind():
    argv = _run_argv()
    for flag in ("--rm", "--init"):
        assert flag in argv
    assert argv[argv.index("--network") + 1] == "none"


def test_the_run_directory_is_the_only_writable_mount():
    argv = _run_argv(work_dir="/home/me/board/simulation", solver_dir="/opt/p/binaries")
    assert "-v" in argv
    mounts = [argv[i + 1] for i, word in enumerate(argv) if word == "-v"]
    assert "/home/me/board/simulation:/work" in mounts
    assert "/opt/p/binaries:/opt/solver:ro" in mounts
    assert len(mounts) == 2  # nothing else of the user's is visible


def test_the_solver_runs_in_the_mounted_directory():
    # config.write_yaml writes every path in the config relative to the yaml's
    # own folder, which is why the native launcher sets cwd to it too. Get this
    # wrong and every gerber in the config resolves to nothing.
    argv = _run_argv(work_dir="/board/sim")
    assert argv[argv.index("-w") + 1] == cmd.WORK_DIR
    assert argv[argv.index("-w") + 2] == TAG  # the image, then the command


def test_a_run_can_be_named():
    argv = _run_argv(name="antenna-run-9")
    assert argv[argv.index("--name") + 1] == "antenna-run-9"
    # No --cidfile: its path was the run directory's, the same for every run of
    # a board, and an engine refuses (125) to start a run whose cidfile exists.
    assert "--cidfile" not in argv


def test_the_arguments_after_the_image_are_the_solvers():
    argv = cmd.run_argv(TAG, "/opt/solver/x", args=["/work/pcb.yaml", "--grid-only"])
    assert argv[-3:] == ["/opt/solver/x", "/work/pcb.yaml", "--grid-only"]


# --------------------------------------------------------------------------- #
# paths, across the mount
# --------------------------------------------------------------------------- #
def test_a_file_in_the_run_directory_keeps_its_name_and_loses_its_prefix():
    assert cmd.inside(
        "/home/me/b/simulation/pcb.yaml", "/home/me/b/simulation", "/work"
    )
    assert (
        cmd.inside("/home/me/b/simulation/pcb.yaml", "/home/me/b/simulation", "/work")
        == "/work/pcb.yaml"
    )
    assert (
        cmd.inside("/a/sim/gerbers/edge.gbr", "/a/sim", "/work")
        == "/work/gerbers/edge.gbr"
    )
    assert cmd.inside("/a/sim", "/a/sim", "/work") == "/work"


# --------------------------------------------------------------------------- #
# who the run is
# --------------------------------------------------------------------------- #
def test_a_linux_run_owns_what_it_writes():
    # Without this a run's gerbers, config and results in the mounted project
    # belong to root, and the user cannot delete their own results.
    assert runtime.user_argument("posix").count(":") == 1


def test_windows_is_given_no_user():
    # There is no uid to give, and the Desktop engine maps ownership itself.
    assert runtime.user_argument("nt") is None


def test_the_desktop_engines_map_ownership_themselves():
    assert runtime.is_desktop("darwin") and runtime.is_desktop("win32")
    assert not runtime.is_desktop("linux")


# --------------------------------------------------------------------------- #
# which build the container runs
# --------------------------------------------------------------------------- #
def test_the_container_runs_the_build_for_its_own_architecture():
    stem = product.BINARY
    assert runtime.solver_path("amd64", stem) == f"/opt/solver/{stem}-linux-x86_64"
    assert runtime.solver_path("arm64", stem) == f"/opt/solver/{stem}-linux-aarch64"


def test_an_architecture_nothing_is_built_for_has_no_solver():
    assert runtime.solver_path("riscv64", product.BINARY) is None


def test_a_solve_names_the_yaml_as_the_container_sees_it(tmp_path):
    # The one path translation there is. An untranslated /home/... would be a
    # file the container cannot see, and the run would die on its first read.
    yaml = tmp_path / "pcb.yaml"
    yaml.write_text("", encoding="utf-8")
    argv = runtime.solve_argv(
        TAG, product.BINARY, "amd64", str(yaml), system="linux", name="n"
    )
    assert argv[-1] == "/work/pcb.yaml"
    mounts = [argv[i + 1] for i, word in enumerate(argv) if word == "-v"]
    assert f"{tmp_path}:/work" in mounts


def test_a_solve_on_an_unbuilt_architecture_is_no_command_at_all(tmp_path):
    # A refusal the caller turns into a sentence, never a command line that
    # would fail inside the container where nobody can read it.
    yaml = tmp_path / "pcb.yaml"
    yaml.write_text("", encoding="utf-8")
    assert runtime.solve_argv(TAG, product.BINARY, "sparc", str(yaml)) is None


# --------------------------------------------------------------------------- #
# the image's name
# --------------------------------------------------------------------------- #
def test_the_tag_is_the_product_and_the_release():
    assert image.tag() == f"{product.NAME_KEY}-workbench:{versions.plugin_version()}"
    assert image.name() == f"{product.NAME_KEY}-workbench"


def test_a_new_release_wants_a_new_image():
    # The image carries the plugin's own code, so an upgraded plugin is an
    # image that no longer matches -- and asking for a tag that does not exist
    # is how "rebuild it" gets said instead of last release's code answering.
    assert image.tag("0.1.0") != image.tag("0.2.0")
    assert image.stale("0.1.0", version="0.2.0")
    assert not image.stale("0.2.0", version="0.2.0")


def test_an_image_with_no_version_label_is_stale():
    # Built before the label existed, or by hand. Either way it cannot say it
    # is the right one, so it is not treated as one.
    assert image.stale(None, version="0.2.0")


def test_the_image_records_what_is_in_it():
    recorded = dict(image.labels("0.2.0"))
    assert recorded[image.VERSION_LABEL] == "0.2.0"
    assert recorded[image.KICAD_LABEL] == image.KICAD_VERSION
    assert recorded[image.PRODUCT_LABEL] == product.NAME_KEY


def test_the_context_holds_the_package_and_the_binaries_and_nothing_else(tmp_path):
    # Staged rather than pointed at the install: docker copies only from
    # inside its context, and the package and the binaries do not live in one
    # directory in both of this plugin's layouts.
    package = licensed(tmp_path / "pkg")
    (package / "emkit" / "sim").mkdir(parents=True)
    (package / "emkit" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "x.pyc").write_text("", encoding="utf-8")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / f"{product.BINARY}-linux-x86_64").write_text("", encoding="utf-8")

    staged = pathlib.Path(
        image.stage_context(tmp_path / "ctx", package=package, binaries=binaries)
    )
    assert (staged / "Dockerfile").is_file()
    assert (staged / "package" / "emkit" / "__init__.py").is_file()
    assert (staged / "binaries" / f"{product.BINARY}-linux-x86_64").is_file()
    assert not (staged / "package" / "__pycache__").exists()


def test_only_the_builds_a_container_could_run_are_staged(tmp_path):
    # Everything staged is sent to the daemon, and a Windows .exe is several
    # megabytes of a file this image can never launch. A container is Linux
    # whatever the host is.
    package = licensed(tmp_path / "pkg")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for build in builds.BUILDS:
        (binaries / build.filename(product.BINARY)).write_text("x", encoding="utf-8")

    staged = pathlib.Path(
        image.stage_context(tmp_path / "ctx", package=package, binaries=binaries)
    )
    carried = sorted(p.name for p in (staged / "binaries").iterdir())
    assert carried == sorted(
        build.filename(product.BINARY)
        for build in builds.shipped_builds()
        if build.os_key == builds.CONTAINER_OS
    )


def test_the_staged_package_does_not_carry_binaries_twice(tmp_path):
    # An install keeps binaries/ inside the package; the context gives them a
    # place of their own, and shipping both would double the image's weight in
    # the one file that is measured in megabytes.
    package = licensed(tmp_path / "pkg")
    (package / "binaries").mkdir(parents=True)
    (package / "binaries" / "monopole-linux-x86_64").write_text("x", encoding="utf-8")
    staged = pathlib.Path(
        image.stage_context(tmp_path / "ctx", package=package, binaries=None)
    )
    assert not (staged / "package" / "binaries").exists()


# --------------------------------------------------------------------------- #
# the licences
# --------------------------------------------------------------------------- #
def test_both_licences_are_staged_whichever_layout_they_are_in(tmp_path):
    # An install keeps its licences inside the package; an assembled checkout
    # keeps them at its root, beside it. The image needs them either way --
    # it carries the solver, so it carries the terms -- so the search covers
    # both and the Dockerfile copies from one fixed place.
    beside = tmp_path / "checkout"
    package = beside / "pkg"
    package.mkdir(parents=True)
    for name in image.LICENCE_FILES:
        (beside / name).write_text(f"{name} text", encoding="utf-8")

    staged = pathlib.Path(
        image.stage_context(tmp_path / "ctx", package=package, binaries=None)
    )
    for name in image.LICENCE_FILES:
        assert (staged / name).read_text(encoding="utf-8") == f"{name} text"


def test_a_context_without_the_licences_is_refused(tmp_path):
    # Not a warning and not a build that quietly omits them: an image holding a
    # non-commercial-only solver with no statement of its terms anywhere inside
    # it is the one outcome this must not produce, and the staging step is the
    # last place that can still tell.
    package = tmp_path / "pkg"
    package.mkdir()
    try:
        image.stage_context(tmp_path / "ctx", package=package, binaries=None)
    except FileNotFoundError as exc:
        assert image.LICENCE_FILES[0] in str(exc)
    else:  # pragma: no cover -- the assertion is the raise
        raise AssertionError("staged a context with no licence in it")


def test_one_licence_missing_is_still_a_refusal(tmp_path):
    # The solver's terms are the half that matters most, and the half a
    # checkout is most likely to be missing after a file is moved.
    package = tmp_path / "pkg"
    package.mkdir()
    (package / image.LICENCE_FILES[0]).write_text("mit", encoding="utf-8")
    try:
        image.licence_paths(package)
    except FileNotFoundError as exc:
        assert image.LICENCE_FILES[1] in str(exc)
    else:  # pragma: no cover -- the assertion is the raise
        raise AssertionError("accepted a package with one licence")


if __name__ == "__main__":
    run_module_tests(globals())
