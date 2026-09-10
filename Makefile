# Install / uninstall the Antenna Designer pcbnew plugin (Linux / macOS / Windows).
#
#   make install      copy the plugin into KiCad's user plugin directory
#   make uninstall    remove it
#   make where        print the target install directory
#   make install-cli  install the command line's one-word shortcut (what the
#                     About page's tick writes): a small script with KiCad's
#                     Python and the plugin's path baked in, plus its folder on
#                     your own PATH. Untick the box, or delete the script, to
#                     undo it. It runs the install above where there is one,
#                     and this checkout where there is not -- so it works on a
#                     headless box with kicad-cli and no KiCad user directory.
#                     PYTHON names the interpreter it bakes in, which has to be
#                     one with pcbnew if the window has never recorded KiCad's:
#                       make install-cli PYTHON=/usr/bin/python3
#
# These follow the newest version directory they can find, which is whichever
# major KiCad you installed last; KICAD_VER (below) names another one.
#
#   make package      build dist/AntennaDesigner-<ver>-pcm.zip, the KiCad
#                     add-on for people who don't have a checkout -- what a
#                     release is. One file for every machine, installed from
#                     inside KiCad (Plugin and Content Manager > Install from
#                     File): the route that needs nothing of the user's
#                     machine, no PowerShell, no shell, no Python, and asks
#                     them to pick nothing, since it carries every solver
#                     build and the plugin chooses. Needs all three present in
#                     binaries/: <solver>-linux-x86_64, -linux-aarch64 and
#                     -windows.exe. (No macOS build: there the solver runs in
#                     a container, which is Linux.)
#   make test         the test suite (needs pytest)
#   make clean        delete what the targets above generate -- dist/, the
#                     tool caches, every __pycache__ (clean/dry-run lists them
#                     and removes nothing). Never the solvers in binaries/:
#                     those are copied in, not built here.
#   make docker-image the container image solves can run in (needs Docker)
#   make docker-smoke ...and one run of the command line inside it
#   make lint         ruff's findings (lint/fix applies them, see below)
#   make format       ruff's formatter (format-check reports instead)
#
# The actual filesystem work lives in tools/install.py so it behaves the same
# whether make runs under sh (Linux/macOS/Git Bash) or cmd.exe (native
# Windows); tools/lint.py and tools/clean.py are the same arrangement for the
# lint and clean targets -- `rm -rf` is one shell's, and this one runs on
# Windows too.
#
# Override detection when needed:
#   make install KICAD_VER=8.0
#   make install PLUGIN_DIR="C:/Users/me/Documents/KiCad/9.0/scripting/plugins"

# Pick a Python interpreter that exists on each platform.
ifeq ($(OS),Windows_NT)
  PYTHON ?= py -3
else
  PYTHON ?= python3
endif

# Fold optional overrides into installer flags only when the user set them.
INSTALL_ARGS :=
ifdef KICAD_VER
  INSTALL_ARGS += --kicad-ver $(KICAD_VER)
endif
ifdef PLUGIN_DIR
  INSTALL_ARGS += --plugin-dir "$(PLUGIN_DIR)"
endif

.PHONY: install uninstall reinstall where help package test install-cli \
        docker-image docker-smoke clean clean/dry-run \
        lint lint/fix lint/changed format format-check format/changed

help:
	@$(PYTHON) tools/install.py --help

install:
	$(PYTHON) tools/install.py install $(INSTALL_ARGS)

uninstall:
	$(PYTHON) tools/install.py uninstall $(INSTALL_ARGS)

reinstall: uninstall install

# The short name for the other frontend. Same two steps as the checkbox on the
# plugin's About page, through the same two modules (agent/shim.py,
# agent/userpath.py) -- run it after install, and again after a KiCad upgrade
# moves its Python. With no install to point at it points here instead, which
# is what makes it work on a machine KiCad's window has never run on.
install-cli:
	$(PYTHON) tools/install.py install-cli $(INSTALL_ARGS)

where:
	@$(PYTHON) tools/install.py where $(INSTALL_ARGS)

# The redistributable package: the plugin with the solver binaries already
# nested inside it, wrapped as the KiCad add-on that KiCad's own Plugin and
# Content Manager installs with nothing else involved. It builds on any OS --
# no NSIS, no dpkg, no signing toolchain -- so a release can be cut from the
# machine the plugin is developed on; what can't be cross-built is the solver,
# so every OS's build has to be present in binaries/ already.
#
# Naming an OS (`tools/make_package.py windows`) narrows it to that solver, for
# a checkout that has only one built; the package then says so in its metadata
# and KiCad refuses it elsewhere.
package:
	$(PYTHON) tools/make_package.py

