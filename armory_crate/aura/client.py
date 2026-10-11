"""Thin D-Bus client for armory-crated (used by the CLI and the GUI)."""

import json

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from ..daemon.service import BUS_NAME, OBJECT_PATH  # noqa: E402


def connect():
    """Return a proxy if the daemon owns its name, else None."""
    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
            BUS_NAME, OBJECT_PATH, BUS_NAME, None)
    except GLib.Error:
        return None
    return proxy if proxy.get_name_owner() else None


def _call(proxy, method, sig=None, args=()):
    params = GLib.Variant(sig, args) if sig else None
    return proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, 5000, None)


def get_state(proxy):
    return json.loads(_call(proxy, "GetState").unpack()[0])


def set_effect(proxy, effect):
    _call(proxy, "SetEffect", "(s)", (json.dumps(effect),))


def set_device_enabled(proxy, device_id, enabled):
    _call(proxy, "SetDeviceEnabled", "(sb)", (device_id, enabled))


def set_zone_leds(proxy, device_id, zone, leds):
    _call(proxy, "SetZoneLeds", "(sii)", (device_id, zone, leds))


def rescan(proxy):
    _call(proxy, "Rescan")


def error_message(err):
    """Strip the GDBus remote-error prefix for display."""
    msg = getattr(err, "message", str(err))
    return msg.split(": ", 1)[-1] if msg.startswith("GDBus.Error") else msg
