"""armory-crated: the only process that writes to RGB hardware.

Session D-Bus service org.armorycrate.Aura1. Payloads are JSON strings to keep
the interface small and easy to evolve.
"""

import json
import logging
import signal
import sys
from dataclasses import asdict

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .. import config as cfg  # noqa: E402
from ..aura import effects, registry  # noqa: E402
from ..aura.hidraw import discover  # noqa: E402
from ..aura.sync import SyncManager  # noqa: E402

log = logging.getLogger("armory-crated")

BUS_NAME = "org.armorycrate.Aura1"
OBJECT_PATH = "/org/armorycrate/Aura1"
INTERFACE_XML = f"""
<node>
  <interface name="{BUS_NAME}">
    <method name="GetState"><arg type="s" name="state" direction="out"/></method>
    <method name="SetEffect"><arg type="s" name="effect" direction="in"/></method>
    <method name="SetDeviceEnabled">
      <arg type="s" name="device_id" direction="in"/><arg type="b" name="enabled" direction="in"/>
    </method>
    <method name="SetZoneLeds">
      <arg type="s" name="device_id" direction="in"/><arg type="i" name="zone" direction="in"/>
      <arg type="i" name="leds" direction="in"/>
    </method>
    <method name="Rescan"/>
    <signal name="StateChanged"><arg type="s" name="state"/></signal>
  </interface>
</node>
"""

FRAME_MS = 33          # ~30 fps render clock; workers cap per device
HOTPLUG_POLL_S = 3
RETRY_EVERY_POLLS = 10   # retry errored devices every ~30 s
RESUME_DELAY_MS = 2000
KEEPALIVE_S = 1