# The suite, against this tree's own plugin: tests/ loads it through
# tools/install.py, so what is tested is the package that is installed from
# here (see tests/bare_package.py). pytest.ini pins where the tests are.
test:
	$(PYTHON) -m pytest

# Undo what the targets above wrote: the packages in dist/, the tool caches,
# and every __pycache__ a test run left in the tree. Not a step anything else
# needs -- a package is rebuilt from scratch either way -- so it exists for the
# times a stale artefact is the suspect, and for reclaiming the space.
#
# It removes only paths .gitignore already names, and specifically not the
# solver builds in binaries/ (copied in from the simulator, not built here) nor
# any repository that happens to live inside this one. tools/clean.py holds
# that list, and says why for each; run the dry-run twin to see what a clean
# would take before it takes it.
clean:
	$(PYTHON) tools/clean.py

clean/dry-run:
	@$(PYTHON) tools/clean.py --dry-run

# The container the solver can run in (emkit/sim/container/). Both targets are
# the plugin's own code doing the work, not a second copy of it in shell: the
# About page's buttons and the command line's `docker` verb take the same path.
#
#   make docker-image   build it (minutes: it installs KiCad)
#   make docker-smoke   build it, then prove the three halves met each other
#
# The smoke check is the only thing that tests an image at all -- that KiCad's
# Python, the copied-in package and the generated shortcut actually found one
# another. It needs a Docker on this machine, which the test suite does not
# have and does not require: everything else about this feature is checked as
# argument lists and states (tests/test_container_*.py).
docker-image:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); \
	  import install; c = install.load_plugin_module('emkit', 'sim', 'container'); \
	  raise SystemExit(0 if c.image_build(on_line=print) else 1)"

docker-smoke: docker-image
	$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); \
	  import install; c = install.load_plugin_module('emkit', 'sim', 'container'); \
	  print(c.image.tag())" > .docker-image-tag
	docker run --rm -v "$(CURDIR):/work" $$(cat .docker-image-tag) versions
	docker run --rm -v "$(CURDIR):/work" $$(cat .docker-image-tag) guide
	rm -f .docker-image-tag

# ---------------------------------------------------------------------------
# Lint and format. Both are ruff, configured by ruff.toml at the repo root so
# an editor picks up the same rules; it is not an install dependency, so
# `pip install ruff` where you lint. Nothing here touches ems/ -- the
# simulator has its own lint (make -C ems lint).
#
# PATHS scopes every target below to a file or directory:
#   make lint PATHS=antenna_plugin/gui
# and the /changed pair scopes to what differs from LINT_BASE instead, which
# is the pre-commit form. The default compares the working tree against the
# last commit; pass a branch (`make lint/changed LINT_BASE=master`) to cover
# everything a branch touched, uncommitted work included.
# ---------------------------------------------------------------------------
PATHS ?=
LINT_BASE ?= HEAD

lint:
	$(PYTHON) tools/lint.py lint $(PATHS)

# The safe fixes only (import order, unused imports, ...). Review the diff:
# a fix is a suggestion, not a proof.
lint/fix:
	$(PYTHON) tools/lint.py fix $(PATHS)

lint/changed:
	$(PYTHON) tools/lint.py lint --changed $(LINT_BASE)

# The tree predates the formatter and is hand-wrapped a little narrower, so
# a bare `make format` rewrites nearly every file. That is a change worth
# making on its own, not one to bury in a feature commit -- reach for
# format/changed, or an explicit PATHS, in day-to-day work.
format:
	$(PYTHON) tools/lint.py format $(PATHS)

format-check:
	$(PYTHON) tools/lint.py format-check $(PATHS)

format/changed:
	$(PYTHON) tools/lint.py format --changed $(LINT_BASE)

# ---------------------------------------------------------------------------
# Machine-local rules. Makefile.local is not tracked: it holds targets that
# only make sense on one machine -- the KiCad majors it actually has, a test
# box to copy a package to. The leading `-` makes the include silent when
# there is no such file, which is the normal case in a fresh clone; the
# include comes last so nothing there can take over the default goal (`make`
# alone stays `help`). Everything the project itself needs is above this line.
# ---------------------------------------------------------------------------
-include Makefile.local
