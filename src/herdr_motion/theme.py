"""Resolve HerdR's theme the way HerdR does, so the picker matches the host UI.

HerdR picks a built-in palette by [theme] name (or dark_name/light_name when
auto_switch is on), then layers [theme.custom] and the matching
[theme.custom.dark] or [theme.custom.light] table on top. The built-in
palettes below are the published values of the themes HerdR ships; tokens a
theme does not define fall back to its nearest equivalent.

Bundled rather than imported from a sibling plugin so this plugin works alone.
"""
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

TOKENS = (
    "accent", "panel_bg", "sidebar_bg", "active_row_bg", "selection_bg", "surface0",
    "surface1", "surface_dim", "overlay0", "overlay1", "text", "subtext0", "mauve",
    "green", "yellow", "red", "blue", "teal", "peach",
)


def _palette(base, mantle, crust, surface0, surface1, overlay0, overlay1, text, subtext0,
             accent, mauve, green, yellow, red, blue, teal, peach, selection=None) -> Dict[str, str]:
    return dict(
        panel_bg=base, sidebar_bg=mantle, surface_dim=crust, active_row_bg=surface0,
        selection_bg=selection or surface1, surface0=surface0, surface1=surface1,
        overlay0=overlay0, overlay1=overlay1, text=text, subtext0=subtext0, accent=accent,
        mauve=mauve, green=green, yellow=yellow, red=red, blue=blue, teal=teal, peach=peach,
    )


BUILTIN: Dict[str, Dict[str, str]] = {
    "catppuccin": _palette("#1e1e2e", "#181825", "#11111b", "#313244", "#45475a", "#6c7086",
                           "#7f849c", "#cdd6f4", "#a6adc8", "#f5c2e7", "#cba6f7", "#a6e3a1",
                           "#f9e2af", "#f38ba8", "#89b4fa", "#94e2d5", "#fab387"),
    "catppuccin-latte": _palette("#eff1f5", "#e6e9ef", "#dce0e8", "#ccd0da", "#bcc0cc", "#9ca0b0",
                                 "#8c8fa1", "#4c4f69", "#6c6f85", "#ea76cb", "#8839ef", "#40a02b",
                                 "#df8e1d", "#d20f39", "#1e66f5", "#179299", "#fe640b"),
    "tokyo-night": _palette("#1a1b26", "#16161e", "#13131a", "#292e42", "#3b4261", "#565f89",
                            "#737aa2", "#c0caf5", "#a9b1d6", "#7aa2f7", "#bb9af7", "#9ece6a",
                            "#e0af68", "#f7768e", "#7aa2f7", "#73daca", "#ff9e64"),
    "dracula": _palette("#282a36", "#21222c", "#191a21", "#343746", "#44475a", "#6272a4",
                        "#7a86b8", "#f8f8f2", "#bfbfbf", "#bd93f9", "#ff79c6", "#50fa7b",
                        "#f1fa8c", "#ff5555", "#8be9fd", "#8be9fd", "#ffb86c"),
    "nord": _palette("#2e3440", "#2b303b", "#242933", "#3b4252", "#434c5e", "#4c566a",
                     "#616e88", "#eceff4", "#d8dee9", "#88c0d0", "#b48ead", "#a3be8c",
                     "#ebcb8b", "#bf616a", "#81a1c1", "#8fbcbb", "#d08770"),
    "gruvbox": _palette("#282828", "#1d2021", "#141617", "#3c3836", "#504945", "#665c54",
                        "#7c6f64", "#ebdbb2", "#d5c4a1", "#fabd2f", "#d3869b", "#b8bb26",
                        "#fabd2f", "#fb4934", "#83a598", "#8ec07c", "#fe8019"),
    "one-dark": _palette("#282c34", "#21252b", "#1b1f23", "#2c313a", "#3e4451", "#5c6370",
                         "#7f848e", "#abb2bf", "#9da5b4", "#61afef", "#c678dd", "#98c379",
                         "#e5c07b", "#e06c75", "#61afef", "#56b6c2", "#d19a66"),
    "solarized": _palette("#002b36", "#00252f", "#001e26", "#073642", "#0a4655", "#586e75",
                          "#657b83", "#93a1a1", "#839496", "#268bd2", "#6c71c4", "#859900",
                          "#b58900", "#dc322f", "#268bd2", "#2aa198", "#cb4b16"),
    "kanagawa": _palette("#1f1f28", "#16161d", "#121218", "#2a2a37", "#363646", "#54546d",
                         "#727169", "#dcd7ba", "#c8c093", "#7e9cd8", "#957fb8", "#98bb6c",
                         "#e6c384", "#e82424", "#7e9cd8", "#7aa89f", "#ffa066"),
    "rose-pine": _palette("#191724", "#1f1d2e", "#13111c", "#26233a", "#403d52", "#6e6a86",
                          "#908caa", "#e0def4", "#c4c1d8", "#ebbcba", "#c4a7e7", "#31748f",
                          "#f6c177", "#eb6f92", "#9ccfd8", "#9ccfd8", "#ea9a97"),
    "vesper": _palette("#101010", "#0b0b0b", "#080808", "#1c1c1c", "#282828", "#505050",
                       "#7a7a7a", "#ffffff", "#a0a0a0", "#ffc799", "#c7b8ff", "#99ffe4",
                       "#ffc799", "#ff8080", "#a0c8ff", "#99ffe4", "#ffb380"),
}
# The terminal theme defers to the host's ANSI colours; approximate with a neutral dark.
BUILTIN["terminal"] = _palette("#000000", "#000000", "#000000", "#1c1c1c", "#303030", "#585858",
                               "#808080", "#d0d0d0", "#a8a8a8", "#5fafff", "#af87ff", "#87d787",
                               "#ffd75f", "#ff5f5f", "#5fafff", "#5fd7d7", "#ffaf5f")
