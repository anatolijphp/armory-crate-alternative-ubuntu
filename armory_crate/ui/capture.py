"""Off-screen page capture for README media and CI screenshots - the same idea as ttlcd's own
--screenshot/--record (TTLcdStudio.exe --record docs/media/<scene>.gif <scene>): render a page
through Gtk.WidgetPaintable + Gsk.Renderer, no cooler/hardware interaction needed and no visible
window beyond what Xvfb (CI) or a real display provides. A bare Adw.Application with its own
application id is used instead of ArmoryCrateApp, so this never touches the tray or a real
instance's D-Bus name.

--screenshot needs nothing extra. --record encodes the captured frames as a GIF with Pillow
(apt install python3-pil / pip install pillow) - not a runtime dependency of the app itself.
"""

import io
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk  # noqa: E402

WIDTH = 1320
HEIGHT = int(os.environ.get("ARMORY_SHOT_HEIGHT", "900"))


def _pump(ms=80):
    """Runs the main loop for ms of real wall-clock time. A widget invalidated by queue_draw()
    (e.g. selecting a row, a tick callback) isn't repainted until the compositor's next frame
    callback arrives asynchronously - draining only already-pending events (ctx.iteration(False)
    in a tight loop) can finish before that callback ever shows up, leaving a stale/empty render
    tree. Confirmed directly: Gtk.Snapshot.to_node() came back None right after selecting an aura
    effect row with the old non-blocking pump, and fixed by actually waiting here instead."""
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def _build_window(page_key):
    from .app import CSS_PATH
    from .window import PAGES, MainWindow

    if not any(k == page_key for k, *_ in PAGES):
        raise SystemExit(f"unknown page {page_key!r}; choices: {', '.join(k for k, *_ in PAGES)}")

    app = Adw.Application(application_id="org.armorycrate.ArmoryCrate.capture")
    app.register()
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    provider = Gtk.CssProvider()
    provider.load_from_path(str(CSS_PATH))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    win = MainWindow(app)
    win.show_page(page_key)
    win.set_default_size(WIDTH, HEIGHT)
    win.present()
    _pump(80)
    return win


def _grab(win):
    widget = win.get_content()
    w, h = widget.get_width(), widget.get_height()
    renderer = win.get_native().get_renderer()
    viewport = Graphene.Rect()
    viewport.init(0, 0, w, h)
    # Still occasionally races the compositor's frame callback even after _pump's wait (the
    # window's own repaint of a just-invalidated widget isn't synchronous), yielding an empty
    # Gtk.Snapshot (to_node() -> None) that render_texture rejects. Retrying with another real
    # wait resolves it in practice; this is capture tooling, not the app's own render path.
    for attempt in range(5):
        snapshot = Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(widget).snapshot(snapshot, w, h)
        node = snapshot.to_node()
        if node is not None:
            return renderer.render_texture(node, viewport)
        _pump(60 * (attempt + 1))
    raise RuntimeError("capture: widget snapshot stayed empty after retrying")


def _aura_scene(win, frame):
    """Cycles the Aura Sync page through a few effects, like ttlcd's own "style" scene cycles
    overlay settings - makes the Aura Sync GIF show the thing that page is actually for."""
    from .pages.aura import EFFECT_KEYS
    if frame % 10:
        return
    page = win.stack.get_child_by_name("aura")
    if page is None:
        return
    key = EFFECT_KEYS[(frame // 10) % len(EFFECT_KEYS)]
    page.effect_list.select_row(page.effect_rows[key])


SCENES = {"aura": _aura_scene}


def screenshot(path, page_key):
    win = _build_window(page_key)
    texture = _grab(win)
    texture.save_to_png(path)
    size = f"{texture.get_width()}x{texture.get_height()}"
    win.destroy()
    print(f"saved {path} ({size})")
    return 0


def record(path, page_key, frames=48, interval_ms=120):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("--record needs Pillow: sudo apt install python3-pil")

    win = _build_window(page_key)
    scene = SCENES.get(page_key)
    images = []
    for i in range(frames):
        if scene:
            scene(win, i)
        _pump(interval_ms)   # also the frame's own timing; see _pump's docstring
        data = _grab(win).save_to_png_bytes()
        images.append(Image.open(io.BytesIO(data.get_data())).convert("RGB"))
    win.destroy()

    # The UI is flat colour, not photographic, so a shared 192-colour palette (built from the
    # first frame, reused for the rest via Image.quantize's default dithering) costs essentially
    # nothing visually and cuts file size by roughly 5-10x versus Pillow's default GIF handling.
    palette = images[0].quantize(colors=192)
    frames_q = [palette] + [im.quantize(colors=192, palette=palette) for im in images[1:]]
    frames_q[0].save(path, save_all=True, append_images=frames_q[1:], duration=interval_ms, loop=0,
                     optimize=True)
    print(f"saved {path} ({len(images)} frames)")
    return 0
