"""motion.json in the plugin config directory; every key is optional.

{
  "enabled": true,
  "style": "lively",           lively, smooth, snappy, bouncy, gentle, subtle, cinematic, instant
  "fps": 60,                   10 to 60; lower is gentler on busy terminals
  "grow": true,                new panes slide open from their edge
  "rebalance_on_close": true,  the row or column a pane left shares the space evenly
  "even_out": true,            a pane split into a row or column grows into an equal share
  "flash_moves": false         opt in: swapped panes briefly show a mark as their title
}

The style sets duration_ms, easing, grow_easing, grow_depth, flash_ms and flash_mark; any of those keys written here overrides the style.
"""
import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

from .engine import EASINGS, Settings
from .styles import DEFAULT_STYLE, STYLES


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    style: str = DEFAULT_STYLE
    duration_ms: int = 260
    easing: str = "out-cubic"
    grow_easing: str = "spring"
    grow_depth: float = 1.0
    flash_ms: int = 600
    flash_mark: str = "⇄"
    fps: int = 60
    grow: bool = True
    rebalance_on_close: bool = True
    even_out: bool = True
    flash_moves: bool = False

    @property
    def settings(self) -> Settings:
        return Settings(self.grow, self.rebalance_on_close, self.flash_moves,
                        self.grow_depth, self.even_out)


def parse(value: object) -> Config:
    config = Config()
    if not isinstance(value, dict):
        return config
    style = value.get("style")
    changes = dict(STYLES[style] if style in STYLES else STYLES[DEFAULT_STYLE])
    changes["style"] = style if style in STYLES else DEFAULT_STYLE
    for key in ("enabled", "grow", "rebalance_on_close", "even_out", "flash_moves"):
        if isinstance(value.get(key), bool):
            changes[key] = value[key]
    depth = value.get("grow_depth")
    if isinstance(depth, (int, float)) and not isinstance(depth, bool):
        changes["grow_depth"] = min(1.0, max(0.0, float(depth)))
    flash_ms = value.get("flash_ms")
    if isinstance(flash_ms, int) and not isinstance(flash_ms, bool):
        changes["flash_ms"] = max(100, min(3000, flash_ms))
    mark = value.get("flash_mark")
    if isinstance(mark, str) and 0 < len(mark) <= 4:
        changes["flash_mark"] = mark
    duration = value.get("duration_ms")
    if isinstance(duration, int) and not isinstance(duration, bool):
        changes["duration_ms"] = max(0, min(1000, duration))
    for key in ("easing", "grow_easing"):
        if value.get(key) in EASINGS:
            changes[key] = value[key]
    fps = value.get("fps")
    if isinstance(fps, int) and not isinstance(fps, bool):
        changes["fps"] = max(10, min(60, fps))
    return replace(config, **changes)


class ConfigFile:
    """Re-read when the file changes, so edits and the toggle action apply without a restart."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stamp: Optional[float] = None
        self._config = Config()

    def get(self) -> Config:
        try:
            stamp = self.path.stat().st_mtime
        except OSError:
            stamp = None
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._config = parse(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, UnicodeError):
                self._config = Config()
        return self._config

    def raw(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def update(self, **changes: object) -> None:
        """Change only the named keys, so a style switch never pins the style's own values."""
        self._write({**self.raw(), **changes})

    def set_style(self, name: str) -> None:
        self.update(style=name)

    def save(self, config: Config) -> None:
        self._write(asdict(config))

    def _write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".motion-", dir=str(self.path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2)
                handle.write("\n")
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
