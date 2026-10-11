# Virtual devices: connecting software (e.g. TT LCD) to Aura Sync

A **virtual device** shows up in Aura Sync like any other RGB device, but it has no hardware behind it. On every frame
the engine renders colours for its LEDs, and the virtual device passes them on to another program, which draws them
however it likes. TT LCD Studio, for example, draws them as a visualiser on the cooler's screen.

This page covers:
1. how ttlcd does it on Windows with Armoury Crate (the model followed here)
2. the Linux design for armory-crate
3. step by step: the armory-crate side
4. step by step: the ttlcd side
5. testing, and the safety rules

> **Status (2026-10-11):** both sides are implemented.
> - armory-crate: `armory_crate/aura/virtual_ttas.py`, enabled with `armory-crate virtual add ttlcd`.
> - ttlcd: `AuraState.ReadLinux()` plus the Aura mode in the GTK Studio.
>
> The chain armory-crated → file → ttlcd renderer was verified on this machine. Running it against the LCD itself is
> still to do.
---

## 1. How ttlcd does it on Windows

Source: `ttlcd/aura/AuraHal.cs` (the plugin) and `ttlcd/src/Aura.cs` (reader, renderer, installer).

```
Armoury Crate ─▶ ASUS LightingService (SYSTEM, 32-bit)
                   │ loads COM plugins registered under the Aura HAL category
                   ▼
                 TTLcdAura.dll  (IAacLedDeviceHal → 1 × IAacLedDevice, 8 virtual LEDs)
                   │ SetEffect / SetEffectOptSpeed / Synchronize
                   ▼
                 shared memory  "Global\TTLcdAuraSync"  (layout "TTAS")
                   │ read every frame
                   ▼
                 TT LCD Studio: AuraState.Read() → AuraRender.Render() → 480×480 frame → LCD
```

The main points:

- **Registration.** `ttlcd aura install` registers COM CLSID `{C0C96C60-30E3-4021-9904-966EC4FA0F0F}` under
  `HKLM\SOFTWARE\Classes\CLSID\{109DC3E4-…}\Instance\{E9BBD754-…}\Instance\{CLSID}`. It does this in both registry
  views, with `DeviceType = External`. It then restarts `LightingService`, which creates the object.
- **Capabilities.** `GetCapability()` returns XML describing the device:
  - type `0x64000` (EXTERNAL_GENERAL_RGB_LIGHTING)
  - 8 LEDs in a row
  - the supported effects (Static, Breathing, Strobing, Color cycle, Rainbow)
- **Data path.** Armoury Crate calls `SetEffect(effectId, colors[], n)`. The plugin writes the effect ID, the colours
  and the speed into shared memory. `Synchronize(effectId, ms)` stores a shared clock so the LCD animates in phase with
  other devices.
- **Consumer.** TT LCD Studio reads the block 30 times a second. It animates the effect itself (`AuraRender`), then
  paints the MilkDrop-style visualiser in those colours.
- **Decoupling.** The plugin never touches the LCD and Studio never talks to Armoury Crate. The memory block is the
  only contract between them.

### The `TTAS` block (shared by both sides)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | u32 | magic | `0x53415454` ("TTAS" as bytes) |
| 4 | u32 | seq | change counter (see §3.3 for the Linux rule) |
| 8 | u32 | effectId | 0 Manual, 1 Static, 2 Breathing, 3 Strobing, 4 Color cycle, 5 Rainbow, 0xFF Default |
| 12 | u32 | ledCount | LEDs in `colors` that are valid (≤ 64) |
| 16 | u32 | speed | Aura speed level 0–3 |
| 20 | u32 | direction | 0 = forward |
| 24 | i64 | syncMs | shared animation clock, in ms |
| 32 | i64 | updatedUtcTicks | .NET `DateTime.UtcNow.Ticks`: 100 ns units since 0001-01-01 UTC |
| 40 | u32 × 64 | colors | `0x00BBGGRR`, little-endian, so the bytes are `R G B 00` |

The block is 296 bytes. All values are little-endian.

---

## 2. Linux design

