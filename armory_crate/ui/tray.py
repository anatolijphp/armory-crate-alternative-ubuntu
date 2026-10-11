"""System tray icon via the StatusNotifierItem / dbusmenu D-Bus protocols directly - the same category of
approach apps like Docker Desktop (Electron, no GTK) use on Linux. AyatanaAppIndicator3's Python binding
needs a GTK3 Gtk.Menu for its menu, which can't be constructed from a process that's already loaded GTK4
(see window.py's close_request comment) - these two protocols are the thing that binding wraps, and they're
plain D-Bus, so implementing them directly sidesteps the GTK3/GTK4 conflict entirely. Confirmed feasible on
this system: org.kde.StatusNotifierWatcher is live here (that's what Docker's own tray icon registers with).

Menu: Show Armory Crate, an "Aura Sync Effect" submenu (one radio item per effects.EFFECTS key, talking
straight to armory-crated over D-Bus via the same client module the Aura page uses - no GTK involved), and
Quit. Activate (primary click/scroll-click on the icon itself) shows the window. No dynamic icon/status.
"""

from gi.repository import Gio, GLib

from ..aura import client, effects

WATCHER_BUS_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/StatusNotifierItem/Menu"

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <method name="Activate"><arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/></method>
    <method name="Scroll"><arg type="i" name="delta" direction="in"/><arg type="s" name="orientation" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s" name="status"/></signal>
  </interface>
</node>
"""

# com.canonical.dbusmenu, trimmed to what a host needs for a static two-item flat menu: GetLayout (the
# whole tree in one call), Event (click notifications), AboutToShow (always "nothing changed" here since
# this menu never changes), GetGroupProperties (some hosts call this instead of/after GetLayout).
MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parentId"/></signal>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
  </interface>
</node>
"""

ITEM_PROPS = {
    "Category": GLib.Variant("s", "ApplicationStatus"),
    "Id": GLib.Variant("s", "org.armorycrate.ArmoryCrate"),
    "Title": GLib.Variant("s", "Armory Crate"),
    "Status": GLib.Variant("s", "Active"),
    "WindowId": GLib.Variant("i", 0),
    "IconName": GLib.Variant("s", "org.armorycrate.ArmoryCrate"),
    "IconThemePath": GLib.Variant("s", ""),
    "ItemIsMenu": GLib.Variant("b", False),
    "Menu": GLib.Variant("o", MENU_PATH),
    "ToolTip": GLib.Variant("(sa(iiay)ss)", ("org.armorycrate.ArmoryCrate", [], "Armory Crate", "")),
}

MENU_PROPS = {
    "Version": GLib.Variant("u", 3),
    "TextDirection": GLib.Variant("s", "ltr"),
    "Status": GLib.Variant("s", "normal"),
    "IconThemePath": GLib.Variant("as", []),
}

# Item ids in the layout below (0 is always the implicit root). Effect items get one id per key in
# effects.EFFECTS, starting at EFFECT_ID_BASE, in EFFECT_KEYS order.
MENU_SHOW, MENU_EFFECTS, MENU_SEPARATOR, MENU_QUIT = 1, 3, 9, 2
EFFECT_KEYS = list(effects.EFFECTS)
EFFECT_ID_BASE = 10
EFFECT_IDS = {key: EFFECT_ID_BASE + i for i, key in enumerate(EFFECT_KEYS)}
ID_TO_EFFECT = {v: k for k, v in EFFECT_IDS.items()}


def _menu_item_props(label):
    return {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", True),
            "visible": GLib.Variant("b", True)}


def _effect_item_props(key, current, connected):
    state = (1 if key == current else 0) if connected else -1
    return {"label": GLib.Variant("s", effects.EFFECTS[key]), "enabled": GLib.Variant("b", connected),
            "visible": GLib.Variant("b", True), "toggle-type": GLib.Variant("s", "radio"),
            "toggle-state": GLib.Variant("i", state)}


