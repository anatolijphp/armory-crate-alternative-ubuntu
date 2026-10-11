"""Motherboard: DMI identity, ASUS EC temperatures, Super-I/O fans. Read-only."""

import os
from dataclasses import dataclass, field

from .hwmon import SYSFS, find, read_text

# Super-I/O chips handled by the nct6775 driver.
SUPERIO_PREFIXES = ("nct6", "nct5")


@dataclass
class Fan:
    key: str        # stable id, e.g. "nct6799/fan2"
    label: str
    rpm: float
    duty: float | None = None   # % from pwmN, view only


@dataclass
class BoardInfo:
    vendor: str = ""
    name: str = ""
    bios_version: str = ""
    bios_date: str = ""
    temps: dict = field(default_factory=dict)     # label -> °C (asusec)
    voltages: dict = field(default_factory=dict)  # label -> V
    fans: list = field(default_factory=list)
    superio: str | None = None                    # chip name, None if nct6775 not loaded


def read_dmi(root=SYSFS):
    dmi = os.path.join(root, "devices", "virtual", "dmi", "id")
    return {k: read_text(os.path.join(dmi, k)) or "" for k in
            ("board_vendor", "board_name", "bios_version", "bios_date", "product_name")}


def read(chips, root=SYSFS, fan_labels=None, dmi=None):
    fan_labels = fan_labels or {}
    dmi = dmi or read_dmi(root)
    info = BoardInfo(vendor=dmi["board_vendor"], name=dmi["board_name"],
                     bios_version=dmi["bios_version"], bios_date=dmi["bios_date"])
    ec = find(chips, "asusec")
    if ec:
        for r in ec.readings:
            if r.kind == "temp":
                info.temps[r.label] = r.value
            elif r.kind == "in":
                info.voltages[r.label] = r.value

    sio = next((c for c in chips if c.name.startswith(SUPERIO_PREFIXES)), None)
    if sio:
        info.superio = sio.name
        for r in sio.readings:
            if r.kind == "fan":
                key = f"{sio.name}/fan{r.index}"
                pwm = sio.get("pwm", index=r.index)
                info.fans.append(Fan(key, fan_labels.get(key, f"Fan {r.index}"), r.value,
                                     pwm.value if pwm else None))
            elif r.kind == "in" and r.label != f"in{r.index}":
                info.voltages.setdefault(r.label, r.value)
    return info


def gpu_fan(gpu):
    if gpu is None or gpu.fan_rpm is None:
        return None
    return Fan("amdgpu/fan1", "GPU fan", gpu.fan_rpm)