There is no LightingService or COM on Linux. armory-crated already plays the LightingService role: it owns the effect
engine and the shared clock. So the plugin becomes a **driver inside armory-crated**, and the Windows named memory map
becomes a **file in the user's runtime directory** with the same `TTAS` layout:

```
armory-crate UI ─D-Bus─▶ armory-crated (systemd --user)
                           SyncManager.tick()  — one effect, one clock, every device
                           ├─▶ AsusAuraUSB        → /dev/hidraw13 (motherboard + ARGB hub)
                           └─▶ TtasSharedMemory   → $XDG_RUNTIME_DIR/armory-crate/virtual/ttlcd.ttas
                                                       │ read 30×/s
                                                       ▼
                                                    ttlcd run (systemd --user, Mono)
                                                    AuraState.Read() [Linux branch] → AuraRender → LCD
```

Why this design:

| Choice | Reason |
|---|---|
| **Keep the `TTAS` layout** | ttlcd's `AuraSnapshot`, `AuraRender` and its visualiser work unchanged. Only the reader needs a Linux branch. |
| **A file, not D-Bus** | ttlcd's rules say "install nothing", and Mono has no D-Bus without extra packages. Reading a 296-byte file needs only the `System.IO` base class library. |
| **`$XDG_RUNTIME_DIR` (`/run/user/1000`)** | It's tmpfs, so there's no disk I/O. Only this user can access it, and it's cleared at logout. Both services run as the same user, so no permissions or udev rules are involved. |
| **Send finished frames (effect 0, "Manual")** | armory-crated has already worked out every LED colour for this exact moment, including dithering. If ttlcd re-animated a native effect, the LCD would run on its own clock and drift from the fans. In Manual mode, `AuraRender` uses the colours as they are, so the LCD matches the motherboard frame for frame. |
| **A built-in driver, not a plugin folder** | The daemon is the one process allowed near the hardware. Loading arbitrary Python from a folder would let any file in it run inside that process. New virtual drivers are added to the source tree and reviewed like the hardware drivers. |

---

## 3. The armory-crate side

### 3.1 The driver contract

Every device, real or virtual, subclasses `RGBDevice` (`armory_crate/aura/device.py`):

| Member | What a virtual device does |
|---|---|
| `kind` | `"virtual"` (the UI shows it with its own icon) |
| `supported` | `True`. It is controllable. |
| `max_fps` | 30. The worker thread caps writes to this rate. |
| `zones` | e.g. `[Zone("LCD", 8)]`. The LED count decides how many colours are produced. |
| `open()` | Create or attach the output (the file below). It must not touch `/dev`. |
| `probe()` | Check that the output works, then set `status = "ok"`. The read-only-first rule is satisfied trivially. |
| `set_frame(frame)` | `frame[zone][led] = (r, g, b)`. Publish it. It runs on the device's own worker thread. |
| `reset_direct()` | Clear any "last sent" cache (called after resume or a rescan). |
| `close()` | Mark the output inactive and release it. |

### 3.2 Configuration

The quick way is `armory-crate virtual add ttlcd`, which adds the preset below and rescans the daemon. Remove it again
with `armory-crate virtual remove ttlcd`, and list entries with `armory-crate virtual list`. The CLI saves the change to
`~/.config/armory-crate/config.json`. The daemon's `Rescan` method re-reads that file. Virtual devices aren't
discovered automatically, because there's no hardware to find:

```json
"virtual_devices": [
  {
    "id": "virtual:ttlcd",
    "driver": "ttas-shm",
    "name": "TT LCD CL-W383",
    "leds": 8,
    "file": "ttlcd.ttas"
  }
]
```

- `file` is relative to `$XDG_RUNTIME_DIR/armory-crate/virtual/`. Absolute paths and `..` are rejected, so the daemon
  can only write inside that folder.
- `leds` must be 1–64, the `TTAS` limit. Use 8 to match the Windows plugin. ttlcd blends between LEDs along its
  waveform, so the count changes how much colour detail the LCD shows, not its size.
- Per-device enable and disable work as for hardware, under `devices["virtual:ttlcd"].enabled`.

### 3.3 Writing the block (the Linux seq rule)

On Windows the writer only increments `seq` after writing, so a reader can still catch a half-written block. On Linux
the writer uses a proper **seqlock**:

