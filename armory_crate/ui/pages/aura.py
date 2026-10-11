"""Aura Sync page, laid out like Armoury Crate: effect modes on the left, a live
preview of the lit devices on the right. All hardware access goes through
armory-crated over D-Bus; the preview uses the daemon's own render code."""

import json
import math
import time

import gi

gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

from ...aura import client, effects, registry  # noqa: E402
from ...daemon.service import BUS_NAME  # noqa: E402
from ..widgets.common import scrolled_page  # noqa: E402
from ..widgets.graph import rect, rgba  # noqa: E402
from ..widgets.icons import LineIcon  # noqa: E402
from ..widgets.rog import Panel  # noqa: E402

KIND_ICONS = {"motherboard": "cpu", "monitor": "system", "virtual": "aura"}
STATUS_TEXT = {"ok": "SYNCED", "busy": "IN USE", "no-access": "NO ACCESS", "error": "ERROR",
               "unsupported": "NOT CONTROLLED", "disconnected": "OFFLINE"}
VIRTUAL_BADGE = "VIRTUAL"
EFFECT_KEYS = list(effects.EFFECTS)
DEBOUNCE_MS = 150
SWATCHES = ["#ff1a2e", "#ff7a00", "#ffd400", "#3cff3c", "#00e5ff", "#1f5bff", "#b026ff", "#ffffff"]

FAN_LEDS = 12          # LEDs drawn per preview fan
STRIP_LEDS = 30
PREVIEW_FANS = 3


def rgba_to_hex(c):
    return effects.to_hex(tuple(round(x * 255) for x in (c.red, c.green, c.blue)))


def hex_to_rgba(color):
    c = Gdk.RGBA()
    c.parse(color)
    return c


def _pt(x, y):
    return Graphene.Point().init(x, y)


