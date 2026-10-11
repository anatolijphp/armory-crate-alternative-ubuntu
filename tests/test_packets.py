import unittest

from armory_crate.aura import packets_aura as A


class AuraPacketTests(unittest.TestCase):
    def test_queries_match_reference(self):
        self.assertEqual(A.firmware_query(), bytes([0xEC, 0x82]) + bytes(63))
        self.assertEqual(A.config_query(), bytes([0xEC, 0xB0]) + bytes(63))

    def test_direct_mode_never_sets_shutdown_effect(self):
        self.assertEqual(A.direct_mode(1)[:6], bytes([0xEC, 0x35, 0x01, 0x00, 0x00, 0xFF]))
        self.assertEqual(len(A.direct_mode(1)), 65)

    def test_direct_frames_chunking_and_apply_flag(self):
        colors = [(i, i + 1, i + 2) for i in range(25)]
        p1, p2 = A.direct_frames(0x04, colors)
        self.assertEqual(p1[:5], bytes([0xEC, 0x40, 0x04, 0x00, 20]))
        self.assertEqual(p1[5:8], bytes([0, 1, 2]))
        self.assertEqual(p1[5 + 19 * 3:5 + 20 * 3], bytes([19, 20, 21]))
        self.assertEqual(p2[:5], bytes([0xEC, 0x40, 0x84, 20, 5]))
        self.assertEqual(p2[5:8], bytes([20, 21, 22]))
        self.assertTrue(all(len(p) == 65 for p in (p1, p2)))

    def test_single_packet_has_apply(self):
        (p,) = A.direct_frames(0x00, [(1, 2, 3)])
        self.assertEqual(p[:8], bytes([0xEC, 0x40, 0x80, 0x00, 0x01, 1, 2, 3]))

    def test_led_limit(self):
        with self.assertRaises(ValueError):
            A.direct_frames(0, [(0, 0, 0)] * 256)
        self.assertEqual(A.direct_frames(0, []), [])

    def test_opcode_allow_list(self):
        accepted = set()
        for op in range(256):
            try:
                A._packet(op)
                accepted.add(op)
            except ValueError:
                pass
        self.assertEqual(accepted, {0x82, 0xB0, 0x35, 0x40})
        for forbidden in (0x36, 0x3F, 0x52):
            self.assertNotIn(forbidden, accepted)

    def test_parse_firmware(self):
        reply = bytes([0xEC, 0x02]) + b"AUMA0-E6K5-0106\0" + bytes(47)
        self.assertEqual(A.parse_firmware(reply), "AUMA0-E6K5-0106")
        with self.assertRaises(A.ProtocolError):
            A.parse_firmware(bytes([0xEC, 0x30]) + bytes(63))
        with self.assertRaises(A.ProtocolError):
            A.parse_firmware(None)

    def test_parse_config(self):
        table = bytearray(60)
        table[0x02], table[0x1B], table[0x1D] = 1, 6, 1
        reply = bytes([0xEC, 0x30, 0, 0]) + bytes(table) + bytes(1)
        raw, layout = A.parse_config(reply)
        self.assertEqual(raw, bytes(table))
        self.assertEqual(layout, {"argb_headers": 1, "mainboard_leds": 6, "rgb_headers": 1})

    def test_parse_config_rgb_headers_clamped(self):
        table = bytearray(60)
        table[0x1B], table[0x1D] = 1, 3
        _, layout = A.parse_config(bytes([0xEC, 0x30, 0, 0]) + bytes(table))
        self.assertEqual(layout["rgb_headers"], 0)


if __name__ == "__main__":
    unittest.main()
