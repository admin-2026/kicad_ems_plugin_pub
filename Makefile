# Install / uninstall the Antenna Designer pcbnew plugin (Linux / macOS / Windows).
#
#   make install      copy the plugin into KiCad's user plugin directory
#   make uninstall    remove it
#   make where        print the target install directory
#
# These follow the newest version directory they can find, which is whichever
# major KiCad you installed last; KICAD_VER (below) names another one.
#
#   make package      build dist/AntennaDesigner-<ver>-pcm.zip, the KiCad
#                     add-on for people who don't have a checkout -- what a
#                     release is. One file for every OS, installed from inside
#                     KiCad (Plugin and Content Manager > Install from File):
#                     the route that needs nothing of the user's machine, no
#                     PowerShell, no shell, no Python, and asks them to pick
#                     nothing, since it carries every solver build and the
#                     plugin chooses. Needs both binaries/monopole (an ELF)
#                     and binaries/monopole.exe present.
#   make icon         regenerate the bundled PNGs (needs Pillow)
#   make lint         ruff's findings (lint/fix applies them, see below)
#   make format       ruff's formatter (format-check reports instead)
#
# The actual filesystem work lives in tools/install.py so it behaves the same
# whether make runs under sh (Linux/macOS/Git Bash) or cmd.exe (native
# Windows); tools/lint.py is the same arrangement for the lint targets.
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

.PHONY: install uninstall reinstall where icon help package \
        lint lint/fix lint/changed format format-check format/changed

help:
	@$(PYTHON) tools/install.py --help

install:
	$(PYTHON) tools/install.py install $(INSTALL_ARGS)

uninstall:
	$(PYTHON) tools/install.py uninstall $(INSTALL_ARGS)

reinstall: uninstall install

where:
	@$(PYTHON) tools/install.py where $(INSTALL_ARGS)

icon:
	$(PYTHON) tools/make_icon.py

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
