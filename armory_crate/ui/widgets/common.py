"""Small helpers shared by pages."""

from gi.repository import Adw, Gtk


def fmt(value, unit, digits=0, missing="—"):
    if value is None:
        return missing
    return f"{value:.{digits}f}{unit}"


class ValueRow(Adw.ActionRow):
    """ActionRow with a right-aligned value label."""

    def __init__(self, title, subtitle=None):
        super().__init__(title=title)
        if subtitle:
            self.set_subtitle(subtitle)
        self.value = Gtk.Label(xalign=1, selectable=True)
        self.value.add_css_class("numeric")
        self.value.add_css_class("dim-label")
        self.add_suffix(self.value)

    def set_value(self, text):
        if self.value.get_label() != text:
            self.value.set_label(text)


def flow_row(children, min_per_line=1, max_per_line=3, spacing=14):
    """A row of roughly-equal widgets (panels, meters, cards) that wraps to fewer per line -
    down to one per line, stacked - as the window narrows, instead of a fixed Gtk.Box/Gtk.Grid
    squeezing everyone into a width that no longer fits. Same FlowBox convention already used for
    fan cards (fans.py's FanCard grid): min/max_children_per_line, column_spacing=row_spacing=14,
    homogeneous=True - reused here for page-level panel grids (home, system, cpu) instead of a
    one-off Gtk.Grid per page."""
    box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=min_per_line,
                      max_children_per_line=max_per_line, column_spacing=spacing, row_spacing=spacing,
                      homogeneous=True)
    for c in children:
        c.set_hexpand(True)
        box.append(c)
    return box


def scrolled_page(child, title=None, subtitle=None):
    """Scrollable page body, optionally headed by an Armoury-Crate-style title."""
    if title:
        from .rog import page_title
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        outer.append(page_title(title, subtitle))
        outer.append(child)
        child = outer
    clamp = Adw.Clamp(maximum_size=1240, tightening_threshold=900, child=child)
    clamp.set_margin_top(22)
    clamp.set_margin_bottom(28)
    clamp.set_margin_start(16)
    clamp.set_margin_end(16)
    sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_child(clamp)
    return sw
