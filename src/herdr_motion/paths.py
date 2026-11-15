"""Where the plugin reads settings and keeps runtime files.

HerdR sets HERDR_PLUGIN_CONFIG_DIR (settings), HERDR_PLUGIN_STATE_DIR (locks, pid, logs),
HERDR_SOCKET_PATH and HERDR_PLUGIN_ID for plugin commands. The fallbacks below apply only when the
plugin is run by hand outside HerdR, and follow XDG_CONFIG_HOME / XDG_STATE_HOME.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_PLUGIN_ID = "herdr-motion"


def _xdg(env: Mapping[str, str], variable: str, fallback: str) -> Path:
    configured = env.get(variable)
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path(env.get("HOME") or str(Path.home())) / fallback


@dataclass(frozen=True)
class Paths:
    plugin_id: str
    config_dir: Path
    state_dir: Path
    socket: Path
    herdr_config: Path  # HerdR's config.toml, read only for the theme colours of the picker

    @property
    def settings(self) -> Path:
        return self.config_dir / "motion.json"

    @property
    def tag(self) -> str:
        """One worker per HerdR server: sessions have their own sockets."""
        return hashlib.sha1(str(self.socket).encode("utf-8")).hexdigest()[:12]

    @property
    def lock(self) -> Path:
        return self.state_dir / ("worker-%s.lock" % self.tag)

    @property
    def pid(self) -> Path:
        return self.state_dir / ("worker-%s.pid" % self.tag)

    @property
    def flashes(self) -> Path:
        return self.state_dir / ("flashes-%s.json" % self.tag)

    @property
    def log(self) -> Path:
        return self.state_dir / "worker.log"


def resolve(env: Mapping[str, str]) -> Paths:
    plugin_id = env.get("HERDR_PLUGIN_ID") or DEFAULT_PLUGIN_ID
    config_home = _xdg(env, "XDG_CONFIG_HOME", ".config")
    config_dir = env.get("HERDR_PLUGIN_CONFIG_DIR")
    state_dir = env.get("HERDR_PLUGIN_STATE_DIR")
    socket = env.get("HERDR_SOCKET_PATH")
    herdr_config = env.get("HERDR_CONFIG_PATH")
    return Paths(
        plugin_id=plugin_id,
        config_dir=Path(config_dir) if config_dir else config_home / "herdr" / "plugins" / "config" / plugin_id,
        state_dir=Path(state_dir) if state_dir else _xdg(env, "XDG_STATE_HOME", ".local/state") / "herdr" / plugin_id,
        socket=Path(socket) if socket else config_home / "herdr" / "herdr.sock",
        herdr_config=Path(herdr_config) if herdr_config else config_home / "herdr" / "config.toml",
    )
