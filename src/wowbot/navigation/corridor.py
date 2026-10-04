"""Route-to-corridor conversion; no geometric shortcut is invented here."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .contracts import GlobalRoute, PathCorridor


@dataclass(frozen=True, slots=True)
class CorridorPolicy:
    default_half_width: float = 4.0


class PathCorridorBuilder:
    """Expose bounded local choices around observed/global route anchors."""

    def __init__(self, policy: CorridorPolicy | None = None) -> None:
        self.policy = policy or CorridorPolicy()

    def build(self, route: GlobalRoute, *, constraints: dict | None = None) -> PathCorridor:
        constraints = {"half_width": self.policy.default_half_width, **(constraints or {})}
        segments = tuple(
            {"segment_id": f"{route.route_id}:{index}", "from": dict(start), "to": dict(end),
             "half_width": constraints["half_width"], "source": "GLOBAL_ROUTE", "fact": False}
            for index, (start, end) in enumerate(zip(route.anchors, route.anchors[1:]))
        )
        digest = hashlib.sha256(repr((route.route_id, segments, constraints)).encode("utf-8")).hexdigest()[:20]
        return PathCorridor("corridor:" + digest, route.route_id, segments, route.confidence, constraints)
