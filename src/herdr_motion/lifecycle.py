"""Start, stop and inspect the background effects worker.

The startup hook only calls ``start``: it spawns the worker fully detached (its own session, stdio
sent to a log file in the plugin state directory) and returns at once. The worker holds an
exclusive flock on a lock file keyed by the socket path, so there is one worker per Herdr server,
and writes its pid next to it. ``stop`` signals only a pid whose lock is actually held.
"""
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .paths import Paths

ENTRY = Path(__file__).resolve().parents[2] / "bin" / "herdr-motion"
LOG_LIMIT = 256 * 1024
LOCK_WAIT = 5.0  # a worker started during a live handoff waits this long for its predecessor to exit


def acquire(path: Path, wait: float = 0.0, step: float = 0.25,
            sleep: Callable[[float], None] = time.sleep):
    """The open, exclusively locked lock file; None when another worker still holds it after ``wait``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    waited = 0.0
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except BlockingIOError:
            if waited >= wait:
                handle.close()
                return None
            sleep(step)
            waited += step


def is_locked(path: Path) -> bool:
    if not path.exists():
        return False
    handle = acquire(path)
    if handle is None:
        return True
    handle.close()
    return False


def read_pid(paths: Paths) -> Optional[int]:
    try:
        return int(paths.pid.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(paths: Paths) -> None:
    paths.pid.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid(paths: Paths) -> None:
    try:
        paths.pid.unlink()
    except OSError:
        pass


def worker_pid(paths: Paths) -> Optional[int]:
    """The running worker's pid, or None; a pid file without a held lock is stale and ignored."""
    return read_pid(paths) if is_locked(paths.lock) else None


def spawn_worker(paths: Paths, env: Mapping[str, str]) -> int:
    """Run the worker detached in a new session, its stdio in the log file; returns its pid."""
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        if paths.log.stat().st_size > LOG_LIMIT:
            os.replace(str(paths.log), str(paths.log) + ".1")
    except OSError:
        pass
    with paths.log.open("ab") as log:
        process = subprocess.Popen([sys.executable, str(ENTRY), "--worker"], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True, close_fds=True,
                                   env=dict(env))
    return process.pid


def start(paths: Paths, env: Mapping[str, str],
          spawn: Optional[Callable[[Paths, Mapping[str, str]], Any]] = None) -> int:
    """The startup hook: launch the worker and return. A worker that finds one running exits itself."""
    try:
        (spawn or spawn_worker)(paths, env)
    except OSError as error:
        print("herdr-motion could not start its worker: %s" % error, file=sys.stderr)
        return 1
    return 0


def stop(paths: Paths, timeout: float = 5.0, sleep: Callable[[float], None] = time.sleep,
         kill: Callable[[int, int], None] = os.kill) -> bool:
    """Ask the worker to exit and wait for its lock to be released; True when none is left."""
    pid = worker_pid(paths)
    if pid is None:
        remove_pid(paths)
        return True
    try:
        kill(pid, signal.SIGTERM)
    except OSError:
        pass
    waited = 0.0
    while is_locked(paths.lock):
        if waited >= timeout:
            return False
        sleep(0.1)
        waited += 0.1
    return True
