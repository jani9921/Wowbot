from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MapMouseover:
    surface: str
    semantic_type: str
    map_id: int | None
    x: float | None
    y: float | None
    local_x: float | None
    local_y: float | None
    tooltip: str


def classify_tooltip(text: str | None) -> str:
    value = (text or "").casefold()
    if not value.strip():
        return "UNKNOWN"
    if any(token in value for token in ("turn in", "turn-in", "complete quest", "quest complete")):
        return "QUEST_TURN_IN"
    if any(token in value for token in ("quest giver", "available quest", "accept quest")):
        return "QUEST_GIVER"
    if "quest" in value:
        return "QUEST_RELATED"
    return "UNKNOWN"


def normalize_map_mouseover(raw: dict[str, Any] | None) -> MapMouseover | None:
    if not raw or not raw.get("surface"):
        return None
    return MapMouseover(
        surface=str(raw.get("surface")),
        semantic_type=str(raw.get("semantic_type") or classify_tooltip(raw.get("tooltip"))),
        map_id=int(raw["map_id"]) if raw.get("map_id") is not None else None,
        x=float(raw["x"]) if raw.get("x") is not None else None,
        y=float(raw["y"]) if raw.get("y") is not None else None,
        local_x=float(raw["local_x"]) if raw.get("local_x") is not None else None,
        local_y=float(raw["local_y"]) if raw.get("local_y") is not None else None,
        tooltip=str(raw.get("tooltip") or ""),
    )
