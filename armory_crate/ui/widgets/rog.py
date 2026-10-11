"""Armoury-Crate-style building blocks: chamfered panels, slash headers, arc gauges."""

import math

import gi

gi.require_version("Gsk", "4.0")
from gi.repository import Gsk, Gtk, Pango  # noqa: E402

from .graph import rect, rgba  # noqa: E402

RED = (1.0, 0.10, 0.18)
TRACK = (0.17, 0.17, 0.20)

GAUGE_SWEEP = 240.0          # degrees, opening at the bottom
GAUGE_START = 150.0          # degrees, measured clockwise from +x


class Slash(Gtk.Widget):
    """The red parallelogram used as a heading marker."""

    def __init__(self, width=10, height=16):
        super().__init__(width_request=width, height_request=height, valign=Gtk.Align.CENTER)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        b = Gsk.PathBuilder.new()
        b.move_to(w * 0.45, 0)
        b.line_to(w, 0)
        b.line_to(w * 0.55, h)
        b.line_to(0, h)
        b.close()
        snapshot.append_fill(b.to_path(), Gsk.FillRule.WINDING, rgba(*RED))


def section_title(text, suffix=None):
    box = Gtk.Box(spacing=8)
    box.add_css_class("ac-section-title")
    box.append(Slash())
    label = Gtk.Label(label=text.upper(), xalign=0, hexpand=True)
    label.add_css_class("ac-heading")
    box.append(label)
    if suffix is not None:
        box.append(suffix)
    return box


class Panel(Gtk.Box):
    """Dark panel with chamfered corners and an uppercase slash title."""

    def __init__(self, title=None, suffix=None, spacing=12):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.add_css_class("ac-panel")
        if title:
            self.append(section_title(title, suffix))


def view_only_strip(text):
    box = Gtk.Box(halign=Gtk.Align.FILL)
    box.add_css_class("ac-strip")
    label = Gtk.Label(label=text.upper(), hexpand=True, ellipsize=Pango.EllipsizeMode.END)
    box.append(label)
    return box


def page_title(text, subtitle=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("ac-page-title")
    label = Gtk.Label(label=text.upper(), xalign=0)
    label.add_css_class("ac-title")
    box.append(label)
    bar = Gtk.Box(halign=Gtk.Align.START)
    bar.add_css_class("ac-title-bar")
    box.append(bar)
    if subtitle:
        sub = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        sub.add_css_class("ac-subtitle")
        box.append(sub)
    return box


class _Arc(Gtk.Widget):
    def __init__(self, size):
        super().__init__(width_request=size, height_request=size, halign=Gtk.Align.CENTER)
        self.fraction = 0.0

    def _arc(self, cx, cy, r, start_deg, sweep_deg):
        b = Gsk.PathBuilder.new()
        a0 = math.radians(start_deg)
        a1 = math.radians(start_deg + sweep_deg)
        b.move_to(cx + r * math.cos(a0), cy + r * math.sin(a0))
        b.svg_arc_to(r, r, 0, sweep_deg > 180, True, cx + r * math.cos(a1), cy + r * math.sin(a1))
        return b.to_path()

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        size = min(w, h)
        cx, cy, r = w / 2, h / 2, size / 2 - 8
        track = Gsk.Stroke.new(6.0)
        track.set_line_cap(Gsk.LineCap.BUTT)
        snapshot.append_stroke(self._arc(cx, cy, r, GAUGE_START, GAUGE_SWEEP), track, rgba(*TRACK))

        # tick marks every 10 % of the sweep
        tick = Gsk.Stroke.new(1.5)
        for i in range(11):
            a = math.radians(GAUGE_START + GAUGE_SWEEP * i / 10)
            r0, r1 = r - 9, r - (14 if i % 5 == 0 else 12)
            b = Gsk.PathBuilder.new()
            b.move_to(cx + r0 * math.cos(a), cy + r0 * math.sin(a))
            b.line_to(cx + r1 * math.cos(a), cy + r1 * math.sin(a))
            snapshot.append_stroke(b.to_path(), tick, rgba(1, 1, 1, 0.18))

        frac = max(0.0, min(1.0, self.fraction))
        if frac > 0.002:
            # soft glow under the value arc, then the arc itself
            glow = Gsk.Stroke.new(12.0)
            path = self._arc(cx, cy, r, GAUGE_START, GAUGE_SWEEP * frac)
            snapshot.append_stroke(path, glow, rgba(*RED, 0.18))
            value = Gsk.Stroke.new(6.0)
            value.set_line_cap(Gsk.LineCap.BUTT)
            snapshot.append_stroke(path, value, rgba(*RED))
            # bright tip
            a = math.radians(GAUGE_START + GAUGE_SWEEP * frac)
            snapshot.append_color(rgba(1, 1, 1, 0.9),
                                  rect(cx + r * math.cos(a) - 2, cy + r * math.sin(a) - 2, 4, 4))


class Gauge(Gtk.Box):
    """Arc gauge with centred value/unit and a caption underneath."""

    def __init__(self, caption, unit="", size=132, max_value=100.0, digits=0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER)
        self.add_css_class("ac-gauge")
        self.max_value, self.digits, self.unit = max_value, digits, unit
        self.arc = _Arc(size)
        overlay = Gtk.Overlay(child=self.arc)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER,
                         valign=Gtk.Align.CENTER)
        self.value = Gtk.Label(label="—")
        self.value.add_css_class("ac-gauge-value")
        center.append(self.value)
        self.unit_label = Gtk.Label(label=unit)
        self.unit_label.add_css_class("ac-gauge-unit")
        center.append(self.unit_label)
        overlay.add_overlay(center)
        # caption sits in the open bottom of the arc, like Armoury Crate's dials
        self.caption = Gtk.Label(label=caption.upper(), valign=Gtk.Align.END, halign=Gtk.Align.CENTER)
        self.caption.add_css_class("ac-gauge-caption")
        overlay.add_overlay(self.caption)
        self.append(overlay)

    def set_caption(self, caption):
        if self.caption.get_label() != caption.upper():
            self.caption.set_label(caption.upper())

    def set_value(self, value, unit=None):
        if unit is not None and unit != self.unit_label.get_label():
            self.unit_label.set_label(unit)
        if value is None:
            self.value.set_label("—")
            self.arc.fraction = 0.0
        else:
            self.value.set_label(f"{value:.{self.digits}f}")
            self.arc.fraction = value / self.max_value if self.max_value else 0.0
        self.arc.queue_draw()


class Meter(Gtk.Box):
    """Label + thin red bar + value, for compact readings."""

    def __init__(self, label, max_value=100.0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("ac-meter")
        self.max_value = max_value
        top = Gtk.Box()
        self.name = Gtk.Label(label=label.upper(), xalign=0, hexpand=True)
        self.name.add_css_class("ac-meter-label")
        self.value = Gtk.Label(xalign=1)
        self.value.add_css_class("ac-meter-value")
        top.append(self.name)
        top.append(self.value)
        self.append(top)
        self.bar = Gtk.LevelBar(min_value=0, max_value=max_value)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.bar.remove_offset_value(offset)
        self.append(self.bar)

    def set_value(self, value, text):
        self.value.set_label(text)
        self.bar.set_value(0 if value is None else max(0.0, min(value, self.bar.get_max_value())))

    def set_max(self, max_value):
        self.bar.set_max_value(max(max_value, 1e-6))
