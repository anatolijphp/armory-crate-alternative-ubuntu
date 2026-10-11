"""hidraw discovery (pure sysfs reads) and a locked read/write handle.

Discovery never opens /dev nodes. Only HidrawHandle opens a node, and only
drivers that passed strict matching in aura.registry create one.
"""

import errno
import fcntl
import os
import select
from dataclasses import dataclass

from ..sensors.hwmon import SYSFS, read_text


@dataclass(frozen=True)
class HidInfo:
    node: str            # /dev/hidrawN
    name: str            # hidrawN
    vid: int
    pid: int
    product: str
    interface: int | None
    usage_page: int | None
    usage: int | None
    serial: str
    usb_path: str        # e.g. "3-2.1" — stable per physical port

    @property
    def vid_pid(self):
        return f"{self.vid:04x}:{self.pid:04x}"


def parse_usage(descriptor):
    """Return (usage_page, usage) of the first top-level collection.

    Walks short HID items; good enough for the vendor descriptors we match on.
    """
    page = usage = None
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item
            if i + 1 >= len(descriptor):
                break
            i += 3 + descriptor[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        tag_type = prefix & 0xFC
        data = int.from_bytes(descriptor[i + 1:i + 1 + size], "little")
        if tag_type == 0x04 and page is None:      # Usage Page (global)
            page = data
        elif tag_type == 0x08 and usage is None:   # Usage (local)
            usage = data
        elif tag_type == 0xA0:                     # Collection
            break
        i += 1 + size
    return page, usage


def _uevent(path):
    out = {}
    for line in (read_text(path) or "").splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


def discover(root=SYSFS, dev_root="/dev"):
    base = os.path.join(root, "class", "hidraw")
    try:
        names = sorted(os.listdir(base), key=lambda n: int(n[6:]) if n[6:].isdigit() else 0)
    except OSError:
        return []
    found = []
    for name in names:
        hid_dev = os.path.realpath(os.path.join(base, name, "device"))
        ev = _uevent(os.path.join(hid_dev, "uevent"))
        try:
            bus, vid, pid = (int(x, 16) for x in ev.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if bus != 0x0003:  # USB only
            continue
        try:
            with open(os.path.join(hid_dev, "report_descriptor"), "rb") as f:
                desc = f.read()
        except OSError:
            desc = b""
        page, usage = parse_usage(desc)
        usb_iface = os.path.dirname(hid_dev)
        iface = read_text(os.path.join(usb_iface, "bInterfaceNumber"))
        found.append(HidInfo(
            node=os.path.join(dev_root, name), name=name, vid=vid, pid=pid,
            product=ev.get("HID_NAME", ""),
            interface=int(iface, 16) if iface else None,
            usage_page=page, usage=usage,
            serial=ev.get("HID_UNIQ", ""),
            usb_path=os.path.basename(usb_iface).split(":")[0],
        ))
    return found


class DeviceBusy(OSError):
    pass


class HidrawHandle:
    """Exclusive (flock) hidraw handle with output-report writes and timed reads."""

    def __init__(self, node):
        self.node = node
        self.fd = os.open(node, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(self.fd)
            self.fd = None
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise DeviceBusy(e.errno, f"{node} is in use by another application") from e
            raise

    def write(self, data):
        n = os.write(self.fd, bytes(data))
        if n != len(data):
            raise OSError(errno.EIO, f"short write to {self.node}: {n}/{len(data)}")

    def read(self, size=64 + 1, timeout=0.25):
        """Read one input report, or return None on timeout."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        try:
            return os.read(self.fd, size)
        except BlockingIOError:
            return None

    def drain(self):
        while self.read(timeout=0) is not None:
            pass

    def close(self):
        if self.fd is not None:
            os.close(self.fd)  # releases the flock
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
