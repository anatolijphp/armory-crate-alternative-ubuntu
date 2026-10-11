"""Periodic sensor sampling shared by all pages, with short history buffers."""

from collections import defaultdict, deque

import psutil
from gi.repository import GLib, GObject

from .. import config as cfg
from .. import sensors
from ..sensors import board

HISTORY = 120        # samples (2 minutes at 1 Hz)
INTERVAL_MS = 1000


class Sampler(GObject.Object):
    __gsignals__ = {"updated": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.config = cfg.load()
        self.snapshot = None
        self.history = defaultdict(lambda: deque(maxlen=HISTORY))
        psutil.cpu_percent(percpu=True)   # prime the load counters
        self._tick()
        GLib.timeout_add(INTERVAL_MS, self._tick)

    def _push(self, key, value):
        if value is not None:
            self.history[key].append(value)

    def _tick(self):
        snap = sensors.sample(fan_labels=self.config["fan_labels"])
        self.snapshot = snap
        self._push("cpu.temp", snap.cpu.tctl)
        self._push("cpu.load", snap.cpu.load_total)
        self._push("cpu.clock", snap.cpu.avg_mhz)
        if snap.gpu:
            self._push("gpu.temp", snap.gpu.temps.get("edge"))
            self._push("gpu.load", snap.gpu.busy)
            self._push("gpu.power", snap.gpu.power_w)
        self._push("mb.vrm", snap.board.temps.get("VRM"))
        self._push("mem.used", snap.system.mem_used_gb)
        for fan in self.fans():
            self._push(f"fan.{fan.key}", fan.rpm)
        self.emit("updated")
        return GLib.SOURCE_CONTINUE

    def fans(self):
        snap = self.snapshot
        fans = list(snap.board.fans)
        g = board.gpu_fan(snap.gpu)
        if g:
            fans.append(g)
        return fans

    def rename_fan(self, key, label):
        labels = self.config["fan_labels"]
        if label.strip():
            labels[key] = label.strip()
        else:
            labels.pop(key, None)
        cfg.save(self.config)
        self._tick()
