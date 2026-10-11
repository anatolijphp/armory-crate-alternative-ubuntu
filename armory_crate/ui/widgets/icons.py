"""Thin line icons in the spirit of Armoury Crate's UI, drawn with Gsk paths.

Each icon is designed on a 24×24 grid and drawn in the widget's CSS colour, so
:hover / :selected states recolour it. Original drawings (no ASUS artwork).
"""

import math

import gi

gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Graphene, Gsk, Gtk  # noqa: E402

STROKE = 1.6


def _pt(x, y):
    return Graphene.Point().init(x, y)


def _arc(b, cx, cy, r, a0, a1):
    """Arc from angle a0 to a1 (degrees, clockwise from +x)."""
    s, e = math.radians(a0), math.radians(a1)
    b.move_to(cx + r * math.cos(s), cy + r * math.sin(s))
    sweep = (a1 - a0) % 360 or 360
    if sweep >= 359.9:
        b.add_circle(_pt(cx, cy), r)
        return
    b.svg_arc_to(r, r, 0, sweep > 180, True, cx + r * math.cos(e), cy + r * math.sin(e))


def _poly(b, pts, close=False):
    b.move_to(*pts[0])
    for p in pts[1:]:
        b.line_to(*p)
    if close:
        b.close()


# Each painter returns (stroke_builder, fill_builder_or_None).
def _menu(s, f):
    for y in (7, 12, 17):
        s.move_to(4, y)
        s.line_to(20, y)


def _home(s, f):
    _poly(s, [(3, 11), (12, 3.5), (21, 11)])
    _poly(s, [(5.5, 9), (5.5, 20), (18.5, 20), (18.5, 9)])
    _poly(s, [(10, 20), (10, 14), (14, 14), (14, 20)])


def _cpu(s, f):
    _poly(s, [(6, 6), (18, 6), (18, 18), (6, 18)], close=True)
    _poly(s, [(9.5, 9.5), (14.5, 9.5), (14.5, 14.5), (9.5, 14.5)], close=True)
    for p in (9, 12, 15):
        for a, b_ in (((p, 6), (p, 3)), ((p, 18), (p, 21)), ((6, p), (3, p)), ((18, p), (21, p))):
            s.move_to(*a)
            s.line_to(*b_)


def _fan(s, f):
    s.add_circle(_pt(12, 12), 9.5)
    f.add_circle(_pt(12, 12), 1.8)
    for k in range(3):
        a = math.radians(k * 120 - 90)
        # blade: curved sweep from hub to rim
        x0, y0 = 12 + 2.6 * math.cos(a), 12 + 2.6 * math.sin(a)
        a1 = a + math.radians(70)
        x1, y1 = 12 + 7.8 * math.cos(a1), 12 + 7.8 * math.sin(a1)
        cx, cy = 12 + 8.5 * math.cos(a + math.radians(10)), 12 + 8.5 * math.sin(a + math.radians(10))
        s.move_to(x0, y0)
        s.quad_to(cx, cy, x1, y1)
        cx2, cy2 = 12 + 4.0 * math.cos(a1 + math.radians(25)), 12 + 4.0 * math.sin(a1 + math.radians(25))
        s.quad_to(cx2, cy2, x0, y0)


def _aura(s, f):
    # lighting mark: three arcs radiating up from a glowing core
    _arc(s, 12, 15, 8.5, 200, 340)
    _arc(s, 12, 15, 5, 210, 330)
    f.add_circle(_pt(12, 15), 2)
    for ang in (235, 270, 305):
        a = math.radians(ang)
        s.move_to(12 + 10.5 * math.cos(a), 15 + 10.5 * math.sin(a))
        s.line_to(12 + 12 * math.cos(a), 15 + 12 * math.sin(a))


def _system(s, f):
    _poly(s, [(3, 4.5), (21, 4.5), (21, 16.5), (3, 16.5)], close=True)
    _poly(s, [(9, 20), (15, 20)])
    _poly(s, [(12, 16.5), (12, 20)])
    f.add_circle(_pt(12, 8), 1.0)
    _poly(s, [(12, 10.5), (12, 14)])


def _power(s, f):
    _arc(s, 12, 13, 8, -50, 230)
    _poly(s, [(12, 3), (12, 12)])


def _static(s, f):
    s.add_circle(_pt(12, 12), 8.5)
    f.add_circle(_pt(12, 12), 4.5)


def _breathing(s, f):
    s.move_to(2.5, 12)
    for i in range(4):
        x = 2.5 + i * 4.75
        s.cubic_to(x + 1.6, 4 if i % 2 == 0 else 20, x + 3.15, 4 if i % 2 == 0 else 20, x + 4.75, 12)


def _strobe(s, f):
    _poly(s, [(13.5, 2.5), (5.5, 13.5), (11.5, 13.5), (10, 21.5), (18.5, 10), (12.5, 10), (13.5, 2.5)], close=True)


def _color_cycle(s, f):
    _arc(s, 12, 12, 8, 200, 340)
    _arc(s, 12, 12, 8, 20, 160)
    # arrow heads
    _poly(s, [(19.5, 6.5), (19.6, 9.7), (16.4, 9.4)])
    _poly(s, [(4.5, 17.5), (4.4, 14.3), (7.6, 14.6)])


def _spectrum(s, f):
    s.add_circle(_pt(12, 12), 9)
    for k in range(6):
        a = math.radians(k * 60 - 90)
        s.move_to(12 + 3 * math.cos(a), 12 + 3 * math.sin(a))
        s.line_to(12 + 9 * math.cos(a), 12 + 9 * math.sin(a))
    s.add_circle(_pt(12, 12), 3)


def _rainbow(s, f):
    for r in (9, 6, 3):
        _arc(s, 12, 17, r, 180, 360)
    _poly(s, [(2, 17), (22, 17)])


def _check(s, f):
    _poly(s, [(5, 12.5), (10, 17.5), (19.5, 7)])


def _chevron_left(s, f):
    _poly(s, [(14.5, 6), (8.5, 12), (14.5, 18)])


def _chevron_right(s, f):
    _poly(s, [(9.5, 6), (15.5, 12), (9.5, 18)])


PAINTERS = {
    "menu": _menu, "home": _home, "cpu": _cpu, "fan": _fan, "aura": _aura, "system": _system,
    "off": _power, "static": _static, "breathing": _breathing, "strobe": _strobe,
    "color_cycle": _color_cycle, "spectrum": _spectrum, "rainbow_wave": _rainbow,
    "check": _check, "chevron-left": _chevron_left, "chevron-right": _chevron_right,
}


class LineIcon(Gtk.Widget):
    def __init__(self, name, size=22):
        super().__init__(width_request=size, height_request=size,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.name = name
        self.add_css_class("ac-icon")

    def set_name_(self, name):
        if name != self.name:
            self.name = name
            self.queue_draw()

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        size = min(w, h)
        if size <= 0:
            return
        s, f = Gsk.PathBuilder.new(), Gsk.PathBuilder.new()
        PAINTERS[self.name](s, f)
        snapshot.save()
        snapshot.translate(_pt((w - size) / 2, (h - size) / 2))
        snapshot.scale(size / 24.0, size / 24.0)
        color = self.get_color()
        stroke = Gsk.Stroke.new(STROKE)
        stroke.set_line_cap(Gsk.LineCap.ROUND)
        stroke.set_line_join(Gsk.LineJoin.ROUND)
        snapshot.append_stroke(s.to_path(), stroke, color)
        fill = f.to_path()
        if not fill.is_empty():
            snapshot.append_fill(fill, Gsk.FillRule.WINDING, color)
        snapshot.restore()
