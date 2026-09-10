# Installing by hand

The normal way in is KiCad's **Plugin and Content Manager**, and
[README.md](../README.md) covers it. This page is the other way: the package is
a plain zip and installing it is only a folder copy, so you can do that part
yourself — worth knowing if the manager refuses the file, or if the KiCad you
want it in isn't the one you are looking at.

1. Unzip
   [`AntennaDesigner-<ver>-pcm.zip`](https://github.com/admin-2026/kicad_ems_plugin_pub/releases).
   The plugin is the `plugins` folder inside it; the rest is what the manager
   reads.
2. In the PCB editor: **Tools > External Plugins > Open Plugin Directory**.
   KiCad opens its own plugin folder in your file manager — that is the
   destination, whatever the path turns out to be.
3. Copy that `plugins` folder into it and **rename it `antenna_plugin`**. The
   name becomes the plugin's module name, so anything valid works, but it has
   to be a name and not `plugins`. Copy it whole: the simulator binaries sit
   inside it. If an older copy is already there, delete that copy first rather
   than merging the two — modules dropped since would otherwise stay behind
   and still be imported.
4. **Tools > External Plugins > Refresh Plugins**, or restart KiCad.

Repeat per KiCad if you run more than one; each version has its own plugin
directory.

`antenna_plugin/binaries/` holds one build of the simulator per machine, each
named for the machine it is for:

| File | Runs on |
| --- | --- |
| `monopole-linux-x86_64` | Linux, Intel/AMD 64-bit |
| `monopole-linux-aarch64` | Linux, 64-bit ARM |
| `monopole-windows.exe` | Windows |

There is no macOS build: on a Mac the solver runs inside a Docker container,
which is Linux, so what a Mac runs is one of the two Linux builds above. Keep
them even though no Mac launches them directly — they are what the container
runs.

On Linux and macOS, check that yours is still executable afterwards
(`chmod +x`) — some archive managers drop the execute bit on the way out of a
zip, which KiCad's own installer does not. You can delete the ones you don't
need; the plugin only ever reaches for its own, and picks it by that name.