class AuraService:
    def __init__(self, loop):
        self.loop = loop
        self.config = cfg.load()
        self.sync = None
        self.conn = None
        self._anim_id = 0
        self._keepalive_id = 0
        self._fingerprint = None
        self._polls = 0
        self.start_devices()

    # -- hardware --------------------------------------------------------
    def _enabled_map(self):
        return {did: d.get("enabled", True) for did, d in self.config["devices"].items()}

    def start_devices(self):
        if self.sync:
            self.sync.close_all()
        infos = discover()
        self._fingerprint = self._fp(infos)
        devices = registry.build_devices(self.config, infos)
        self.sync = SyncManager(devices, self._enabled_map())
        self.sync.set_effect(effects.Effect.from_dict(self.config["effect"]))
        self.sync.open_all()
        for d in devices:
            log.info("%s [%s] %s %s", d.name, d.id, d.status, d.detail)
        self.apply()

    @staticmethod
    def _fp(infos):
        return frozenset((i.name, i.vid, i.pid, i.interface) for i in infos)

    def apply(self):
        """Push the current effect; run the animation clock only if needed."""
        for attr in ("_anim_id", "_keepalive_id"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, 0)
        self.sync.tick()
        if self.sync.effect.animated:
            self._anim_id = GLib.timeout_add(FRAME_MS, self._on_frame)
        elif self.sync.needs_keepalive():
            # static effect: refresh only devices that want it (virtual ones), not hardware
            self._keepalive_id = GLib.timeout_add_seconds(KEEPALIVE_S, self._on_keepalive)
        self.emit_state()

    def _on_keepalive(self):
        self.sync.tick(only=lambda d: bool(d.keepalive_s))
        return GLib.SOURCE_CONTINUE

    def _on_frame(self):
        self.sync.tick()
        return GLib.SOURCE_CONTINUE

    def _poll_hotplug(self):
        infos = discover()
        self._polls += 1
        if self._fp(infos) != self._fingerprint:
            log.info("hidraw devices changed; rescanning")
            self.start_devices()
        elif self._polls % RETRY_EVERY_POLLS == 0 and any(
                d.supported and d.status == "error" for d in self.sync.devices):
            # e.g. mouse was switched off while its dongle stayed plugged in.
            log.info("retrying devices in error state")
            self.start_devices()
        return GLib.SOURCE_CONTINUE

    def on_prepare_for_sleep(self, conn, sender, path, iface, signal_name, params):
        (going_to_sleep,) = params.unpack()
        if not going_to_sleep:
            log.info("resumed from sleep; re-applying")
            GLib.timeout_add(RESUME_DELAY_MS, self._after_resume)

    def _after_resume(self):
        self.start_devices()
        return GLib.SOURCE_REMOVE

    # -- state -----------------------------------------------------------
    def state(self):
        devices = []
        for d in self.sync.devices:
            s = asdict(d.state())
            s["enabled"] = cfg.device_settings(self.config, d.id)["enabled"] if d.supported else False
            devices.append(s)
        return {"effect": self.sync.effect.to_dict(), "devices": devices,
                "effects": effects.EFFECTS}

    def emit_state(self):
        if self.conn:
            self.conn.emit_signal(None, OBJECT_PATH, BUS_NAME, "StateChanged",
                                  GLib.Variant("(s)", (json.dumps(self.state()),)))

    def _device(self, device_id):
        for d in self.sync.devices:
            if d.id == device_id:
                return d
        raise KeyError(f"unknown device {device_id}")

    # -- D-Bus -----------------------------------------------------------
    def on_method_call(self, conn, sender, path, iface, method, params, invocation):
        try:
            args = params.unpack()
            if method == "GetState":
                invocation.return_value(GLib.Variant("(s)", (json.dumps(self.state()),)))
                return
            if method == "SetEffect":
                effect = effects.Effect.from_dict(json.loads(args[0]))
                self.sync.set_effect(effect)
                self.config["effect"] = effect.to_dict()
            elif method == "SetDeviceEnabled":
                device_id, enabled = args
                dev = self._device(device_id)
                if not dev.supported:
                    raise PermissionError("device is display-only")
                cfg.device_settings(self.config, device_id)["enabled"] = bool(enabled)
                self.sync.enabled[device_id] = bool(enabled)
            elif method == "SetZoneLeds":
                device_id, zone, leds = args
                dev = self._device(device_id)
                if not hasattr(dev, "resize_zone"):
                    raise ValueError("device has no resizable zones")
                dev.resize_zone(zone, leds)
                cfg.device_settings(self.config, device_id)["argb_leds"][str(zone)] = dev.zones[zone].leds
            elif method == "Rescan":
                # re-read the file: the CLI edits virtual_devices there
                self.config = cfg.load()
                self.start_devices()
                invocation.return_value(None)
                return
            cfg.save(self.config)
            self.apply()
            invocation.return_value(None)
        except Exception as e:
            log.warning("%s failed: %s", method, e)
            invocation.return_dbus_error(f"{BUS_NAME}.Error", str(e))

    def on_bus_acquired(self, conn, name):
        self.conn = conn
        node = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        conn.register_object(OBJECT_PATH, node.interfaces[0], self.on_method_call, None, None)

    def shutdown(self):
        for source in (self._anim_id, self._keepalive_id):
            if source:
                GLib.source_remove(source)
        if self.sync:
            self.sync.close_all()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    loop = GLib.MainLoop()
    service = AuraService(loop)

    def lost(conn, name):
        log.error("could not own %s (already running?)", BUS_NAME)
        loop.quit()

    owner = Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
                             service.on_bus_acquired, None, lost)
    try:
        system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        system_bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                                    "PrepareForSleep", "/org/freedesktop/login1", None,
                                    Gio.DBusSignalFlags.NONE, service.on_prepare_for_sleep)
    except GLib.Error as e:
        log.warning("no system bus, resume handling disabled: %s", e.message)
    GLib.timeout_add_seconds(HOTPLUG_POLL_S, service._poll_hotplug)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, loop.quit)
    loop.run()
    Gio.bus_unown_name(owner)
    service.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
