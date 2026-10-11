"""Home dashboard: Armoury-Crate-style gauges and meters."""

from gi.repository import Gtk, Pango

from ..widgets.common import flow_row, fmt, scrolled_page
from ..widgets.graph import PALETTE, Graph
from ..widgets.rog import Gauge, Meter, Panel

FAN_GAUGE_MAX = 3000.0


def _row(*children, spacing=12, homogeneous=True):
    box = Gtk.Box(spacing=spacing, homogeneous=homogeneous)
    for c in children:
        c.set_hexpand(True)
        box.append(c)
    return box


class HomePage(Gtk.Box):
    title = "Home"

    def __init__(self, sampler):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sampler = sampler
        snap = sampler.snapshot
        c = snap.cpu

        # CPU panel
        self.cpu_temp = Gauge("Temperature", "°C", max_value=95)
        self.cpu_load = Gauge("Usage", "%", max_value=100)
        self.cpu_clock = Gauge("Frequency", "GHz", max_value=max(c.max_mhz / 1000, 1), digits=2)
        cpu = Panel("CPU", suffix=self._dim(c.model))
        cpu.append(_row(self.cpu_temp, self.cpu_load, self.cpu_clock))
        self.cpu_graph = Graph(height=54, y_max=100)
        cpu.append(self.cpu_graph)

        # GPU panel
        g = snap.gpu
        self.gpu_temp = Gauge("Temperature", "°C", max_value=110)
        self.gpu_load = Gauge("Usage", "%", max_value=100)
        self.gpu_power = Gauge("Power", "W", max_value=320)
        gpu = Panel("GPU", suffix=self._dim(g.name if g else "No AMD GPU"))
        gpu.append(_row(self.gpu_temp, self.gpu_load, self.gpu_power))
        self.gpu_graph = Graph(height=54, y_max=100)
        gpu.append(self.gpu_graph)

        # Motherboard / memory / storage
        self.board_meters = {}
        board = Panel("Motherboard", suffix=self._dim(snap.board.name))
        for label in ("VRM", "CPU", "Motherboard"):
            m = Meter(label, max_value=100)
            self.board_meters[label] = m
            board.append(m)

        mem = Panel("Memory")
        self.mem_big = Gtk.Label(xalign=0)
        self.mem_big.add_css_class("ac-big")
        mem.append(self.mem_big)
        self.mem_meter = Meter("In use", max_value=snap.system.mem_total_gb)
        mem.append(self.mem_meter)
        self.dimm_meter = Meter("DIMM temperature", max_value=85)
        mem.append(self.dimm_meter)

        storage = Panel("Storage")
        self.drive_meters = []
        for model, _ in snap.system.drives:
            m = Meter(model, max_value=85)
            self.drive_meters.append(m)
            storage.append(m)
        if not self.drive_meters:
            storage.append(self._dim("No NVMe drives"))

        # Fans
        self.fans_panel = Panel("Fan speed")
        self.fan_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=2,
                                   max_children_per_line=8, column_spacing=14, row_spacing=14,
                                   homogeneous=True)
        self.fans_panel.append(self.fan_box)
        self.fan_note = self._dim("Motherboard fan sensors not loaded — see Fan Xpert")
        self.fans_panel.append(self.fan_note)
        self.fan_gauges = {}

        # Two independently-reflowing rows instead of a fixed 6-column grid: cpu/gpu (the wider,
        # busier tiles) wrap to one-per-line before board/mem/storage do, matching their extra width.
        dash = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        dash.append(flow_row([cpu, gpu], max_per_line=2))
        dash.append(flow_row([board, mem, storage], max_per_line=3))
        dash.append(self.fans_panel)

        self.append(scrolled_page(dash, "Home", f"{snap.board.vendor} {snap.board.name}".strip()))
        sampler.connect("updated", lambda *_: self.refresh())
        self.refresh()

    @staticmethod
    def _dim(text):
        label = Gtk.Label(label=text, xalign=1, ellipsize=Pango.EllipsizeMode.END)
        label.add_css_class("ac-dim")
        return label

    def refresh(self):
        s, h = self.sampler.snapshot, self.sampler.history
        c = s.cpu
        self.cpu_temp.set_value(c.tctl)
        self.cpu_load.set_value(c.load_total)
        self.cpu_clock.set_value(c.avg_mhz / 1000)
        self.cpu_graph.set_series([(h["cpu.temp"], PALETTE[0]), (h["cpu.load"], (0.55, 0.55, 0.6))])

        g = s.gpu
        if g:
            self.gpu_temp.set_value(g.temps.get("edge"))
            self.gpu_load.set_value(g.busy)
            self.gpu_power.set_value(g.power_w)
            self.gpu_graph.set_series([(h["gpu.temp"], PALETTE[0]), (h["gpu.load"], (0.55, 0.55, 0.6))])

        for label, meter in self.board_meters.items():
            t = s.board.temps.get(label)
            meter.set_value(t, fmt(t, " °C"))

        m = s.system
        self.mem_big.set_label(f"{m.mem_used_gb:.1f} / {m.mem_total_gb:.0f} GB")
        self.mem_meter.set_value(m.mem_used_gb, f"{m.mem_used_gb / m.mem_total_gb * 100:.0f}%")
        dimm = max(m.dimm_temps, default=None)
        self.dimm_meter.set_value(dimm, fmt(dimm, " °C"))
        for meter, (_, temp) in zip(self.drive_meters, m.drives):
            meter.set_value(temp, fmt(temp, " °C"))

        fans = self.sampler.fans()
        self.fan_note.set_visible(s.board.superio is None)
        for fan in fans:
            gauge = self.fan_gauges.get(fan.key)
            if gauge is None:
                gauge = Gauge(fan.label, "RPM", size=104, max_value=FAN_GAUGE_MAX)
                self.fan_gauges[fan.key] = gauge
                self.fan_box.append(gauge)
            gauge.set_caption(fan.label)
            gauge.max_value = max(FAN_GAUGE_MAX, fan.rpm)
            gauge.set_value(fan.rpm)
