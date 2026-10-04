"""Decaying local danger costs for the one canonical navigation service."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class DangerEntry:
    danger_id: str
    kind: str
    x: float
    y: float
    radius: float
    cost: float
    confidence: float
    created_at: float
    expires_at: float
    source: str
    entity_id: str | None = None


class DangerMap:
    """Evidence-weighted, expiring costs; it never chooses movement input."""

    def __init__(self) -> None:
        self._entries: dict[str, DangerEntry] = {}
        self.revision = 0

    def reset(self) -> None:
        self._entries.clear()
        self.revision += 1

    def add(self, *, danger_id: str, kind: str, x: float, y: float, radius: float,
            cost: float, confidence: float, now: float, ttl: float, source: str,
            entity_id: str | None = None) -> DangerEntry:
        entry = DangerEntry(str(danger_id), str(kind), float(x), float(y), max(.01, float(radius)),
                            max(0., float(cost)), max(0., min(1., float(confidence))),
                            float(now), float(now) + max(.1, float(ttl)), str(source), entity_id)
        prior = self._entries.get(entry.danger_id)
        self._entries[entry.danger_id] = entry
        if (prior is None or prior.kind != entry.kind
                or math.hypot(prior.x-entry.x, prior.y-entry.y) > .25
                or abs(prior.radius-entry.radius) > .25
                or abs(prior.cost-entry.cost) > .25
                or abs(prior.confidence-entry.confidence) > .05):
            self.revision += 1
        return entry

    def observe_hostiles(self, state: dict, now: float) -> None:
        """Add only explicit attackable telemetry with simultaneous coordinates."""
        for row in state.get("nearby_attackable_entities") or state.get("threats") or ():
            if not isinstance(row, dict) or row.get("attackable", row.get("is_attackable")) is not True:
                continue
            pos = row.get("world_position") or row.get("position") or row
            try:
                x, y = float(pos["x"]), float(pos["y"])
            except (KeyError, TypeError, ValueError):
                continue
            entity_id = str(row.get("guid") or "") or None
            confidence = float(row.get("identity_confidence") or row.get("confidence") or .5)
            self.add(danger_id=f"hostile:{entity_id or round(x, 1), round(y, 1)}", kind="HOSTILE_AGGRO",
                     x=x, y=y, radius=float(row.get("aggro_radius") or 10.), cost=6.,
                     confidence=confidence, now=now, ttl=8., source="ADDON_TELEMETRY",
                     entity_id=entity_id)

    def cost_at(self, x: float, y: float, now: float, *, exempt_entity_id: str | None = None) -> float:
        self._expire(now)
        total = 0.
        for entry in self._entries.values():
            if exempt_entity_id and entry.entity_id == exempt_entity_id:
                continue
            distance = math.hypot(float(x) - entry.x, float(y) - entry.y)
            if distance < entry.radius:
                total += entry.cost * entry.confidence * (1. - distance / entry.radius)
        return total

    def permits(self, x: float, y: float, now: float, *, avoid_combat: bool,
                allow_combat: bool, exempt_entity_id: str | None = None) -> bool:
        if allow_combat or not avoid_combat:
            return True
        return self.cost_at(x, y, now, exempt_entity_id=exempt_entity_id) < 8.

    def snapshot(self, now: float) -> list[dict]:
        self._expire(now)
        return [asdict(entry) for entry in sorted(self._entries.values(), key=lambda row: row.danger_id)]

    def active_entries(self, now: float, *, exempt_entity_id: str | None = None) -> tuple[DangerEntry, ...]:
        self._expire(now)
        return tuple(entry for entry in sorted(self._entries.values(), key=lambda row: row.danger_id)
                     if not exempt_entity_id or entry.entity_id != exempt_entity_id)

    def has_navigation_failures(self, now: float) -> bool:
        return any(entry.kind == "NAVIGATION_FAILURE" for entry in self.active_entries(now))

    def route_cost(self, anchors: tuple[dict, ...] | list[dict], now: float, *,
                   exempt_entity_id: str | None = None) -> float:
        """Return geometric length plus sampled, confidence-weighted danger.

        This is a planning score, not a movement decision.  Sampling keeps the
        representation honest when the route graph has no polygonal cost-map
        backend yet and is deterministic for replay.
        """
        if len(anchors) < 2:
            return 0.
        total = 0.
        for left, right in zip(anchors, anchors[1:]):
            dx, dy = float(right["x"])-float(left["x"]), float(right["y"])-float(left["y"])
            length = math.hypot(dx, dy)
            total += length
            samples = max(4, min(32, int(math.ceil(length / 2.))))
            for index in range(1, samples):
                fraction = index/samples
                x = float(left["x"]) + dx*fraction
                y = float(left["y"]) + dy*fraction
                total += self.cost_at(x, y, now, exempt_entity_id=exempt_entity_id) * length/samples
        return total

    DETOUR_SCALES = (1.0, 1.6, 2.3)

    def avoidance_anchors(self, anchors: tuple[dict, ...] | list[dict], now: float, *,
                          exempt_entity_id: str | None = None,
                          clearance: float = 2., walkable=None) -> tuple[dict, ...]:
        """Insert deterministic left/right detours around intersecting danger.

        Both alternatives are scored through the same DangerMap.  The method
        never emits input and never fabricates semantic obstacle classes.
        """
        active = self.active_entries(now, exempt_entity_id=exempt_entity_id)
        if len(anchors) < 2 or not active:
            return tuple(dict(point) for point in anchors)
        result = [dict(anchors[0])]
        for end in anchors[1:]:
            start = result[-1]
            hazards = [entry for entry in active
                       if self._segment_distance(start, end, entry.x, entry.y) < entry.radius]
            for entry in hazards:
                dx, dy = float(end["x"])-float(start["x"]), float(end["y"])-float(start["y"])
                length = math.hypot(dx, dy)
                if length <= 1e-6:
                    continue
                nx, ny = -dy/length, dx/length
                base = entry.radius + max(.5, float(clearance))
                candidates: tuple[dict, ...] = ()
                # Without a walkability check the nearest pair is used as
                # before; with one, widen the detour until a side lands on the
                # navmesh, and skip the detour when neither ever does.
                for scale in (self.DETOUR_SCALES if walkable else (1.0,)):
                    offset = base*scale
                    pair = (
                        {"x": entry.x + nx*offset, "y": entry.y + ny*offset,
                         "danger_detour": entry.danger_id, "detour_side": "LEFT"},
                        {"x": entry.x - nx*offset, "y": entry.y - ny*offset,
                         "danger_detour": entry.danger_id, "detour_side": "RIGHT"},
                    )
                    candidates = tuple(point for point in pair if not walkable or walkable(point))
                    if candidates:
                        break
                if not candidates:
                    continue
                chosen = min(candidates, key=lambda point: (
                    self.route_cost([start, point, end], now,
                                    exempt_entity_id=exempt_entity_id),
                    point["detour_side"],
                ))
                result.append(chosen)
                start = chosen
            result.append(dict(end))
        return tuple(result)

    @staticmethod
    def _segment_distance(left: dict, right: dict, x: float, y: float) -> float:
        ax, ay = float(left["x"]), float(left["y"])
        bx, by = float(right["x"]), float(right["y"])
        dx, dy = bx-ax, by-ay
        length_sq = dx*dx + dy*dy
        if length_sq <= 1e-12:
            return math.hypot(x-ax, y-ay)
        fraction = max(0., min(1., ((x-ax)*dx+(y-ay)*dy)/length_sq))
        return math.hypot(x-(ax+fraction*dx), y-(ay+fraction*dy))

    def _expire(self, now: float) -> None:
        retained = {key: value for key, value in self._entries.items() if value.expires_at > now}
        if len(retained) != len(self._entries):
            self.revision += 1
        self._entries = retained
