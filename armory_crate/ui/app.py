"""GTK4 / libadwaita application entry point (Wayland)."""

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import APP_ID  # noqa: E402

CSS_PATH = Path(__file__).with_name("style.css")


class ArmoryCrateApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None
        self.tray = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Armoury Crate is dark-only.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        # Above USER priority: Ubuntu's Yaru-patched libadwaita loads its theme high.
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS_PATH))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

        # The window's own close button only closes the window (MainWindow.close_request hides it -
        # armory-crated keeps running regardless). This "quit" action is the actual way to exit: via
        # Ctrl+Q, the tray icon's menu (below), and the app's menubar registration (so a real global-menu
        # setup can show "Quit Armory Crate" too - though the one GNOME Shell extension available here
        # doesn't actually read it, see window.py).
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_a: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])
        menu = Gio.Menu()
        menu.append("Quit Armory Crate", "app.quit")
        self.set_menubar(menu)

        from .tray import TrayIcon
        self.tray = TrayIcon(self.get_dbus_connection(), on_show=self.activate, on_quit=self.quit)

    def do_activate(self):
        if self.window is None:
            from .window import MainWindow
            self.window = MainWindow(self)
        self.window.present()


def main():
    return ArmoryCrateApp().run(sys.argv[:1])
