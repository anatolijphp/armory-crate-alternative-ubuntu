"""System information page."""

from gi.repository import Gtk

from ..widgets.common import ValueRow, flow_row, fmt, scrolled_page
from ..widgets.rog import Panel


def _uptime(seconds):
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return (f"{d}d " if d else "") + f"{h}h {m:02d}m"


class SystemPage(Gtk.Box):
    title = "System Info"

    def __init__(self, sampler):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sampler = sampler
        self.rows = {}

        def panel(title, items):
            p = Panel(title)
            lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lst.add_css_class("boxed-list")
            for key, label in items:
                self.rows[key] = ValueRow(label)
                lst.append(self.rows[key])
            p.append(lst)
            p.list = lst
            return p

        self.storage = panel("Storage", [])
        # FlowBox instead of a fixed 2-column grid: reflows to fewer panels per line (down to one,
        # stacked) as the window narrows, rather than squeezing a fixed 2-column layout.
        grid = flow_row([
            panel("Motherboard", [("mb.name", "Model"), ("mb.vendor", "Manufacturer"),
                                  ("mb.bios", "BIOS"), ("mb.sio", "Sensor chips"),
                                  ("mb.volt", "Voltages")]),
            panel("Processor", [("cpu.model", "Model"), ("cpu.topo", "Topology")]),
            panel("Graphics", [("gpu.name", "Model"), ("gpu.vram", "VRAM"), ("gpu.clk", "Clocks"),
                               ("gpu.vbios", "VBIOS")]),
            panel("Memory", [("mem.total", "Installed"), ("mem.dimm", "DIMM temperature")]),
            self.storage,
            panel("Operating system", [("os.name", "Distribution"), ("os.kernel", "Kernel"),
                                       ("os.session", "Session"), ("os.uptime", "Uptime")]),
        ], max_per_line=3)
        self.drive_rows = []
        self.append(scrolled_page(grid, "System Info"))
        sampler.connect("updated", lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        s = self.sampler.snapshot
        r = self.rows
        b, c, g, m = s.board, s.cpu, s.gpu, s.system
        r["mb.name"].set_value(b.name or "—")
        r["mb.vendor"].set_value(b.vendor or "—")
        r["mb.bios"].set_value(f"{b.bios_version} ({b.bios_date})" if b.bios_version else "—")
        r["mb.sio"].set_value(", ".join(x for x in ("asusec" if b.temps else None, b.superio) if x) or "—")
        r["mb.volt"].set_value(", ".join(f"{k} {v:.3f} V" for k, v in list(b.voltages.items())[:3]) or "—")
        r["cpu.model"].set_value(c.model)
        r["cpu.topo"].set_value(f"{c.cores} cores, {c.threads} threads, up to {c.max_mhz:.0f} MHz")
        if g:
            r["gpu.name"].set_value(g.name)
            r["gpu.vram"].set_value(f"{fmt(g.vram_used_mb and g.vram_used_mb / 1024, ' GB', 1)} used of "
                                    f"{fmt(g.vram_total_mb and g.vram_total_mb / 1024, ' GB', 0)}")
            r["gpu.clk"].set_value(f"core {fmt(g.sclk_mhz, ' MHz')}, memory {fmt(g.mclk_mhz, ' MHz')}")
            r["gpu.vbios"].set_value(g.vbios or "—")
        r["mem.total"].set_value(f"{m.mem_total_gb:.1f} GB ({m.mem_used_gb:.1f} GB used)")
        r["mem.dimm"].set_value(", ".join(f"{t:.1f} °C" for t in m.dimm_temps) or "—")
        if len(self.drive_rows) != len(m.drives):
            for row in self.drive_rows:
                self.storage.list.remove(row)
            self.drive_rows = [ValueRow(model) for model, _ in m.drives]
            for row in self.drive_rows:
                self.storage.list.append(row)
        for row, (_, temp) in zip(self.drive_rows, m.drives):
            row.set_value(fmt(temp, " °C", 1))
        r["os.name"].set_value(m.os_name)
        r["os.kernel"].set_value(m.kernel)
        r["os.session"].set_value(m.session or "—")
        r["os.uptime"].set_value(_uptime(m.uptime_s))
