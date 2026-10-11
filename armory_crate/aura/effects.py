"""Software lighting effects. Pure functions of (time, position) -> RGB."""

import colorsys
import math
from dataclasses import dataclass, field

EFFECTS = {
    "off": "Off",
    "static": "Static",
    "breathing": "Breathing",
    "strobe": "Strobe",
    "color_cycle": "Color cycle",
    "spectrum": "Spectrum cycle",
    "rainbow_wave": "Rainbow wave",
}

BREATHING_GAMMA = 2.2

ANIMATED = frozenset({"breathing", "strobe", "color_cycle", "spectrum", "rainbow_wave"})


def parse_hex(color):
    s = color.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"bad colour {color!r}")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


@dataclass
class Effect:
    name: str = "static"
    colors: list = field(default_factory=lambda: ["#ff0000", "#0000ff"])
    speed: float = 1.0          # 0.25 .. 4.0, cycles scale
    brightness: int = 100       # 0 .. 100
    direction: str = "forward"  # forward | reverse

    @classmethod
    def from_dict(cls, d):
        e = cls(**{k: d[k] for k in ("name", "colors", "speed", "brightness", "direction") if k in d})
        e.validate()
        return e

    def to_dict(self):
        return {"name": self.name, "colors": list(self.colors), "speed": self.speed,
                "brightness": self.brightness, "direction": self.direction}

    def validate(self):
        if self.name not in EFFECTS:
            raise ValueError(f"unknown effect {self.name!r}")
        if not self.colors:
            raise ValueError("at least one colour is required")
        for c in self.colors:
            parse_hex(c)
        self.speed = min(4.0, max(0.25, float(self.speed)))
        self.brightness = min(100, max(0, int(self.brightness)))
        if self.direction not in ("forward", "reverse"):
            raise ValueError("direction must be forward or reverse")

    @property
    def animated(self):
        return self.name in ANIMATED


def _scale(rgb, k):
    return tuple(c * k for c in rgb)


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _hue(h):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)
    return (r * 255, g * 255, b * 255)


def render_float(effect, t, x):
    """Colour at time t (s) for normalized position x in [0, 1), as floats 0..255."""
    colors = [parse_hex(c) for c in effect.colors]
    s = effect.speed
    if effect.direction == "reverse":
        x = 1.0 - x
    name = effect.name
    if name == "off":
        rgb = (0, 0, 0)
    elif name == "static":
        rgb = colors[0]
    elif name == "breathing":
        # One breath every 4 s at speed 1, fading fully to off. LED brightness is
        # perceived non-linearly, so apply gamma to make the fade look even.
        k = (0.5 - 0.5 * math.cos(2 * math.pi * t * s / 4.0)) ** BREATHING_GAMMA
        rgb = _scale(colors[0], k)
    elif name == "strobe":
        rgb = colors[0] if (t * s * 4.0) % 1.0 < 0.15 else (0, 0, 0)
    elif name == "color_cycle":
        pos = (t * s / 3.0) % len(colors)
        i = int(pos)
        rgb = _lerp(colors[i], colors[(i + 1) % len(colors)], pos - i)
    elif name == "spectrum":
        rgb = _hue(t * s / 10.0)
    elif name == "rainbow_wave":
        rgb = _hue(x - t * s / 5.0)
    else:
        raise ValueError(name)
    k = effect.brightness / 100.0
    return tuple(max(0.0, min(255.0, c * k)) for c in rgb)


def render(effect, t, x):
    """Colour rounded to 8-bit (UI previews, tests)."""
    return tuple(round(c) for c in render_float(effect, t, x))


# Golden-ratio low-discrepancy sequence: spreads dither thresholds evenly across
# LEDs and changes them every frame, so the error averages out in space and time.
_PHI = 0.6180339887498949
_PHI2 = 0.7548776662466927


def dither(value, led, frame):
    """Quantize a 0..255 float so its average over neighbouring LEDs and frames
    equals the float. Exact integers pass through unchanged."""
    threshold = (led * _PHI + frame * _PHI2) % 1.0
    return min(255, int(value + threshold))


def render_layout(effect, t, layout, frame=None):
    """layout: list (per device) of list (per zone) of LED counts.

    LEDs are placed on one shared axis across all devices so waves flow from
    one device into the next. Returns the same nesting with 8-bit RGB tuples.
    With a frame number, fractional brightness is dithered (smooth deep fades);
    without one, values are simply rounded.
    """
    total = sum(n for zones in layout for n in zones) or 1
    out, pos = [], 0
    for zones in layout:
        dev = []
        for n in zones:
            leds = []
            for i in range(n):
                rgb = render_float(effect, t, (pos + i) / total)
                if frame is None:
                    leds.append(tuple(round(c) for c in rgb))
                else:
                    # offset channels so R/G/B don't step on the same LEDs together
                    leds.append(tuple(dither(c, pos + i + ch * 7, frame) for ch, c in enumerate(rgb)))
            dev.append(leds)
            pos += n
        out.append(dev)
    return out
