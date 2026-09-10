"""The toolbar button registers, off KiCad.

This is the one module KiCad imports *for* us: it runs at pcbnew startup, and
anything it raises leaves the plugin with no button at all and the reason only
in KiCad's script log. It is also the one module a test could not reach by
accident -- it imports pcbnew at module level, so it stayed out of every suite
until a bad relative import shipped in it.

So: on the stand-in ActionPlugin wx_stub installs, let the plugin's own
subclass describe itself the way KiCad asks it to, and check the button it
describes is one KiCad could draw.

    python3 tests/test_action_plugin.py   (or pytest)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wx_stub  # noqa: E402,F401  (installs the empty wx / pcbnew)
from bare_package import PKG, PRODUCT, load, run_module_tests  # noqa: E402

plugin = load("action_plugin")


def _button():
    """The plugin's button, described as KiCad asks it to describe itself."""
    subclasses = [
        value
        for value in vars(plugin).values()
        if isinstance(value, type)
        and issubclass(value, plugin.PluginBase)
        and value is not plugin.PluginBase
    ]
    assert len(subclasses) == 1, f"one button per plugin, found {subclasses}"
    button = subclasses[0]()
    button.defaults()
    return button


def test_the_package_imports_the_way_kicad_imports_it():
    """A wrong relative import inside the nested core is invisible until
    something loads this module -- and then it costs the whole plugin."""
    assert issubclass(plugin.PluginBase, sys.modules["pcbnew"].ActionPlugin)


def test_the_button_names_the_product():
    button = _button()
    assert button.name == PRODUCT.NAME
    assert button.category == PRODUCT.CATEGORY
    assert PRODUCT.NAME in button.description
    assert button.show_toolbar_button is True


def test_the_icon_is_the_products_own_and_is_there():
    """Beside the package root, not the core's: an icon that resolved into
    emkit/ would be one glyph for every product -- and a missing file is a
    button KiCad silently draws blank."""
    icon = pathlib.Path(_button().icon_file_name)
    assert icon == PKG / PRODUCT.ICON
    assert icon.is_file(), f"{icon} is not in the package"


def test_pressing_the_button_opens_this_plugins_window():
    """The whole path KiCad takes on a click, short of building the frame: the
    button reaches its package's ``show``, which reaches the core's with this
    plugin's Shell. It is worth walking because every module on it is imported
    late -- nothing else here would notice the day one of them moved."""
    core = load("emkit.gui.shell")
    opened = []
    real = core.show
    core.show = lambda shell_class, parent=None: opened.append((shell_class, parent))
    try:
        _button().open()
    finally:
        core.show = real
    assert len(opened) == 1, opened
    shell_class, parent = opened[0]
    assert issubclass(shell_class, core.Shell) and shell_class is not core.Shell
    assert parent is None


def test_opening_is_the_subclasss_job():
    try:
        plugin.PluginBase().open()
        raise AssertionError("expected the base class to refuse")
    except NotImplementedError:
        pass


if __name__ == "__main__":
    run_module_tests(globals())
