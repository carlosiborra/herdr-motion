"""The settings popup: choose a style while a miniature tab plays it, and switch effects on or off.

Pure parts (the model, the preview geometry and the frame renderer) are kept apart from the
terminal loop so they can be tested without a terminal. Every change is written to motion.json
straight away; the daemon re-reads that file on its next frame, so a choice takes effect in the
real panes while the popup is still open.
"""
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import Config, ConfigFile
from .engine import EASINGS
from .styles import DESCRIPTIONS, STYLES, names
from .theme import Palette

# Switches shown under the styles: (config key, label, what it does).
SWITCHES: Tuple[Tuple[str, str, str], ...] = (
    ("enabled", "Effects", "master switch for every effect"),
    ("grow", "Grow new panes", "a new pane slides open from its edge"),
    ("even_out", "Even out rows", "a split row ends as equal shares"),
    ("rebalance_on_close", "Rebalance on close", "the row a pane left shares its space"),
    ("flash_moves", "Flash swaps", "opt in: swapped panes show a mark in their title"),
)
SPEEDS = (0, 130, 200, 260, 300, 420, 480, 700, 1000)

# The preview plays a short story on a miniature tab of columns: a pane opens and the row evens
# out, a pane closes and the rest share its space, two panes trade places. Each scene is
# (label, effect, start widths, end widths, names); widths are fractions of the tab per column.
SCENES = (
    ("new pane", "grow", (0.5, 0.5, 0.0), (1 / 3, 1 / 3, 1 / 3), ("you", "shell", "new")),
    ("close", "close", (1 / 3, 0.0, 2 / 3), (0.5, 0.0, 0.5), ("you", "", "new")),
    ("swap", "swap", (0.5, 0.5), (0.5, 0.5), ("you", "shell")),
)
HOLD = 0.6  # seconds each scene rests after its animation


@dataclass
class Model:
    raw: Dict[str, object]  # motion.json as written by the user
    config: Config
    row: int = 0  # index into rows(): styles first, then switches, then speed
    started: float = 0.0
    message: str = ""

    def rows(self) -> List[Tuple[str, str]]:
        return ([("style", name) for name in names()] + [("switch", key) for key, _, _ in SWITCHES]
                + [("speed", "duration_ms")])

    def current(self) -> Tuple[str, str]:
        return self.rows()[self.row]


def preview_style(model: Model) -> Config:
    """The style under the cursor, with the user's own overrides, as the preview should play it."""
    kind, value = model.current()
    if kind != "style":
        return model.config
    from .config import parse
    return parse({**model.raw, "style": value})


