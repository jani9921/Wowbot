from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from wowbot.vision.models import MapPoint, WorldPosition


@dataclass(frozen=True, slots=True)
class CanonicalWorldContext:
    """Stable internal identity for a navigation coordinate context.

    Client ``map_id`` values are retained as source metadata, but they are not
    the primary identity because map IDs may differ between UI/map layers or
    client versions.
    """

    context_id: str
    continent: str | None = None
    zone: str | None = None
    subzone: str | None = None
    client_map_id: str | None = None
    instance_type: str | None = None
    coordinate_space: str = "world"
    confidence: float = 0.0

    @property
    def semantic_key(self) -> str:
        # Subzone is descriptive metadata, not part of the primary navigation
        # context identity. It must not fragment route memory every time the
        # player crosses a subzone boundary inside the same zone.
        parts = [self.continent, self.zone, self.instance_type]
        return "/".join(_slug(p) for p in parts if p) or "unknown"


class MapIdentityResolver:
    """Resolve client facts into a canonical navigation context."""

    def resolve(
        self,
        *,
        map_id: object = None,
        continent: object = None,
        zone: object = None,
        subzone: object = None,
        instance_type: object = None,
        coordinate_space: str = "world",
    ) -> CanonicalWorldContext:
        values = {
            "continent": _text(continent),
            "zone": _text(zone),
            "subzone": _text(subzone),
            "instance_type": _text(instance_type),
        }
        # Canonical context is intentionally based on stable semantic fields.
        # Subzone stays available on the context record but is excluded from
        # identity so route experience remains reusable across local subzones.
        semantic_parts = [values["continent"], values["zone"], values["instance_type"]]
        semantic = "/".join(_slug(v) for v in semantic_parts if v)
        if not semantic:
            raw_map = _text(map_id)
            semantic = f"map-{_slug(raw_map) or 'unknown'}"
            confidence = 0.25 if raw_map else 0.0
        else:
            confidence = 1.0 if values["zone"] else 0.7
            if values["subzone"]:
                confidence = min(1.0, confidence + 0.05)

        context_id = f"wc:{semantic}:{_slug(coordinate_space) or 'world'}"
        return CanonicalWorldContext(
            context_id=context_id,
            continent=values["continent"],
            zone=values["zone"],
            subzone=values["subzone"],
            client_map_id=_text(map_id),
            instance_type=values["instance_type"],
            coordinate_space=coordinate_space,
            confidence=confidence,
        )

    def resolve_from_facts(self, facts: Mapping[str, object], *, coordinate_space: str = "world") -> CanonicalWorldContext:
        return self.resolve(
            map_id=facts.get("map_id"),
            continent=facts.get("continent"),
            zone=facts.get("zone"),
            subzone=facts.get("subzone"),
            instance_type=facts.get("instance_type"),
            coordinate_space=str(facts.get("coordinate_space") or coordinate_space),
        )


@dataclass(frozen=True, slots=True)
class CoordinateBounds:
    """Affine mapping between a detected map rectangle and world coordinates."""

    pixel_min_x: float
    pixel_max_x: float
    pixel_min_y: float
    pixel_max_y: float
    world_min_x: float
    world_max_x: float
    world_min_y: float
    world_max_y: float
    world_z: float = 0.0


class CoordinateMapper:
    """Convert map-space pixels into the internal WorldPosition model."""

    def __init__(self, bounds_by_context: Mapping[str, CoordinateBounds] | None = None) -> None:
        self._bounds = dict(bounds_by_context or {})

    def add_bounds(self, context_id: str, bounds: CoordinateBounds) -> None:
        self._bounds[context_id] = bounds

    def map_point(self, context: CanonicalWorldContext, point: MapPoint) -> WorldPosition | None:
        bounds = self._bounds.get(context.context_id)
        if bounds is None:
            return None
        px_span = bounds.pixel_max_x - bounds.pixel_min_x
        py_span = bounds.pixel_max_y - bounds.pixel_min_y
        if px_span == 0 or py_span == 0:
            raise ValueError("coordinate bounds cannot have zero pixel span")
        nx = (point.x - bounds.pixel_min_x) / px_span
        ny = (point.y - bounds.pixel_min_y) / py_span
        wx = bounds.world_min_x + nx * (bounds.world_max_x - bounds.world_min_x)
        wy = bounds.world_min_y + ny * (bounds.world_max_y - bounds.world_min_y)
        return WorldPosition(wx, wy, bounds.world_z)

    def player_position(
        self,
        *,
        context: CanonicalWorldContext,
        map_point: MapPoint | None,
        addon_facts: Mapping[str, object],
    ) -> WorldPosition | None:
        # Only explicitly named world coordinates are treated as WoW world
        # position. The addon's generic `position.x/y` payload is map-space
        # (typically normalized 0..1) and must not be mistaken for world XYZ.
        exact = _world_position_from_facts(addon_facts)
        if exact is not None:
            return exact
        return self.map_point(context, map_point) if map_point is not None else None


def _world_position_from_facts(facts: Mapping[str, object]) -> WorldPosition | None:
    position = facts.get("world_position")
    if isinstance(position, Mapping):
        try:
            return WorldPosition(float(position["x"]), float(position["y"]), float(position.get("z", 0.0)))
        except (KeyError, TypeError, ValueError):
            return None
    for key in ("player_x", "player_y"):
        if key not in facts:
            return None
    try:
        return WorldPosition(float(facts["player_x"]), float(facts["player_y"]), float(facts.get("player_z", 0.0)))
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slug(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text