class TrayIcon:
    """Owns the StatusNotifierItem/dbusmenu D-Bus objects. on_show and on_quit are plain callables run on
    the main loop thread (the same one GTK runs on - D-Bus method calls arrive on it already)."""

    def __init__(self, connection, on_show, on_quit):
        self._connection = connection
        self._on_show = on_show
        self._on_quit = on_quit
        self._item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML)
        self._menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML)
        self._item_reg_id = connection.register_object(
            ITEM_PATH, self._item_info.interfaces[0], self._handle_item_call, self._handle_item_get, None)
        self._menu_reg_id = connection.register_object(
            MENU_PATH, self._menu_info.interfaces[0], self._handle_menu_call, self._handle_menu_get, None)
        connection.call(WATCHER_BUS_NAME, WATCHER_PATH, WATCHER_BUS_NAME, "RegisterStatusNotifierItem",
                         GLib.Variant("(s)", (connection.get_unique_name(),)), None,
                         Gio.DBusCallFlags.NONE, -1, None, self._on_registered)

    def _on_registered(self, connection, result):
        try:
            connection.call_finish(result)
        except GLib.Error as e:
            print(f"tray: StatusNotifierWatcher registration failed: {e}")

    # ---- StatusNotifierItem ----
    def _handle_item_get(self, connection, sender, path, interface, prop_name, user_data=None):
        return ITEM_PROPS.get(prop_name)

    def _handle_item_call(self, connection, sender, path, interface, method, params, invocation, user_data=None):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(self._on_show)
        # ContextMenu/Scroll: nothing to do - the host opens Menu itself for ContextMenu.
        invocation.return_value(None)

    # ---- dbusmenu ----
    def _handle_menu_get(self, connection, sender, path, interface, prop_name, user_data=None):
        return MENU_PROPS.get(prop_name)

    def _current_effect(self):
        """Best-effort read of the daemon's current effect, for the submenu's radio marks. Returns
        (name_or_None, connected) - a fresh synchronous call each time, since this only runs when a host
        is about to show the menu (AboutToShow/GetLayout), not on a timer."""
        proxy = client.connect()
        if not proxy:
            return None, False
        try:
            return client.get_state(proxy)["effect"]["name"], True
        except (GLib.Error, KeyError):
            return None, False

    def _flat_item_props(self):
        current, connected = self._current_effect()
        props = {MENU_SHOW: _menu_item_props("Show Armory Crate"),
                 MENU_EFFECTS: {"label": GLib.Variant("s", "Aura Sync Effect"),
                                "children-display": GLib.Variant("s", "submenu"),
                                "enabled": GLib.Variant("b", True), "visible": GLib.Variant("b", True)},
                 MENU_SEPARATOR: {"type": GLib.Variant("s", "separator"), "visible": GLib.Variant("b", True)},
                 MENU_QUIT: _menu_item_props("Quit Armory Crate")}
        for key in EFFECT_KEYS:
            props[EFFECT_IDS[key]] = _effect_item_props(key, current, connected)
        return props

    def _handle_menu_call(self, connection, sender, path, interface, method, params, invocation, user_data=None):
        if method == "GetLayout":
            props = self._flat_item_props()
            effect_children = [GLib.Variant("(ia{sv}av)", (EFFECT_IDS[key], props[EFFECT_IDS[key]], []))
                                for key in EFFECT_KEYS]
            children = [
                GLib.Variant("(ia{sv}av)", (MENU_SHOW, props[MENU_SHOW], [])),
                GLib.Variant("(ia{sv}av)", (MENU_EFFECTS, props[MENU_EFFECTS], effect_children)),
                GLib.Variant("(ia{sv}av)", (MENU_SEPARATOR, props[MENU_SEPARATOR], [])),
                GLib.Variant("(ia{sv}av)", (MENU_QUIT, props[MENU_QUIT], [])),
            ]
            layout = (0, {}, children)
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, layout)))
        elif method == "GetGroupProperties":
            ids = params.unpack()[0]
            props = self._flat_item_props()
            result = [(i, props[i]) for i in ids if i in props]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            props = self._flat_item_props().get(item_id, {})
            invocation.return_value(GLib.Variant("(v)", (props.get(name, GLib.Variant("s", "")),)))
        elif method == "Event":
            item_id, event_id = params.unpack()[0], params.unpack()[1]
            if event_id == "clicked":
                if item_id == MENU_SHOW:
                    GLib.idle_add(self._on_show)
                elif item_id == MENU_QUIT:
                    GLib.idle_add(self._on_quit)
                elif item_id in ID_TO_EFFECT:
                    GLib.idle_add(self._set_effect, ID_TO_EFFECT[item_id])
            invocation.return_value(None)
        elif method == "AboutToShow":
            # needUpdate=True tells the host to re-fetch the whole tree via GetLayout right as this
            # submenu is opening - confirmed on real hardware to tear the just-opened submenu back down
            # immediately (the host's layout-update walk churns through existing items while the submenu
            # popup is on screen). The effect list itself never changes, so there's nothing to re-fetch;
            # the cost is the radio mark can be one GetLayout-cycle stale (reopening the menu picks up any
            # change made elsewhere, e.g. from the main window), which is an acceptable tradeoff here.
            invocation.return_value(GLib.Variant("(b)", (False,)))
        else:
            invocation.return_value(None)

    def _set_effect(self, name):
        proxy = client.connect()
        if not proxy:
            return
        try:
            effect = effects.Effect.from_dict(client.get_state(proxy)["effect"])
            effect.name = name
            effect.validate()
            client.set_effect(proxy, effect.to_dict())
        except (GLib.Error, KeyError, ValueError):
            pass

    def close(self):
        self._connection.unregister_object(self._item_reg_id)
        self._connection.unregister_object(self._menu_reg_id)
