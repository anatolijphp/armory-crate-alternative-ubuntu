"""RGB device model shared by drivers, the sync engine, the daemon and the UI."""

from dataclasses import dataclass, field


@dataclass
class Zone:
    name: str
    leds: int
    resizable: bool = False       # ARGB headers: LED count is user-configured
    max_leds: int = 0


@dataclass
class DeviceState:
    """Serializable description sent over D-Bus to the UI."""
    id: str
    name: str
    kind: str                     # motherboard | monitor | virtual
    supported: bool
    status: str                   # ok | unsupported | busy | no-access | error | disconnected
    detail: str = ""
    firmware: str = ""
    zones: list = field(default_factory=list)   # [{"name", "leds", "resizable", "max_leds"}]
    extra: dict = field(default_factory=dict)


class RGBDevice:
    """Base driver. Subclasses implement open/probe/set_frame/close."""

    kind = "device"
    supported = True
    max_fps = 30
    keepalive_s = None   # if set, re-send a static frame this often (consumers detect staleness)

    def __init__(self, info, device_id, name):
        self.info = info
        self.id = device_id
        self.name = name
        self.zones = []
        self.firmware = ""
        self.status = "disconnected"
        self.detail = ""

    def open(self):
        raise NotImplementedError

    def probe(self):
        """Read-only identification. Must succeed before any colour write."""
        raise NotImplementedError

    def set_frame(self, frame):
        """frame: list (per zone) of lists of (r, g, b)."""
        raise NotImplementedError

    def close(self):
        pass

    def extra(self):
        return {}

    def state(self):
        return DeviceState(
            id=self.id, name=self.name, kind=self.kind, supported=self.supported,
            status=self.status, detail=self.detail, firmware=self.firmware,
            zones=[vars(z).copy() for z in self.zones], extra=self.extra(),
        )


class UnsupportedDevice(RGBDevice):
    """Detected but no verified protocol: never opened, never written."""

    supported = False

    def __init__(self, info, device_id, name, kind, reason):
        super().__init__(info, device_id, name)
        self.kind = kind
        self.status = "unsupported"
        self.detail = reason

    def open(self):
        raise PermissionError("unsupported device is display-only")

    def probe(self):
        raise PermissionError("unsupported device is display-only")

    def set_frame(self, frame):
        raise PermissionError("unsupported device is display-only")