1. `seq += 1`, which makes it **odd**: "write in progress".
2. Write every field, with the colours last.
3. `seq += 1`, which makes it **even** again: "complete".

The reader accepts a snapshot only if `seq` is even and the same before and after reading (§4.2).

Other writer rules:
- **Create the file in place and never replace it.** Open it with `O_RDWR | O_CREAT`, mode `0600`, and extend it with
  `ftruncate` only if it's smaller than 296 bytes. Never delete and recreate it while running. The reader keeps
  reopening the same path, so it reattaches on its own after a daemon restart, just as the Windows plugin reattaches
  to its existing memory block.
- **On `close()`:** write magic = 0 inside a seq update. ttlcd then shows *"Waiting for Armoury Crate / Aura Sync"*
  instead of a frozen last frame.
- **Keepalive:** the timestamp must keep advancing at least once a second, even for a static effect. After 30 s
  without an update, ttlcd's `AuraRender` labels the stream "(no recent updates)".

### 3.4 Reference driver: `armory_crate/aura/virtual_ttas.py`

```python
"""Virtual Aura device: publishes each frame as a TTAS block for TT LCD Studio (Linux)."""

import mmap
import os
import struct
import time

from .device import RGBDevice, Zone

MAGIC = 0x53415454                  # "TTAS"
MAX_LEDS = 64
SIZE = 40 + MAX_LEDS * 4            # 296 bytes
EFFECT_MANUAL = 0                   # colours are final frames; ttlcd draws them as-is
DOTNET_EPOCH_TICKS = 621355968000000000   # DateTime(1970-01-01).Ticks


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        raise RuntimeError("XDG_RUNTIME_DIR is not set")
    path = os.path.join(base, "armory-crate", "virtual")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


class TtasSharedMemory(RGBDevice):
    kind = "virtual"
    max_fps = 30
    keepalive_s = 1.0               # see §3.5

    def __init__(self, device_id, name, leds, file):
        super().__init__(info=None, device_id=device_id, name=name)
        if not 1 <= leds <= MAX_LEDS:
            raise ValueError(f"leds must be 1..{MAX_LEDS}")
        if os.path.isabs(file) or os.sep in file or file.startswith("."):
            raise ValueError("file must be a plain name inside the virtual/ folder")
        self.zones = [Zone("LCD", leds)]
        self.file = file
        self.fd = self.view = None
        self.t0 = time.monotonic()

    def open(self):
        path = os.path.join(runtime_dir(), self.file)
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        if os.fstat(self.fd).st_size < SIZE:
            os.ftruncate(self.fd, SIZE)          # grow only; never truncate a live block
        self.view = mmap.mmap(self.fd, SIZE)

    def probe(self):
        self._publish([(0, 0, 0)] * self.zones[0].leds)
        self.status, self.detail = "ok", f"→ {os.path.join(runtime_dir(), self.file)}"

    def set_frame(self, frame):
        self._publish(frame[0][:self.zones[0].leds])

    def _publish(self, colors, magic=MAGIC):
        v = self.view
        seq = struct.unpack_from("<I", v, 4)[0]
        if seq & 1:                               # left odd by a crash: realign
            seq += 1
        struct.pack_into("<I", v, 4, (seq + 1) & 0xFFFFFFFF)          # odd: writing
        ticks = DOTNET_EPOCH_TICKS + int(time.time() * 10_000_000)
        sync_ms = int((time.monotonic() - self.t0) * 1000)
        struct.pack_into("<IIIIIIqq", v, 0, magic, (seq + 1) & 0xFFFFFFFF, EFFECT_MANUAL,
                         len(colors), 0, 0, sync_ms, ticks)
        packed = bytearray(MAX_LEDS * 4)
        for i, (r, g, b) in enumerate(colors):
            packed[i * 4:i * 4 + 3] = bytes((r, g, b))               # 0x00BBGGRR little-endian
        v[40:SIZE] = bytes(packed)
        struct.pack_into("<I", v, 4, (seq + 2) & 0xFFFFFFFF)          # even: complete

    def close(self):
        if self.view is not None:
            self._publish([], magic=0)            # reader shows "waiting for Aura"
            self.view.close()
            os.close(self.fd)
            self.view = self.fd = None
```

