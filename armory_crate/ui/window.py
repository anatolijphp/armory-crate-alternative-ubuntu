"""Main window: Armoury-Crate-style title bar and collapsible navigation rail."""

from gi.repository import Adw, GLib, Gtk

from .. import __version__
from .pages.aura import AuraPage
from .pages.cpu import CpuPage
from .pages.fans import FansPage
from .pages.home import HomePage
from .pages.system import SystemPage
from .sampler import Sampler
from .widgets.icons import LineIcon
from .widgets.rog import Slash

PAGES = [
    ("home", "Home", "home", HomePage),
    ("aura", "Aura Sync", "aura", AuraPage),
    ("fans", "Fan Xpert", "fan", FansPage),
    ("cpu", "CPU", "cpu", CpuPage),
    ("system", "System Info", "system", SystemPage),
]

RAIL_EXPANDED = 232
RAIL_COLLAPSED = 64
RAIL_ANIM_MS = 140


class NavRail(Gtk.Box):
    """Sidebar that animates between full width and an icon-only rail."""

    def __init__(self, on_select):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("ac-rail")
        self.on_select = on_select
        self.collapsed = False
        self.labels = []
        self.set_size_request(RAIL_EXPANDED, -1)

        # Small, left-aligned icon button - like ttlcd's own nav toggle (IconButton, Halign.Start, fixed
        # size), not stretched across the rail's width. The icon is centered in the button's own box
        # (the button's hover/focus outline is that box, so an off-center icon - e.g. the old manual
        # 18px start margin, carried over from the full-width version - made the outline look shifted
        # relative to it); the button itself, not the icon, carries the left inset.
        menu_icon = LineIcon("menu", 20)
        self.menu_button = Gtk.Button(child=menu_icon, tooltip_text="Collapse navigation",
                                       halign=Gtk.Align.START, margin_start=11,
                                       margin_top=12, margin_bottom=4)
        self.menu_button.add_css_class("flat")
        self.menu_button.add_css_class("ac-menu-button")
        self.menu_button.connect("clicked", lambda *_: self.toggle())
        self.append(self.menu_button)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, vexpand=True)
        self.listbox.add_css_class("ac-nav")
        for key, title, icon, _cls in PAGES:
            box = Gtk.Box(spacing=16)
            box.append(LineIcon(icon, 22))
            label = Gtk.Label(label=title.upper(), xalign=0)
            label.add_css_class("ac-nav-label")
            box.append(label)
            self.labels.append(label)
            row = Gtk.ListBoxRow(child=box, tooltip_text=title)
            row.page_key = key
            self.listbox.append(row)
        self.listbox.connect("row-activated", lambda _lb, row: self.on_select(row.page_key))
        self.append(self.listbox)

        self.footer = Gtk.Label(label=f"v{__version__} · view-only monitoring", xalign=0)
        self.footer.add_css_class("ac-sidebar-footer")
        self.append(self.footer)
        self.labels.append(self.footer)

        # Adw.TimedAnimation ties its callback to the GTK frame clock, which - measured directly on this
        # machine - ticks irregularly during this exact animation (alternating ~4ms and ~16ms gaps within
        # one run, not a steady vsync-locked cadence). Irregular timing reads as jerky even though every
        # individual step is cheap. ttlcd's own collapsible nav (same cubic ease, a plain fixed-interval
        # GLib timeout instead) is visibly smoother on this same machine/GPU - so the frame clock itself,
        # not per-step cost, looks like the actual culprit. This ports that same proven approach.
        self._anim_id = 0
        self._anim_from = 1.0
        self._anim_to = 1.0
        self._anim_start_us = 0
        self._progress = 1.0   # 1 = expanded, 0 = collapsed
        self._update_tooltips()

    def select(self, key):
        for i, (k, *_rest) in enumerate(PAGES):
            if k == key:
                self.listbox.select_row(self.listbox.get_row_at_index(i))

    def set_collapsed(self, collapsed, animate=True):
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        self.menu_button.set_tooltip_text("Expand navigation" if collapsed else "Collapse navigation")
        if not collapsed:
            for label in self.labels:
                label.set_visible(True)
        self._anim_from = self._progress
        self._anim_to = 0.0 if collapsed else 1.0
        if self._anim_id:
            GLib.source_remove(self._anim_id)
            self._anim_id = 0
        if animate:
            self._anim_start_us = GLib.get_monotonic_time()
            self._anim_id = GLib.timeout_add(15, self._on_tick)
        else:
            self._progress = self._anim_to
            self._apply(self._progress)
            self._on_anim_done()
        self._update_tooltips()

    def toggle(self):
        self.set_collapsed(not self.collapsed)

    def _on_tick(self):
        elapsed_ms = (GLib.get_monotonic_time() - self._anim_start_us) / 1000
        k = min(1.0, elapsed_ms / RAIL_ANIM_MS)
        e = 4 * k * k * k if k < 0.5 else 1 - pow(-2 * k + 2, 3) / 2   # ease-out-cubic, matching ttlcd's
        self._progress = self._anim_from + (self._anim_to - self._anim_from) * e
        self._apply(self._progress)
        if k >= 1.0:
            self._anim_id = 0
            self._on_anim_done()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _apply(self, value):
        width = round(RAIL_COLLAPSED + (RAIL_EXPANDED - RAIL_COLLAPSED) * value)
        self.set_size_request(width, -1)
        # labels fade out quickly so they never squash against the icons
        alpha = max(0.0, min(1.0, (value - 0.35) / 0.65))
        for label in self.labels:
            label.set_opacity(alpha)

    def _on_anim_done(self):
        if self.collapsed:
            for label in self.labels:
                label.set_visible(False)

    def _update_tooltips(self):
        # tooltips only help when the names are hidden
        row = self.listbox.get_first_child()
        while row is not None:
            row.set_has_tooltip(self.collapsed)
            row = row.get_next_sibling()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Armory Crate", default_width=1320, default_height=840)
        self.set_size_request(360, 420)
        self.sampler = Sampler()

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150,
                               hexpand=True)
        for key, title, _icon, cls in PAGES:
            self.stack.add_titled(cls(self.sampler), key, title)

        self.rail = NavRail(self.show_page)

        # one black title bar across the window: wordmark on the left, window controls right. The menu
        # toggle now lives in the nav rail itself, just above the nav items.
        header = Adw.HeaderBar(show_title=False)
        header.add_css_class("ac-titlebar")
        brand = Gtk.Box(spacing=8, margin_start=6)
        brand.append(Slash(width=14, height=18))
        word = Gtk.Label(label="ARMORY CRATE")
        word.add_css_class("ac-wordmark")
        brand.append(word)
        header.pack_start(brand)

        # No visible menu button here by request. The real way to quit is Ctrl+Q (app.quit, registered in
        # app.py - an accelerator, not tied to any button, so this doesn't affect it) or the app.quit
        # D-Bus action directly. The globalmenu@ShiroOSL.github.io GNOME Shell extension's "Quit" item
        # looks like a real app menu but isn't one - it's hardcoded to action "close" -> window.delete(),
        # the same window-manager close request the titlebar X sends, which close_request below turns into
        # a hide either way. There's no way to make that extension call a real app action, with or without
        # a button here - that's an extension limitation, not something this app can fix.

        self.toasts = Adw.ToastOverlay(child=self.stack, hexpand=True)
        self.toasts.add_css_class("ac-content")
        body = Gtk.Box()
        body.append(self.rail)
        body.append(self.toasts)

        view = Adw.ToolbarView(content=body)
        view.add_top_bar(header)
        self.set_content(view)

        # narrow windows: fold the rail to icons automatically
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 820sp"))
        bp.connect("apply", lambda *_: self.rail.set_collapsed(True))
        bp.connect("unapply", lambda *_: self.rail.set_collapsed(False))
        self.add_breakpoint(bp)

        # Closing hides the window instead of quitting: armory-crated (the actual Aura Sync engine) keeps
        # running either way, so this is purely about the control panel. Nothing else holds the GApplication
        # open while hidden - that's deliberate: GApplication's own single-instance D-Bus activation already
        # re-presents this exact window (do_activate below) when the app is launched again from the dock or
        # Activities, with no tray icon needed. (A real tray icon would need a GTK3 Gtk.Menu for
        # AyatanaAppIndicator3's set_menu(), which can't be constructed from a process that's already loaded
        # GTK4 - see the window's own menu button for the in-window alternative.)
        self.connect("close-request", self._on_close_request)

        self.show_page("home")

    def _on_close_request(self, *_a):
        self.set_visible(False)
        return True  # True = handled, don't destroy the window

    def show_page(self, key):
        self.stack.set_visible_child_name(key)
        self.rail.select(key)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))
