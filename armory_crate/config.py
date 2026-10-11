"""Persistent user configuration (~/.config/armory-crate/config.json)."""

import copy
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "armory-crate"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Upper bound for LEDs on one ARGB header. Keeping this <= 255 means the Aura
# direct-mode offset never needs the 8-bit overflow flag.
MAX_ARGB_LEDS = 120

DEFAULTS = {
    "effect": {
        "name": "static",
        "colors": ["#ff0000", "#0000ff"],
        "speed": 1.0,
        "brightness": 100,
        "direction": "forward",
    },
    # device_id -> {"enabled": bool, "argb_leds": {zone_index: count}}
    "devices": {},
    # software-only Aura devices, see docs/virtual-devices.md
    "virtual_devices": [],
    # hwmon fan label overrides, e.g. {"nct6799/fan2": "CPU_FAN"}
    "fan_labels": {},
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path=CONFIG_PATH):
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return _merge(DEFAULTS, data if isinstance(data, dict) else {})


def save(config, path=CONFIG_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def device_settings(config, device_id):
    dev = config["devices"].setdefault(device_id, {})
    dev.setdefault("enabled", True)
    dev.setdefault("argb_leds", {})
    return dev
