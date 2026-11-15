import unittest

from herdr_motion.engine import Animate, Flash, Settings, Step, decide, grow_steps, rebalance_steps


def pane(pane_id):
    return {"type": "pane", "pane_id": pane_id}


def split(direction, ratio, first, second):
    return {"type": "split", "direction": direction, "ratio": ratio, "first": first, "second": second}


def layout(root, focused="a", zoomed=False):
    return {"tab_id": "w1:t1", "zoomed": zoomed, "focused_pane_id": focused, "root": root}


TWO = layout(split("right", 0.5, pane("a"), pane("b")))
THREE = layout(split("right", 0.5, pane("a"), split("down", 0.5, pane("b"), pane("c"))))
COLUMNS = layout(split("right", 0.33, pane("a"), split("right", 0.5, pane("b"), pane("c"))))
SETTINGS = Settings()


class EvenOutTests(unittest.TestCase):
    def test_splitting_a_column_grows_into_equal_thirds(self):
        before = layout(split("right", 0.5, pane("a"), pane("b")))
        after = layout(split("right", 0.5, pane("a"), split("right", 0.5, pane("b"), pane("c"))))
        (action,) = decide(before, after, SETTINGS)
        steps = {step.path: step for step in action.steps}
        self.assertAlmostEqual(steps[()].end, 0.3333, places=3)
        self.assertEqual(steps[(True,)].start, 0.9)
        self.assertEqual(steps[(True,)].end, 0.5)

    def test_even_out_can_be_turned_off(self):
        before = layout(split("right", 0.5, pane("a"), pane("b")))
        after = layout(split("right", 0.5, pane("a"), split("right", 0.5, pane("b"), pane("c"))))
        (action,) = decide(before, after, Settings(even_out=False))
        self.assertEqual([step.path for step in action.steps], [(True,)])


class EngineTests(unittest.TestCase):
    def test_new_pane_grows_from_its_edge(self):
        actions = decide(TWO, THREE, SETTINGS)
        self.assertEqual(actions, [Animate("w1:t1", (Step((True,), 0.9, 0.5),), "grow")])

    def test_new_first_child_grows_from_the_other_side(self):
        steps = grow_steps(split("down", 0.4, pane("new"), pane("a")), "new")
        self.assertEqual(steps, (Step((), 0.1, 0.4),))

    def test_closing_rebalances_the_row_it_left(self):
        four = layout(split("right", 0.25, pane("a"), split("right", 0.33, pane("b"),
                                                              split("right", 0.5, pane("c"), pane("d")))))
        three = layout(split("right", 0.25, pane("a"), split("right", 0.33, pane("b"), pane("d"))))
        (action,) = decide(four, three, SETTINGS)
        self.assertEqual(action.reason, "close")
        ends = {step.path: step.end for step in action.steps}
        self.assertAlmostEqual(ends[()], 0.3333, places=3)
        self.assertAlmostEqual(ends[(True,)], 0.5, places=3)

    def test_closing_the_last_split_needs_no_effect(self):
        self.assertEqual(decide(TWO, layout(pane("a")), SETTINGS), [])

    def test_ratio_only_updates_are_ignored(self):
        resized = layout(split("right", 0.7, pane("a"), split("down", 0.5, pane("b"), pane("c"))))
        self.assertEqual(decide(THREE, resized, SETTINGS), [])

    def test_swapped_panes_do_nothing_unless_flash_is_enabled(self):
        swapped = layout(split("right", 0.5, pane("b"), split("down", 0.5, pane("a"), pane("c"))))
        self.assertEqual(decide(THREE, swapped, SETTINGS), [])

    def test_swapped_panes_flash(self):
        swapped = layout(split("right", 0.5, pane("b"), split("down", 0.5, pane("a"), pane("c"))))
        self.assertEqual(decide(THREE, swapped, Settings(flash_moves=True)), [Flash("w1:t1", ("a", "b"))])

    def test_zoomed_tabs_and_first_sightings_do_nothing(self):
        self.assertEqual(decide(None, THREE, SETTINGS), [])
        self.assertEqual(decide(TWO, layout(THREE["root"], zoomed=True), SETTINGS), [])

    def test_settings_turn_effects_off(self):
        off = Settings(grow=False, rebalance_on_close=False, flash_moves=False)
        self.assertEqual(decide(TWO, THREE, off), [])
        self.assertEqual(decide(THREE, TWO, off), [])

    def test_rebalance_skips_splits_already_even(self):
        self.assertEqual(rebalance_steps(TWO["root"], ()), ())
        self.assertEqual(rebalance_steps(COLUMNS["root"], (True,)), ())
        lopsided = split("right", 0.2, pane("a"), split("right", 0.5, pane("b"), pane("c")))
        self.assertEqual([step.path for step in rebalance_steps(lopsided, (True,))], [()])


if __name__ == "__main__":
    unittest.main()
