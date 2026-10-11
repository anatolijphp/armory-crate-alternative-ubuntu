"""Aura Sync engine: renders one effect across all enabled devices.

Each opened device gets its own worker thread with a latest-frame mailbox, so
a slow or stalled device never holds up the rest.
Workers enforce the per-device max_fps write cap.
"""

import logging
import threading
import time

from . import effects
from .hidraw import DeviceBusy

log = logging.getLogger(__name__)


class DeviceWorker(threading.Thread):
    def __init__(self, device, on_error):
        super().__init__(name=f"aura-{device.id}", daemon=True)
        self.device = device
        self.on_error = on_error
        self._frame = None
        self._cond = threading.Condition()
        self._stopping = False

    def submit(self, frame):
        with self._cond:
            self._frame = frame
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stopping = True
            self._cond.notify()

    def run(self):
        interval = 1.0 / self.device.max_fps
        last = 0.0
        while True:
            with self._cond:
                while self._frame is None and not self._stopping:
                    self._cond.wait()
                if self._stopping:
                    return
                frame, self._frame = self._frame, None
            wait = last + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                self.device.set_frame(frame)
            except OSError as e:
                log.warning("%s: write failed: %s", self.device.id, e)
                self.on_error(self.device, e)
                return
            last = time.monotonic()


class SyncManager:
    def __init__(self, devices, enabled=None):
        self.devices = devices
        self.enabled = enabled or {}           # device id -> bool
        self.effect = effects.Effect()
        self.t0 = time.monotonic()
        self.workers = {}
        self.frame = 0
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------
    def open_all(self):
        """Open and read-only probe every supported device."""
        for dev in self.devices:
            if not dev.supported:
                continue
            try:
                dev.open()
                dev.probe()
            except DeviceBusy as e:
                dev.status, dev.detail = "busy", str(e)
                dev.close()
            except PermissionError as e:
                hint = " — install the udev rule" if dev.info is not None else ""
                dev.status, dev.detail = "no-access", f"{e.strerror or e}{hint}"
                dev.close()
            except Exception as e:  # protocol mismatch, timeout: disable for this session
                dev.status, dev.detail = "error", str(e)
                dev.close()
            else:
                self._start_worker(dev)

    def _start_worker(self, dev):
        w = DeviceWorker(dev, self._on_worker_error)
        self.workers[dev.id] = w
        w.start()

    def _on_worker_error(self, dev, err):
        with self._lock:
            self.workers.pop(dev.id, None)
        dev.status, dev.detail = "error", f"write failed: {err}"
        dev.close()

    def close_all(self):
        for w in list(self.workers.values()):
            w.stop()
        for w in list(self.workers.values()):
            w.join(timeout=1.0)
        self.workers.clear()
        for dev in self.devices:
            dev.close()

    # -- rendering -------------------------------------------------------
    def active_devices(self):
        return [d for d in self.devices if d.id in self.workers and self.enabled.get(d.id, True)]

    def set_effect(self, effect):
        effect.validate()
        self.effect = effect

    def tick(self, now=None, only=None):
        """Render one frame for every active device and hand it to its worker.

        only: optional predicate; the layout still spans every active device (so
        positions don't shift) but frames go only to devices it accepts. Used for
        keepalives, so hardware isn't rewritten just to refresh a virtual device.
        """
        devs = self.active_devices()
        if not devs:
            return
        t = (now if now is not None else time.monotonic()) - self.t0
        layout = [[z.leds for z in d.zones] for d in devs]
        self.frame += 1
        frames = effects.render_layout(self.effect, t, layout, frame=self.frame)
        for dev, frame in zip(devs, frames):
            if only is not None and not only(dev):
                continue
            w = self.workers.get(dev.id)
            if w:
                w.submit(frame)

    def needs_keepalive(self):
        return any(d.keepalive_s for d in self.active_devices())

    def reset_direct(self):
        for d in self.devices:
            if hasattr(d, "reset_direct"):
                d.reset_direct()
