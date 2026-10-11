"""Strict device matching: which hidraw interface (if any) a driver may open.

A driver attaches only when VID, PID, USB interface number AND the report
descriptor's usage page all match what was verified on this machine and in the
reference implementations. Known-but-unverified devices become display-only.

Virtual devices (no hardware, e.g. the TT LCD bridge) are declared in the
config and built only from drivers listed in VIRTUAL_DRIVERS; they never go
through match() and never open anything under /dev.
"""

import logging
from dataclasses import dataclass

from .asus_aura_usb import AsusAuraUSB
from .device import UnsupportedDevice
from .hidraw import discover
from .virtual_ttas import TtasSharedMemory

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Match:
    vid: int
    pid: int
    interface: int
    usage_page: int
    name: str
    driver: type


SUPPORTED = (
    Match(0x0B05, 0x19AF, 2, 0xFF72, "ASUS Aura (ROG STRIX B650E-I)", AsusAuraUSB),
)

NO_PROTOCOL = "Detected — no verified protocol (not controlled)"

UNSUPPORTED = {
    (0x0B05, 0x1BA3): ("ROG Gaming Display Aura", "monitor",
                       NO_PROTOCOL + ". Not supported by OpenRGB; protocol undocumented."),
}


VIRTUAL_DRIVERS = {
    "ttas-shm": TtasSharedMemory,
}

VIRTUAL_ID_PREFIX = "virtual:"

# Ready-made entries for `armory-crate virtual add <preset>`.
VIRTUAL_PRESETS = {
    "ttlcd": {"id": "virtual:ttlcd", "driver": "ttas-shm", "name": "TT LCD CL-W383",
              "leds": 8, "file": "ttlcd.ttas"},
}


def build_virtual(entry):
    """Create one virtual device from a config entry, or raise ValueError."""
    driver = VIRTUAL_DRIVERS.get(entry.get("driver"))
    if driver is None:
        raise ValueError(f"unknown virtual driver {entry.get('driver')!r}")
    vid = str(entry.get("id", ""))
    if not vid.startswith(VIRTUAL_ID_PREFIX) or len(vid) <= len(VIRTUAL_ID_PREFIX):
        raise ValueError(f"virtual device id must start with {VIRTUAL_ID_PREFIX!r}")
    return driver(vid, str(entry.get("name") or vid), entry.get("leds", 8), entry.get("file", ""))


def device_id(info):
    return f"{info.vid:04x}:{info.pid:04x}@{info.usb_path}"


def match(info):
    for m in SUPPORTED:
        if (info.vid, info.pid, info.interface, info.usage_page) == (m.vid, m.pid, m.interface, m.usage_page):
            return m
    return None


def build_devices(config=None, infos=None):
    """Return driver objects (unopened) for every matched or known device."""
    from ..config import device_settings
    infos = discover() if infos is None else infos
    devices, seen_unsupported = [], set()
    for info in infos:
        m = match(info)
        if m:
            did = device_id(info)
            kwargs = {}
            if m.driver is AsusAuraUSB and config is not None:
                kwargs["argb_leds"] = device_settings(config, did)["argb_leds"]
            devices.append(m.driver(info, did, m.name, **kwargs))
            continue
        key = (info.vid, info.pid)
        if key in UNSUPPORTED and key not in seen_unsupported:
            seen_unsupported.add(key)
            name, kind, reason = UNSUPPORTED[key]
            devices.append(UnsupportedDevice(info, device_id(info), name, kind, reason))
    for entry in (config or {}).get("virtual_devices", []):
        try:
            devices.append(build_virtual(entry))
        except (ValueError, TypeError) as e:
            log.warning("skipping virtual device %r: %s", entry.get("id") if isinstance(entry, dict) else entry, e)
    return devices
