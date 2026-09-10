# The workbench image: KiCad, this plugin, its command line and its solver.
#
# Built on the user's machine, never shipped -- what this project ships is this
# recipe. Two reasons, and both are load-bearing: the image carries a
# proprietary, non-commercial-only solver (LICENSE-solver.txt), so it is not
# ours to publish and not yours to push; and it carries the plugin's own code,
# so an image is only ever right for the release that built it.
#
# What it is for
# --------------
# Running a simulation without giving the solver -- or an AI agent driving it --
# the run of the machine. The container sees one directory: the project you
# mount. No network (`--network none`), no home directory, nothing else of
# yours.
#
# Because KiCad and the plugin are in here too, it is also a place to *work*:
#
#     docker run --rm -v "$PWD:/work" <image> versions
#     docker run --rm -v "$PWD:/work" <image> run start --board /work/b.kicad_pcb
#     docker run --rm -it -v "$PWD:/work" <image> bash
#
# Why this base
# -------------
# Ubuntu 24.04 with the KiCad project's own PPA, which is where KiCad 10
# packages come from. Not Debian: the PPA does not cover it, and the KiCad in
# Debian trixie is 9.
#
# **The KiCad in here must not be older than yours.** A board saved by KiCad 10
# comes back from KiCad 9's LoadBoard as a bare None -- so a 9 image cannot read
# a 10 user's boards, while a 10 image reads everybody's. Nothing in here ever
# *writes* a board (the command line loads from a path and is read-only by
# construction), so the newer KiCad cannot upgrade your files behind your back.
#
# --no-install-recommends, deliberately: it drops the symbol, footprint and 3D
# libraries, which are gigabytes and which nothing here uses -- the marker
# footprints this plugin places ship inside the plugin. What is left is about
# 100 MB of KiCad, and pcbnew imports in it with no display attached.
FROM ubuntu:24.04

# Everything apt does, in one layer, with its caches gone by the end of it.
# software-properties-common is only here to add the PPA and is removed again.
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates gnupg software-properties-common; \
    add-apt-repository -y ppa:kicad/kicad-10.0-releases; \
    apt-get update; \
    apt-get install -y --no-install-recommends kicad; \
    apt-get purge -y software-properties-common gnupg; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

# The plugin itself: the install this image was built from, copied in whole --
# the package with the core nested inside it, and the solver builds. Copied
# rather than mounted so that the image is a complete thing: it runs on a
# machine with no checkout, and what is inside it is exactly the code that
# built it.
#
# What is copied is staged by sim/container/image.py rather than being whatever
# the install happened to look like -- see stage_context for why.
COPY package /opt/plugin
COPY binaries /opt/plugin/binaries

# ...and the terms both of those are used under, next to them: the plugin's
# Python is MIT, the solver is proprietary and free for non-commercial use
# only. An install carries this pair for the same reason -- whatever holds the
# binary holds the licence -- and an image is a place the code can be read with
# no checkout anywhere near it, so it is a place the licence has to be readable
# too. Named here rather than left to ride along inside `package`, because
# where they sit relative to it differs between an install and a checkout.
COPY LICENSE LICENSE-solver.txt /opt/plugin/

# The command line, by name. `shim.py` writes this from an interpreter and a
# launcher path; in here both are known at build time, so there is nothing to
# discover and nothing to record -- which is just as well, since the recording
# (agent/hostpy.py) is written by the *window*, and no window ever opens in a
# container.
ARG PRODUCT=plugin
RUN set -eux; \
    printf '#!/bin/sh\nexec /usr/bin/python3 /opt/plugin/emkit/run_agent.py "$@"\n' \
        > /usr/local/bin/"$PRODUCT"-agent; \
    chmod 0755 /usr/local/bin/"$PRODUCT"-agent

# An AI agent, if that is what you are building this for
# ------------------------------------------------------
# None ships. Which agent -- and the terms it is used under, and the account it
# bills -- is yours to choose, and baking one in would be choosing for you.
#
# Add it here and it stands beside the command line above: inside, with KiCad,
# the plugin and the solver, and with nothing of yours in reach but the
# directory you mount. Most of them are a package away -- a Node-based CLI, for
# instance:
#
#     RUN set -eux; \
#         export DEBIAN_FRONTEND=noninteractive; \
#         apt-get update; \
#         apt-get install -y --no-install-recommends nodejs npm; \
#         npm install -g <the agent's package>; \
#         rm -rf /var/lib/apt/lists/*
#
# Then start it yourself, rather than through the entrypoint's verbs:
#
#     docker run --rm -it -v "$PWD:/work" -e <ITS_API_KEY> <image> <the agent>
#
# Two things such a container needs that a solve does not, and neither belongs
# in this file: a network -- a solve is started with --network none, and an
# agent cannot reach its model that way -- and its key, which is `-e` at the
# docker run, never a line in here. A key written into a Dockerfile is in the
# image, and stays in it.

# /work is the mount point and the home directory both. A run is given the
# caller's uid on Linux, and that uid has no passwd entry in here -- so HOME
# points at the one directory it is certain to be able to write.
ENV HOME=/work
# What the entrypoint hands a bare verb to. Baked, because the entrypoint is
# one file for every product and the name is not.
ENV AGENT=${PRODUCT}-agent
WORKDIR /work

COPY --chmod=0755 package/emkit/sim/container/entrypoint.sh \
     /usr/local/bin/entrypoint.sh

# Recorded so that the image can be asked what it is without being started:
# which release built it (an upgraded plugin wants a rebuild) and which KiCad
# is in it (an older one cannot read your boards).
ARG VERSION=unknown
LABEL org.opencontainers.image.version=$VERSION
LABEL io.kicad.version=10.0
LABEL product=$PRODUCT

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
