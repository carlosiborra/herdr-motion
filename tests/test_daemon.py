import json
import tempfile
import unittest
from pathlib import Path

from herdr_motion.client import HerdrError
from herdr_motion.config import Config, ConfigFile
from herdr_motion.daemon import Daemon, FlashStore
from herdr_motion.engine import Step


def pane(pane_id):
    return {"type": "pane", "pane_id": pane_id}


def split(direction, ratio, first, second):
    return {"type": "split", "direction": direction, "ratio": ratio, "first": first, "second": second}


class FakeClient:
    def __init__(self, root):
        self.root = root
        self.writes = []
        self.titles = []
        self.exports = 0
        self.plugin_calls = 0
        self.plugin_on = True
        self.fail_writes = False

    def export(self, tab_id):
        self.exports += 1
        return {"tab_id": tab_id, "zoomed": False, "focused_pane_id": "a", "root": self.root}

    def set_ratio(self, tab_id, path, ratio):
        if self.fail_writes and ratio != self.final:
            raise HerdrError("boom")
        self.writes.append((tuple(path), ratio))
        node = self.root
        for second in path:
            node = node["second" if second else "first"]
        node["ratio"] = ratio

    final = None

    def tab_ids(self):
        return ["w1:t1"]

    def title(self, pane_id, text, ttl_ms=None):
        self.titles.append((pane_id, text, ttl_ms))

    def plugin_enabled(self, plugin_id):
        self.plugin_calls += 1
        return self.plugin_on


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Stop(Exception):
    pass


class FakeSubscription:
    def __init__(self, batches=()):
        self.batches = list(batches)

    def read(self):
        return self.batches.pop(0)


class DaemonCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ConfigFile(self.root / "motion.json")
        self.store = FlashStore(self.root / "flashes.json")
        self.clock = Clock()

    def tearDown(self):
        self.temp.cleanup()

    def daemon(self, client, **kwargs):
        return Daemon(client, self.config, self.store, clock=self.clock, **kwargs)

    def event(self, daemon):
        daemon.on_event({"type": "layout_updated", "layout": {"tab_id": "w1:t1"}})

    def run_frames(self, daemon, seconds=0.5):
        while daemon.running and self.clock.now < seconds:
            self.clock.now += 1 / 60
            daemon.tick()

    def three(self):
        return split("right", 0.5, pane("a"), split("down", 0.5, pane("b"), pane("c")))


