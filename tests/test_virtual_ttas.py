import os
import struct
import tempfile
import time
import unittest
from unittest import mock

from armory_crate.aura import registry
from armory_crate.aura import virtual_ttas as V
from armory_crate.aura.hidraw import DeviceBusy
from armory_crate.aura.sync import SyncManager


def read_block(path):
    with open(path, "rb") as f:
        b = f.read()
    magic, seq, effect, leds, speed, direction, sync_ms, ticks = V.HEADER.unpack_from(b)
    colors = [tuple(b[40 + i * 4:44 + i * 4]) for i in range(leds)]
    return dict(size=len(b), magic=magic, seq=seq, effect=effect, leds=leds, sync_ms=sync_ms,
                ticks=ticks, colors=colors)


class TtasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def make(self, leds=8):
        return V.TtasSharedMemory("virtual:ttlcd", "TT LCD", leds, "ttlcd.ttas")

    def test_block_layout_matches_ttlcd(self):
        d = self.make()
        d.open()
        d.probe()
        d.set_frame([[(255, 0, 0), (0, 255, 0), (0, 0, 255)] + [(1, 2, 3)] * 5])
        blk = read_block(d.path)
        self.assertEqual(blk["size"], 296)
        self.assertEqual(blk["magic"], 0x53415454)
        self.assertEqual(blk["seq"] % 2, 0)
        self.assertEqual(blk["effect"], 0)
        self.assertEqual(blk["leds"], 8)
        # 0x00BBGGRR little-endian => bytes R, G, B, 0
        self.assertEqual(blk["colors"][:4], [(255, 0, 0, 0), (0, 255, 0, 0), (0, 0, 255, 0), (1, 2, 3, 0)])
        # .NET UtcNow.Ticks
        now_ticks = V.DOTNET_EPOCH_TICKS + int(time.time() * 10_000_000)
        self.assertLess(abs(blk["ticks"] - now_ticks), 5 * 10_000_000)
        self.assertEqual(os.stat(d.path).st_mode & 0o777, 0o600)
        d.close()

    def test_seqlock_even_after_each_publish_and_odd_recovery(self):
        d = self.make()
        d.open()
        seqs = []
        for i in range(5):
            d.set_frame([[(i, i, i)] * 8])
            seqs.append(read_block(d.path)["seq"])
        self.assertTrue(all(s % 2 == 0 for s in seqs))
        self.assertEqual(seqs, sorted(seqs))
        struct.pack_into("<I", d.view, 4, 7)          # simulate a crash mid-write
        d.set_frame([[(9, 9, 9)] * 8])
        self.assertEqual(read_block(d.path)["seq"] % 2, 0)
        d.close()

    def test_close_clears_magic_and_reattach_keeps_counting(self):
        d = self.make()
        d.open()
        d.probe()
        d.close()
        blk = read_block(d.path)
        self.assertEqual(blk["magic"], 0)
        d2 = self.make()
        d2.open()
        d2.probe()
        self.assertGreater(read_block(d2.path)["seq"], blk["seq"])
        self.assertEqual(os.path.getsize(d2.path), 296)
        d2.close()

    def test_second_writer_is_busy(self):
        d = self.make()
        d.open()
        with self.assertRaises(DeviceBusy):
            self.make().open()
        d.close()

    def test_file_name_and_led_validation(self):
        for bad in ("../x", "/tmp/x", ".hidden", "a/b", ""):
            with self.assertRaises(ValueError):
                V.TtasSharedMemory("virtual:x", "n", 8, bad)
        for leds in (0, 65):
            with self.assertRaises(ValueError):
                V.TtasSharedMemory("virtual:x", "n", leds, "x.ttas")

    def test_writes_stay_inside_runtime_dir(self):
        d = self.make()
        self.assertTrue(d.path.startswith(os.path.join(self.tmp.name, "armory-crate", "virtual") + os.sep))


class VirtualRegistryTests(unittest.TestCase):
    def test_build_from_config_and_reject_unknown(self):
        conf = {"virtual_devices": [
            registry.VIRTUAL_PRESETS["ttlcd"],
            {"id": "virtual:evil", "driver": "python-exec", "file": "x"},
            {"id": "no-prefix", "driver": "ttas-shm", "file": "y.ttas"},
            {"id": "virtual:big", "driver": "ttas-shm", "file": "z.ttas", "leds": 500},
        ]}
        with self.assertLogs("armory_crate.aura.registry", "WARNING") as logs:
            devs = registry.build_devices(conf, infos=[])
        self.assertEqual([d.id for d in devs], ["virtual:ttlcd"])
        self.assertIsInstance(devs[0], V.TtasSharedMemory)
        self.assertEqual(len(logs.output), 3)

    def test_virtual_never_matches_hidraw(self):
        self.assertNotIn(V.TtasSharedMemory, [m.driver for m in registry.SUPPORTED])


class KeepaliveTests(unittest.TestCase):
    def test_keepalive_tick_skips_hardware(self):
        class Dev:
            def __init__(self, did, keepalive):
                self.id, self.keepalive_s, self.supported = did, keepalive, True
                self.zones = [type("Z", (), {"leds": 2})()]

        class Worker:
            def __init__(self):
                self.frames = []

            def submit(self, frame):
                self.frames.append(frame)

        hw, virt = Dev("hw", None), Dev("virtual:x", 1.0)
        sync = SyncManager([hw, virt])
        sync.workers = {"hw": Worker(), "virtual:x": Worker()}
        self.assertTrue(sync.needs_keepalive())
        sync.tick(only=lambda d: bool(d.keepalive_s))
        self.assertEqual(len(sync.workers["hw"].frames), 0)
        self.assertEqual(len(sync.workers["virtual:x"].frames), 1)


if __name__ == "__main__":
    unittest.main()
