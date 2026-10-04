"""Context-aware World3D scheduling profiles (one pipeline, no new authority)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class World3DPerceptionProfile:
    name: str
    detector_hz: float
    tracker_hz: float
    ocr_interval_seconds: float
    ocr_max_regions: int
    priorities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["priorities"] = list(self.priorities)
        return payload


PROFILES = {
    "BALANCED": World3DPerceptionProfile(
        "BALANCED", 8., 40., .60, 3,
        ("generic_subjects", "overhead_cues", "traversability", "targeted_ocr")),
    "COMBAT": World3DPerceptionProfile(
        "COMBAT", 15., 40., 1.00, 1,
        ("target_track", "nameplate", "health_cast_cues", "hostile_candidates", "los_obstacles")),
    "QUEST_SEARCH": World3DPerceptionProfile(
        "QUEST_SEARCH", 12., 40., .25, 4,
        ("quest_cues", "interact_cues", "subject_object_candidates", "tooltip_probes", "entrances")),
    "NAVIGATION": World3DPerceptionProfile(
        "NAVIGATION", 10., 40., 1.20, 1,
        ("traversability", "obstacles", "landmark_motion", "target_bearing", "entrances")),
}


def resolve_world3d_profile(context: dict[str, Any] | None) -> World3DPerceptionProfile:
    context = context or {}
    explicit = str(context.get("world3d_profile_name") or "").upper()
    if explicit in PROFILES:
        return PROFILES[explicit]
    if bool(context.get("is_in_combat") or context.get("combat_active")):
        return PROFILES["COMBAT"]
    if bool(context.get("quest_search") or context.get("tooltip_probe")
            or context.get("quest_local_search")):
        return PROFILES["QUEST_SEARCH"]
    if bool(context.get("navigation_active") or context.get("fast_visual_servo")
            or context.get("movement_active")):
        return PROFILES["NAVIGATION"]
    return PROFILES["BALANCED"]