### 3.5 Wiring it in (the changes in armory-crate)

| File | Change |
|---|---|
| `aura/virtual_ttas.py` | New: the driver above. |
| `aura/registry.py` | Add `VIRTUAL_DRIVERS = {"ttas-shm": TtasSharedMemory}`. In `build_devices()`, after the hidraw devices, add one driver per `config["virtual_devices"]` entry. **Only names listed in `VIRTUAL_DRIVERS` are accepted.** An unknown `driver` is logged and skipped. Virtual devices never go through `match()`, and hidraw devices can never be virtual. |
| `daemon/service.py` | Keepalive: in `apply()`, when the effect is not animated but some active device has `keepalive_s`, schedule `GLib.timeout_add_seconds(1, …)` to call `self.sync.tick()`. Animated effects already tick at 30 fps. Hotplug: leave virtual devices out of the hidraw fingerprint. |
| `ui/pages/aura.py` | Add `"virtual": "video-display-symbolic"` to `KIND_ICONS`. |
| `tests/` | Add `test_virtual_ttas.py`. Use a temporary `XDG_RUNTIME_DIR`, call `open()`/`probe()`/`set_frame()`, then parse the file back and check that the magic is right, `seq` is even, the colour bytes are in `R G B 0` order, and `close()` clears the magic. Also check that a `file` containing `..` or `/` is rejected. |

The LCD's LEDs join the shared effect axis after the motherboard zones, so a Rainbow Wave carries on from the ARGB
header onto the LCD. Your ARGB hub mirrors one signal to every fan, so the LCD shows the next slice of the rainbow
after the fans. A later option could be `"placement": "mirror"` in the config, which would render the LCD at the same
positions as ARGB header 1 so it matches the fans exactly.

---

## 4. The ttlcd side (Linux)

Two small changes. Everything else (`AuraRender`, the visualiser, the Studio Aura page) is shared with Windows already.

### 4.1 Allow the mode on Linux: `src/LinuxHid.cs`

Add `Mode.Aura` to `Os.Supports(mode)`. Today it allows Image, Gif, Color, Clock and Off. The GTK Studio then offers
Aura Sync in its mode list, and `Engine` already calls `AuraRender.Render(AuraState.Read(), …)` for it.

### 4.2 Read the file: `src/Aura.cs` → `AuraState.Read()`

Keep the Windows path as it is and add a Linux branch at the top. This is C# 5 for `mcs`, with no new references:

```csharp
// Linux: armory-crated publishes the same TTAS block as a file (see Armory-crate docs/virtual-devices.md).
static string LinuxPath()
{
    string run = Environment.GetEnvironmentVariable("XDG_RUNTIME_DIR");
    return string.IsNullOrEmpty(run) ? null : Path.Combine(run, "armory-crate/virtual/ttlcd.ttas");
}

static byte[] ReadBlock(string path)
{
    // A fresh unbuffered open each time: re-reading through one FileStream could be served from its buffer.
    using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1))
    {
        var buf = new byte[Size];
        int got = 0, n;
        while (got < Size && (n = fs.Read(buf, got, Size - got)) > 0) got += n;
        return got == Size ? buf : null;
    }
}

static AuraSnapshot ReadLinux()
{
    string path = LinuxPath();
    if (path == null || !File.Exists(path)) return null;
    for (int attempt = 0; attempt < 3; attempt++)
    {
        byte[] a, b;
        try { a = ReadBlock(path); b = ReadBlock(path); }
        catch (IOException) { return null; }
        if (a == null || b == null) return null;
        int seq = BitConverter.ToInt32(a, 4);
        if ((seq & 1) != 0 || seq != BitConverter.ToInt32(b, 4)) continue;   // writer was mid-update
        if (BitConverter.ToInt32(a, 0) != 0x53415454) return null;           // not running / closed
        var s = new AuraSnapshot();
        s.Seq = seq;
        s.Effect = BitConverter.ToInt32(a, 8);
        s.LedCount = BitConverter.ToInt32(a, 12);
        s.Speed = BitConverter.ToInt32(a, 16);
        s.Direction = BitConverter.ToInt32(a, 20);
        s.SyncMs = BitConverter.ToInt64(a, 24);
        long ticks = BitConverter.ToInt64(a, 32);
        s.UpdatedUtc = ticks > 0 ? new DateTime(ticks, DateTimeKind.Utc) : DateTime.MinValue;
        Buffer.BlockCopy(a, 40, s.Colors, 0, 64 * 4);
        return s;
    }
    return null;
}

public static AuraSnapshot Read()
{
    if (Os.Linux) return ReadLinux();
    // … existing Windows MemoryMappedFile code unchanged …
}
```

