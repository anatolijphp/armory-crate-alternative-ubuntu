"""ASUS Aura USB mainboard protocol (0b05:19af) — allow-listed packet builders.

Reference: OpenRGB Controllers/AsusAuraUSBController/AsusAuraUSBController
(AsusAuraUSBController.{h,cpp}, AsusAuraMainboardController.{h,cpp}).

Only volatile commands exist here. Deliberately absent, and rejected by
_packet(): 0x36 (effect colour), 0x3F (commit / save to flash), 0x52 (gen1).
"""

REPORT_ID = 0xEC
REPORT_LEN = 65   # report id + 64 bytes

REQUEST_FIRMWARE = 0x82
REQUEST_CONFIG = 0xB0
SET_EFFECT_MODE = 0x35
DIRECT = 0x40

REPLY_FIRMWARE = 0x02
REPLY_CONFIG = 0x30

ALLOWED_OPCODES = frozenset({REQUEST_FIRMWARE, REQUEST_CONFIG, SET_EFFECT_MODE, DIRECT})

MODE_DIRECT = 0xFF
DIRECT_APPLY = 0x80
LEDS_PER_PACKET = 20
MAX_LEDS = 255     # stay below the 8-bit offset overflow path

MAINBOARD_DIRECT_CHANNEL = 0x04


class ProtocolError(Exception):
    pass


def _packet(opcode, *payload):
    if opcode not in ALLOWED_OPCODES:
        raise ValueError(f"Aura opcode 0x{opcode:02X} is not allow-listed")
    if len(payload) > REPORT_LEN - 2:
        raise ValueError("payload too long")
    buf = bytearray(REPORT_LEN)
    buf[0] = REPORT_ID
    buf[1] = opcode
    buf[2:2 + len(payload)] = bytes(payload)
    return bytes(buf)


def firmware_query():
    return _packet(REQUEST_FIRMWARE)


def config_query():
    return _packet(REQUEST_CONFIG)


def direct_mode(effect_channel):
    """Switch one effect channel to Direct (software-driven, volatile)."""
    # [ch, 0x00, shutdown_effect=0, mode]
    return _packet(SET_EFFECT_MODE, effect_channel, 0x00, 0x00, MODE_DIRECT)


def direct_frames(direct_channel, colors):
    """Split a zone's colours into 0x40 packets; the last one carries APPLY."""
    n = len(colors)
    if n == 0:
        return []
    if n > MAX_LEDS:
        raise ValueError(f"{n} LEDs exceeds the {MAX_LEDS} LED limit")
    packets = []
    for offset in range(0, n, LEDS_PER_PACKET):
        chunk = colors[offset:offset + LEDS_PER_PACKET]
        cmd = direct_channel
        if offset + len(chunk) >= n:
            cmd |= DIRECT_APPLY
        rgb = [c for color in chunk for c in color]
        packets.append(_packet(DIRECT, cmd, offset, len(chunk), *rgb))
    return packets


def _check_reply(reply, expected):
    if not reply or len(reply) < 2 or reply[0] != REPORT_ID or reply[1] != expected:
        got = reply[:2].hex() if reply else "nothing"
        raise ProtocolError(f"expected reply {REPORT_ID:02x}{expected:02x}, got {got}")


def parse_firmware(reply):
    _check_reply(reply, REPLY_FIRMWARE)
    return bytes(reply[2:18]).split(b"\0", 1)[0].decode("ascii", "replace")


def parse_config(reply):
    """Return (raw_table, layout) from a 0x30 reply.

    layout keys: argb_headers (table[0x02]), mainboard_leds (table[0x1B]),
    rgb_headers (table[0x1D]). Same offsets as OpenRGB's mainboard controller.
    """
    _check_reply(reply, REPLY_CONFIG)
    table = bytes(reply[4:64])
    if len(table) < 0x1E:
        raise ProtocolError("config table too short")
    mainboard = table[0x1B]
    rgb_headers = table[0x1D]
    if mainboard < rgb_headers:
        rgb_headers = 0
    return table, {"argb_headers": table[0x02], "mainboard_leds": mainboard, "rgb_headers": rgb_headers}
