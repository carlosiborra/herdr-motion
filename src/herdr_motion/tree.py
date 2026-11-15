"""HerdR split trees as exported by layout.export, and the ratio arithmetic on them.

Paths follow layout.set_split_ratio: booleans from the root, False for the
first child and True for the second. HerdR clamps ratios to 0.1-0.9.
"""
from typing import Any, Dict, List, Mapping, Optional, Tuple

Path = Tuple[bool, ...]
Rect = Tuple[float, float, float, float]
MIN_RATIO, MAX_RATIO = 0.1, 0.9


def clamp(ratio: float) -> float:
    return round(min(MAX_RATIO, max(MIN_RATIO, ratio)), 4)


def is_pane(node: Mapping[str, Any]) -> bool:
    return node.get("type") == "pane"


def leaves(node: Mapping[str, Any]) -> List[str]:
    if is_pane(node):
        return [str(node.get("pane_id"))]
    return leaves(node["first"]) + leaves(node["second"])  # type: ignore[arg-type]


def splits(node: Mapping[str, Any], path: Path = ()) -> Dict[Path, Mapping[str, Any]]:
    if is_pane(node):
        return {}
    found: Dict[Path, Mapping[str, Any]] = {path: node}
    found.update(splits(node["first"], path + (False,)))  # type: ignore[arg-type]
    found.update(splits(node["second"], path + (True,)))  # type: ignore[arg-type]
    return found


def node_at(root: Mapping[str, Any], path: Path) -> Optional[Mapping[str, Any]]:
    node = root
    for second in path:
        if is_pane(node):
            return None
        node = node["second" if second else "first"]  # type: ignore[assignment]
    return node


def parent_of(root: Mapping[str, Any], pane_id: str) -> Optional[Tuple[Path, bool]]:
    """Path of the split directly holding the pane, and whether the pane is its second child."""
    for path, node in splits(root).items():
        for second, key in ((False, "first"), (True, "second")):
            child = node[key]
            if is_pane(child) and child.get("pane_id") == pane_id:  # type: ignore[union-attr]
                return path, second
    return None


def rectangles(node: Mapping[str, Any], region: Rect = (0.0, 0.0, 1.0, 1.0)) -> Dict[str, Rect]:
    if is_pane(node):
        return {str(node.get("pane_id")): region}
    ratio = float(node["ratio"])  # type: ignore[arg-type]
    x, y, width, height = region
    if node["direction"] == "right":
        first = (x, y, width * ratio, height)
        second = (x + width * ratio, y, width * (1 - ratio), height)
    else:
        first = (x, y, width, height * ratio)
        second = (x, y + height * ratio, width, height * (1 - ratio))
    result = rectangles(node["first"], first)  # type: ignore[arg-type]
    result.update(rectangles(node["second"], second))  # type: ignore[arg-type]
    return result


def run_weight(node: Mapping[str, Any], direction: str) -> int:
    """Panes sharing space along ``direction`` in a run of same-direction splits."""
    if not is_pane(node) and node.get("direction") == direction:
        return run_weight(node["first"], direction) + run_weight(node["second"], direction)  # type: ignore[arg-type]
    return 1


def balanced_ratio(node: Mapping[str, Any]) -> float:
    direction = str(node["direction"])
    first = run_weight(node["first"], direction)  # type: ignore[arg-type]
    second = run_weight(node["second"], direction)  # type: ignore[arg-type]
    return clamp(first / (first + second))


def run_root(root: Mapping[str, Any], path: Path) -> Path:
    """Walk up while the parent split has the same direction: the top of this row or column."""
    node = node_at(root, path)
    if node is None or is_pane(node):
        return path
    direction = node.get("direction")
    while path:
        parent = node_at(root, path[:-1])
        if parent is None or parent.get("direction") != direction:
            break
        path = path[:-1]
    return path


def run_paths(root: Mapping[str, Any], path: Path) -> List[Path]:
    """Every split in the same-direction run that starts at ``path``."""
    node = node_at(root, path)
    if node is None or is_pane(node):
        return []
    direction = node.get("direction")
    found = [path]
    for second, key in ((False, "first"), (True, "second")):
        child = node[key]
        if not is_pane(child) and child.get("direction") == direction:  # type: ignore[union-attr]
            found += run_paths(root, path + (second,))
    return found


def signature(root: Mapping[str, Any]) -> Tuple[object, ...]:
    """The tree's structure and pane placement without ratios: equal means only sizes changed."""
    if is_pane(root):
        return ("pane", root.get("pane_id"))
    return (root.get("direction"), signature(root["first"]), signature(root["second"]))  # type: ignore[arg-type]
