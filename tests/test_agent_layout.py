"""The rules that keep the two frontends from drifting apart.

Both are greps, and both are cheap and exact. They exist because the mistake
they catch is *silent*: nothing breaks, nothing fails to import, and the
duplication is only noticed when the two surfaces start disagreeing about
what a run is.

**``agent/`` computes nothing.** A verb maps arguments to one call into
``sim/`` and hands back what came out. The moment a renderer works out a
bandwidth there are two scorers, and one of them is the one nobody maintains.

**Nothing shared names a product or a design.** ``emkit/`` is the same code in
every plugin built here, so a design key or a product name inside it is a
plugin's business leaking into everybody's. ``tests/test_designs.py`` already
holds each topology to its contract; this holds the core to not knowing they
exist. Adding a fourth design must need no edit under ``sim/`` or ``agent/``.

    python3 tests/test_agent_layout.py   (or pytest)
"""

import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import CORE, PRODUCT, run_module_tests  # noqa: E402

# The shared packages held to the rule below. The first two are the slice this
# started as; ``userlib`` joined them by having broken it -- the folder the
# user's saved entries live in was one product's name, written into the core,
# so a second product kept its user's files in the first one's directory.
SHARED = ("agent", "sim", "userlib")

# Names no shared module may spell. The product's, off its own manifest -- so
# a second product's name joins this list by existing -- plus the antenna's
# design keys, which are the other thing a shortcut reaches for.
DESIGN_KEYS = ("lmonopole", "ifa", "meander", "monopole")


def _sources(package):
    root = CORE / package
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_verb_surface_does_no_arithmetic():
    """No ``- * / % **`` anywhere under ``agent/``.

    A rule about where work happens, not about which expressions are
    dangerous: the moment a renderer works out a bandwidth there are two
    scorers, and one of them is the one nobody maintains. What a verb may do
    is call ``sim/`` and hand back what came out.

    ``+`` is left out of it deliberately -- it is how a renderer joins two
    lists of lines, and banning it would buy nothing this does not already
    cover. Division is the useful one to keep: it bans both the arithmetic and
    pathlib's ``Path / "x"``, so path joining under ``agent/`` is written
    ``os.path.join``, which is the spelling that behaves the same on Windows.

    Read off the parse tree rather than the lines, because half of this
    package is prose *about* arithmetic and a grep cannot tell the two apart.
    """
    banned = (ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    guilty = []
    for path in _sources("agent"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, banned):
                guilty.append(
                    f"{path.relative_to(CORE)}:{node.lineno}: {type(node.op).__name__}"
                )
    assert not guilty, (
        "agent/ computes; that belongs in sim/ where the window can reach "
        "it too:\n  " + "\n  ".join(guilty)
    )


def test_nothing_shared_names_a_product_or_a_design():
    """Over the code and the *user-facing strings*, not the prose.

    Docstrings and comments are where this rule gets explained, and a
    line-by-line grep cannot tell "never name an antenna here" from naming
    one. So the names are read off the parsed module instead: every
    identifier, and every string literal that is not a docstring. That is
    exactly the set a user or another module can see -- which is where a
    product leaking into the shared core actually does harm, and it is what
    caught the one real instance (an unsupported-host message that told a
    signal-integrity user about antennas).
    """
    banned = {PRODUCT.NAME.lower(), PRODUCT.NAME_KEY, PRODUCT.BINARY, PRODUCT.PACKAGE}
    banned.update(DESIGN_KEYS)
    banned.discard("")
    guilty = []
    for package in SHARED:
        for path in _sources(package):
            for number, text in _visible(path):
                for word in sorted(banned):
                    if re.search(rf"\b{re.escape(word)}\b", text.lower()):
                        guilty.append(
                            f"{path.relative_to(CORE)}:{number}: {word!r} — {text}"
                        )
    assert not guilty, (
        "the shared core names a product or a design; it reads them off "
        "product.py and <product>.runjob instead:\n  " + "\n  ".join(guilty)
    )


def _visible(path):
    """Every name and every non-docstring string literal in ``path``, as
    ``(line, text)``. What a caller or a user can see, as opposed to what the
    source says about itself."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.alias):
            yield getattr(node, "lineno", 0), node.name
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            yield node.lineno, node.name
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                yield node.lineno, node.value


def test_every_verb_offers_the_four_names_and_no_more():
    """The whole contract of a verb module. Walked off the table rather than
    a list, so a verb added tomorrow is held to it the day it lands."""
    verbs = __import__("bare_package").load("emkit.agent.verbs")
    assert verbs.VERBS, "no verbs at all"
    for verb in verbs.VERBS:
        assert isinstance(verb.NAME, str) and verb.NAME, verb
        assert isinstance(verb.HELP, str) and verb.HELP, verb.NAME
        assert callable(verb.add_arguments), verb.NAME
        assert callable(verb.run), verb.NAME
        assert callable(verb.lines), verb.NAME
    assert len(set(verbs.names())) == len(verbs.VERBS), "two verbs, one name"


if __name__ == "__main__":
    run_module_tests(globals())