DEFAULT_THEME = "catppuccin"
NAMED = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#00ff00",
    "blue": "#0000ff", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff",
    "gray": "#808080", "grey": "#808080",
}


def parse_color(value: str) -> Optional[str]:
    """Accept #rrggbb, rgb(r,g,b) and basic names; "reset" means the terminal default."""
    value = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    match = re.fullmatch(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", value)
    if match and all(int(part) <= 255 for part in match.groups()):
        return "#%02x%02x%02x" % tuple(int(part) for part in match.groups())
    if value == "reset":
        return "reset"
    return NAMED.get(value)


def read_theme_tables(source: str) -> Dict[str, Dict[str, str]]:
    """Read the [theme] tables with a tolerant line parser; no TOML dependency on Python 3.9."""
    tables: Dict[str, Dict[str, str]] = {}
    current = None
    for raw in source.splitlines():
        header = re.fullmatch(r"\[\s*([A-Za-z0-9_.\-]+)\s*\]", raw.strip())
        if header:
            name = header.group(1)
            current = name if name == "theme" or name.startswith("theme.") else None
            if current is not None:
                tables.setdefault(current, {})
            continue
        if current is None:
            continue
        match = re.fullmatch(r"\s*([A-Za-z0-9_]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(true|false))\s*(?:#.*)?", raw)
        if match:
            value = match.group(2) if match.group(2) is not None else (
                match.group(3) if match.group(3) is not None else match.group(4))
            tables[current][match.group(1)] = value
    return tables


def system_appearance(env: Mapping[str, str]) -> str:
    """Best-effort dark/light detection matching HerdR's auto_switch intent."""
    forced = env.get("HERDR_LAYOUTS_APPEARANCE", "").lower()
    if forced in ("dark", "light"):
        return forced
    colorfgbg = env.get("COLORFGBG", "")
    if ";" in colorfgbg:
        try:
            return "light" if int(colorfgbg.rsplit(";", 1)[1]) in (7, 15) else "dark"
        except ValueError:
            pass
    if os.uname().sysname == "Darwin":
        try:
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                    capture_output=True, text=True, timeout=0.5, check=False)
            return "dark" if "dark" in result.stdout.lower() else "light"
        except (OSError, subprocess.SubprocessError):
            pass
    return "dark"


@dataclass(frozen=True)
class ResolvedTheme:
    name: str
    appearance: str
    colors: Dict[str, str]
    notes: Tuple[str, ...] = ()


def resolve_theme(source: str, env: Mapping[str, str], appearance: Optional[str] = None) -> ResolvedTheme:
    tables = read_theme_tables(source)
    theme = tables.get("theme", {})
    notes: List[str] = []
    auto = theme.get("auto_switch", "false") == "true"
    mode = appearance or (system_appearance(env) if auto else "dark")
    if auto:
        name = theme.get("light_name" if mode == "light" else "dark_name") or theme.get("name") or DEFAULT_THEME
    else:
        name = theme.get("name") or DEFAULT_THEME
    if name not in BUILTIN:
        notes.append("unknown HerdR theme %r; using %s" % (name, DEFAULT_THEME))
        name = DEFAULT_THEME
    colors = dict(BUILTIN[name])
    layers = [tables.get("theme.custom", {})]
    if auto:
        layers.append(tables.get("theme.custom." + mode, {}))
    transparent = False
    for layer in layers:
        for key, value in layer.items():
            if key not in TOKENS:
                continue
            parsed = parse_color(value)
            if parsed is None:
                notes.append("ignored theme color %s = %r" % (key, value))
            elif parsed == "reset":
                transparent = transparent or key == "panel_bg"
            else:
                colors[key] = parsed
    if transparent:
        # A transparent panel shows the terminal background, which the theme
        # cannot know; the darkest surface token is the closest stand-in.
        colors["panel_bg"] = colors["surface_dim"]
    if not auto:
        # Without auto_switch, infer light themes from the background itself.
        mode = "light" if _luminance(colors["panel_bg"]) > 0.5 else "dark"
    return ResolvedTheme(name, mode, colors, tuple(notes))


