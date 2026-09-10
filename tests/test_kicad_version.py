"""Unit tests for antenna_plugin.kicad.version (pure, no KiCad).

Loaded through the bare package: the package __init__ imports pcbnew.
"""

from bare_package import load

kicad_version = load("emkit.kicad.version")


def test_parses_plain_version():
    assert kicad_version._parse_major_minor("9.0.0") == (9, 0)


def test_parses_dev_build_suffix():
    assert kicad_version._parse_major_minor("9.0.1-rc1-1519-g0058bb5a24") == (9, 0)


def test_unparseable_returns_none():
    assert kicad_version._parse_major_minor("unknown") is None


def test_no_warning_on_current_and_newer(monkeypatch):
    monkeypatch.setattr(kicad_version, "get_kicad_version", lambda: (9, 0))
    assert kicad_version.kicad_version_warning() is None
    monkeypatch.setattr(kicad_version, "get_kicad_version", lambda: (9, 5))
    assert kicad_version.kicad_version_warning() is None
    monkeypatch.setattr(kicad_version, "get_kicad_version", lambda: (10, 0))
    assert kicad_version.kicad_version_warning() is None


def test_older_version_warns_naming_both_versions(monkeypatch):
    monkeypatch.setattr(kicad_version, "get_kicad_version", lambda: (8, 0))
    warning = kicad_version.kicad_version_warning()
    assert warning is not None
    assert "9.0" in warning and "8.0" in warning


def test_no_warning_when_undetectable(monkeypatch):
    monkeypatch.setattr(kicad_version, "get_kicad_version", lambda: None)
    assert kicad_version.kicad_version_warning() is None
