import tempfile
import unittest
from pathlib import Path

from herdr_motion.config import Config, ConfigFile, parse
from herdr_motion.tree import rectangles


def pane(pane_id):
    return {"type": "pane", "pane_id": pane_id}


def split(direction, ratio, first, second):
    return {"type": "split", "direction": direction, "ratio": ratio, "first": first, "second": second}


class ConfigTests(unittest.TestCase):
    def test_parse_clamps_and_ignores_bad_values(self):
        config = parse({"duration_ms": 5000, "easing": "wobble", "grow": "yes", "enabled": False})
        self.assertEqual(config.duration_ms, 1000)
        self.assertEqual(config.easing, "out-cubic")
        self.assertTrue(config.grow)
        self.assertFalse(config.enabled)
        self.assertEqual(parse([]), Config())

    def test_file_reloads_on_change(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "motion.json")
            self.assertTrue(config.get().enabled)
            config.save(Config(enabled=False))
            self.assertFalse(config.get().enabled)


class TreeTests(unittest.TestCase):
    def test_rectangles(self):
        rects = rectangles(split("right", 0.25, pane("a"), split("down", 0.5, pane("b"), pane("c"))))
        self.assertEqual(rects["a"], (0.0, 0.0, 0.25, 1.0))
        self.assertEqual(rects["c"], (0.25, 0.5, 0.75, 0.5))


class EasingTests(unittest.TestCase):
    def test_every_easing_starts_at_zero_and_lands_on_one(self):
        from herdr_motion.engine import EASINGS
        for name, curve in EASINGS.items():
            self.assertAlmostEqual(curve(0.0), 0.0, delta=0.01, msg=name)
            self.assertEqual(curve(1.0), 1.0, name)

    def test_spring_overshoots_then_settles(self):
        from herdr_motion.engine import EASINGS
        values = [EASINGS["spring"](i / 100) for i in range(101)]
        self.assertGreater(max(values), 1.03)
        self.assertLess(max(values), 1.2)
        self.assertAlmostEqual(values[-2], 1.0, delta=0.02)


class StyleTests(unittest.TestCase):
    def test_every_style_is_complete_and_valid(self):
        from herdr_motion.engine import EASINGS
        from herdr_motion.styles import DEFAULT_STYLE, DESCRIPTIONS, STYLES
        self.assertIn(DEFAULT_STYLE, STYLES)
        self.assertEqual(set(STYLES), set(DESCRIPTIONS))
        for name, style in STYLES.items():
            self.assertIn(style["easing"], EASINGS, name)
            self.assertIn(style["grow_easing"], EASINGS, name)
            self.assertTrue(0 <= style["duration_ms"] <= 1000, name)
            self.assertTrue(0 <= style["grow_depth"] <= 1, name)

    def test_style_sets_values_and_user_keys_override(self):
        self.assertEqual(parse({"style": "snappy"}).duration_ms, 130)
        config = parse({"style": "snappy", "duration_ms": 90, "grow_easing": "spring", "flash_mark": "◆"})
        self.assertEqual((config.duration_ms, config.grow_easing, config.easing, config.flash_mark),
                         (90, "spring", "out-quint", "◆"))
        self.assertEqual(parse({"style": "nope"}).style, "lively")

    def test_switching_style_keeps_other_user_keys_and_pins_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "motion.json")
            config.update(fps=30)
            config.set_style("gentle")
            self.assertEqual(config.raw(), {"fps": 30, "style": "gentle"})
            self.assertEqual(config.get().duration_ms, 480)
            config.update(enabled=False)
            self.assertFalse(config.get().enabled)

    def test_cycling_visits_every_style_once(self):
        from herdr_motion.styles import names, next_name
        seen, name = [], "lively"
        for _ in names():
            seen.append(name)
            name = next_name(name)
        self.assertEqual(sorted(seen), sorted(names()))
        self.assertEqual(name, "lively")

    def test_subtle_grow_starts_partway(self):
        from herdr_motion.engine import grow_steps
        root = split("right", 0.5, pane("a"), pane("b"))
        (step,) = grow_steps(root, "b", 0.4)
        self.assertAlmostEqual(step.start, 0.66, places=2)
        self.assertEqual(grow_steps(root, "b", 1.0)[0].start, 0.9)

    def test_flash_moves_is_opt_in(self):
        self.assertFalse(Config().flash_moves)
        self.assertFalse(parse({"style": "lively"}).flash_moves)
        self.assertTrue(parse({"flash_moves": True}).flash_moves)

    def test_removed_auto_layout_key_is_ignored(self):
        self.assertFalse(hasattr(parse({"follow_auto": True}), "follow_auto"))


if __name__ == "__main__":
    unittest.main()
