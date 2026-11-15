"""Named motion styles. Each is a bundle of timing and shape; motion.json keys override any field."""
from typing import Dict, Mapping

DEFAULT_STYLE = "lively"

# duration_ms and easings drive the animation; grow_depth is how far a new pane starts from its
# final size (1 = fully collapsed at its edge, 0.4 = it starts 40% of the way out and eases in).
STYLES: Dict[str, Mapping[str, object]] = {
    "lively": dict(duration_ms=260, easing="out-cubic", grow_easing="spring", grow_depth=1.0, flash_ms=600, flash_mark="⇄"),
    "smooth": dict(duration_ms=300, easing="out-cubic", grow_easing="out-cubic", grow_depth=1.0, flash_ms=600, flash_mark="⇄"),
    "snappy": dict(duration_ms=130, easing="out-quint", grow_easing="out-quint", grow_depth=1.0, flash_ms=400, flash_mark="⇄"),
    "bouncy": dict(duration_ms=420, easing="spring", grow_easing="spring", grow_depth=1.0, flash_ms=700, flash_mark="⇄"),
    "gentle": dict(duration_ms=480, easing="in-out", grow_easing="in-out", grow_depth=1.0, flash_ms=900, flash_mark="⇄"),
    "subtle": dict(duration_ms=200, easing="out-cubic", grow_easing="out-cubic", grow_depth=0.4, flash_ms=600, flash_mark="⇄"),
    "cinematic": dict(duration_ms=700, easing="out-quint", grow_easing="out-quint", grow_depth=1.0, flash_ms=1200, flash_mark="⇄"),
    "instant": dict(duration_ms=0, easing="linear", grow_easing="linear", grow_depth=1.0, flash_ms=600, flash_mark="⇄"),
}

DESCRIPTIONS = {
    "lively": "balanced, new panes land with a small spring (default)",
    "smooth": "even, unhurried ease with no overshoot",
    "snappy": "quick and crisp; gets out of the way",
    "bouncy": "pronounced spring on everything",
    "gentle": "slow start and finish, calm",
    "subtle": "short; new panes only grow part of the way, no move flash",
    "cinematic": "long, dramatic deceleration",
    "instant": "no animation, layouts land at once",
}


def names():
    return list(STYLES)


def next_name(current: str) -> str:
    order = names()
    return order[(order.index(current) + 1) % len(order)] if current in order else DEFAULT_STYLE
