#!/bin/sh
# The container's front door. Three things arrive here and all three have to
# work, because one image serves all of them:
#
#   docker run ... <image> versions --json        a verb of the command line
#   docker run ... <image> bash                   a person having a look round
#   docker run ... <image> /opt/solver/<build> /work/pcb.yaml
#                                                 the solver itself, which is
#                                                 how a window on the host runs
#                                                 one solve in here
#
# So: anything that names a program runs as that program, and anything else is
# handed to this product's command line. The test is whether the first word is
# an executable file or a command on PATH -- not a list of verbs, which would
# be a second copy of the verb registry and would go stale the first time one
# was added.
set -eu

# The mounted directory is also HOME (see the Dockerfile): a run is given the
# caller's uid, which has no passwd entry in here, so there is nowhere else it
# can be certain of writing. Nothing is created if the mount is missing -- a
# run with no /work is a mistake worth failing on rather than papering over.
if [ ! -d /work ]; then
    echo "entrypoint: nothing is mounted at /work -- run with -v <dir>:/work" >&2
    exit 2
fi

if [ "$#" -eq 0 ]; then
    set -- --help
fi

if [ -x "$1" ] || command -v "$1" >/dev/null 2>&1; then
    exec "$@"
fi

exec "/usr/local/bin/${AGENT}" "$@"
