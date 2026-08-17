"""The rules every bundled help guide must satisfy, in one place.

Three test modules reach a ``Problem`` with a help page from three different
directions (pre-flight, the area checks, the scan planner) and all want the
same thing checked of the page it names, so the checks live here:

    from helppage import assert_guide_loads
    assert_guide_loads(problem)

Not every guide belongs to a problem -- the About page's settings reference is
one of the whole form -- so the rules are also reachable by file name:

    assert_page_loads("settings.html")

A guide is displayed straight from the install tree, so what has to hold is
that it is plain offline HTML and that every resource it links exists next to
it: no scripts (KiCad's WebView runs them with no network and no CDN), no
absolute or remote URLs, and a stylesheet link that resolves to a real file.
"""

import re

from bare_package import load

# href/src of every subresource the page pulls in.
_REF = re.compile(r'<(?:link|script|img)\b[^>]*?\b(?:href|src)="([^"]+)"')


def assert_guide_loads(problem):
    """Check ``problem``'s installed guide and return its text, so a caller
    can assert on the content too."""
    return assert_page_loads(problem.help, label=problem.id)


def assert_page_loads(filename, label=None):
    """The same rules, for a guide named by file rather than by problem
    (``help/<filename>``); returns its text."""
    import pathlib

    simulate = load("sim.simulate")
    pid = label or filename
    path = simulate.guide_page(filename)
    assert path is not None, f"help page missing for {pid}"
    page = pathlib.Path(path)
    text = page.read_text(encoding="utf-8")

    # Offline and inert: the viewer has no network, and a guide is prose.
    assert "<script" not in text, f"{pid}: help pages must not use scripts"

    refs = _REF.findall(text)
    assert refs, f"{pid}: guide links no stylesheet"
    for ref in refs:
        assert "//" not in ref and not ref.startswith("/"), (
            f"{pid}: {ref} is remote or absolute; guides must stay local"
        )
        assert (page.parent / ref).is_file(), (
            f"{pid}: {ref} does not resolve next to the installed guide"
        )

    # The link is only worth anything if it lands on the guides' sheets, in
    # order -- palette.css defines the tokens help_theme.css refers to.
    assert [pathlib.Path(r).name for r in refs] == [
        "palette.css",
        "help_theme.css",
    ], f"{pid}: unexpected stylesheet links {refs}"
    return text
