"""The effects loop: event-driven, single-threaded.

The loop blocks on the event subscription. It wakes only for an event, for a signal, or, while an
animation or a move flash is in progress, for the next frame or the flash expiry. With nothing
animating there is no timer at all, so an idle worker costs no wakeups.

One thread multiplexes the stream and every running animation, so effects in different tabs play
at once and a new change in a tab replaces its running animation from wherever it is.

Herdr batches layout events about every 100 ms, so a new pane can appear at full size for up to
that long before its grow starts. That latency is accepted: the alternative was polling.
"""
import json
import os
import select
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple

from .client import Client, HerdrError
from .config import ConfigFile
from .engine import EASINGS, Animate, Flash, Step, at, decide
from .tree import leaves

# A ratio change smaller than about a terminal cell resizes nothing but still costs a write
# and wakes every pane, so frames skip changes below this.
MIN_DELTA = 0.004
# How often, at most, an event triggers a check that this plugin is still installed and enabled.
PLUGIN_CHECK_EVERY = 5.0
# Herdr drops a flash title by itself this long after the worker meant to clear it.
FLASH_GRACE_MS = 1500


@dataclass
class Running:
    steps: Tuple[Step, ...]
    started: float
    duration: float
    easing: str
    last: Dict[Tuple[bool, ...], float] = field(default_factory=dict)


