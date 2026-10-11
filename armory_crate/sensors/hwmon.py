"""Read-only access to sysfs. Nothing in sensors/ ever opens a file for writing."""

import os
import re
from dataclasses import dataclass, field

SYSFS = "/sys"

_ENTRY_RE = re.compile(r"^(temp|fan|in|power|pwm)(\d+)_input$|^(pwm)(\d+)$")


def read_text(path):
    """Return the stripped contents of a sysfs file, or None if unreadable."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def read_int(path):
    text = read_text(path)
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


@dataclass
class Reading:
    kind: str       # temp | fan | in | power | pwm
    index: int
    label: str
    value: float    # °C, RPM, V, W, %


@dataclass
class Chip:
    name: str
    path: str
    readings: list = field(default_factory=list)

    def get(self, kind, label=None, index=None):
        for r in self.readings:
            if r.kind == kind and (label is None or r.label == label) and (index is None or r.index == index):
                return r
        return None


def _scale(kind, raw):
    if kind == "temp":
        return raw / 1000.0
    if kind == "in":
        return raw / 1000.0
    if kind == "power":
        return raw / 1_000_000.0
    if kind == "pwm":
        return raw * 100.0 / 255.0
    return float(raw)


def read_chip(path):
    name = read_text(os.path.join(path, "name")) or os.path.basename(path)
    chip = Chip(name=name, path=path)
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return chip
    for entry in entries:
        m = _ENTRY_RE.match(entry)
        if not m:
            continue
        kind = m.group(1) or m.group(3)
        index = int(m.group(2) or m.group(4))
        raw = read_int(os.path.join(path, entry))
        if raw is None:
            continue
        label = read_text(os.path.join(path, f"{kind}{index}_label")) or f"{kind}{index}"
        chip.readings.append(Reading(kind, index, label, _scale(kind, raw)))
    if chip.get("power") is None:
        # amdgpu exposes power1_average instead of power1_input on some kernels.
        raw = read_int(os.path.join(path, "power1_average"))
        if raw is not None:
            label = read_text(os.path.join(path, "power1_label")) or "power1"
            chip.readings.append(Reading("power", 1, label, _scale("power", raw)))
    return chip


def scan(root=SYSFS):
    """Return every hwmon chip, sorted by hwmon index."""
    base = os.path.join(root, "class", "hwmon")
    try:
        names = os.listdir(base)
    except OSError:
        return []
    names.sort(key=lambda n: int(n[5:]) if n[5:].isdigit() else 0)
    return [read_chip(os.path.join(base, n)) for n in names]


def find(chips, name):
    return next((c for c in chips if c.name == name), None)