class EffectTests(DaemonCase):
    def test_split_grows_the_new_pane_and_lands_exactly(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        daemon.prime()
        client.root = self.three()
        self.event(daemon)
        self.assertEqual(client.writes[0], ((True,), 0.9))
        self.run_frames(daemon)
        self.assertEqual(client.writes[-1], ((True,), 0.5))
        self.assertGreater(len(client.writes), 5)
        self.assertEqual(daemon.running, {})

    def test_own_frames_do_not_trigger_more_effects(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        daemon.prime()
        client.root = self.three()
        self.event(daemon)
        self.clock.now += 0.05
        daemon.tick()
        before = len(client.writes)
        daemon.on_event({"type": "layout_updated", "layout": {
            "tab_id": "w1:t1", "panes": [{"pane_id": "a"}, {"pane_id": "b"}, {"pane_id": "c"}]}})
        self.assertEqual(len(client.writes), before)

    def test_ratio_only_event_costs_no_export_unless_flashing(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        daemon.prime()
        exports = client.exports
        event = {"type": "layout_updated", "layout": {"tab_id": "w1:t1", "panes": [{"pane_id": "a"}, {"pane_id": "b"}]}}
        daemon.on_event(event)
        self.assertEqual(client.exports, exports)
        self.config.save(Config(flash_moves=True))
        daemon.on_event(event)
        self.assertEqual(client.exports, exports + 1)

    def test_new_change_continues_from_the_current_ratio(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        daemon.start("w1:t1", (Step((), 0.1, 0.5),))
        self.clock.now = 0.05
        daemon.tick()
        midway = client.root["ratio"]
        daemon.start("w1:t1", (Step((), 0.2, 0.7),))
        self.assertEqual(daemon.running["w1:t1"].steps[0].start, midway)

    def test_zero_duration_jumps_without_animating(self):
        self.config.save(Config(duration_ms=0))
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        daemon.start("w1:t1", (Step((), 0.1, 0.5),))
        self.assertEqual(client.writes, [((), 0.5)])
        self.assertEqual(daemon.running, {})

    def test_new_tab_is_remembered_so_its_first_split_animates(self):
        client = FakeClient(pane("a"))
        daemon = self.daemon(client)
        daemon.prime()
        daemon.on_event({"type": "tab_created", "tab": {"tab_id": "w1:t1"}})
        client.root = split("right", 0.5, pane("a"), pane("b"))
        self.event(daemon)
        self.assertEqual(client.writes[0], ((), 0.9))

    def test_write_failure_snaps_to_the_final_ratio_once(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        client.final = 0.5
        daemon = self.daemon(client)
        daemon.start("w1:t1", (Step((), 0.1, 0.5),))
        client.fail_writes = True
        self.clock.now = 0.05
        daemon.tick()
        self.assertEqual(daemon.running, {})
        self.assertEqual(client.writes[-1], ((), 0.5))
        self.assertEqual(client.root["ratio"], 0.5)


class IdleTests(DaemonCase):
    def test_idle_loop_blocks_without_a_timeout(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        self.assertIsNone(daemon.timeout())
        seen = []

        def wait(watched, _w, _x, timeout):
            seen.append(timeout)
            if len(seen) == 2:
                raise Stop()
            return [], [], []

        daemon.wait = wait
        with self.assertRaises(Stop):
            daemon.run(FakeSubscription(), lambda: False)
        self.assertEqual(seen, [None, None])

    def test_timer_exists_only_while_something_animates(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        daemon.start("w1:t1", (Step((), 0.1, 0.5),))
        self.assertAlmostEqual(daemon.timeout(), 1 / 60, places=4)
        self.run_frames(daemon)
        self.assertIsNone(daemon.timeout())

    def test_disabled_effects_consume_events_without_exports_or_writes(self):
        self.config.save(Config(enabled=False))
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        sub = FakeSubscription([[{"type": "layout_updated", "layout": {"tab_id": "w1:t1"}}]])
        calls = []

        def wait(watched, _w, _x, timeout):
            calls.append(timeout)
            if len(calls) == 2:
                raise Stop()
            return [sub], [], []

        daemon.wait = wait
        with self.assertRaises(Stop):
            daemon.run(sub, lambda: False)
        self.assertEqual(client.exports, 0)
        self.assertEqual(client.writes, [])
        self.assertEqual(calls, [None, None])


class PluginStateTests(DaemonCase):
    def test_exits_when_the_plugin_is_disabled_at_start(self):
        client = FakeClient(pane("a"))
        client.plugin_on = False
        daemon = self.daemon(client, plugin_id="herdr-motion")
        daemon.wait = lambda *a: self.fail("must not wait once the plugin is gone")
        daemon.run(FakeSubscription(), lambda: False)
        self.assertTrue(daemon.gone)

    def test_notices_a_later_disable_on_an_event_at_most_every_five_seconds(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client, plugin_id="herdr-motion")
        daemon.prime()
        daemon.check_plugin(force=True)
        self.assertEqual(client.plugin_calls, 1)
        client.plugin_on = False
        self.clock.now = 2.0
        self.event(daemon)
        self.assertEqual(client.plugin_calls, 1)  # throttled
        self.assertFalse(daemon.gone)
        self.clock.now = 6.0
        self.event(daemon)
        self.assertTrue(daemon.gone)

    def test_no_plugin_id_means_no_check(self):
        client = FakeClient(pane("a"))
        daemon = self.daemon(client)
        daemon.check_plugin(force=True)
        self.assertEqual(client.plugin_calls, 0)


class FlashTests(DaemonCase):
    def swap(self, client, daemon):
        daemon.prime()
        client.root = split("right", 0.5, pane("b"), pane("a"))
        self.event(daemon)

    def test_flash_is_off_by_default(self):
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        self.swap(client, self.daemon(client))
        self.assertEqual(client.titles, [])

    def test_swap_flashes_with_a_ttl_and_clears_titles(self):
        self.config.save(Config(flash_moves=True))
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        self.swap(client, daemon)
        self.assertEqual(sorted((p, t) for p, t, _ in client.titles), [("a", "⇄"), ("b", "⇄")])
        self.assertTrue(all(ttl for _, _, ttl in client.titles))
        self.assertEqual(self.store.load(), {"a", "b"})
        self.assertAlmostEqual(daemon.timeout(), 0.6, places=3)
        self.clock.now = 1.0
        daemon.tick()
        self.assertEqual(sorted((p, t) for p, t, _ in client.titles[2:]), [("a", None), ("b", None)])
        self.assertEqual(self.store.load(), set())
        self.assertIsNone(daemon.timeout())

    def test_stale_titles_from_a_dead_worker_are_cleared(self):
        self.store.save({"x", "y"})
        client = FakeClient(pane("a"))
        self.daemon(client).clear_flashes()
        self.assertEqual(sorted((p, t) for p, t, _ in client.titles), [("x", None), ("y", None)])
        self.assertEqual(self.store.load(), set())

    def test_only_tracked_panes_are_ever_cleared(self):
        client = FakeClient(pane("a"))
        self.daemon(client).clear_flashes()
        self.assertEqual(client.titles, [])

    def test_exit_clears_live_flashes(self):
        self.config.save(Config(flash_moves=True))
        client = FakeClient(split("right", 0.5, pane("a"), pane("b")))
        daemon = self.daemon(client)
        self.swap(client, daemon)
        client.titles.clear()
        daemon.clear_flashes()
        self.assertEqual(sorted(p for p, _, _ in client.titles), ["a", "b"])
        self.assertEqual(daemon.flashes, {})

    def test_store_survives_garbage(self):
        (self.root / "flashes.json").write_text("{not json")
        self.assertEqual(self.store.load(), set())
        (self.root / "flashes.json").write_text(json.dumps({"a": 1}))
        self.assertEqual(self.store.load(), set())


if __name__ == "__main__":
    unittest.main()
