"""armory-crate CLI: gui (default) | daemon | probe | apply | devices."""

import argparse
import sys
import time


def cmd_devices(args):
    """List hidraw interfaces and how each is classified. Pure sysfs, no I/O to devices."""
    from .aura import registry
    from .aura.hidraw import discover
    for info in discover():
        m = registry.match(info)
        if m:
            verdict = f"SUPPORTED -> {m.driver.__name__}"
        elif (info.vid, info.pid) in registry.UNSUPPORTED:
            verdict = "known, display-only (no verified protocol)"
        else:
            verdict = "ignored"
        page = f"0x{info.usage_page:04X}" if info.usage_page is not None else "-"
        print(f"{info.node:14} {info.vid_pid}  if={info.interface}  page={page:7} {info.product[:40]:40} {verdict}")
    return 0


def cmd_probe(args):
    """Read-only identification of supported devices. Sends query commands only."""
    from . import config as cfg
    from .aura import registry
    from .aura.hidraw import DeviceBusy
    devices = registry.build_devices(cfg.load())
    rc = 0
    for dev in devices:
        where = dev.info.node if dev.info is not None else "(virtual)"
        print(f"== {dev.name} [{dev.id}] {where}")
        if not dev.supported:
            print(f"   not opened: {dev.detail}")
            continue
        try:
            dev.open()
            dev.probe()
        except DeviceBusy as e:
            print(f"   BUSY: {e}")
            rc = 1
            continue
        except PermissionError as e:
            print(f"   NO ACCESS: {e} — run packaging/install.sh (udev rule)")
            rc = 1
            continue
        except Exception as e:
            print(f"   PROBE FAILED (driver disabled): {type(e).__name__}: {e}")
            rc = 1
            continue
        finally:
            dev.close()
        if dev.firmware:
            print(f"   firmware: {dev.firmware}")
        extra = dev.extra()
        if "config_table" in extra:
            table = bytes.fromhex(extra["config_table"])
            for off in range(0, len(table), 6):
                print(f"   cfg[{off:02X}]: {table[off:off + 6].hex(' ')}")
            print(f"   layout: {extra['layout']}")
        if dev.detail:
            print(f"   note: {dev.detail}")
        print(f"   zones: {[(z.name, z.leds) for z in dev.zones]}")
    return rc


def _effect_from_args(args):
    from .aura.effects import Effect
    e = Effect(name=args.effect, colors=args.color or ["#ff0000"], speed=args.speed,
               brightness=args.brightness, direction=args.direction)
    e.colors = [c if c.startswith("#") else "#" + c for c in e.colors]
    e.validate()
    return e


def cmd_apply(args):
    effect = _effect_from_args(args)
    from .aura import client
    proxy = client.connect()
    if proxy is not None:
        client.set_effect(proxy, effect.to_dict())
        print("applied via armory-crated")
        return 0

    from . import config as cfg
    from .aura import registry
    from .aura.sync import SyncManager
    conf = cfg.load()
    sync = SyncManager(registry.build_devices(conf),
                       {k: v.get("enabled", True) for k, v in conf["devices"].items()})
    sync.set_effect(effect)
    sync.open_all()
    for d in sync.devices:
        print(f"{d.name}: {d.status} {d.detail}")
    if not sync.workers:
        print("no controllable devices")
        return 1
    try:
        if effect.animated:
            print("running (Ctrl-C to stop)…")
            while True:
                sync.tick()
                time.sleep(1 / 30)
        else:
            sync.tick()
            time.sleep(0.5)   # let workers flush
    except KeyboardInterrupt:
        pass
    finally:
        sync.close_all()
    return 0


def cmd_virtual(args):
    """Manage software-only Aura devices (docs/virtual-devices.md)."""
    from . import config as cfg
    from .aura import client, registry
    conf = cfg.load()
    entries = conf["virtual_devices"]
    if args.action == "list":
        if not entries:
            print("no virtual devices (presets: " + ", ".join(registry.VIRTUAL_PRESETS) + ")")
        for e in entries:
            print(f"{e.get('id')}  {e.get('driver')}  {e.get('name')}  leds={e.get('leds')}  file={e.get('file')}")
        return 0
    if args.action == "add":
        preset = registry.VIRTUAL_PRESETS.get(args.target)
        if preset is None:
            print(f"unknown preset {args.target!r}; available: {', '.join(registry.VIRTUAL_PRESETS)}")
            return 1
        entry = dict(preset)
        if args.leds is not None:
            entry["leds"] = args.leds
        registry.build_virtual(entry)  # validate before saving
        conf["virtual_devices"] = [e for e in entries if e.get("id") != entry["id"]] + [entry]
    elif args.action == "remove":
        target = args.target if args.target.startswith(registry.VIRTUAL_ID_PREFIX) else registry.VIRTUAL_ID_PREFIX + args.target
        if not any(e.get("id") == target for e in entries):
            print(f"no virtual device {target}")
            return 1
        conf["virtual_devices"] = [e for e in entries if e.get("id") != target]
    cfg.save(conf)
    proxy = client.connect()
    if proxy is not None:
        client.rescan(proxy)
        print(f"{args.action}: done; armory-crated rescanned")
    else:
        print(f"{args.action}: saved; takes effect when armory-crated starts")
    return 0


def main(argv=None):
    from .aura.effects import EFFECTS
    p = argparse.ArgumentParser(prog="armory-crate")
    p.add_argument("--screenshot", nargs=2, metavar=("PATH", "PAGE"),
                   help="render one page off-screen to a PNG and exit (home, aura, cpu, fans, system)")
    p.add_argument("--record", nargs=2, metavar=("PATH", "PAGE"),
                   help="render a short scripted tour of one page off-screen to a GIF and exit")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the window (default)")
    sub.add_parser("daemon", help="run the Aura service (armory-crated)")
    sub.add_parser("devices", help="list hidraw interfaces and their classification")
    sub.add_parser("probe", help="read-only query of supported RGB devices")
    a = sub.add_parser("apply", help="apply an effect (via daemon if running)")
    a.add_argument("--effect", choices=sorted(EFFECTS), default="static")
    a.add_argument("--color", action="append", help="hex colour, repeatable")
    a.add_argument("--speed", type=float, default=1.0)
    a.add_argument("--brightness", type=int, default=100)
    a.add_argument("--direction", choices=("forward", "reverse"), default="forward")
    v = sub.add_parser("virtual", help="manage virtual (software) Aura devices")
    v.add_argument("action", choices=("list", "add", "remove"))
    v.add_argument("target", nargs="?", help="preset to add (e.g. ttlcd) or id to remove")
    v.add_argument("--leds", type=int, help="override the preset's LED count (1-64)")
    args = p.parse_args(argv)
    if args.cmd == "virtual" and args.action != "list" and not args.target:
        p.error("virtual add/remove needs a target")

    if args.screenshot:
        from .ui.capture import screenshot
        return screenshot(*args.screenshot)
    if args.record:
        from .ui.capture import record
        return record(*args.record)

    if args.cmd in (None, "gui"):
        from .ui.app import main as gui_main
        return gui_main()
    if args.cmd == "daemon":
        from .daemon.service import main as daemon_main
        return daemon_main()
    return {"devices": cmd_devices, "probe": cmd_probe, "apply": cmd_apply,
            "virtual": cmd_virtual}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
