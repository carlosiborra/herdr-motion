import io
import json
import os
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from herdr_motion import app, lifecycle
from herdr_motion.paths import resolve


class PathTests(unittest.TestCase):
    def test_herdr_variables_win(self):
        paths = resolve({"HERDR_PLUGIN_ID": "herdr-motion", "HERDR_PLUGIN_CONFIG_DIR": "/c", "HERDR_PLUGIN_STATE_DIR": "/s",
                         "HERDR_SOCKET_PATH": "/run/h.sock", "HERDR_CONFIG_PATH": "/cfg/config.toml"})
        self.assertEqual((paths.config_dir, paths.state_dir, paths.socket, paths.herdr_config),
                         (Path("/c"), Path("/s"), Path("/run/h.sock"), Path("/cfg/config.toml")))
        self.assertEqual(paths.settings, Path("/c/motion.json"))
        self.assertEqual(paths.lock.parent, Path("/s"))
        self.assertEqual(paths.log, Path("/s/worker.log"))

    def test_fallbacks_follow_xdg(self):
        paths = resolve({"HOME": "/h", "XDG_CONFIG_HOME": "/x/config", "XDG_STATE_HOME": "/x/state"})
        self.assertEqual(paths.herdr_config, Path("/x/config/herdr/config.toml"))
        self.assertEqual(paths.socket, Path("/x/config/herdr/herdr.sock"))
        self.assertEqual(paths.config_dir, Path("/x/config/herdr/plugins/config/carlosiborra.motion"))
        self.assertEqual(paths.state_dir, Path("/x/state/herdr/carlosiborra.motion"))
        plain = resolve({"HOME": "/h"})
        self.assertEqual(plain.herdr_config, Path("/h/.config/herdr/config.toml"))
        self.assertEqual(plain.state_dir, Path("/h/.local/state/herdr/carlosiborra.motion"))

    def test_relative_xdg_is_ignored_and_plugin_id_comes_from_the_environment(self):
        self.assertEqual(resolve({"HOME": "/h", "XDG_CONFIG_HOME": "rel"}).herdr_config, Path("/h/.config/herdr/config.toml"))
        self.assertEqual(resolve({"HERDR_PLUGIN_ID": "other"}).plugin_id, "other")

    def test_lock_is_keyed_by_socket(self):
        one = resolve({"HERDR_PLUGIN_STATE_DIR": "/s", "HERDR_SOCKET_PATH": "/a.sock"})
        two = resolve({"HERDR_PLUGIN_STATE_DIR": "/s", "HERDR_SOCKET_PATH": "/b.sock"})
        self.assertNotEqual(one.lock, two.lock)
        self.assertEqual(one.lock, resolve({"HERDR_PLUGIN_STATE_DIR": "/s", "HERDR_SOCKET_PATH": "/a.sock"}).lock)


class LifecycleCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = {"HERDR_PLUGIN_STATE_DIR": str(self.root / "state"), "HERDR_PLUGIN_CONFIG_DIR": str(self.root / "cfg"),
                    "HERDR_SOCKET_PATH": str(self.root / "none.sock")}
        self.paths = resolve(self.env)

    def tearDown(self):
        self.temp.cleanup()