class AuraScene(Gtk.Widget):
    """Live preview of the lit setup: hub-mirrored ARGB fans, an LED strip and,
    when connected, the TT LCD — like Armoury Crate's device preview."""

    def __init__(self, get_effect, t0):
        super().__init__(hexpand=True, height_request=300)
        self.add_css_class("ac-scene")
        self.get_effect, self.t0 = get_effect, t0
        self.show_lcd = False
        # Redrawing on every display tick (uncapped - could be 60-240Hz depending on the monitor) sends a
        # continuous stream of GSK buffer swaps with no benefit: this is an ambient lighting preview, not
        # something that needs native refresh rate. Capped to the same 30 fps the hardware writer already
        # uses (RGBDevice.max_fps), which is also kinder to the GPU driver during long sessions.
        self._last_draw_us = 0
        self.add_tick_callback(self._on_tick)

    def _on_tick(self, widget, frame_clock):
        now_us = frame_clock.get_frame_time()
        if now_us - self._last_draw_us >= 1_000_000 // 30:
            self._last_draw_us = now_us
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _color(self, effect, t, x):
        r, g, b = effects.render(effect, t, x)
        return r / 255, g / 255, b / 255

    def _ring(self, snapshot, effect, t, cx, cy, r, width, glow):
        seg = 360 / FAN_LEDS
        stroke = Gsk.Stroke.new(width * (2.4 if glow else 1.0))
        stroke.set_line_cap(Gsk.LineCap.BUTT)
        for i in range(FAN_LEDS):
            a0, a1 = math.radians(i * seg - 90 + 1.5), math.radians((i + 1) * seg - 90 - 1.5)
            b = Gsk.PathBuilder.new()
            b.move_to(cx + r * math.cos(a0), cy + r * math.sin(a0))
            b.svg_arc_to(r, r, 0, False, True, cx + r * math.cos(a1), cy + r * math.sin(a1))
            col = self._color(effect, t, i / FAN_LEDS)
            snapshot.append_stroke(b.to_path(), stroke, rgba(*col, 0.55 if glow else 1.0))

    def _fan(self, snapshot, effect, t, cx, cy, r):
        frame = Gsk.PathBuilder.new()
        frame.add_rect(Graphene.Rect().init(cx - r * 1.18, cy - r * 1.18, r * 2.36, r * 2.36))
        snapshot.append_stroke(frame.to_path(), Gsk.Stroke.new(1.0), rgba(1, 1, 1, 0.10))
        hub = Gsk.PathBuilder.new()
        hub.add_circle(_pt(cx, cy), r * 0.22)
        snapshot.append_fill(hub.to_path(), Gsk.FillRule.WINDING, rgba(0.14, 0.14, 0.16))
        blades = Gsk.PathBuilder.new()
        spin = t * 2.2
        for k in range(7):
            a = spin + k * 2 * math.pi / 7
            x0, y0 = cx + r * 0.24 * math.cos(a), cy + r * 0.24 * math.sin(a)
            a1 = a + 0.9
            x1, y1 = cx + r * 0.78 * math.cos(a1), cy + r * 0.78 * math.sin(a1)
            blades.move_to(x0, y0)
            blades.quad_to(cx + r * 0.8 * math.cos(a + 0.2), cy + r * 0.8 * math.sin(a + 0.2), x1, y1)
        snapshot.append_stroke(blades.to_path(), Gsk.Stroke.new(2.0), rgba(1, 1, 1, 0.16))

    def _label(self, snapshot, text, cx, y):
        layout = self.create_pango_layout(text)
        _ink, logical = layout.get_pixel_extents()
        snapshot.save()
        snapshot.translate(_pt(cx - logical.width / 2, y))
        snapshot.append_layout(layout, rgba(0.55, 0.55, 0.59))
        snapshot.restore()

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        if w <= 0 or h <= 0:
            return
        effect = self.get_effect()
        t = time.monotonic() - self.t0
        lcd_w = w * 0.22 if self.show_lcd else 0
        fan_area = w - lcd_w
        r = min(h * 0.24, fan_area / (PREVIEW_FANS * 2.9))
        cy = h * 0.40
        xs = [fan_area * (i + 0.5) / PREVIEW_FANS for i in range(PREVIEW_FANS)]
        strip_y, strip_x0, strip_x1 = h * 0.80, w * 0.06, w * 0.94
        cell = (strip_x1 - strip_x0) / STRIP_LEDS
        lcd_cx, lcd_r = fan_area + lcd_w / 2, min(lcd_w * 0.38, h * 0.22)

        for x in xs:
            self._fan(snapshot, effect, t, x, cy, r)

        def lights(glow):
            for x in xs:
                self._ring(snapshot, effect, t, x, cy, r * 0.95, r * 0.13, glow)
            for j in range(STRIP_LEDS):
                col = self._color(effect, t, j / STRIP_LEDS)
                pad = 1 if not glow else -3
                snapshot.append_color(rgba(*col, 0.6 if glow else 1.0),
                                      rect(strip_x0 + j * cell + pad, strip_y - (8 if glow else 3),
                                           cell - 2 * pad, 16 if glow else 6))
            if self.show_lcd:
                disc = Gsk.PathBuilder.new()
                disc.add_circle(_pt(lcd_cx, cy), lcd_r)
                col = self._color(effect, t, 0.5)
                snapshot.append_fill(disc.to_path(), Gsk.FillRule.WINDING, rgba(*col, 0.35 if glow else 0.22))
                ring = Gsk.PathBuilder.new()
                ring.add_circle(_pt(lcd_cx, cy), lcd_r)
                snapshot.append_stroke(ring.to_path(), Gsk.Stroke.new(3.0 if not glow else 8.0),
                                       rgba(*col, 0.5 if glow else 1.0))

        snapshot.push_blur(14)
        lights(glow=True)
        snapshot.pop()
        lights(glow=False)

        self._label(snapshot, "ARGB HEADER · HUB (MIRRORED)", fan_area / 2, cy + r * 1.3 + 6)
        self._label(snapshot, "LED STRIP", w / 2, strip_y + 14)
        if self.show_lcd:
            self._label(snapshot, "TT LCD", lcd_cx, cy + lcd_r + 12)


class EffectRow(Gtk.ListBoxRow):
    def __init__(self, name):
        super().__init__()
        self.effect_name = name
        box = Gtk.Box(spacing=14)
        box.append(LineIcon(name, 22))
        label = Gtk.Label(label=effects.EFFECTS[name].upper(), xalign=0, hexpand=True)
        label.add_css_class("ac-effect-label")
        box.append(label)
        self.set_child(box)


