"""CPU view: clocks, policy and temperatures. Read-only — no tuning."""

import os
import re
from dataclasses import dataclass, field

import psutil

from .hwmon import SYSFS, find, read_int, read_text


@dataclass
class CpuInfo:
    model: str = "Unknown CPU"
    cores: int = 0
    threads: int = 0
    freqs_mhz: list = field(default_factory=list)     # per logical CPU
    loads: list = field(default_factory=list)         # per logical CPU, %
    load_total: float = 0.0
    min_mhz: float = 0.0
    max_mhz: float = 0.0
    driver: str = ""
    driver_status: str = ""
    governor: str = ""
    epp: str = ""
    boost: bool | None = None
    tctl: float | None = None
    ccds: dict = field(default_factory=dict)           # label -> °C
    vcore: float | None = None

    @property
    def avg_mhz(self):
        return sum(self.freqs_mhz) / len(self.freqs_mhz) if self.freqs_mhz else 0.0

    @property
    def peak_mhz(self):
        return max(self.freqs_mhz, default=0.0)


def _model_name(proc_cpuinfo="/proc/cpuinfo"):
    text = read_text(proc_cpuinfo) or ""
    m = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else "Unknown CPU"


def _logical_cpus(root):
    base = os.path.join(root, "devices", "system", "cpu")
    try:
        names = os.listdir(base)
    except OSError:
        return []
    return sorted((int(n[3:]) for n in names if re.fullmatch(r"cpu\d+", n)))


def read(chips, root=SYSFS, proc_cpuinfo="/proc/cpuinfo", with_load=True):
    info = CpuInfo(model=_model_name(proc_cpuinfo))
    cpu_base = os.path.join(root, "devices", "system", "cpu")
    cpus = _logical_cpus(root)
    info.threads = len(cpus)
    info.cores = psutil.cpu_count(logical=False) or info.threads

    for n in cpus:
        khz = read_int(os.path.join(cpu_base, f"cpu{n}", "cpufreq", "scaling_cur_freq"))
        info.freqs_mhz.append(khz / 1000.0 if khz else 0.0)

    pol = os.path.join(cpu_base, "cpu0", "cpufreq")
    min_khz = read_int(os.path.join(pol, "cpuinfo_min_freq"))
    max_khz = read_int(os.path.join(pol, "cpuinfo_max_freq"))
    info.min_mhz = min_khz / 1000.0 if min_khz else 0.0
    info.max_mhz = max_khz / 1000.0 if max_khz else 0.0
    info.driver = read_text(os.path.join(pol, "scaling_driver")) or ""
    info.governor = read_text(os.path.join(pol, "scaling_governor")) or ""
    info.epp = read_text(os.path.join(pol, "energy_performance_preference")) or ""
    info.driver_status = read_text(os.path.join(cpu_base, "amd_pstate", "status")) or ""
    boost = read_int(os.path.join(cpu_base, "cpufreq", "boost"))
    info.boost = None if boost is None else bool(boost)

    if with_load:
        info.loads = psutil.cpu_percent(percpu=True)
        info.load_total = sum(info.loads) / len(info.loads) if info.loads else 0.0

    k10 = find(chips, "k10temp")
    if k10:
        for r in k10.readings:
            if r.kind != "temp":
                continue
            if r.label == "Tctl":
                info.tctl = r.value
            elif r.label.startswith("Tccd"):
                info.ccds[r.label] = r.value
    ec = find(chips, "asusec")
    if ec:
        v = ec.get("in", "CPU Core")
        info.vcore = v.value if v else None
    return info
