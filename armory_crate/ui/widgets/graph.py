"""Small line graph for sensor history, drawn with Gtk.Snapshot / Gsk paths (no cairo)."""

import gi

gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Graphene, Gsk, Gtk  # noqa: E402

# Distinct series colours that read on both light and dark backgrounds.
PALETTE = [(1.0, 0.10, 0.18), (0.21, 0.52, 0.89), (0.18, 0.76, 0.49),
           (0.96, 0.60, 0.07), (0.57, 0.38, 0.86), (0.13, 0.70, 0.78)]


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


class Graph(Gtk.Widget):
    def __init__(self, height=64, y_min=0.0, y_max=None, capacity=120):
        super().__init__(hexpand=True, height_request=height)
        self.y_min, self.y_max, self.capacity = y_min, y_max, capacity
        self.series = []      # list of (values, rgb)

    def set_series(self, series):
        self.series = [(list(v), c) for v, c in series]
        self.queue_draw()

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        if width <= 0 or height <= 0:
            return
        fg = self.get_color()
        grid = rgba(fg.red, fg.green, fg.blue, 0.08)
        for i in range(1, 4):
            snapshot.append_color(grid, rect(0, round(height * i / 4), width, 1))

        values = [x for v, _ in self.series for x in v]
        if not values:
            return
        lo = self.y_min if self.y_min is not None else min(values)
        hi = self.y_max if self.y_max is not None else max(values)
        hi = max(hi, max(values))
        if hi - lo < 1e-6:
            hi = lo + 1.0
        hi += (hi - lo) * 0.08
        step = width / max(1, self.capacity - 1)

        stroke = Gsk.Stroke.new(2.0)
        stroke.set_line_join(Gsk.LineJoin.ROUND)
        for vals, (r, g, b) in self.series:
            if len(vals) < 2:
                continue
            x0 = width - (len(vals) - 1) * step
            pts = [(x0 + i * step, height - (v - lo) / (hi - lo) * (height - 2) - 1) for i, v in enumerate(vals)]
            line = Gsk.PathBuilder.new()
            line.move_to(*pts[0])
            for p in pts[1:]:
                line.line_to(*p)
            area = Gsk.PathBuilder.new()
            area.move_to(pts[0][0], height)
            for p in pts:
                area.line_to(*p)
            area.line_to(pts[-1][0], height)
            area.close()
            snapshot.append_fill(area.to_path(), Gsk.FillRule.WINDING, rgba(r, g, b, 0.12))
            snapshot.append_stroke(line.to_path(), stroke, rgba(r, g, b))
