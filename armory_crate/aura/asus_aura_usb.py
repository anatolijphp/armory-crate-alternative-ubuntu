"""ASUS Aura USB mainboard controller (0b05:19af), Direct mode only."""

from .. import config as cfg
from . import packets_aura as P
from .device import RGBDevice, Zone
from .hidraw import HidrawHandle


class AsusAuraUSB(RGBDevice):
    kind = "motherboard"
    max_fps = 30

    def __init__(self, info, device_id, name, argb_leds=None):
        super().__init__(info, device_id, name)
        self.argb_leds = dict(argb_leds or {})   # zone index (str) -> LED count
        self.handle = None
        self.table = b""
        self.layout = {}
        self._channels = []      # per zone: (effect_channel, direct_channel)
        self._direct_entered = set()

    def open(self):
        self.handle = HidrawHandle(self.info.node)

    def _query(self, packet):
        self.handle.drain()
        self.handle.write(packet)
        # The controller may emit unrelated reports; take the first 0xEC reply.
        for _ in range(4):
            reply = self.handle.read(timeout=0.5)
            if reply is None:
                break
            if reply[:1] == bytes([P.REPORT_ID]):
                return reply
        return None

    def probe(self):
        self.firmware = P.parse_firmware(self._query(P.firmware_query()))
        self.table, self.layout = P.parse_config(self._query(P.config_query()))
        self._build_zones()
        self.status = "ok"

    def _build_zones(self):
        self.zones, self._channels = [], []
        effect_ch = 0
        mb = self.layout["mainboard_leds"]
        if mb > 0:
            rgb = self.layout["rgb_headers"]
            label = "Onboard LEDs" + (f" + {rgb} RGB header" + ("s" if rgb > 1 else "") if rgb else "")
            self.zones.append(Zone(label, mb))
            self._channels.append((effect_ch, P.MAINBOARD_DIRECT_CHANNEL))
            effect_ch += 1
        for i in range(self.layout["argb_headers"]):
            idx = len(self.zones)
            count = min(int(self.argb_leds.get(str(idx), 0)), cfg.MAX_ARGB_LEDS)
            self.zones.append(Zone(f"ARGB header {i + 1}", count, resizable=True, max_leds=cfg.MAX_ARGB_LEDS))
            self._channels.append((effect_ch, i))
            effect_ch += 1

    def resize_zone(self, index, leds):
        zone = self.zones[index]
        if not zone.resizable:
            raise ValueError("zone is not resizable")
        zone.leds = max(0, min(int(leds), zone.max_leds))
        self.argb_leds[str(index)] = zone.leds

    def set_frame(self, frame):
        for idx, (zone, colors) in enumerate(zip(self.zones, frame)):
            if zone.leds == 0:
                continue
            effect_ch, direct_ch = self._channels[idx]
            if idx not in self._direct_entered:
                self.handle.write(P.direct_mode(effect_ch))
                self._direct_entered.add(idx)
            for packet in P.direct_frames(direct_ch, colors[:zone.leds]):
                self.handle.write(packet)

    def reset_direct(self):
        """Re-send the Direct mode switch on next frame (after resume/replug)."""
        self._direct_entered.clear()

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def extra(self):
        return {"layout": self.layout, "config_table": self.table.hex()}
