"""Decide which effect a layout change deserves. Pure: layouts in, actions out.

HerdR reports every change as a fresh layout for the tab. Comparing it with
the previous one tells what happened:

- a pane appeared      grow it open from its edge
- a pane disappeared   rebalance the row or column it left
- panes traded places  flash the panes that moved
- only ratios changed  nothing: a resize by hand, or one of our own frames

Our own animation frames only change ratios, so they never trigger new effects.
"""
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .tree import (
    Path, balanced_ratio, clamp, leaves, node_at, parent_of, rectangles, run_paths, run_root, signature,
    MAX_RATIO, MIN_RATIO,
)


@dataclass(frozen=True)
class Step:
    path: Path
    start: float
    end: float


@dataclass(frozen=True)
class Animate:
    tab_id: str
    steps: Tuple[Step, ...]
    reason: str


@dataclass(frozen=True)
class Flash:
    tab_id: str
    pane_ids: Tuple[str, ...]


Action = Any  # Animate | Flash


@dataclass(frozen=True)
class Settings:
    grow: bool = True
    rebalance_on_close: bool = True
    flash_moves: bool = False
    grow_depth: float = 1.0
    # A pane split into a row of columns (or a column of rows) grows into an equal share,
    # so three columns end as thirds rather than 50 / 25 / 25.
    even_out: bool = True


def grow_steps(root: Mapping[str, Any], pane_id: str, depth: float = 1.0) -> Tuple[Step, ...]:
    """Open the split holding a new pane from collapsed (depth 1) to its real ratio."""
    found = parent_of(root, pane_id)
    if found is None:
        return ()
    path, second = found
    node = node_at(root, path)
    end = clamp(float(node["ratio"]))  # type: ignore[index]
    depth = min(1.0, max(0.0, depth))
    start = end + (MAX_RATIO - end) * depth if second else end - (end - MIN_RATIO) * depth
    return (Step(path, clamp(start), end),)


def rebalance_steps(root: Mapping[str, Any], around: Path) -> Tuple[Step, ...]:
    """Equal shares along the row or column at ``around`` (the run it belongs to)."""
    node = node_at(root, around)
    if node is None or node.get("type") == "pane":
        return ()
    steps = []
    for path in run_paths(root, run_root(root, around)):
        split = node_at(root, path)
        start = clamp(float(split["ratio"]))  # type: ignore[index]
        end = balanced_ratio(split)  # type: ignore[arg-type]
        if abs(end - start) > 0.01:
            steps.append(Step(path, start, end))
    return tuple(steps)


def _moved(before: Mapping[str, Any], after: Mapping[str, Any]) -> Tuple[str, ...]:
    old, new = rectangles(before), rectangles(after)
    return tuple(sorted(pane for pane in new if pane in old
                        and any(abs(a - b) > 0.02 for a, b in zip(old[pane], new[pane]))))


def decide(previous: Optional[Mapping[str, Any]], layout: Mapping[str, Any], settings: Settings) -> List[Action]:
    """Actions for one tab, given its previous and current layout.export layouts."""
    if previous is None or layout.get("zoomed") or previous.get("zoomed"):
        return []
    before, after = previous.get("root"), layout.get("root")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    tab_id = str(layout.get("tab_id"))
    if signature(before) == signature(after):
        return []
    old_panes, new_panes = set(leaves(before)), set(leaves(after))
    added, removed = new_panes - old_panes, old_panes - new_panes

    if len(added) == 1 and not removed:
        pane = next(iter(added))
        steps = grow_steps(after, pane, settings.grow_depth) if settings.grow else ()
        if settings.even_out:
            found = parent_of(after, pane)
            if found is not None:
                grown = {step.path: step for step in steps}
                for step in rebalance_steps(after, found[0]):
                    if step.path in grown:
                        grown[step.path] = Step(step.path, grown[step.path].start, step.end)
                    else:
                        grown[step.path] = step
                steps = tuple(sorted(grown.values(), key=lambda item: len(item.path)))
        return [Animate(tab_id, steps, "grow")] if steps else []

    if removed and not added:
        if settings.rebalance_on_close:
            steps: Tuple[Step, ...] = ()
            for pane in removed:
                found = parent_of(before, pane)
                if found is None:
                    continue
                # The parent split collapsed into the surviving sibling, which now sits at
                # the parent's path; the row or column around it gets the space back evenly.
                path = found[0]
                around = path[:-1] if path else path
                node = node_at(after, around)
                if node is not None and node.get("type") != "pane":
                    steps += tuple(step for step in rebalance_steps(after, around)
                                   if step.path not in {s.path for s in steps})
            if steps:
                return [Animate(tab_id, steps, "close")]
        return []

    if not added and not removed and settings.flash_moves:
        moved = _moved(before, after)
        if moved:
            return [Flash(tab_id, moved)]
    return []


def at(steps: Sequence[Step], t: float) -> List[Tuple[Path, float]]:
    return [(step.path, clamp(step.start + (step.end - step.start) * t)) for step in steps]


def _spring(t: float, damping: float = 0.6, frequency: float = 9.0) -> float:
    """Step response of a damped spring: starts at rest, overshoots about 9% near the middle,
    settles before the end. The final frame is pinned to exactly 1 by the caller."""
    if t >= 1:
        return 1.0
    decay = damping * frequency
    ringing = frequency * math.sqrt(1 - damping * damping)
    return 1 - math.exp(-decay * t) * (math.cos(ringing * t) + decay / ringing * math.sin(ringing * t))


EASINGS: Dict[str, Any] = {
    "linear": lambda t: t,
    "out-cubic": lambda t: 1 - (1 - t) ** 3,
    "out-quint": lambda t: 1 - (1 - t) ** 5,
    "out-back": lambda t: 1 + 2.2 * (t - 1) ** 3 + 1.2 * (t - 1) ** 2,
    # A damped spring: overshoots by about 9% and settles, so new panes feel like they land.
    "spring": lambda t: _spring(t),
    "in-out": lambda t: 3 * t * t - 2 * t ** 3,
}
