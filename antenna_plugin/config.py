"""The runner YAML for the antenna flow: the monopole schema, one feed port.

Everything about *writing* a config -- the YAML scalars, the block order, the
board facts, the mesh knobs, the shared validation -- is the core's
``emkit.config.ConfigWriter``. What is here is what makes this flow's config
this flow's: the schema version its own binary reads, and the single port.

The runner's RunConfig loader (``src/config/PcbRunConfig.cpp`` in the
simulator) is the only reader and understands exactly this schema;
``ems/schema/monopole.yaml`` is the annotated reference. Keep the two in step.
"""

from .emkit.config import ConfigWriter, kv

# Config schema version (semver), written as the first line of every emitted
# YAML. Kept in lockstep with kConfigVersionMajor/Minor in
# ems/src/config/PcbRunConfig.hpp; ems/schema/monopole.yaml is the annotated
# reference. The reader refuses a config whose MAJOR differs from the build's
# (CFG-005), so this writer must track the major -- and a major bump is not
# always a key change: the schema also majors when the same config on the same
# board comes out different, a derived mesh that moves or geometry that is now
# read (the holes below), because carrying it over unchanged would silently
# simulate another board.
#
# 16.0.0: the solver writes data, not pages. Every HTML view moved out of the
# binary into a checked-in static app, which this plugin ships its own copy of
# (antenna_plugin/viewer/), so `report_grid` / `report_html` are gone and every
# run writes both dumps unconditionally.
#
# 17.0.0: a lattice over `mesh_budget_gb` is re-meshed instead of refused. The
# solver has named the finest cell_mm that would have fitted inside MESH-014
# for a while; now it takes that cell and resolves the whole run again at it,
# warning MESH-028. The new `mesh_fit_cell` key (below) is the switch. A major
# with one key added, because the same config on the same board now produces
# results where it used to produce an error.
#
# 17.1.0: `cell_max_mm`, a ceiling on the base cell (0 = none). A minor, not a
# major: an untouched config still emits 0 and still meshes exactly as it did.
# The key composes with `cell_mm` instead of replacing it -- with the cell auto
# it joins the automatic rule as a third term (so the cell can come out finer
# than lambda/20 and the driven copper alone would have made it), and with the
# cell pinned it bounds how far the budget re-mesh above may coarsen it. The
# pair is the antenna_plugin.cellsize package: it owns the two fields, the
# sentence the window captions them with, and the two combinations the runner
# refuses at load (an empty range, CFG-042; a feature floor above the ceiling,
# CFG-043), which write_yaml raises here before a run is prepared.
#
# 18.0.0: the substrate z cell is a property of each SLAB, not one number for
# the whole stackup. No key changed -- each dielectric is now cut in its own
# permittivity and its own thickness, and `substrate_cell_mm` became a CEILING
# on all of them (0 = none, the normal case) rather than the cell itself -- but
# the same config on the same board meshes differently, which is what a major
# says.
#
# 19.0.0: a mask entry that gives `thickness_mm` and `eps` is MESHED as a thin
# dielectric coating on that face of the board, where before the two were
# accepted and ignored and the layer was only drawn. No key changed here
# either: this writer has emitted both on every included mask since the
# coating became an option (`include_mask`, the Materials tick), so the same
# form now simulates a layer it used to draw -- a different lattice and a much
# smaller time step, because the coating is one z cell of its own thickness and
# that is then the finest cell the run has. A run that wants the old picture
# turns the mask off, which drops the entries entirely (_apply_overrides), not
# their material. The loss stays optional (a coating with neither sigma nor
# loss_tangent is lossless and the run says so, CFG-045); giving one of
# thickness_mm/eps without the other is refused (CFG-044), which is the
# pre-flight blocker the mask row already raises before a run is prepared.
#
# 20.0.0: a gerber that declares its own polarity is read that way, so
# `is_negative:` is an override rather than the only way to say it. This is the
# one that matters most for a KiCad board and it is why nothing here changed:
# pcbnew exports a solder mask as the OPENINGS and stamps the file
# `TF.FilePolarity,Negative` (X2 `%TF%` or the X1 `G04 #@!` comment form --
# simulate.plot_gerbers writes X1, which carries the same attribute), so the
# coating is now meshed everywhere the mask actually is instead of over the
# pads. Copper, paste and outline exports all declare Positive and are
# unaffected. This writer states no `is_negative` on any entry and should not
# start: the key is for correcting a file that got its own polarity wrong, and
# what KiCad writes is right.

CONFIG_VERSION = "20.0.0"


class AntennaConfig(ConfigWriter):
    """One antenna run's config: one port, driven by a marker or a wizard."""

    CONFIG_VERSION = CONFIG_VERSION

    def ports(self):
        """The single ``feed_ports:`` entry, from ``params['feed']`` -- a point
        on the feed line plus the direction vector (dir_x/dir_y toward the
        antenna), gerber mm. That is the whole port: the runner infers the
        trace axis and width from the copper under the point and severs a
        one-cell gap on the simulation grid, so no clearance rect and no gap
        width is written. Both the placed feed marker
        (``feed_marker.feed_dict``) and the wizards
        (``design.geometry.Geometry.feed_dict``) produce this feed.

        The port-wide ``feed_snap_to_center`` rides just above the list: it
        decides whether the runner keeps that point or centers it on the copper
        it drives. ``layer`` is the copper foil the port sits on, by its
        stackup copper entry name (e.g. ``F_Cu``); it defaults to the top foil.
        """
        feed = self.p.get("feed")
        if not feed:
            raise RuntimeError(
                "no feed specified: place a feed marker (Feed marker box) on "
                "the feed line"
            )
        layer = self.p.get("feed_layer") or self.top_copper()
        return [
            "# --- feed port (point + direction; the runner infers the trace) ---",
            "# true = move the point onto the centerline of the copper the driven edge",
            "# bridges (the port only; everything else is measured off that "
            "copper either way)",
            kv("feed_snap_to_center", bool(self.p["feed_snap_to_center"])),
            "feed_ports:",
            *self.port_entry(feed, layer),
        ]


def write_yaml(gerbers, stack, params, yaml_path):
    """Write the runner config to ``yaml_path``; returns its outdir.

    ``gerbers`` is the dict from ``plot_gerbers`` (resolved paths by role),
    ``stack`` the ``collect_stackup`` result, ``params`` the GUI knobs. This is
    what ``simulate.write_config`` calls -- the one entry point every flow's
    ``config`` module offers the core.
    """
    return AntennaConfig(gerbers, stack, params).write(yaml_path)
