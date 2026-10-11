import unittest

from armory_crate.aura import effects as E


class EffectTests(unittest.TestCase):
    def test_static_and_brightness(self):
        e = E.Effect("static", ["#ff8000"], brightness=50)
        self.assertEqual(E.render(e, 0, 0), (128, 64, 0))

    def test_off(self):
        self.assertEqual(E.render(E.Effect("off"), 3.3, 0.5), (0, 0, 0))

    def test_breathing_range(self):
        e = E.Effect("breathing", ["#ffffff"])
        lo = E.render(e, 0, 0)[0]
        hi = E.render(e, 2.0, 0)[0]   # half period at speed 1
        self.assertEqual(lo, 0)       # fades fully to off
        self.assertEqual(hi, 255)
        # gamma: at a quarter period the raw sine is 50%, perceived-even fade is darker
        self.assertLess(E.render(e, 1.0, 0)[0], 64)

    def test_rainbow_wave_varies_with_position_and_direction(self):
        e = E.Effect("rainbow_wave")
        self.assertNotEqual(E.render(e, 0, 0.0), E.render(e, 0, 0.33))
        r = E.Effect("rainbow_wave", direction="reverse")
        self.assertEqual(E.render(r, 0, 0.25), E.render(e, 0, 0.75))

    def test_layout_shared_axis(self):
        e = E.Effect("rainbow_wave")
        out = E.render_layout(e, 0, [[2, 0], [3]])
        self.assertEqual([len(z) for d in out for z in d], [2, 0, 3])
        flat = [c for d in out for z in d for c in z]
        self.assertEqual(flat[0], E.render(e, 0, 0.0))
        self.assertEqual(flat[2], E.render(e, 0, 2 / 5))

    def test_validation(self):
        with self.assertRaises(ValueError):
            E.Effect.from_dict({"name": "lasers"})
        with self.assertRaises(ValueError):
            E.Effect.from_dict({"name": "static", "colors": ["red"]})
        e = E.Effect.from_dict({"name": "spectrum", "speed": 99, "brightness": -5})
        self.assertEqual((e.speed, e.brightness), (4.0, 0))

    def test_dither_preserves_average_and_integers(self):
        # 1.4 averaged over many LEDs/frames comes out ~1.4, never jumps to 2+
        vals = [E.dither(1.4, led, f) for led in range(30) for f in range(30)]
        self.assertAlmostEqual(sum(vals) / len(vals), 1.4, delta=0.05)
        self.assertEqual(set(vals), {1, 2})
        self.assertEqual({E.dither(255.0, i, i) for i in range(50)}, {255})
        self.assertEqual({E.dither(0.0, i, i) for i in range(50)}, {0})
        self.assertEqual({E.dither(128.0, i, 3) for i in range(50)}, {128})

    def test_layout_dithered_static_is_exact(self):
        e = E.Effect("static", ["#ff8000"])
        out = E.render_layout(e, 0, [[30]], frame=7)
        self.assertEqual(set(out[0][0]), {(255, 128, 0)})

    def test_color_cycle_interpolates(self):
        e = E.Effect("color_cycle", ["#000000", "#ffffff"])
        self.assertEqual(E.render(e, 0, 0), (0, 0, 0))
        self.assertEqual(E.render(e, 1.5, 0), (128, 128, 128))


if __name__ == "__main__":
    unittest.main()