def scene_at(config: Config, elapsed: float) -> Tuple[str, Tuple[float, ...], Tuple[str, ...], float, bool]:
    """The scene playing at ``elapsed``: label, column widths, pane names, progress, and flash state."""
    duration = max(0.0, config.duration_ms / 1000.0)
    length = duration + HOLD
    elapsed %= length * len(SCENES)
    index = int(elapsed // length)
    label, effect, start, end, panes = SCENES[index]
    t = elapsed - index * length
    progress = 1.0 if duration == 0 else min(1.0, t / duration)
    enabled = config.enabled and {"grow": config.grow, "close": config.rebalance_on_close,
                                  "swap": config.flash_moves}[effect]
    if effect == "grow" and enabled and not config.even_out:
        end = (0.5, 0.25, 0.25)  # without even-out the new pane only takes half of its neighbour
    if effect == "grow" and enabled and config.grow_depth < 1:
        # A partial grow starts part of the way open.
        depth = config.grow_depth
        start = tuple(a + (b - a) * (1 - depth) for a, b in zip(start, end))
    if not enabled:
        progress = 1.0
    curve = EASINGS.get(config.grow_easing if effect == "grow" else config.easing, EASINGS["out-cubic"])
    eased = curve(progress) if progress < 1 else 1.0
    widths = tuple(a + (b - a) * eased for a, b in zip(start, end))
    if effect == "swap":
        # A swap has no motion, only the flash, so its bar follows the flash instead.
        flash = config.flash_ms / 1000.0
        progress = min(1.0, t / flash) if enabled and flash else 1.0
        if enabled and t < flash:
            return label, widths, (panes[1], panes[0]), progress, True
    return label, widths, panes, progress, False


LINES = {
    frozenset(): " ", frozenset("EW"): "─", frozenset("NS"): "│", frozenset("ES"): "╭", frozenset("WS"): "╮",
    frozenset("EN"): "╰", frozenset("WN"): "╯", frozenset("NSE"): "├", frozenset("NSW"): "┤",
    frozenset("EWS"): "┬", frozenset("EWN"): "┴", frozenset("NSEW"): "┼",
}


def preview_boxes(width: int, height: int, widths: Sequence[float]) -> List[Tuple[int, int, int, int, int]]:
    """Column boxes (index, left, top, right, bottom) sharing border cells. Columns narrower than
    a cell are dropped, so a closing pane disappears and an opening one appears at its edge."""
    total = sum(widths) or 1.0
    edges, acc = [0], 0.0
    for w in widths:
        acc += w / total
        edges.append(round(acc * (width - 1)))
    boxes = []
    for index in range(len(widths)):
        left, right = edges[index], edges[index + 1]
        if right - left >= 1:
            boxes.append((index, left, 0, right, height - 1))
    # Close any rounding gap so the outer border is whole.
    if boxes:
        last = boxes[-1]
        boxes[-1] = (last[0], last[1], 0, width - 1, height - 1)
    return boxes


def preview(width: int, height: int, widths: Sequence[float], names_: Sequence[str], flashing: bool,
            palette: Palette, mark: str) -> List[str]:
    """A miniature tab drawn the way Herdr draws panes: shared borders, filled interiors."""
    boxes = preview_boxes(width, height, widths)
    links: List[List[set]] = [[set() for _ in range(width)] for _ in range(height)]
    for _, left, top, right, bottom in boxes:
        for col in range(left, right):
            for row in (top, bottom):
                links[row][col].add("E")
                links[row][col + 1].add("W")
        for row in range(top, bottom):
            for col in (left, right):
                links[row][col].add("S")
                links[row + 1][col].add("N")
    border = palette.role("border_selected") if flashing else palette.role("border")
    cells = [[(LINES.get(frozenset(cell), "┼"), border, None) for cell in row] for row in links]
    for index, left, top, right, bottom in boxes:
        name = names_[index] if index < len(names_) else ""
        role = {"you": "you", "new": "new"}.get(name, "other")
        fill, ink = palette.role(role + "_fill"), palette.role(role + "_ink")
        for row in range(top + 1, bottom):
            for col in range(left + 1, right):
                cells[row][col] = (" ", border, fill)
        label = (mark + " " + name) if flashing and name else name
        inner = right - left - 1
        if inner < len(label):
            label = label[:1] if name else ""
        if bottom - top >= 2 and label and inner >= 1:
            row, start = (top + bottom) // 2, left + 1 + (inner - len(label)) // 2
            for offset, ch in enumerate(label):
                cells[row][start + offset] = (ch, ink, fill)
    return [_paint_row(row, palette) for row in cells]


def _paint_row(row: Sequence[Tuple[str, str, Optional[str]]], palette: Palette) -> str:
    """One canvas row as escapes, grouping runs of one style so a row carries few escapes."""
    parts, run, style = [], [], None
    for ch, fg, bg in row:
        if (fg, bg) != style and run and style is not None:
            parts.append(palette.fg(style[0]) + (palette.bg(style[1]) if style[1] else "") + "".join(run) + palette.reset)
            run = []
        run.append(ch)
        style = (fg, bg)
    if run and style is not None:
        parts.append(palette.fg(style[0]) + (palette.bg(style[1]) if style[1] else "") + "".join(run) + palette.reset)
    return "".join(parts)


def _visible(text: str) -> int:
    import re
    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _visible(text))


