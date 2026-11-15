"""HerdR socket API: one connection per request, plus a long-lived event subscription.

The ``herdr`` CLI has no generic API call, and the three things this plugin needs (the
``events.subscribe`` stream, ``layout.export`` / ``layout.set_split_ratio``, and
``pane.report_metadata``) exist only on the newline-delimited JSON socket, so it speaks that
protocol directly.
"""
import json
import socket
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional, Sequence


SOURCE = "herdr-motion"


class HerdrError(RuntimeError):
    pass


class Client:
    def __init__(self, path: Path, timeout_seconds: float = 2.0) -> None:
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds

    def call(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        request = json.dumps({"id": SOURCE, "method": method, "params": dict(params)})
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.path))
                connection.sendall(request.encode("utf-8") + b"\n")
                buffer = b""
                while not buffer.endswith(b"\n"):
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
            payload = json.loads(buffer)
        except (OSError, ValueError) as exc:
            raise HerdrError("%s failed: %s" % (method, exc)) from exc
        if not isinstance(payload, dict):
            raise HerdrError("%s returned a malformed response" % method)
        if isinstance(payload.get("error"), dict):
            raise HerdrError("%s failed: %s" % (method, payload["error"].get("message", "unknown error")))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise HerdrError("%s returned no result" % method)
        return result

    def export(self, tab_id: str) -> Mapping[str, Any]:
        layout = self.call("layout.export", {"tab_id": tab_id}).get("layout")
        if not isinstance(layout, dict) or not isinstance(layout.get("root"), dict):
            raise HerdrError("layout export is malformed")
        return layout

    def set_ratio(self, tab_id: str, path: Sequence[bool], ratio: float) -> None:
        self.call("layout.set_split_ratio", {"tab_id": tab_id, "path": list(path), "ratio": round(ratio, 4)})

    def tab_ids(self) -> List[str]:
        snapshot = self.call("session.snapshot", {}).get("snapshot")
        tabs = snapshot.get("tabs") if isinstance(snapshot, dict) else None
        return [tab["tab_id"] for tab in tabs or [] if isinstance(tab, dict) and isinstance(tab.get("tab_id"), str)]

    def plugin_enabled(self, plugin_id: str) -> bool:
        """False only when HerdR lists no such plugin, or lists it disabled."""
        plugins = self.call("plugin.list", {"plugin_id": plugin_id}).get("plugins")
        for plugin in plugins if isinstance(plugins, list) else []:
            if isinstance(plugin, dict) and plugin.get("plugin_id") == plugin_id:
                return bool(plugin.get("enabled", True))
        return False

    def title(self, pane_id: str, text: Optional[str], ttl_ms: Optional[int] = None) -> None:
        """Set or clear this plugin's own title for a pane; titles reported by other sources are untouched.

        ``ttl_ms`` makes HerdR drop the title by itself, so a flash cannot outlive a dead worker.
        """
        params: dict = {"pane_id": pane_id, "source": SOURCE}
        params.update({"title": text} if text else {"clear_title": True})
        if text and ttl_ms:
            params["ttl_ms"] = int(ttl_ms)
        self.call("pane.report_metadata", params)


class Subscription:
    """Yields events as they arrive; ``poll(timeout)`` returns those ready within the timeout."""

    TYPES = ("layout.updated", "tab.created", "tab.closed")

    def __init__(self, path: Path) -> None:
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.connect(str(path))
        request = {"id": SOURCE + "-events", "method": "events.subscribe",
                   "params": {"subscriptions": [{"type": kind} for kind in self.TYPES]}}
        self.socket.sendall(json.dumps(request).encode("utf-8") + b"\n")
        self.buffer = b""

    def fileno(self) -> int:
        return self.socket.fileno()

    def read(self) -> Iterator[Mapping[str, Any]]:
        chunk = self.socket.recv(262144)
        if not chunk:
            raise HerdrError("event stream closed")
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and isinstance(message.get("data"), dict):
                yield message["data"]

    def close(self) -> None:
        try:
            self.socket.close()
        except OSError:
            pass
