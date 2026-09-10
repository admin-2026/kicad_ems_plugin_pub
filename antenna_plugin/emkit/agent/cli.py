"""Argument parsing, dispatch, and the one promise this surface makes.

**The promise: a caller who asks for JSON gets JSON, whatever happens.** Not
only when a verb fails -- when the arguments themselves are wrong. Argparse's
default is to print usage to stderr and exit, which leaves a program that
asked for a machine-readable answer parsing English out of a stream it was not
reading. So the parser is subclassed, and its ``error`` goes through the same
failure path as everything else.

The three exits, which are the whole contract::

    0   the verb answered; the payload is on stdout
    1   the verb raised; the plugin's own message is the error
    2   the arguments were wrong; the message is argparse's

1 and 2 are kept apart because they mean different things to a caller: a 2 is
worth re-reading ``--help`` over, a 1 is worth acting on.

**The usage lines are spelled with the shortcut's name.** Argparse would put
``sys.argv[0]`` there -- ``run_agent.py``, the launcher inside the install --
and a caller copying that out of a usage line has a command it cannot type
without also naming KiCad's Python. The shim's name is what the guide teaches
and what every failure's pointer already spells (:func:`_pointer`), so it is
what the usage lines say too, whether or not the shim happens to be installed:
one command in one spelling, everywhere this surface names itself.

**The output streams are forced to UTF-8.** The verbs print ``✓ ✗ ⚠ Ω ·`` and
on Windows, when stdout is a *pipe* -- which is always, when an agent captures
output -- Python encodes with the locale codec, typically cp1252, and those
characters raise ``UnicodeEncodeError``. It works in an interactive console
and breaks under capture, which is to say it breaks in the agent's only mode.
"""

import argparse
import functools
import json
import sys
import textwrap

from . import verbs

# The flag, in the one place both the parser and the failure path read it from.
JSON_FLAG = "--json"


def main(argv=None):
    """Run one command. Returns the process' exit code."""
    _utf8(sys.stdout)
    _utf8(sys.stderr)
    argv = list(sys.argv[1:] if argv is None else argv)
    # Read out of argv rather than off the parsed arguments: a usage error is
    # reported before parsing finishes, and it has to honour the flag too.
    as_json = JSON_FLAG in argv
    args = build_parser(as_json).parse_args(argv)
    try:
        payload = args.verb.run(args)
    except Exception as exc:
        # Every verb's failure is the plugin's own message -- a knob named, a
        # pre-flight blocker, a missing board -- so it is worth printing as
        # itself rather than as a traceback.
        fail(str(exc), as_json)
        return 1
    emit(payload, as_json, args.verb.lines)
    return 0


def _utf8(stream):
    """Encode this stream as UTF-8 whatever the console's codepage says, and
    replace anything it still cannot carry rather than raising. Best effort:
    a stream somebody replaced with a plain object has no reconfigure."""
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# --------------------------------------------------------------------------- #
# The parser
# --------------------------------------------------------------------------- #
class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that reports usage errors the way the rest of this
    program reports errors.

    ``as_json`` rides on the instance and is inherited by every subparser it
    makes, at whatever depth: ``… --json nosuchverb``, ``… --json run nope``
    and ``… --json run start --nope`` all answer in JSON at whichever level
    notices. That is why the flag is carried down here rather than passed in
    at each ``add_subparsers`` -- a verb that grows a topic of its own
    (``verbs/run.py``) does not have to know the promise exists to keep it.
    """

    def __init__(self, *args, as_json=False, **kwargs):
        self.as_json = as_json
        # Descriptions here are prose written in paragraphs -- a verb's
        # docstring, a topic's page -- and argparse's default formatter
        # reflows the lot into one block, which is what made the longest of
        # them unreadable rather than merely long.
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)

    def add_subparsers(self, **kwargs):
        kwargs.setdefault(
            "parser_class", functools.partial(_Parser, as_json=self.as_json)
        )
        return super().add_subparsers(**kwargs)

    def error(self, message):
        fail(message, self.as_json, usage=self.format_usage().strip())
        raise SystemExit(2)


def build_parser(as_json=False):
    from ... import product
    from . import shim

    parser = _Parser(
        # The name a caller can actually type, not the launcher's file name.
        prog=shim.STEM,
        description=f"{product.NAME} — the same plugin, driven by argv.",
        # Wrapped here rather than left to argparse: the formatter above
        # prints a description and an epilog exactly as given, which is what
        # keeps the verbs' paragraphs, and this one sentence is written as one
        # line because every other place it appears wants it that way.
        epilog=textwrap.fill(_pointer(), 78),
        as_json=as_json,
    )
    parser.add_argument(
        JSON_FLAG, action="store_true", help="Print the answer as JSON, not as lines"
    )
    subparsers = parser.add_subparsers(dest="verb_name", required=True)
    for verb in verbs.VERBS:
        sub = subparsers.add_parser(verb.NAME, help=verb.HELP, description=verb.__doc__)
        verb.add_arguments(sub)
        sub.set_defaults(verb=verb)
    return parser


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def emit(payload, as_json, lines):
    """The answer. JSON when asked for it or when the verb offers no lines --
    an answer nobody rendered is better shown as data than not at all."""
    if as_json or lines is None:
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False))
        return
    for line in lines(payload):
        print(line)


def fail(message, as_json, usage=None):
    """The failure. On stdout as JSON when JSON was asked for -- a caller that
    parses stdout should not have to also watch stderr to find out it failed --
    and on stderr as a sentence otherwise.

    Every failure also carries the pointer at the guide. A caller that fumbles
    its first invocation is reading this message and nothing else, so it is
    the one place a "you can ask for the manual" is certain to be seen; and it
    is one line, on a path nobody reaches twice by accident.
    """
    if as_json:
        payload = {"ok": False, "error": message, "guide": _pointer()}
        if usage:
            payload["usage"] = usage
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"error: {message}", file=sys.stderr)
    if usage:
        print(usage, file=sys.stderr)
    print(_pointer(), file=sys.stderr)


def _pointer():
    """The one line that says the manual exists, in the two places a caller
    who does not know this surface will actually look: the foot of ``--help``
    and the foot of every failure."""
    from . import shim

    return (
        f"New here? Run `{shim.STEM} {verbs.guide.NAME}` — how this plugin "
        "works, which files are yours to edit, and how to drive a simulation "
        "end to end. It needs no board."
    )
