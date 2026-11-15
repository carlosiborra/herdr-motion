import tempfile
import unittest
from pathlib import Path

from herdr_motion.config import ConfigFile, parse
from herdr_motion.picker import Model, Picker, preview_boxes, render, scene_at
from herdr_motion.styles import names
from herdr_motion.theme import Palette


class FakeTerminal:
    def __init__(self, keys, size=(110, 32)):
        self._keys = list(keys)
        self._size = size
        self.frames = []
        outer = self

        class _Screen:
            def draw(self, lines, size):
                outer.frames.append("\n".join(lines))

        self.screen = _Screen()

    def size(self):
        return self._size

    def keys(self, timeout=0.1):
        return (self._keys.pop(0),) if self._keys else ("escape",)


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = ConfigFile(Path(self.temp.name) / "motion.json")

    def tearDown(self):
        self.temp.cleanup()

    def run_picker(self, keys):
        self.terminal = FakeTerminal(keys)
        clock = iter(i * 0.03 for i in range(10000))
        Picker(self.config, self.terminal, Palette("none"), clock=lambda: next(clock)).run()
        return self.terminal.frames[-1]

    def test_opens_on_the_current_style_with_preview_and_keys(self):
        self.config.set_style("snappy")
        frame = self.run_picker([])
        self.assertIn("style snappy", frame)
        self.assertIn("▌ ● snappy", frame)
        self.assertIn("PREVIEW", frame)
        self.assertIn("esc", frame)

    def test_enter_chooses_a_style_and_saves_it(self):
        frame = self.run_picker(["down", "down", "enter"])
        self.assertEqual(self.config.raw()["style"], "snappy")
        self.assertIn("Style snappy", frame)

    def test_choosing_a_style_drops_a_custom_speed_but_keeps_other_keys(self):
        self.config.update(duration_ms=900, fps=30)
        self.run_picker(["down", "enter"])
        self.assertEqual(self.config.raw(), {"fps": 30, "style": "smooth"})

    def test_space_toggles_a_switch(self):
        grow_row = len(names()) + 1
        self.run_picker(["down"] * grow_row + [" "])
        self.assertFalse(self.config.get().grow)

    def test_e_turns_everything_off_and_on(self):
        self.run_picker(["e"])
        self.assertFalse(self.config.get().enabled)
        frame = self.run_picker(["e"])
        self.assertTrue(self.config.get().enabled)
        self.assertIn("effects on", frame)

    def test_speed_steps_and_resets(self):
        self.run_picker(["end", "right"])
        self.assertEqual(self.config.raw()["duration_ms"], 300)
        self.run_picker(["end", "0"])
        self.assertNotIn("duration_ms", self.config.raw())

    def test_small_popup_explains(self):
        self.terminal = FakeTerminal([], size=(40, 10))
        Picker(self.config, self.terminal, Palette("none")).run()
        self.assertIn("Enlarge", self.terminal.frames[-1])


class PreviewTests(unittest.TestCase):
    def test_story_grows_a_pane_then_closes_one_then_swaps(self):
        config = parse({"style": "smooth", "flash_moves": True})
        label, widths, names_, progress, _ = scene_at(config, 0.0)
        self.assertEqual((label, round(widths[2], 2), progress), ("new pane", 0.0, 0.0))
        label, widths, _, progress, _ = scene_at(config, 0.3)
        self.assertEqual(label, "new pane")
        self.assertAlmostEqual(widths[2], 1 / 3, places=2)
        self.assertEqual(scene_at(config, 0.95)[0], "close")
        label, _, names_, _, flashing = scene_at(config, 1.85)
        self.assertEqual((label, names_, flashing), ("swap", ("shell", "you"), True))

    def test_disabled_effect_jumps_to_its_end(self):
        config = parse({"grow": False})
        _, widths, _, progress, _ = scene_at(config, 0.01)
        self.assertEqual(progress, 1.0)
        self.assertAlmostEqual(widths[2], 1 / 3, places=2)

    def test_without_even_out_the_new_pane_takes_half_its_neighbour(self):
        _, widths, _, _, _ = scene_at(parse({"even_out": False, "style": "instant"}), 0.0)
        self.assertEqual(tuple(round(w, 2) for w in widths), (0.5, 0.25, 0.25))

    def test_boxes_share_borders_and_cover_the_canvas(self):
        boxes = preview_boxes(61, 12, (1 / 3, 1 / 3, 1 / 3))
        self.assertEqual([b[1] for b in boxes], [0, 20, 40])
        self.assertEqual(boxes[-1][3], 60)
        self.assertEqual(len(preview_boxes(61, 12, (0.5, 0.5, 0.0))), 2)

    def test_every_style_renders(self):
        for name in names():
            model = Model({"style": name}, parse({"style": name}))
            lines = render(model, 110, 32, Palette("none"), 0.2)
            self.assertEqual(len(lines), 32)
            self.assertTrue(all(len(line) <= 112 for line in lines), name)


if __name__ == "__main__":
    unittest.main()