def _rgb(value: str) -> Tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _luminance(value: str) -> float:
    red, green, blue = (channel / 255 for channel in _rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def color_mode(env: Mapping[str, str]) -> str:
    if "NO_COLOR" in env or env.get("TERM") == "dumb":
        return "none"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    return "256"


def nearest_256(rgb) -> int:
    levels = (0, 95, 135, 175, 215, 255)
    indexes = [min(range(6), key=lambda i: abs(levels[i] - c)) for c in rgb]
    cube = 16 + 36 * indexes[0] + 6 * indexes[1] + indexes[2]
    gray = min(range(24), key=lambda i: sum((8 + i * 10 - c) ** 2 for c in rgb))
    cube_error = sum((levels[i] - c) ** 2 for i, c in zip(indexes, rgb))
    gray_error = sum((8 + gray * 10 - c) ** 2 for c in rgb)
    return 232 + gray if gray_error < cube_error else cube


@dataclass(frozen=True)
class Palette:
    """Colour escapes plus the semantic roles the picker paints with."""

    mode: str = "truecolor"
    colors: Dict[str, str] = field(default_factory=lambda: dict(BUILTIN[DEFAULT_THEME]))
    appearance: str = "dark"

    def hex(self, key: str) -> str:
        if key.startswith("#"):
            return key
        return self.colors.get(key) or BUILTIN[DEFAULT_THEME].get(key) or BUILTIN[DEFAULT_THEME]["text"]

    def _escape(self, key: str, background: bool) -> str:
        if self.mode == "none":
            return ""
        rgb = _rgb(self.hex(key))
        channel = 48 if background else 38
        if self.mode == "truecolor":
            return "\x1b[%d;2;%d;%d;%dm" % ((channel,) + rgb)
        return "\x1b[%d;5;%dm" % (channel, nearest_256(rgb))

    def fg(self, key: str) -> str:
        return self._escape(key, False)

    def bg(self, key: str) -> str:
        return self._escape(key, True)

    def mix(self, first: str, second: str, amount: float) -> str:
        """Blend two colours; amount 0 is all first, 1 is all second."""
        a, b = _rgb(self.hex(first)), _rgb(self.hex(second))
        return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(a, b))

    def tint(self, key: str, amount: float) -> str:
        """A colour washed toward the panel background, for fills that sit behind text."""
        return self.mix("panel_bg", key, amount)

    def role(self, name: str) -> str:
        """Semantic colours, all derived from HerdR theme tokens."""
        light = self.appearance == "light"
        roles = {
            "border": self.mix("panel_bg", "overlay0", 0.75 if light else 0.55),
            "border_dim": self.mix("panel_bg", "overlay0", 0.4 if light else 0.28),
            "border_selected": self.hex("accent"),
            "you_fill": self.tint("accent", 0.22 if light else 0.18),
            "you_fill_selected": self.tint("accent", 0.4 if light else 0.36),
            "new_fill": self.tint("yellow", 0.14 if light else 0.08),
            "new_fill_selected": self.tint("yellow", 0.26 if light else 0.18),
            "other_fill": self.hex("surface0") if not light else self.mix("panel_bg", "surface0", 0.6),
            "other_fill_selected": self.hex("surface1") if not light else self.hex("surface0"),
            "muted_fill": self.mix("panel_bg", "surface0", 0.45),
            "chip": self.hex("surface0"),
            "you_ink": self.hex("accent"),
            "new_ink": self.hex("yellow"),
            "other_ink": self.hex("subtext0"),
            "muted_ink": self.hex("overlay0"),
            "favorite": self.hex("yellow"),
        }
        return roles[name]

    @property
    def reset(self) -> str:
        return "" if self.mode == "none" else "\x1b[0m"

    @property
    def bold(self) -> str:
        return "" if self.mode == "none" else "\x1b[1m"

    def paint(self, text: str, key: str = "text", bold: bool = False) -> str:
        return self.fg(key) + (self.bold if bold else "") + text + self.reset


def load_palette(config_path: Path, env: Mapping[str, str]) -> Tuple[Palette, ResolvedTheme]:
    try:
        source = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        source = ""
    resolved = resolve_theme(source, env)
    return Palette(color_mode(env), resolved.colors, resolved.appearance), resolved