class FlashStore:
    """Pane ids whose title this plugin set, so a worker that died can be cleaned up after."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Set[str]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return set()
        return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()

    def save(self, panes: Set[str]) -> None:
        try:
            if panes:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(sorted(panes)), encoding="utf-8")
            elif self.path.exists():
                self.path.unlink()
        except OSError:
            pass


class Daemon:
    def __init__(self, client: Client, config: ConfigFile, flash_store: FlashStore,
                 plugin_id: Optional[str] = None,
                 clock: Callable[[], float] = time.monotonic, log: Callable[[str], None] = lambda _: None,
                 wait: Callable[..., Any] = select.select) -> None:
        self.client = client
        self.config = config
        self.flash_store = flash_store
        self.plugin_id = plugin_id
        self.clock = clock
        self.log = log
        self.wait = wait
        self.known: Dict[str, Mapping[str, Any]] = {}
        self.pane_sets: Dict[str, frozenset] = {}
        self.running: Dict[str, Running] = {}
        self.flashes: Dict[str, float] = {}  # pane_id -> clear at
        self.primed = False
        self.gone = False  # the plugin was disabled or uninstalled
        self._plugin_checked: Optional[float] = None

    # Plugin state ----------------------------------------------------------

    def check_plugin(self, force: bool = False) -> None:
        """Notice that the plugin was disabled or uninstalled. Checked on events, at most every 5 s."""
        if not self.plugin_id:
            return
        now = self.clock()
        if not force and self._plugin_checked is not None and now - self._plugin_checked < PLUGIN_CHECK_EVERY:
            return
        self._plugin_checked = now
        try:
            if not self.client.plugin_enabled(self.plugin_id):
                self.log("plugin disabled or uninstalled; exiting")
                self.gone = True
        except HerdrError as error:
            self.log("plugin.list failed: %s" % error)

    # Events ----------------------------------------------------------------

    def prime(self) -> None:
        tab_ids = self.client.tab_ids()
        self.primed = True
        for tab_id in tab_ids:
            try:
                self._remember(tab_id, self.client.export(tab_id))
            except HerdrError:
                continue

    def _remember(self, tab_id: str, layout: Mapping[str, Any]) -> None:
        self.known[tab_id] = layout
        self.pane_sets[tab_id] = frozenset(leaves(layout["root"]))

    def on_event(self, data: Mapping[str, Any]) -> None:
        self.check_plugin()
        if self.gone:
            return
        if not self.config.get().enabled:
            # Effects are off: consume the event and do nothing else, no export and no write.
            # What was remembered goes stale, so forget it and learn the tabs again when re-enabled.
            self.known.clear()
            self.pane_sets.clear()
            self.primed = False
            return
        if not self.primed:
            try:
                self.prime()
            except HerdrError:
                self.primed = False
            return
        kind = data.get("type")
        if kind == "tab_created":
            tab_id = (data.get("tab") or {}).get("tab_id")
            if isinstance(tab_id, str):
                try:
                    self._remember(tab_id, self.client.export(tab_id))
                except HerdrError:
                    pass
            return
        if kind == "tab_closed":
            tab_id = str(data.get("tab_id"))
            self.known.pop(tab_id, None)
            self.pane_sets.pop(tab_id, None)
            self.running.pop(tab_id, None)
            return
        if kind != "layout_updated":
            return
        event_layout = data.get("layout") or {}
        tab_id = event_layout.get("tab_id")
        if not isinstance(tab_id, str):
            return
        if tab_id in self.pane_sets:
            # The event lists the tab's panes. Our own animation frames echo back as layout updates,
            # and a ratio-only change needs no effect, so export only when the pane set changed, or
            # when move flashes need to see panes trade places.
            panes = frozenset(p.get("pane_id") for p in event_layout.get("panes", []) if isinstance(p, dict))
            if panes == self.pane_sets[tab_id] and (tab_id in self.running or not self.config.get().flash_moves):
                return
        try:
            layout = self.client.export(tab_id)
        except HerdrError:
            self.known.pop(tab_id, None)
            self.pane_sets.pop(tab_id, None)
            return
        self.observe(tab_id, layout)

    def observe(self, tab_id: str, layout: Mapping[str, Any]) -> None:
        """Compare a fresh layout with the remembered one and play whatever effect it calls for."""
        previous = self.known.get(tab_id)
        self._remember(tab_id, layout)
        config = self.config.get()
        if not config.enabled:
            return
        # Our own frames only change ratios, which decide() ignores, so a split or close
        # in the middle of an animation still gets its effect.
        for action in decide(previous, layout, config.settings):
            self.perform(action)

    # Actions ---------------------------------------------------------------

    def perform(self, action: Any) -> None:
        config = self.config.get()
        if isinstance(action, Animate):
            self.start(action.tab_id, action.steps, action.reason)
            self.log("animate %s %s steps=%d" % (action.tab_id, action.reason, len(action.steps)))
        elif isinstance(action, Flash):
            until = self.clock() + config.flash_ms / 1000.0
            for pane_id in action.pane_ids:
                try:
                    self.client.title(pane_id, config.flash_mark, config.flash_ms + FLASH_GRACE_MS)
                except HerdrError:
                    continue
                self.flashes[pane_id] = until
            self.flash_store.save(self.flash_store.load() | set(self.flashes))

    def start(self, tab_id: str, steps: Tuple[Step, ...], reason: str = "") -> None:
        config = self.config.get()
        if not steps:
            return
        if config.duration_ms <= 0:
            for step in sorted(steps, key=lambda item: len(item.path)):
                self._write(tab_id, step.path, step.end)
            return
        current = self.running.get(tab_id)
        if current is not None:
            # Continue from where the running animation is, so nothing jumps.
            steps = tuple(Step(step.path, current.last.get(step.path, step.start), step.end) for step in steps)
        self.running[tab_id] = Running(tuple(sorted(steps, key=lambda item: len(item.path))),
                                       self.clock(), config.duration_ms / 1000.0,
                                       config.grow_easing if reason == "grow" else config.easing)
        self.tick()

    def _write(self, tab_id: str, path: Tuple[bool, ...], ratio: float) -> bool:
        try:
            self.client.set_ratio(tab_id, path, ratio)
            return True
        except HerdrError:
            return False

    # Frames ----------------------------------------------------------------

    def tick(self) -> None:
        now = self.clock()
        for tab_id, running in list(self.running.items()):
            progress = 1.0 if running.duration <= 0 else min(1.0, (now - running.started) / running.duration)
            curve = EASINGS.get(running.easing, EASINGS["out-cubic"])
            ok = True
            for path, ratio in at(running.steps, curve(progress) if progress < 1 else 1.0):
                last = running.last.get(path)
                if last is None or abs(ratio - last) >= MIN_DELTA or progress >= 1:
                    if progress >= 1 and last == ratio:
                        continue
                    ok = self._write(tab_id, path, ratio) and ok
                    running.last[path] = ratio
            if progress >= 1 or not ok:
                del self.running[tab_id]
                if not ok:
                    # A write failed mid-animation: leave the panes at the final ratios, not in between.
                    self.log("write failed in %s; snapping to the final ratios" % tab_id)
                    for step in running.steps:
                        self._write(tab_id, step.path, step.end)
                try:
                    self._remember(tab_id, self.client.export(tab_id))
                except HerdrError:
                    self.known.pop(tab_id, None)
        expired = [pane_id for pane_id, until in self.flashes.items() if now >= until]
        for pane_id in expired:
            del self.flashes[pane_id]
            self._clear_title(pane_id)
        if expired and not self.flashes:
            self.flash_store.save(set())

    def _clear_title(self, pane_id: str) -> None:
        try:
            self.client.title(pane_id, None)
        except HerdrError:
            pass

    def clear_flashes(self) -> None:
        """Clear every title this plugin set: the live ones, and any left by a worker that died."""
        for pane_id in set(self.flashes) | self.flash_store.load():
            self._clear_title(pane_id)
        self.flashes.clear()
        self.flash_store.save(set())

    # Loop ------------------------------------------------------------------

    def timeout(self) -> Optional[float]:
        """Seconds until the next frame or flash expiry; None, block indefinitely, when nothing is due."""
        waits = []
        if self.running:
            waits.append(1.0 / self.config.get().fps)
        if self.flashes:
            waits.append(max(0.0, min(self.flashes.values()) - self.clock()))
        return min(waits) if waits else None

    def run(self, subscription: Any, stop: Callable[[], bool], wake_fd: Optional[int] = None) -> None:
        """Serve one event subscription until it closes, a signal arrives, or the plugin goes away."""
        self.check_plugin(force=True)
        if self.gone:
            return
        if self.config.get().enabled:
            try:
                self.prime()
            except HerdrError as error:
                self.log("prime failed: %s" % error)
        while not stop() and not self.gone:
            watched = [subscription] + ([wake_fd] if wake_fd is not None else [])
            ready, _, _ = self.wait(watched, [], [], self.timeout())
            if wake_fd is not None and wake_fd in ready:
                try:
                    os.read(wake_fd, 4096)
                except OSError:
                    pass
            if subscription in ready:
                for data in subscription.read():
                    self.on_event(data)
            self.tick()