def render(model: Model, width: int, height: int, palette: Palette, now: float) -> List[str]:
    width, height = max(1, width), max(1, height)
    if width < 56 or height < 18:
        return ["", palette.paint("  Motion", "accent", bold=True), "",
                palette.paint("  Enlarge the popup to at least 56 x 18.", "subtext0")][:height]
    config = model.config
    shown = preview_style(model)
    left_width = 38
    lines: List[str] = [""]
    state = palette.paint("on", "green", bold=True) if config.enabled else palette.paint("off", "red", bold=True)
    lines.append("  " + palette.paint("Motion", "accent", bold=True) + palette.paint("   effects ", "subtext0") + state
                 + palette.paint("   style ", "subtext0") + palette.paint(config.style, "text", bold=True))
    lines.append("")

    left: List[str] = [palette.paint("STYLE", "overlay1", bold=True)]
    rows = model.rows()
    for index, (kind, value) in enumerate(rows):
        selected = index == model.row
        cursor = palette.paint("▌", "accent") if selected else " "
        if kind == "style":
            active = value == config.style
            dot = palette.paint("●", "accent") if active else palette.paint("○", "overlay0")
            name_color = "accent" if selected else ("text" if active else "subtext0")
            text = "%s %s %s" % (cursor, dot, palette.paint(value.ljust(10), name_color, bold=selected or active))
            ms = STYLES[value]["duration_ms"]
            text += palette.paint(("%4d ms" % ms) if ms else " instant", "overlay1")
            left.append(text)
            if index == len(names()) - 1:
                left += ["", palette.paint("EFFECTS", "overlay1", bold=True)]
        elif kind == "switch":
            on = bool(getattr(config, value))
            label = next(label for key, label, _ in SWITCHES if key == value)
            box = palette.paint("[x]", "green") if on else palette.paint("[ ]", "overlay0")
            color = "accent" if selected else ("text" if on else "subtext0")
            left.append("%s %s %s" % (cursor, box, palette.paint(label, color, bold=selected)))
            if index == len(rows) - 2:
                left += ["", palette.paint("SPEED", "overlay1", bold=True)]
        else:
            color = "accent" if selected else "text"
            value_text = "instant" if config.duration_ms == 0 else "%d ms" % config.duration_ms
            custom = "" if "duration_ms" not in model.raw else palette.paint("  custom", "yellow")
            left.append("%s %s %s%s" % (cursor, palette.paint("◂", "overlay1"),
                                        palette.paint(value_text.center(9), color, bold=selected),
                                        palette.paint("▸", "overlay1") + custom))

    right_width = max(20, width - left_width - 6)
    preview_height = max(8, min(height - 12, right_width // 3))
    elapsed = now - model.started
    scene, widths, panes, progress, flashing = scene_at(shown, elapsed)
    right: List[str] = [palette.paint("PREVIEW", "overlay1", bold=True) + palette.paint(
        "  %s" % (shown.style if model.current()[0] == "style" else "current settings"), "subtext0")]
    right += preview(right_width, preview_height, widths, panes, flashing, palette, shown.flash_mark)
    bar_width = max(4, right_width - 14)
    filled = round(bar_width * progress)
    right.append(palette.paint(scene.ljust(10), "accent") + palette.paint("━" * filled, "accent")
                 + palette.paint("─" * (bar_width - filled), "surface1"))
    right.append("")
    kind, value = model.current()
    if kind == "style":
        description = DESCRIPTIONS[value]
        detail = "%s, %s grow" % (STYLES[value]["easing"], STYLES[value]["grow_easing"])
    elif kind == "switch":
        description = next(text for key, _, text in SWITCHES if key == value)
        detail = ""
    else:
        description = "how long each animation takes; ◂ ▸ or h l to change, 0 resets to the style"
        detail = ""
    right.append(palette.paint(description, "text"))
    if detail:
        right.append(palette.paint(detail, "overlay1"))

    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else ""
        b = right[index] if index < len(right) else ""
        lines.append("  " + _pad(a, left_width) + "  " + b)

    body = height - 3
    lines = lines[:body]
    while len(lines) < body:
        lines.append("")
    if model.message:
        lines.append("  " + palette.paint(model.message, "green"))
    else:
        lines.append("")
    keys = [("↑↓", "move"), ("enter", "choose"), ("space", "toggle"), ("◂ ▸", "speed"), ("e", "on/off"),
            ("esc", "close")]
    chip = palette.role("chip")
    lines.append("  " + "  ".join(palette.bg(chip) + palette.fg("text") + palette.bold + " %s " % k + palette.reset
                                  + palette.paint(" " + v, "subtext0") for k, v in keys))
    lines.append("")
    return lines[:height]


class Picker:
    def __init__(self, config: ConfigFile, terminal, palette: Palette,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.file = config
        self.terminal = terminal
        self.palette = palette
        self.clock = clock
        raw = config.raw()
        self.model = Model(raw, config.get(), started=clock())
        if self.model.config.style in names():
            self.model.row = names().index(self.model.config.style)

    def _save(self, message: str, **changes: object) -> None:
        self.file.update(**changes)
        self.model.raw = self.file.raw()
        self.model.config = self.file.get()
        self.model.message = message

    def handle(self, key: str) -> Optional[int]:
        model = self.model
        rows = model.rows()
        kind, value = model.current()
        if key in ("escape", "q", "interrupt"):
            return 0
        if key in ("down", "j", "tab"):
            model.row = min(len(rows) - 1, model.row + 1)
        elif key in ("up", "k", "shift_tab"):
            model.row = max(0, model.row - 1)
        elif key == "home":
            model.row = 0
        elif key == "end":
            model.row = len(rows) - 1
        elif key == "e":
            self._save("Effects %s." % ("off" if model.config.enabled else "on"), enabled=not model.config.enabled)
        elif key in ("enter", " ") and kind == "style":
            # A style brings its own timing, so choosing one drops a custom speed.
            raw = {k: v for k, v in model.raw.items() if k not in ("duration_ms",)}
            raw["style"] = value
            self.file._write(raw)
            self.model.raw, self.model.config = self.file.raw(), self.file.get()
            model.message = "Style %s. Split a pane to see it." % value
        elif key in ("enter", " ") and kind == "switch":
            on = not getattr(model.config, value)
            label = next(label for k, label, _ in SWITCHES if k == value)
            self._save("%s %s." % (label, "on" if on else "off"), **{value: on})
        elif key in ("left", "right", "h", "l") and kind == "speed":
            current = model.config.duration_ms
            if key in ("right", "l"):
                nxt = next((s for s in SPEEDS if s > current), SPEEDS[-1])
            else:
                nxt = next((s for s in reversed(SPEEDS) if s < current), SPEEDS[0])
            self._save("Speed %s." % ("instant" if nxt == 0 else "%d ms" % nxt), duration_ms=nxt)
            model.started = self.clock()
        elif key == "0" and kind == "speed":
            raw = {k: v for k, v in model.raw.items() if k != "duration_ms"}
            self.file._write(raw)
            self.model.raw, self.model.config = self.file.raw(), self.file.get()
            model.message = "Speed follows the style again."
        else:
            return None
        if kind != self.model.current()[0] or key in ("up", "down", "j", "k", "tab", "shift_tab", "home", "end"):
            model.started = self.clock()  # restart the preview story for the new selection
        return None

    def run(self) -> int:
        while True:
            width, height = self.terminal.size()
            self.terminal.screen.draw(render(self.model, width, height, self.palette, self.clock()), (width, height))
            # About 30 frames a second keeps the preview smooth without busy work.
            for key in self.terminal.keys(timeout=1 / 30):
                code = self.handle(key)
                if code is not None:
                    return code