class StartTests(LifecycleCase):
    def test_start_spawns_and_returns_without_running_the_worker(self):
        spawn = mock.Mock(return_value=123)
        self.assertEqual(lifecycle.start(self.paths, self.env, spawn=spawn), 0)
        spawn.assert_called_once_with(self.paths, self.env)

    def test_start_failure_is_reported_not_raised(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = lifecycle.start(self.paths, self.env, spawn=mock.Mock(side_effect=OSError("nope")))
        self.assertEqual(code, 1)
        self.assertIn("nope", err.getvalue())

    def test_spawn_is_detached_with_stdio_in_the_state_dir_log(self):
        with mock.patch("herdr_motion.lifecycle.subprocess.Popen") as popen:
            popen.return_value.pid = 42
            self.assertEqual(lifecycle.spawn_worker(self.paths, self.env), 42)
        _, kwargs = popen.call_args
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stdin"], lifecycle.subprocess.DEVNULL)
        self.assertEqual(Path(kwargs["stdout"].name), self.paths.log)
        self.assertEqual(popen.call_args[0][0][-1], "--worker")

    def test_main_start_dispatches_to_the_one_shot_start(self):
        with mock.patch("herdr_motion.lifecycle.spawn_worker") as spawn:
            self.assertEqual(app.main(["--start"], self.env), 0)
        spawn.assert_called_once()


class SingleInstanceTests(LifecycleCase):
    def test_second_worker_cannot_take_the_lock(self):
        first = lifecycle.acquire(self.paths.lock)
        self.assertIsNotNone(first)
        self.assertIsNone(lifecycle.acquire(self.paths.lock))
        self.assertTrue(lifecycle.is_locked(self.paths.lock))
        first.close()
        self.assertFalse(lifecycle.is_locked(self.paths.lock))

    def test_waiting_worker_takes_over_when_the_predecessor_exits(self):
        first = lifecycle.acquire(self.paths.lock)
        naps = []

        def sleep(seconds):
            naps.append(seconds)
            first.close()

        second = lifecycle.acquire(self.paths.lock, wait=1.0, sleep=sleep)
        self.assertIsNotNone(second)
        self.assertEqual(len(naps), 1)
        second.close()

    def test_worker_exits_at_once_when_another_holds_the_lock(self):
        held = lifecycle.acquire(self.paths.lock)
        with mock.patch.object(lifecycle, "LOCK_WAIT", 0.0):
            self.assertEqual(app.run_worker(self.paths, self.env), 0)
        self.assertFalse(self.paths.pid.exists())
        held.close()

    def test_status_and_stop_ignore_a_stale_pid(self):
        self.paths.state_dir.mkdir(parents=True)
        self.paths.pid.write_text(str(os.getpid()))
        self.assertIsNone(lifecycle.worker_pid(self.paths))
        kill = mock.Mock()
        self.assertTrue(lifecycle.stop(self.paths, kill=kill))
        kill.assert_not_called()
        self.assertFalse(self.paths.pid.exists())

    def test_stop_signals_the_pid_of_a_held_lock(self):
        handle = lifecycle.acquire(self.paths.lock)
        lifecycle.write_pid(self.paths)
        sent = []

        def kill(pid, sig):
            sent.append((pid, sig))
            handle.close()

        self.assertTrue(lifecycle.stop(self.paths, kill=kill, sleep=lambda s: None))
        self.assertEqual(sent[0][0], os.getpid())

    def test_stop_reports_a_worker_that_will_not_exit(self):
        handle = lifecycle.acquire(self.paths.lock)
        lifecycle.write_pid(self.paths)
        self.assertFalse(lifecycle.stop(self.paths, timeout=0.2, kill=lambda p, s: None, sleep=lambda s: None))
        handle.close()


class WorkerExitTests(LifecycleCase):
    def test_worker_without_a_server_gives_up_after_a_few_retries_and_cleans_up(self):
        naps = []
        err = io.StringIO()
        with redirect_stderr(err):
            code = app.run_worker(self.paths, self.env, sleep=naps.append)
        self.assertEqual(code, 0)
        self.assertEqual(len(naps), app.CONNECT_ATTEMPTS - 1)
        self.assertLessEqual(sum(naps), 5.0)
        self.assertFalse(self.paths.pid.exists())
        self.assertFalse(lifecycle.is_locked(self.paths.lock))
        self.assertIn("exiting", err.getvalue())

    def test_worker_exits_when_the_event_stream_closes(self):
        sock_path = Path(tempfile.mkdtemp(prefix="hm")) / "s"
        self.env["HERDR_SOCKET_PATH"] = str(sock_path)
        self.env["HERDR_PLUGIN_ID"] = "herdr-motion"
        paths = resolve(self.env)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(8)
        methods = []

        def serve():
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return
                request = json.loads(conn.makefile("rb").readline())
                methods.append(request["method"])
                result = {"plugins": [{"plugin_id": "herdr-motion", "enabled": True}]} \
                    if request["method"] == "plugin.list" else {"snapshot": {"tabs": []}}
                conn.sendall(json.dumps({"id": request["id"], "result": result}).encode() + b"\n")
                conn.close()  # one-shot replies; closing the subscription is the server going away

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(app.run_worker(paths, self.env, sleep=lambda s: None), 0)
        finally:
            server.close()
        self.assertIn("plugin.list", methods)
        self.assertIn("events.subscribe", methods)
        self.assertFalse(lifecycle.is_locked(paths.lock))
        self.assertFalse(paths.pid.exists())


if __name__ == "__main__":
    unittest.main()
