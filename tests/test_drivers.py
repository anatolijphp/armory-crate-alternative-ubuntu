import unittest

from armory_crate.aura import packets_aura as A
from armory_crate.aura import registry
from armory_crate.aura.asus_aura_usb import AsusAuraUSB
from armory_crate.aura.device import UnsupportedDevice
from armory_crate.aura.hidraw import HidInfo, parse_usage
from armory_crate.aura.sync import SyncManager


def info(vid, pid, iface, page, node="/dev/hidrawX"):
    return HidInfo(node=node, name="hidrawX", vid=vid, pid=pid, product="p", interface=iface,
                   usage_page=page, usage=None, serial="", usb_path="1-7")


class FakeHandle:
    """Records writes; answers Aura queries like the real device."""

    def __init__(self, table=None, reply_ok=True):
        self.writes = []
        self.pending = []
        self.table = table or bytearray(60)
        self.reply_ok = reply_ok

    def drain(self):
        self.pending.clear()

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        if not self.reply_ok:
            return
        if data[:2] == bytes([0xEC, 0x82]):
            self.pending.append(bytes([0xEC, 0x02]) + b"AUMA0-TEST\0".ljust(16, b"\0") + bytes(47))
        elif data[:2] == bytes([0xEC, 0xB0]):
            self.pending.append(bytes([0xEC, 0x30, 0, 0]) + bytes(self.table))

    def read(self, size=65, timeout=0.25):
        return self.pending.pop(0) if self.pending else None

    def close(self):
        pass


class RegistryTests(unittest.TestCase):
    def test_strict_matching(self):
        self.assertIs(registry.match(info(0x0B05, 0x19AF, 2, 0xFF72)).driver, AsusAuraUSB)
        # wrong interface / usage page -> never opened
        self.assertIsNone(registry.match(info(0x0B05, 0x19AF, 0, 0xFF72)))
        self.assertIsNone(registry.match(info(0x0B05, 0x19AF, 2, 0xFF00)))

    def test_steelseries_excluded(self):
        infos = [info(0x1038, 0x1838, 3, 0xFFC0), info(0x1038, 0x161E, 1, 0xFFC0)]
        for i in infos:
            self.assertIsNone(registry.match(i))
        self.assertEqual(registry.build_devices(None, infos), [])

    def test_monitor_is_display_only(self):
        devs = registry.build_devices(None, [info(0x0B05, 0x1BA3, 1, 0xFF72), info(0x0B05, 0x1BA3, 0, 0x0001)])
        self.assertEqual(len(devs), 1)
        for d in devs:
            self.assertIsInstance(d, UnsupportedDevice)
            self.assertFalse(d.supported)
            with self.assertRaises(PermissionError):
                d.open()
            with self.assertRaises(PermissionError):
                d.set_frame([[(255, 0, 0)]])

    def test_sync_never_opens_unsupported(self):
        dev = registry.build_devices(None, [info(0x0B05, 0x1BA3, 1, 0xFF72)])[0]
        sync = SyncManager([dev])
        sync.open_all()
        self.assertEqual(sync.workers, {})
        self.assertEqual(dev.status, "unsupported")

    def test_parse_usage(self):
        aura = bytes.fromhex("0672ff09a1a10185ec0910150026ff007508954081020911150026ff00750895409102c0")
        self.assertEqual(parse_usage(aura), (0xFF72, 0xA1))
        self.assertEqual(parse_usage(bytes.fromhex("06c0ff0901a101")), (0xFFC0, 0x01))


class AuraDriverTests(unittest.TestCase):
    def make(self, argb=1, mb=6, leds=None):
        table = bytearray(60)
        table[0x02], table[0x1B], table[0x1D] = argb, mb, 1
        dev = AsusAuraUSB(info(0x0B05, 0x19AF, 2, 0xFF72), "id", "Aura", argb_leds={"1": 30} if leds is None else leds)
        dev.handle = FakeHandle(table)
        return dev

    def test_probe_is_read_only_and_builds_zones(self):
        dev = self.make()
        dev.probe()
        self.assertEqual([w[1] for w in dev.handle.writes], [0x82, 0xB0])
        self.assertEqual(dev.firmware, "AUMA0-TEST")
        self.assertEqual([(z.name, z.leds) for z in dev.zones],
                         [("Onboard LEDs + 1 RGB header", 6), ("ARGB header 1", 30)])

    def test_set_frame_only_emits_allowed_opcodes(self):
        dev = self.make()
        dev.probe()
        dev.handle.writes.clear()
        dev.set_frame([[(1, 2, 3)] * 6, [(4, 5, 6)] * 30])
        dev.set_frame([[(1, 2, 3)] * 6, [(4, 5, 6)] * 30])
        ops = [w[1] for w in dev.handle.writes]
        self.assertTrue(set(ops) <= A.ALLOWED_OPCODES)
        # direct mode entered once per zone, then frames only
        self.assertEqual(ops.count(0x35), 2)
        self.assertEqual(dev.handle.writes[0][:6], bytes([0xEC, 0x35, 0, 0, 0, 0xFF]))
        self.assertEqual(dev.handle.writes[1][2], 0x84)   # mainboard direct channel 4 + apply
        self.assertNotIn(0x3F, ops)

    def test_zero_led_argb_zone_is_skipped(self):
        dev = self.make(leds={})
        dev.probe()
        dev.handle.writes.clear()
        dev.set_frame([[(1, 2, 3)] * 6, []])
        self.assertTrue(all(w[2] in (0x00, 0x84) for w in dev.handle.writes))

    def test_probe_rejects_unexpected_reply(self):
        dev = self.make()
        dev.handle = FakeHandle(reply_ok=False)
        with self.assertRaises(A.ProtocolError):
            dev.probe()

    def test_argb_count_capped(self):
        dev = self.make(leds={"1": 9999})
        dev.probe()
        self.assertEqual(dev.zones[1].leds, 120)
        dev.resize_zone(1, 500)
        self.assertEqual(dev.zones[1].leds, 120)
        with self.assertRaises(ValueError):
            dev.resize_zone(0, 3)


if __name__ == "__main__":
    unittest.main()
