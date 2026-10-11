"""Memory, storage, OS. Read-only."""

import os
import platform
import time
from dataclasses import dataclass, field

import psutil

from .hwmon import SYSFS, read_chip, read_text


@dataclass
class SystemInfo:
    os_name: str = ""
    kernel: str = ""
    session: str = ""
    uptime_s: float = 0.0
    mem_used_gb: float = 0.0
    mem_total_gb: float = 0.0
    dimm_temps: list = field(default_factory=list)   # °C per spd5118 chip
    drives: list = field(default_factory=list)       # (model, °C or None)
    wifi_temp: float | None = None


def _listdir(path):
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _os_name():
    text = read_text("/etc/os-release") or ""
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return platform.system()


def read(chips, root=SYSFS):
    info = SystemInfo(os_name=_os_name(), kernel=platform.release(),
                      session=os.environ.get("XDG_SESSION_TYPE", ""),
                      uptime_s=time.time() - psutil.boot_time())
    vm = psutil.virtual_memory()
    info.mem_used_gb = (vm.total - vm.available) / 2**30
    info.mem_total_gb = vm.total / 2**30

    for c in chips:
        temp = next((r.value for r in c.readings if r.kind == "temp"), None)
        if c.name == "spd5118" and temp is not None:
            info.dimm_temps.append(temp)
        elif c.name.startswith("mt79") and temp is not None:
            info.wifi_temp = temp

    nvme_base = os.path.join(root, "class", "nvme")
    ctrls = _listdir(nvme_base)
    for ctrl in ctrls:
        ctrl_path = os.path.join(nvme_base, ctrl)
        model = read_text(os.path.join(ctrl_path, "model")) or ctrl
        temp = None
        hw = next((n for n in _listdir(ctrl_path) if n.startswith("hwmon")), None)
        if hw:
            comp = read_chip(os.path.join(ctrl_path, hw)).get("temp", "Composite")
            temp = comp.value if comp else None
        info.drives.append((model, temp))
    return info
