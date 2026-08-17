"""Selectable application catalog for the antenna designer.

A high-level "what am I building this antenna for" pick (Bluetooth / BLE, Wi-Fi,
Zigbee, GPS, LoRa, ...) that fills the dialog's design target in one click. Each
application carries the numbers a matched antenna is specified against:

* ``f0_ghz``        the pattern (centre / design) frequency
* ``band``          the operating band edges ``(start_ghz, end_ghz)``
* ``impedance_ohm`` the desired input impedance -- by default 50 Ω, the same as
                    the feed port resistance (``config.py`` ``port_resistance``),
                    so the antenna is designed to look like a matched load to
                    the 50 Ω feed line and no matching network is needed
* ``return_loss_db``the target return loss across the band (a positive dB
                    figure; the match is "good enough" when S11 stays below
                    ``-return_loss_db``)

Return loss and VSWR are two views of the same reflection coefficient, so the
catalog stores the return loss once and derives VSWR from it (``vswr``) rather
than carrying a second, independently-editable number that could drift out of
step. ``vswr_from_return_loss`` / ``return_loss_from_vswr`` expose the
conversion both ways for callers that think in VSWR.

Mirrors ``materials/db.py``: a pure, free-standing data table -- stdlib only, no
wx and nothing from ``pcbnew`` or ``ems`` -- so it stays unit-testable off
KiCad, and the package can be deleted wholesale (the dialog guards the hook)
without stopping the plugin.
"""

import math


def vswr_from_return_loss(return_loss_db):
    """VSWR for a return loss of ``return_loss_db`` (a positive dB figure).

    ``|Γ| = 10**(-RL/20)`` and ``VSWR = (1+|Γ|)/(1-|Γ|)``; a 10 dB return loss
    is ~1.92:1, the familiar "better than 2:1" rule of thumb."""
    gamma = 10.0 ** (-return_loss_db / 20.0)
    return (1.0 + gamma) / (1.0 - gamma)


def return_loss_from_vswr(vswr):
    """The inverse of :func:`vswr_from_return_loss`: the return loss (dB) that a
    given VSWR corresponds to (a 2:1 VSWR is ~9.54 dB)."""
    gamma = (vswr - 1.0) / (vswr + 1.0)
    return -20.0 * math.log10(gamma)


class Application:
    """One named design target and the antenna spec it implies.

    ``band`` is the operating band ``(start_ghz, end_ghz)``; ``f0_ghz`` the
    pattern frequency the design resonates at (usually the band centre, but
    kept explicit so a picked value reproduces the old hard-coded number)."""

    def __init__(self, name, *, f0_ghz, band, impedance_ohm, return_loss_db):
        self.name = name
        self.f0_ghz = f0_ghz
        self.band = band
        self.impedance_ohm = impedance_ohm
        self.return_loss_db = return_loss_db

    @property
    def band_start_ghz(self):
        return self.band[0] if self.band else None

    @property
    def band_end_ghz(self):
        return self.band[1] if self.band else None

    @property
    def bandwidth_mhz(self):
        """The operating bandwidth (MHz) -- the span between the band edges, or
        ``None`` when the band is free (a Custom target with no bandwidth)."""
        return None if not self.band else (self.band[1] - self.band[0]) * 1000.0

    @property
    def vswr(self):
        """The VSWR the target return loss corresponds to (derived, so it can
        never disagree with ``return_loss_db``)."""
        return vswr_from_return_loss(self.return_loss_db)


class Applications:
    """Catalog and lookup for the selectable design targets.

    ``CUSTOM`` is the sentinel last choice: instead of adopting a catalog
    spec, its frequency / bandwidth / impedance are typed by hand and
    :meth:`custom` synthesizes them into an :class:`Application`, so a Custom
    pick is carried and scored like any other."""

    CUSTOM = "Custom…"  # picker entry that leaves the target free

    # Every field is spelled out per row -- no constructor defaults, so a spec
    # is never filled in silently. Band edges are the usable spectrum for each
    # service; f0 is the design frequency (2.45 GHz for the 2.4 GHz ISM
    # services matches the previous hard-coded pick). Impedance is 50 Ω
    # throughout (the feed port value); the return-loss target is the common
    # "better than 2:1 VSWR" 10 dB except GPS, which is habitually tighter.
    _APPS = [
        Application(
            "Bluetooth / BLE (2.4 GHz)",
            f0_ghz=2.45,
            band=(2.400, 2.4835),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
        Application(
            "Wi-Fi 2.4 GHz",
            f0_ghz=2.45,
            band=(2.400, 2.4835),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
        Application(
            "Wi-Fi 5 GHz",
            f0_ghz=5.5,
            band=(5.150, 5.850),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
        Application(
            "Zigbee / 802.15.4 (2.4 GHz)",
            f0_ghz=2.45,
            band=(2.400, 2.4835),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
        Application(
            "GPS L1 (1.575 GHz)",
            f0_ghz=1.575,
            band=(1.563, 1.587),
            impedance_ohm=50.0,
            return_loss_db=15.0,
        ),
        Application(
            "LoRa 868 MHz (EU)",
            f0_ghz=0.868,
            band=(0.863, 0.870),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
        Application(
            "LoRa 915 MHz (US)",
            f0_ghz=0.915,
            band=(0.902, 0.928),
            impedance_ohm=50.0,
            return_loss_db=10.0,
        ),
    ]

    @classmethod
    def names(cls):
        return [a.name for a in cls._APPS]

    @classmethod
    def choices(cls):
        """Picker labels, with the Custom sentinel last."""
        return cls.names() + [cls.CUSTOM]

    @classmethod
    def get(cls, name):
        """The chosen :class:`Application`, or ``None`` for the Custom sentinel
        / an unknown label (meaning: don't touch the hand-typed target)."""
        for a in cls._APPS:
            if a.name == name:
                return a
        return None

    @classmethod
    def custom(cls, *, f0_ghz, bandwidth_mhz, impedance_ohm, return_loss_db=None):
        """A synthesized ``Custom…`` target from hand-typed numbers, so a Custom
        pick is carried and scored exactly like a catalog application (no
        special-casing downstream). The band edges straddle the pattern
        frequency by half the bandwidth; any missing / non-positive input
        leaves that field free (``None``) -- shown, not judged, never
        defaulted."""
        band = None
        if f0_ghz and f0_ghz > 0 and bandwidth_mhz and bandwidth_mhz > 0:
            half = bandwidth_mhz / 1000.0 / 2.0  # MHz -> GHz, half-width
            band = (f0_ghz - half, f0_ghz + half)
        return Application(
            cls.CUSTOM,
            f0_ghz=f0_ghz,
            band=band,
            impedance_ohm=(
                impedance_ohm if impedance_ohm and impedance_ohm > 0 else None
            ),
            return_loss_db=return_loss_db,
        )
