"""No class calls a name nothing in the package defines.

The core calls into its host plugin through a handful of named hooks
(``apply_ports``, ``start_target``, ``score_report``, ``build_pages``), and a
hook that gets renamed leaves the old name at the call site: valid Python,
imports fine, and raises ``AttributeError`` the first time a user presses Run.
That is how ``_apply_marker_footprint`` survived the split into core and
plugin -- the run flow is the one path a test suite cannot walk, because
walking it means running the solver.

So this reads the tree instead: every ``self.<name>`` used inside a class,
against every name any class in the package defines or assigns. It is a
spelling check, not a type check -- it does not know which class is which, so
a name defined on *some* class here passes on all of them.

Which is exactly why the second test is narrower. The core also reaches
*through* the page it was given -- ``self.page.form.update_hint()``, from the
Advanced section -- and there it cannot know what class it has hold of, so the
name has to be one the core itself defines. ``update_hint`` was the antenna
form's alone, and the S-parameter window would not open.

    python3 tests/test_attributes.py   (or pytest)
"""

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import CORE, PKG, run_module_tests  # noqa: E402


def _sources(root=None):
    root = root or PKG
    return [
        p for p in sorted(root.rglob("*.py")) if "tests" not in p.relative_to(PKG).parts
    ]


def _names(paths):
    """Every attribute name the given sources define: methods, class-level
    constants, and anything assigned to ``self``."""
    found = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.add(node.name)
            elif isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    targets = getattr(stmt, "targets", [])
                    if isinstance(stmt, ast.AnnAssign):
                        targets = [stmt.target]
                    found |= {t.id for t in targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.Attribute):
                value = node.value
                if isinstance(value, ast.Name) and value.id == "self":
                    if isinstance(node.ctx, (ast.Store, ast.Del)):
                        found.add(node.attr)
    return found


class _Uses(ast.NodeVisitor):
    """``self.<name>`` read inside a class body, by name and where."""

    def __init__(self, path, used):
        self.path, self.used, self.cls = path, used, None

    def visit_ClassDef(self, node):
        outer, self.cls = self.cls, node.name
        self.generic_visit(node)
        self.cls = outer

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "self" and self.cls:
            if isinstance(node.ctx, ast.Load):
                self.used.setdefault(node.attr, []).append((self.path, node.lineno))
        self.generic_visit(node)


# The stdlib base classes the package subclasses, and so the lower-case names
# that come from *outside* it. wx's and pcbnew's are covered by their leading
# capital; the stdlib's are not, so the few there are get named here. Kept as
# an explicit list rather than an import: this is a spelling check over the
# source, and it should not need the class to be constructible to run.
_INHERITED = {
    "format_usage",  # argparse.ArgumentParser (agent/cli.py's _Parser)
}


def test_no_class_calls_a_name_the_package_never_defines():
    defined, used = _names(_sources()), {}
    for path in _sources():
        _Uses(path.relative_to(PKG), used).visit(ast.parse(path.read_text("utf-8")))

    missing = []
    for name, sites in sorted(used.items()):
        if name in defined or name in _INHERITED or name[:1].isupper():
            # A leading capital is wx's and pcbnew's naming, never this
            # project's: Bind, SetSizer, GetValue come from the base class the
            # widget subclasses, and no source here defines them.
            # ponytail: a spelling rule, not an import of wx -- if a hook is
            # ever named in CamelCase this stops covering it.
            continue
        for where, line in sites:
            missing.append(f"{where}:{line}: self.{name}")
    assert not missing, "names nothing in the package defines:\n  " + "\n  ".join(
        missing
    )


def _through_the_page(path):
    """``self.page.<a>`` and ``self.page.<x>.<a>`` in one source, as
    ``(what, attr, line)`` -- what the core asks of the page it was handed,
    and of the sections hanging off it."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if not isinstance(value, ast.Attribute):
            continue
        if isinstance(value.value, ast.Name) and value.value.id == "self":
            if value.attr == "page":
                yield "page", node.attr, node.lineno
        elif isinstance(value.value, ast.Attribute):
            inner = value.value
            if (
                isinstance(inner.value, ast.Name)
                and inner.value.id == "self"
                and inner.attr == "page"
            ):
                yield f"page.{value.attr}", node.attr, node.lineno


def test_the_core_only_reaches_through_a_page_for_names_it_defines():
    """One level down (``self.page.form.update_hint``) the core is holding an
    object whose class is the plugin's, so the only names it may ask for are
    ones the core itself defines -- on Section, on BookPage, on the sections it
    owns. A name that lives in one plugin's form is a window that opens for
    that product and not the other.

    The page's own attributes are the exception, and are checked against the
    whole package: which sections a page holds is the plugin's answer, and
    every product has to give it (banner, form, run, results, ...)."""
    in_core = _names(_sources(CORE))
    in_package = _names(_sources())
    missing = []
    for path in _sources(CORE):
        for what, attr, line in _through_the_page(path):
            if attr[:1].isupper():
                continue  # a wx control's own API (log_ctrl.Clear)
            known = in_package if what == "page" else in_core
            if attr not in known:
                where = path.relative_to(PKG)
                missing.append(f"{where}:{line}: self.{what}.{attr}")
    assert not missing, (
        "the core reaches for names it cannot count on:\n  " + "\n  ".join(missing)
    )


def test_the_scan_reads_the_hooks_it_is_here_for():
    """A scan that parsed nothing would pass in silence. The core's run flow
    is the file the leftover was in, and its hooks are the names at risk."""
    text = (PKG / "emkit" / "gui" / "sections" / "run.py").read_text(encoding="utf-8")
    assert "self.apply_ports(" in text
    assert len(_sources()) > 50


if __name__ == "__main__":
    run_module_tests(globals())
