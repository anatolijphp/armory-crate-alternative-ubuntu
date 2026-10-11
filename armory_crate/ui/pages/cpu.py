"""CPU page — view only. Nothing here changes clocks, boost, governor or EPP."""

from gi.repository import Gtk

from ..widgets.common import ValueRow, flow_row, fmt, scrolled_page
from ..widgets.graph import PALETTE, Graph
from ..widgets.rog import Gauge, Meter, Panel, view_only_strip


class CpuPage(Gtk.Box):
    title = "CPU"

    def __init__(self, sampler):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sampler = sampler
        c = sampler.snapshot.cpu
        self.append(view_only_strip("View only — CPU clocks, boost and power policy are never changed"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        max_ghz = max(c.max_mhz / 1000, 1)
        self.g_temp = Gauge("Tctl", "°C", max_value=95, digits=1)
        self.g_ccd = Gauge("CCD", "°C", max_value=95, digits=1)
        self.g_load = Gauge("Usage", "%", max_value=100)
        self.g_avg = Gauge("Avg clock", "GHz", max_value=max_ghz, digits=2)
        self.g_peak = Gauge("Peak clock", "GHz", max_value=max_ghz, digits=2)
        live = Panel("Live")
        # spacing=12 matches the gauge rows on the Home page (same kind of element, same spacing)
        row = Gtk.Box(homogeneous=True, spacing=12)
        for g in (self.g_temp, self.g_ccd, self.g_load, self.g_avg, self.g_peak):
            row.append(g)
        live.append(row)
        box.append(live)

        info = Panel("Processor", suffix=self._dim(f"{c.model} · {c.cores}C / {c.threads}T"))
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lst.add_css_class("boxed-list")
        self.rows = {}
        for key, title in (("driver", "Frequency driver"), ("governor", "Governor"),
                           ("epp", "Energy / performance preference"), ("boost", "Core performance boost"),
                           ("range", "Clock range")):
            self.rows[key] = ValueRow(title)
            lst.append(self.rows[key])
        info.append(lst)

        hist = Panel("History", suffix=self._dim("temperature · usage · 2 min"))
        self.graph = Graph(height=150, y_max=100)
        hist.append(self.graph)

        box.append(flow_row([info, hist], max_per_line=2))

        threads = Panel("Per-thread clocks")
        self.thread_meters = [Meter(f"Thread {i}", max_value=max(c.max_mhz, 1)) for i in range(c.threads)]
        threads.append(flow_row(self.thread_meters, min_per_line=2, max_per_line=8))
        box.append(threads)

        self.append(scrolled_page(box, "CPU"))
        sampler.connect("updated", lambda *_: self.refresh())
        self.refresh()

    @staticmethod
    def _dim(text):
        label = Gtk.Label(label=text, xalign=1)
        label.add_css_class("ac-dim")
        return label

    def refresh(self):
        c = self.sampler.snapshot.cpu
        h = self.sampler.history
        self.g_temp.set_value(c.tctl)
        self.g_ccd.set_value(max(c.ccds.values(), default=None))
        self.g_load.set_value(c.load_total)
        self.g_avg.set_value(c.avg_mhz / 1000)
        self.g_peak.set_value(c.peak_mhz / 1000)
        r = self.rows
        r["driver"].set_value(f"{c.driver} ({c.driver_status})" if c.driver_status else c.driver or "—")
        r["governor"].set_value(c.governor or "—")
        r["epp"].set_value(c.epp or "—")
        r["boost"].set_value("—" if c.boost is None else ("Enabled" if c.boost else "Disabled"))
        r["range"].set_value(f"{c.min_mhz:.0f} – {c.max_mhz:.0f} MHz")
        self.graph.set_series([(h["cpu.temp"], PALETTE[0]), (h["cpu.load"], (0.55, 0.55, 0.6))])
        for i, m in enumerate(self.thread_meters):
            mhz = c.freqs_mhz[i] if i < len(c.freqs_mhz) else 0
            load = c.loads[i] if i < len(c.loads) else 0
            m.set_value(mhz, f"{mhz:.0f} MHz · {load:.0f}%")