Notes:
- **Effect 0 hits `AuraRender`'s `default:` ("Manual") case.** The colours are used as delivered, and armory-crated
  owns the animation, phase and dithering.
- **`SyncMs` is informational for Manual.** The other cases would use it to stay in phase, which keeps the format
  compatible if a native effect ID is ever sent.
- **No new package and no udev rule.** The file belongs to the same user who runs `ttlcd run`.
- **The Windows path still works.** On Windows, nothing changes: Armoury Crate and `TTLcdAura.dll` stay the source.

### 4.3 Optional: show the source in Studio

On Linux, `AuraRender`'s waiting text could say *"Waiting for armory-crated / Aura Sync"*. `Platform` already knows
the OS.

---

## 5. Testing it end to end

1. **armory-crate:** add the `virtual_devices` entry to the config, then restart the daemon with
   `systemctl --user restart armory-crated`. The Aura page should list **TT LCD CL-W383 · SYNCED**, with a switch.
2. **Inspect the block** without ttlcd:

   ```sh
   python3 - <<'EOF'
   import os, struct
   p = os.path.join(os.environ["XDG_RUNTIME_DIR"], "armory-crate/virtual/ttlcd.ttas")
   b = open(p, "rb").read()
   magic, seq, eff, n = struct.unpack_from("<IIII", b)
   print(hex(magic), "seq", seq, "even" if seq % 2 == 0 else "ODD", "effect", eff, "leds", n)
   print([tuple(b[40 + i*4:43 + i*4]) for i in range(n)])
   EOF
   ```

   Run it twice with Rainbow Wave on: `seq` grows and the colours change. With Static, `seq` still grows once a second
   (the keepalive).
3. **ttlcd:** select Aura Sync in TT LCD Studio (Linux). The status line reads `Aura Sync · Manual · 30 fps` and the
   visualiser follows your fans' colours.
4. **Restart test:** run `systemctl --user restart armory-crated`. The LCD briefly shows "Waiting…" (magic cleared),
   then picks up again by itself. Neither side needs a restart.
5. **Disable test:** turn the device's switch off on the Aura page. The LCD freezes on its last frame and, after 30 s,
   shows "(no recent updates)".

## 6. Safety rules (the same principles as the hardware drivers)

- **Virtual drivers never open `/dev`, never take part in hidraw matching, and need no udev rule.** They can't reach
  any hardware.
- **Writes are limited to `$XDG_RUNTIME_DIR/armory-crate/virtual/`.** File names are validated, and the files have
  mode `0600`.
- **Only drivers listed in the source are accepted.** Nothing is loaded from config or plugin folders.
- **ttlcd only reads.** The Aura mode only streams live frames, as the other ttlcd modes already do. It never uses the
  LCD's on-device file commands. ttlcd's own rules forbid idle and boot uploads to the original firmware, and this
  integration doesn't touch them.

## Adding other virtual devices

Use the same three steps for any other consumer, such as a game overlay, a Home Assistant bridge or a WLED forwarder:
1. Write a driver class that implements the §3.1 contract, publishing frames in whatever form the consumer reads.
2. Register it in `VIRTUAL_DRIVERS` with a short name, and add a unit test that parses the output.
3. Declare an instance under `virtual_devices` in the config.

If the consumer can speak D-Bus (Python, Rust, Qt and so on), a future option is a `Frame` signal on
`org.armorycrate.Aura1`, so no file is needed. ttlcd uses the file route because of its install-nothing rule.
