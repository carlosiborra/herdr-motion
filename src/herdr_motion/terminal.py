"""Terminal lifecycle, incremental key decoding and flicker-free frame output."""
import os
import select
import signal
import termios
import tty
from typing import List, Optional, Sequence, Tuple

_SEQUENCES = {
    b"\x1b[A": "up", b"\x1b[B": "down", b"\x1b[C": "right", b"\x1b[D": "left",
    b"\x1bOA": "up", b"\x1bOB": "down", b"\x1bOC": "right", b"\x1bOD": "left",
    b"\x1b[Z": "shift_tab", b"\x1b[5~": "page_up", b"\x1b[6~": "page_down",
    b"\x1b[H": "home", b"\x1b[F": "end",
}
_CONTROL = {13: "enter", 10: "enter", 9: "tab", 3: "interrupt", 21: "page_up", 4: "page_down",
            127: "backspace", 8: "backspace"}


class TerminalExit(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class KeyDecoder:
    """Decode bytes as they arrive so pasted or batched input never splits a sequence."""

    def __init__(self) -> None:
        self.pending = bytearray()

    def feed(self, data: bytes) -> Tuple[str, ...]:
        self.pending.extend(data)
        keys: List[str] = []
        while self.pending:
            first = self.pending[0]
            if first == 27:
                if len(self.pending) == 1:
                    break
                if self.pending[1] not in (ord("["), ord("O")):
                    del self.pending[0]
                    keys.append("escape")
                    continue
                end = next(
                    (i for i in range(2, len(self.pending)) if 64 <= self.pending[i] <= 126),
                    None,
                )
                if end is None:
                    if len(self.pending) > 32:
                        self.pending.clear()
                    break
                sequence = bytes(self.pending[: end + 1])
                del self.pending[: end + 1]
                keys.append(_SEQUENCES.get(sequence, "unknown"))
            elif first < 128:
                del self.pending[0]
                keys.append(_CONTROL.get(first, chr(first)))
            else:
                del self.pending[0]
                keys.append("unknown")
        return tuple(keys)

    def flush_escape(self) -> Tuple[str, ...]:
        if self.pending and self.pending[0] == 27:
            self.pending.clear()
            return ("escape",)
        return ()


class Screen:
    """Write only changed lines, so navigation repaints a few rows instead of the popup."""

    def __init__(self, write) -> None:
        self._write = write
        self._previous: List[str] = []
        self._size: Optional[Tuple[int, int]] = None

    def draw(self, lines: Sequence[str], size: Tuple[int, int]) -> None:
        if size != self._size:
            self._previous = []
            self._size = size
            self._write("\x1b[0m\x1b[2J")
        output = []
        for row, line in enumerate(lines):
            if row < len(self._previous) and self._previous[row] == line:
                continue
            output.append("\x1b[%d;1H%s\x1b[0m\x1b[K" % (row + 1, line))
        for row in range(len(lines), len(self._previous)):
            output.append("\x1b[%d;1H\x1b[0m\x1b[K" % (row + 1))
        self._previous = list(lines)
        if output:
            self._write("".join(output))


class Terminal:
    def __init__(self, stdin, stdout) -> None:
        self.stdin, self.stdout = stdin, stdout
        self.fd = stdin.fileno()
        self.attributes = None
        self.signals = {}
        self.decoder = KeyDecoder()
        self.screen = Screen(self.write)

    def write(self, value: str) -> None:
        self.stdout.write(value)
        self.stdout.flush()

    @staticmethod
    def _stop(signum, frame):
        raise TerminalExit(signum)

    def __enter__(self) -> "Terminal":
        self.attributes = termios.tcgetattr(self.fd)
        try:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                self.signals[sig] = signal.getsignal(sig)
                signal.signal(sig, self._stop)
            tty.setraw(self.fd)
            self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J\x1b[H")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.attributes is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.attributes)
        finally:
            for sig, handler in self.signals.items():
                signal.signal(sig, handler)
            try:
                self.write("\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")
            except (OSError, ValueError):
                pass

    def size(self) -> Tuple[int, int]:
        try:
            size = os.get_terminal_size(self.stdout.fileno())
            return max(1, size.columns), max(1, size.lines)
        except OSError:
            return 80, 24

    def keys(self, timeout: float = 0.1) -> Tuple[str, ...]:
        """Return decoded keys, or an empty tuple on timeout so callers can notice resizes."""
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if ready:
            data = os.read(self.fd, 1024)
            return self.decoder.feed(data) if data else ("escape",)
        return self.decoder.flush_escape()
