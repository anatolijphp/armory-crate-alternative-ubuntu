"""Virtual Aura device: publishes each frame as a TTAS block for TT LCD Studio (Linux).

The block layout is the one ttlcd's Windows Armoury Crate plugin (TTLcdAura.dll) uses
for "Global\\TTLcdAuraSync"; on Linux it lives in a file under $XDG_RUNTIME_DIR. See
docs/virtual-devices.md. Touches no hardware: only this one file.
"""

import errno
import fcntl
import mmap
import os
import struct
import time

from .device import RGBDevice, Zone
from .hidraw import DeviceBusy

MAGIC = 0x53415454                  # "TTAS"
MAX_LEDS = 64
SIZE = 40 + MAX_LEDS * 4            # 296 bytes
EFFECT_MANUAL = 0                   # colours are final frames; ttlcd draws them as-is
DOTNET_EPOCH_TICKS = 621355968000000000   # DateTime(1970-01-01).Ticks
HEADER = struct.Struct("<IIIIIIqq")  # magic seq effect leds speed direction syncMs ticks


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        raise RuntimeError("XDG_RUNTIME_DIR is not set")
    path = os.path.join(base, "armory-crate", "virtual")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def validate_file_name(file):
    if not file or os.path.isabs(file) or "/" in file or os.sep in file or file.startswith("."):
        raise ValueError("file must be a plain name inside the virtual/ folder")
    return file


class TtasSharedMemory(RGBDevice):
    kind = "virtual"
    max_fps = 30
    keepalive_s = 1.0               # ttlcd marks the stream stale after 30 s without updates

    def __init__(self, device_id, name, leds, file):
        super().__init__(info=None, device_id=device_id, name=name)
        leds = int(leds)
        if not 1 <= leds <= MAX_LEDS:
            raise ValueError(f"leds must be 1..{MAX_LEDS}")
        self.zones = [Zone("LCD", leds)]
        self.file = validate_file_name(file)
        self.fd = self.view = None
        self.t0 = time.monotonic()

    @property
    def path(self):
        return os.path.join(runtime_dir(), self.file)

    def open(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise DeviceBusy(e.errno, f"{self.file} is being written by another armory-crate process") from e
            raise
        if os.fstat(fd).st_size < SIZE:
            os.ftruncate(fd, SIZE)          # grow only; never truncate a live block
        self.fd = fd
        self.view = mmap.mmap(fd, SIZE)

    def probe(self):
        self._publish([(0, 0, 0)] * self.zones[0].leds)
        self.status, self.detail = "ok", f"Virtual · {self.path}"

    def set_frame(self, frame):
        self._publish(frame[0][:self.zones[0].leds])

    def _publish(self, colors, magic=MAGIC):
        v = self.view
        seq = struct.unpack_from("<I", v, 4)[0]
        if seq & 1:                               # left odd by a crash: realign
            seq += 1
        writing, done = (seq + 1) & 0xFFFFFFFF, (seq + 2) & 0xFFFFFFFF
        struct.pack_into("<I", v, 4, writing)    # odd: update in progress
        ticks = DOTNET_EPOCH_TICKS + int(time.time() * 10_000_000)
        sync_ms = int((time.monotonic() - self.t0) * 1000)
        HEADER.pack_into(v, 0, magic, writing, EFFECT_MANUAL, len(colors), 0, 0, sync_ms, ticks)
        packed = bytearray(MAX_LEDS * 4)
        for i, (r, g, b) in enumerate(colors):
            packed[i * 4:i * 4 + 3] = bytes((r, g, b))    # 0x00BBGGRR little-endian
        v[40:SIZE] = bytes(packed)
        struct.pack_into("<I", v, 4, done)       # even: complete

    def reset_direct(self):
        pass

    def close(self):
        if self.view is not None:
            try:
                self._publish([], magic=0)       # reader shows "waiting for Aura"
            finally:
                self.view.close()
                os.close(self.fd)                # releases the flock
                self.view = self.fd = None

    def extra(self):
        return {"file": self.file}
