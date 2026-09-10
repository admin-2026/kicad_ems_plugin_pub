"""Run one command-line verb in-process, with both streams captured.

Every suite that exercises ``agent/`` wants the same twelve lines -- swap the
streams, call ``cli.main``, catch the SystemExit argparse raises, put the
streams back -- and had its own copy of them. One copy here, so a test module
about a verb is about the verb.

In-process on purpose: a subprocess would test the launcher (that is
test_agent_cli's own business, once) rather than the verb, and would need an
interpreter that can find the package.

    code, out, err = clirun.run(["--json", "form", "options"])
"""

import io
import sys

from bare_package import load

cli = load("emkit.agent.cli")


def run(argv):
    """One command. Returns ``(exit code, stdout, stderr)`` -- the code
    argparse exited with, if it did, and the code ``main`` returned if it did
    not."""
    out, err = io.StringIO(), io.StringIO()
    real = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = cli.main(argv)
    except SystemExit as exc:
        code = exc.code
    finally:
        sys.stdout, sys.stderr = real
    return code, out.getvalue(), err.getvalue()
