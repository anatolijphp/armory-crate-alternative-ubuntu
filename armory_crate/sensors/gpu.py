"""AMD GPU view via amdgpu sysfs. Read-only."""

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .hwmon import SYSFS, read_chip, read_int, read_text

PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids")


@dataclass
class GpuInfo:
    name: str = "GPU"
    busy: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    sclk_mhz: float | None = None
    mclk_mhz: float | None = None
    temps: dict = field(default_factory=dict)   # edge/junction/mem -> °C
    fan_rpm: float | None = None
    power_w: float | None = None
    vbios: str = ""


@lru_cache(maxsize=8)
def pci_name(vendor, device, files=PCI_IDS):
    """Look up a device name in pci.ids ('1002', '7550')."""
    vendor, device = vendor.lower(), device.lower()
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                in_vendor = False
                for line in f:
                    if not line.strip() or line.startswith("#"):
                        continue
                    if not line.startswith("\t"):
                        in_vendor = line.startswith(vendor + " ")
                    elif in_vendor and line.startswith("\t" + device + " "):
                        return line.strip()[len(device):].strip()
        except OSError:
            continue
    return None


def _active_dpm(path):
    """Parse pp_dpm_* ('1: 2400Mhz *') and return the active clock in MHz."""
    text = read_text(path)
    if not text:
        return None
    for line in text.splitlines():
        if line.rstrip().endswith("*"):
            m = re.search(r"(\d+)\s*Mhz", line, re.IGNORECASE)
            if m:
                return float(m.group(1))
    return None


def find_amdgpu(root=SYSFS):
    base = os.path.join(root, "class", "drm")
    try:
        cards = sorted(n for n in os.listdir(base) if re.fullmatch(r"card\d+", n))
    except OSError:
        return None
    for card in cards:
        dev = os.path.join(base, card, "device")
        if read_text(os.path.join(dev, "vendor")) == "0x1002" and os.path.exists(os.path.join(dev, "gpu_busy_percent")):
            return dev
    return None


def read(root=SYSFS, device_path=None):
    dev = device_path or find_amdgpu(root)
    info = GpuInfo()
    if not dev:
        return None
    vendor = (read_text(os.path.join(dev, "vendor")) or "0x0")[2:]
    device = (read_text(os.path.join(dev, "device")) or "0x0")[2:]
    info.name = pci_name(vendor, device) or f"AMD GPU {device}"
    info.busy = read_int(os.path.join(dev, "gpu_busy_percent"))
    used = read_int(os.path.join(dev, "mem_info_vram_used"))
    total = read_int(os.path.join(dev, "mem_info_vram_total"))
    info.vram_used_mb = used / 2**20 if used is not None else None
    info.vram_total_mb = total / 2**20 if total is not None else None
    info.sclk_mhz = _active_dpm(os.path.join(dev, "pp_dpm_sclk"))
    info.mclk_mhz = _active_dpm(os.path.join(dev, "pp_dpm_mclk"))
    info.vbios = read_text(os.path.join(dev, "vbios_version")) or ""

    hw_base = os.path.join(dev, "hwmon")
    try:
        hwmons = os.listdir(hw_base)
    except OSError:
        hwmons = []
    if hwmons:
        chip = read_chip(os.path.join(hw_base, hwmons[0]))
        for r in chip.readings:
            if r.kind == "temp":
                info.temps[r.label] = r.value
            elif r.kind == "fan" and info.fan_rpm is None:
                info.fan_rpm = r.value
            elif r.kind == "power" and info.power_w is None:
                info.power_w = r.value
    return info