class AuraPage(Gtk.Box):
    title = "Aura Sync"

    def __init__(self, sampler=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.proxy = None
        self.state = None
        self.effect = effects.Effect()
        self._updating = False
        self._pending = 0
        self._device_sig = None
        self._zone_spins = {}
        self._zone_pending = {}
        self._t0 = time.monotonic()

        self.banner = Adw.Banner(title="AURA SERVICE IS NOT RUNNING", button_label="Start service")
        self.banner.connect("button-clicked", self._start_service)
        self.append(self.banner)

        # Effects / Sync devices tabs, like Armoury Crate's Aura Sync header
        self.tabs = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        switcher = Gtk.StackSwitcher(stack=self.tabs, halign=Gtk.Align.START)
        switcher.add_css_class("ac-tabs")

        # --- effects tab -------------------------------------------------
        self.effect_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.effect_list.add_css_class("ac-effects")
        self.effect_rows = {}
        for name in EFFECT_KEYS:
            row = EffectRow(name)
            self.effect_rows[name] = row
            self.effect_list.append(row)
        self.effect_list.connect("row-selected", self._on_control_changed)
        modes = Panel("Basic effects")
        modes.append(self.effect_list)
        modes.set_size_request(300, -1)
        modes.set_hexpand(False)   # the title label's hexpand would otherwise spread to the panel
        modes.set_valign(Gtk.Align.START)

        self.scene = AuraScene(lambda: self.effect, self._t0)
        preview = Panel("Preview")
        preview.append(self.scene)

        self.settings = Panel("Settings")
        self.color_rows, self.color_buttons, self.swatch_buttons = [], [], []
        for i in range(2):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            label = Gtk.Label(label=f"COLOR {i + 1}", xalign=0)
            label.add_css_class("ac-meter-label")
            row.append(label)
            line = Gtk.Box(spacing=6)
            swatches = []
            for hexc in SWATCHES:
                b = Gtk.Button(tooltip_text=hexc)
                b.add_css_class("ac-swatch")
                prov = Gtk.CssProvider()
                prov.load_from_string(f"button {{ background: {hexc}; }}")
                b.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
                b.connect("clicked", self._on_swatch, i, hexc)
                line.append(b)
                swatches.append((hexc, b))
            custom = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER,
                                           tooltip_text="Custom colour", margin_start=8)
            custom.add_css_class("ac-color-button")
            custom.connect("notify::rgba", self._on_control_changed)
            line.append(custom)
            row.append(line)
            self.settings.append(row)
            self.color_rows.append(row)
            self.color_buttons.append(custom)
            self.swatch_buttons.append(swatches)
        self.speed = self._scale(0.25, 4.0, 0.25, 2)
        self.speed_row = self._setting("Speed", self.speed)
        self.brightness = self._scale(0, 100, 5, 0)
        self.brightness_row = self._setting("Brightness", self.brightness)
        dir_box = Gtk.Box()
        self.dir_fwd = Gtk.ToggleButton(label="→ FORWARD", active=True)
        self.dir_rev = Gtk.ToggleButton(label="← REVERSE", group=self.dir_fwd)
        for b in (self.dir_fwd, self.dir_rev):
            b.add_css_class("ac-segment")
            b.connect("toggled", self._on_control_changed)
            dir_box.append(b)
        self.direction_row = self._setting("Direction", dir_box)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True)
        right.append(preview)
        right.append(self.settings)
        effects_tab = Gtk.Box(spacing=14)
        effects_tab.append(modes)
        effects_tab.append(right)
        self.tabs.add_titled(effects_tab, "effects", "AURA EFFECTS")

        # --- sync devices tab --------------------------------------------
        self.devices_panel = Panel("Sync devices")
        note = Gtk.Label(wrap=True, xalign=0, label=(
            "Only devices with a verified protocol are controlled. Colours are never saved to device "
            "flash — a power cycle restores the hardware default."))
        note.add_css_class("ac-dim")
        self.devices_panel.append(note)
        self.device_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.device_list.add_css_class("boxed-list")
        self.devices_panel.append(self.device_list)
        self.devices_panel.set_valign(Gtk.Align.START)
        self.tabs.add_titled(self.devices_panel, "devices", "SYNC DEVICES")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.append(switcher)
        body.append(self.tabs)
        self.append(scrolled_page(body, "Aura Sync", "One lighting effect, synced across your devices"))
        self._apply_effect_to_controls(self.effect)
        self._show_disconnected()
        Gio.bus_watch_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
                           self._on_name_appeared, self._on_name_vanished)

    # -- widgets ---------------------------------------------------------
    def _setting(self, title, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label=title.upper(), xalign=0)
        label.add_css_class("ac-meter-label")
        row.append(label)
        widget.set_halign(Gtk.Align.FILL if isinstance(widget, Gtk.Scale) else Gtk.Align.START)
        row.append(widget)
        self.settings.append(row)
        return row

    def _scale(self, lo, hi, step, digits):
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_digits(digits)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_hexpand(True)
        scale.connect("value-changed", self._on_control_changed)
        return scale

    def _on_swatch(self, _button, index, hexc):
        self.color_buttons[index].set_rgba(hex_to_rgba(hexc))   # fires _on_control_changed

    def _mark_swatches(self):
        for i, swatches in enumerate(self.swatch_buttons):
            current = rgba_to_hex(self.color_buttons[i].get_rgba())
            for hexc, b in swatches:
                if hexc == current:
                    b.add_css_class("selected")
                else:
                    b.remove_css_class("selected")

    # -- controls <-> effect --------------------------------------------
    def _selected_effect(self):
        row = self.effect_list.get_selected_row()
        return row.effect_name if row else self.effect.name

    def _apply_effect_to_controls(self, e):
        self._updating = True
        try:
            self.effect_list.select_row(self.effect_rows[e.name])
            for i, btn in enumerate(self.color_buttons):
                btn.set_rgba(hex_to_rgba(e.colors[i] if i < len(e.colors) else e.colors[-1]))
            self.speed.set_value(e.speed)
            self.brightness.set_value(e.brightness)
            (self.dir_rev if e.direction == "reverse" else self.dir_fwd).set_active(True)
        finally:
            self._updating = False
        self._update_visibility()

    def _effect_from_controls(self):
        return effects.Effect(name=self._selected_effect(),
                              colors=[rgba_to_hex(b.get_rgba()) for b in self.color_buttons],
                              speed=self.speed.get_value(), brightness=int(self.brightness.get_value()),
                              direction="reverse" if self.dir_rev.get_active() else "forward")

    def _update_visibility(self):
        name = self._selected_effect()
        self.color_rows[0].set_visible(name in ("static", "breathing", "strobe", "color_cycle"))
        self.color_rows[1].set_visible(name == "color_cycle")
        self.speed_row.set_visible(name in effects.ANIMATED)
        self.brightness_row.set_visible(name != "off")
        self.direction_row.set_visible(name == "rainbow_wave")
        self.settings.set_visible(name != "off")
        self._mark_swatches()

    def _on_control_changed(self, *args):
        if self._updating:
            return
        if args and isinstance(args[0], Gtk.ToggleButton) and not args[0].get_active():
            return  # the other half of the radio pair fires too
        self._update_visibility()
        self.effect = self._effect_from_controls()
        self.effect.validate()
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(DEBOUNCE_MS, self._send_effect)

    def _send_effect(self):
        self._pending = 0
        if self.proxy:
            self._call(client.set_effect, self.effect.to_dict())
        return GLib.SOURCE_REMOVE

    # -- daemon connection ----------------------------------------------
    def _set_controls_sensitive(self, sensitive):
        self.effect_list.set_sensitive(sensitive)
        self.settings.set_sensitive(sensitive)

    def _on_name_appeared(self, conn, name, owner):
        self.proxy = client.connect()
        if not self.proxy:
            return
        self.proxy.connect("g-signal", self._on_signal)
        self.banner.set_revealed(False)
        self._set_controls_sensitive(True)
        try:
            self._on_state(client.get_state(self.proxy))
        except GLib.Error as e:
            self._toast(client.error_message(e))

    def _on_name_vanished(self, conn, name):
        self.proxy = None
        self._show_disconnected()

    def _on_signal(self, proxy, sender, signal, params):
        if signal == "StateChanged":
            self._on_state(json.loads(params.unpack()[0]))

    def _show_disconnected(self):
        self.banner.set_revealed(True)
        self._set_controls_sensitive(False)
        # Still list what is plugged in (pure sysfs), so the user sees the device inventory.
        devices = []
        for d in registry.build_devices(None):
            s = d.state()
            devices.append({"id": s.id, "name": s.name, "kind": s.kind, "supported": s.supported,
                            "status": s.status if not s.supported else "disconnected",
                            "detail": s.detail if not s.supported else "Start the Aura service to control",
                            "firmware": "", "zones": [], "extra": {}, "enabled": False})
        self._render_devices(devices, connected=False)

    def _on_state(self, state):
        self.state = state
        new = effects.Effect.from_dict(state["effect"])
        if new.to_dict() != self._effect_from_controls().to_dict() and not self._pending:
            self.effect = new
            self._apply_effect_to_controls(new)
        self._render_devices(state["devices"], connected=True)
        self.scene.show_lcd = any(d["kind"] == "virtual" and d["status"] == "ok" and d.get("enabled", True)
                                  for d in state["devices"])

    def _start_service(self, *_):
        proc = Gio.Subprocess.new(["systemctl", "--user", "start", "armory-crated.service"],
                                  Gio.SubprocessFlags.STDERR_PIPE)

        def done(p, res):
            try:
                ok = p.wait_check_finish(res)
            except GLib.Error:
                ok = False
            if not ok:
                self._toast("Could not start armory-crated — run packaging/install.sh first")
        proc.wait_check_async(None, done)

    # -- devices ---------------------------------------------------------
    def _render_devices(self, devices, connected):
        sig = json.dumps([(d["id"], d["status"], d["enabled"], [(z["name"], z["resizable"]) for z in d["zones"]],
                           connected) for d in devices])
        if sig == self._device_sig:
            self._update_zone_values(devices)
            return
        self._device_sig = sig
        self.device_list.remove_all()
        self._zone_spins = {}

        for d in devices:
            subtitle = d.get("detail") or ""
            if d.get("firmware"):
                subtitle = f"Firmware {d['firmware']}" + (f" · {subtitle}" if subtitle else "")
            row = Adw.ActionRow(title=d["name"], subtitle=subtitle, subtitle_lines=2)
            row.add_prefix(LineIcon(KIND_ICONS.get(d["kind"], "aura"), 22))
            if d["kind"] == "virtual":
                tag = Gtk.Label(label=VIRTUAL_BADGE, valign=Gtk.Align.CENTER)
                tag.add_css_class("ac-badge")
                row.add_suffix(tag)
            badge = Gtk.Label(label=STATUS_TEXT.get(d["status"], d["status"].upper()), valign=Gtk.Align.CENTER)
            badge.add_css_class("ac-badge")
            if d["status"] == "ok":
                badge.add_css_class("ok")
            row.add_suffix(badge)
            if d["supported"] and connected and d["status"] == "ok":
                switch = Gtk.Switch(active=d["enabled"], valign=Gtk.Align.CENTER,
                                    tooltip_text="Include in Aura Sync")
                switch.connect("notify::active", self._on_device_toggled, d["id"])
                row.add_suffix(switch)
                row.set_activatable_widget(switch)
            self.device_list.append(row)

            for zi, z in enumerate(d["zones"]):
                if not z["resizable"] or not connected:
                    continue
                spin = Adw.SpinRow.new_with_range(0, z["max_leds"], 1)
                spin.set_title(f"{z['name']} — LED count")
                spin.set_subtitle("Number of LEDs on the connected ARGB strip / fans (0 = off)")
                spin.set_value(z["leds"])
                spin.connect("notify::value", self._on_zone_changed, d["id"], zi)
                self.device_list.append(spin)
                self._zone_spins[(d["id"], zi)] = spin

    def _update_zone_values(self, devices):
        for d in devices:
            for zi, z in enumerate(d["zones"]):
                spin = self._zone_spins.get((d["id"], zi))
                if spin and not spin.has_focus() and spin.get_value() != z["leds"]:
                    self._updating = True
                    spin.set_value(z["leds"])
                    self._updating = False

    def _on_device_toggled(self, switch, _pspec, device_id):
        if self.proxy:
            self._call(client.set_device_enabled, device_id, switch.get_active())

    def _on_zone_changed(self, spin, _pspec, device_id, zone):
        if self._updating or not self.proxy:
            return
        key = (device_id, zone)
        old = self._zone_pending.get(key)
        if old:
            GLib.source_remove(old)

        def send():
            self._zone_pending.pop(key, None)
            self._call(client.set_zone_leds, device_id, zone, int(spin.get_value()))
            return GLib.SOURCE_REMOVE
        self._zone_pending[key] = GLib.timeout_add(400, send)

    def _call(self, fn, *args):
        try:
            fn(self.proxy, *args)
        except GLib.Error as e:
            self._toast(client.error_message(e))

    def _toast(self, text):
        root = self.get_root()
        if root and hasattr(root, "toast"):
            root.toast(text)
