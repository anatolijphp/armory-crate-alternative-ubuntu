"""Fan Xpert page — view only. Nothing here writes pwm or fan settings."""

from gi.repository import Adw, Gtk

from ..widgets.common import scrolled_page
from ..widgets.graph import PALETTE, Graph
from ..widgets.rog import Gauge, Panel, view_only_strip

GAUGE_MAX = 3000.0


class FanCard(Gtk.Box):
    def __init__(self, fan, colour, on_rename):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("ac-panel")
        self.add_css_class("ac-fan-card")
        self.key = fan.key
        self.gauge = Gauge(fan.label, "RPM", size=128, max_value=GAUGE_MAX)
        self.append(self.gauge)
        foot = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        swatch = Gtk.Box(width_request=8, height_request=8, valign=Gtk.Align.CENTER)
        swatch.add_css_class(f"ac-swatch-{colour}")
        foot.append(swatch)
        self.detail = Gtk.Label()
        self.detail.add_css_class("ac-dim")
        foot.append(self.detail)
        if fan.key.startswith("nct"):
            edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Rename header")
            edit.add_css_class("flat")
            edit.connect("clicked", lambda *_: on_rename(self.key, self.label))
            foot.append(edit)
        self.append(foot)
        self.label = fan.label

    def update(self, fan):
        self.label = fan.label
        self.gauge.set_caption(fan.label)
        self.gauge.max_value = max(GAUGE_MAX, fan.rpm)
        self.gauge.set_value(fan.rpm)
        if fan.rpm <= 0:
            self.detail.set_label("zero-RPM idle" if fan.key.startswith("amdgpu") else "stopped / not connected")
        elif fan.duty is not None:
            self.detail.set_label(f"duty {fan.duty:.0f}%")
        else:
            self.detail.set_label(fan.key)


class FansPage(Gtk.Box):
    title = "Fan Xpert"

    def __init__(self, sampler):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.sampler = sampler
        self.append(view_only_strip("View only — fan curves stay under BIOS control"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        self.missing = Panel("Fan sensors unavailable")
        note = Gtk.Label(wrap=True, xalign=0, label=(
            "The Nuvoton Super-I/O driver (nct6775) is not loaded, so fan headers can't be read. "
            "Run packaging/install.sh once to load it now and on every boot."))
        note.add_css_class("ac-dim")
        self.missing.append(note)
        box.append(self.missing)

        self.cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=2,
                                 max_children_per_line=6, column_spacing=14, row_spacing=14,
                                 homogeneous=True)
        box.append(self.cards)

        hist = Panel("Fan speed history", suffix=self._dim("RPM · 2 min"))
        self.graph = Graph(height=170, y_min=0)
        hist.append(self.graph)
        box.append(hist)

        self.card_by_key = {}
        self.append(scrolled_page(box, "Fan Xpert", "Live readings from every fan header and the GPU"))
        sampler.connect("updated", lambda *_: self.refresh())
        self.refresh()

    @staticmethod
    def _dim(text):
        label = Gtk.Label(label=text, xalign=1)
        label.add_css_class("ac-dim")
        return label

    def _rename(self, key, current):
        entry = Gtk.Entry(text=current, activates_default=True)
        dialog = Adw.AlertDialog(heading="Rename fan header",
                                 body=f"Label for {key} (e.g. CPU_FAN, CHA_FAN, AIO_PUMP). Leave empty to reset.",
                                 extra_child=entry, default_response="save", close_response="cancel")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, response):
            if response == "save":
                self.sampler.rename_fan(key, entry.get_text())
        dialog.connect("response", on_response)
        dialog.present(self)

    def refresh(self):
        snap = self.sampler.snapshot
        fans = self.sampler.fans()
        self.missing.set_visible(snap.board.superio is None)
        series = []
        for i, fan in enumerate(fans):
            card = self.card_by_key.get(fan.key)
            if card is None:
                card = FanCard(fan, i % len(PALETTE), self._rename)
                self.card_by_key[fan.key] = card
                self.cards.append(card)
            card.update(fan)
            series.append((self.sampler.history[f"fan.{fan.key}"], PALETTE[i % len(PALETTE)]))
        self.graph.set_series(series)
