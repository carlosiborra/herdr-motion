"""Entry point: the one-shot startup hook, the background worker, and small companion commands.

herdr-motion --start    startup hook: launch the worker detached and return at once
herdr-motion --stop     stop the worker and clear any move-flash titles it set
herdr-motion --status   print whether the worker runs, where its files are, and the settings
herdr-motion --toggle   turn effects on or off; the worker notices on its next event
herdr-motion --styles   list the motion styles
herdr-motion --style N  switch to style N
herdr-motion --next     switch to the next style
herdr-motion --pick     the visual settings picker (what the popup runs)
herdr-motion --open     open the picker as a Herdr popup
herdr-motion --worker   the background worker itself (spawned by --start; not for direct use)
"""
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from typing import Mapping, Optional

from . import __version__, lifecycle
from .client import Client, HerdrError, Subscription
from .config import ConfigFile
from .daemon import Daemon, FlashStore
from .paths import Paths, resolve
from .styles import DESCRIPTIONS, names, next_name

CONNECT_ATTEMPTS = 4  # with 0.5 s, 1 s, 1.5 s between them: a missing server ends the worker in about 3 s


def run_worker(paths: Paths, env: Mapping[str, str], sleep=time.sleep) -> int:
    handle = lifecycle.acquire(paths.lock, wait=lifecycle.LOCK_WAIT)
    if handle is None:
        return 0  # another worker already serves this server
    log_path = paths.log
    debug = env.get("HERDR_MOTION_DEBUG") == "1"

    def log(message: str, always: bool = False) -> None:
        if always or debug:
            print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message), file=sys.stderr, flush=True)

    lifecycle.write_pid(paths)
    client = Client(paths.socket)
    flash_store = FlashStore(paths.flashes)
    daemon = Daemon(client, ConfigFile(paths.settings), flash_store,
                    plugin_id=env.get("HERDR_PLUGIN_ID"), log=lambda m: log(m, True) if "exiting" in m else log(m))
    # SIGTERM only sets a flag; the wake-up pipe interrupts the blocking select so it is noticed.
    wake_read, wake_write = os.pipe()
    os.set_blocking(wake_write, False)
    stopped = []
    signal.signal(signal.SIGTERM, lambda signum, frame: stopped.append(signum))
    signal.signal(signal.SIGINT, lambda signum, frame: stopped.append(signum))
    signal.signal(signal.SIGHUP, lambda signum, frame: stopped.append(signum))
    signal.set_wakeup_fd(wake_write)
    log("worker %s started for %s" % (__version__, paths.socket), True)
    try:
        daemon.clear_flashes()  # titles a previous worker set and could not clear
        subscription = None
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                subscription = Subscription(paths.socket)
                break
            except OSError as error:
                log("connect failed: %s" % error)
                if attempt < CONNECT_ATTEMPTS and not stopped:
                    sleep(0.5 * attempt)
        if subscription is None:
            log("no Herdr server to serve; exiting", True)
            return 0
        try:
            daemon.run(subscription, lambda: bool(stopped), wake_read)
        except (HerdrError, OSError) as error:
            log("event stream ended: %s" % error, True)
        finally:
            subscription.close()
    finally:
        try:
            daemon.clear_flashes()
        finally:
            lifecycle.remove_pid(paths)
            handle.close()
        log("worker exited", True)
    return 0


def main(argv=None, environ: Optional[Mapping[str, str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if environ is None else environ)
    if "--version" in args:
        print("herdr-motion %s" % __version__)
        return 0
    if sys.version_info < (3, 9):
        print("Herdr Motion requires Python 3.9 or newer", file=sys.stderr)
        return 2
    paths = resolve(env)
    config = ConfigFile(paths.settings)
    if "--start" in args:
        return lifecycle.start(paths, env)
    if "--worker" in args:
        return run_worker(paths, env)
    if "--stop" in args:
        if lifecycle.stop(paths):
            Daemon(Client(paths.socket), config, FlashStore(paths.flashes)).clear_flashes()
            print("Herdr Motion worker stopped")
            return 0
        print("Herdr Motion worker did not exit; see %s" % paths.log, file=sys.stderr)
        return 1
    if "--status" in args:
        pid = lifecycle.worker_pid(paths)
        print(json.dumps({"worker": "running" if pid else "stopped", "pid": pid, "log": str(paths.log),
                          "state_dir": str(paths.state_dir), "settings_file": str(paths.settings),
                          "settings": asdict(config.get())}))
        return 0
    if "--toggle" in args:
        current = config.get()
        config.update(enabled=not current.enabled)
        print("Herdr Motion effects %s" % ("on" if not current.enabled else "off"))
        return 0
    if "--open" in args:
        # Opens only this plugin's own popup pane; no existing pane is touched.
        binary = env.get("HERDR_BIN_PATH", "herdr")
        completed = subprocess.run([binary, "plugin", "pane", "open", "--plugin", paths.plugin_id,
                                    "--entrypoint", "settings", "--focus"], capture_output=True, text=True)
        if completed.returncode != 0:
            print("Herdr Motion could not open its settings popup: %s"
                  % (completed.stderr or completed.stdout).strip(), file=sys.stderr)
            return 1
        return 0
    if "--pick" in args:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("The Herdr Motion picker needs an interactive terminal; bind it as a popup.", file=sys.stderr)
            return 2
        from .picker import Picker
        from .terminal import Terminal, TerminalExit
        from .theme import load_palette
        palette, _ = load_palette(paths.herdr_config, env)
        try:
            with Terminal(sys.stdin, sys.stdout) as terminal:
                return Picker(config, terminal, palette).run()
        except (TerminalExit, KeyboardInterrupt):
            return 130
    if "--styles" in args:
        current = config.get().style
        for name in names():
            print("%s %-10s %s" % ("*" if name == current else " ", name, DESCRIPTIONS[name]))
        return 0
    if "--style" in args and args.index("--style") + 1 < len(args):
        name = args[args.index("--style") + 1]
        if name not in names():
            print("unknown style %r; choose one of: %s" % (name, ", ".join(names())), file=sys.stderr)
            return 2
        config.set_style(name)
        print("Herdr Motion style: %s" % name)
        return 0
    if "--next" in args:
        name = next_name(config.get().style)
        config.set_style(name)
        print("Herdr Motion style: %s" % name)
        return 0
    print("usage: herdr-motion --start | --stop | --status | --toggle | --next | --style NAME | --styles"
          " | --pick | --open | --version", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
