"""Reducer for target/mouseover entity evidence entering the canonical model."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Observation, number

if TYPE_CHECKING:
    from .world import WorldModel

# V4-010: approximate the spec's identity-evidence source taxonomy
# (addon_quest_reference / target_frame_tooltip_name / stable_nameplate_text /
# quest_marker_and_context / visual_appearance_classifier) from the sensor
# sources this build actually produces. ADDON_TELEMETRY reads the WoW Target
# frame / nameplate-under-cursor via the addon API directly -- the closest
# real ground-truth analog to target_frame_tooltip_name / stable_nameplate_text
# respectively. MINIMAP_CV/WORLD_MAP_CV are literal map-marker detections;
# the remaining CV sources are general visual classification. Anything else
# is passed through unmapped rather than force-fit into a category it does
# not resemble -- rank_identity_source() already ranks an unknown tag last.
_MAP_MARKER_SOURCES = frozenset({"MINIMAP_CV", "WORLD_MAP_CV"})
_VISUAL_CLASSIFIER_SOURCES = frozenset({"WORLD3D", "WORLD3D_LOCAL_VIEW", "UI_CV", "VISION", "CROSS_VIEW"})


def _identity_source_tag(unit_key: str, observation_source: str) -> str:
    if observation_source == "ADDON_TELEMETRY":
        return "target_frame_tooltip_name" if unit_key == "target" else "stable_nameplate_text"
    if observation_source in _MAP_MARKER_SOURCES:
        return "quest_marker_and_context"
    if observation_source in _VISUAL_CLASSIFIER_SOURCES:
        return "visual_appearance_classifier"
    return observation_source


class WorldEntityReducer:
    """Mutates only the supplied canonical WorldModel from addon unit facts."""

    def apply(self, model: "WorldModel", state: dict, observation: Observation) -> None:
        for unit_key in ("target", "mouseover"):
            unit = state.get(unit_key) or {}
            guid = unit.get("guid")
            identity = f"npc:{unit['npc_id']}" if unit.get("npc_id") is not None else str(guid or "")
            if not identity:
                continue
            entity = model.entities.setdefault(identity, {"entity_id": identity, "first_seen": observation.received_at,
                                                           "guids": []})
            is_new_entity = entity.get("last_seen") is None
            if guid and guid not in entity["guids"]:
                entity["guids"].append(guid)
            entity.update({"npc_id": unit.get("npc_id"), "name": unit.get("name"),
                           "unit_type": unit.get("unit_type"), "last_seen": observation.received_at})
            if unit.get("name"):
                model._record_entity_identity_evidence(
                    identity, unit["name"], _identity_source_tag(unit_key, observation.source), observation)
            if is_new_entity:
                model._emit_derived_event("ENTITY_APPEARED", {
                    "entity_guid": identity, "unit_type": unit.get("unit_type"),
                    "name": unit.get("name"), "observation_role": unit_key.upper()}, observation)
            if unit.get("world_position"):
                previous_location = model.entity_locations.get(identity, [])[-1] if model.entity_locations.get(identity) else None
                location = model._record_entity_location(identity, unit["world_position"], state,
                                                         unit_key.upper(), observation)
                if location:
                    model.link(f"entity:{identity}", "located_at", f"location_cluster:{location.cluster_id}", observation)
                if (location and previous_location is not None
                        and previous_location.get("cluster_id") != location.cluster_id):
                    model._emit_derived_event("ENTITY_LOCATION_CHANGED", {
                        "entity_guid": identity, "map_id": state.get("map_id"),
                        "previous_cluster_id": previous_location.get("cluster_id"),
                        "current_cluster_id": location.cluster_id}, observation)
                px, py = number(unit["world_position"].get("x")), number(unit["world_position"].get("y"))
                if px is not None and py is not None:
                    model._world_prediction("ENTITY_PERSISTENCE", f"entity:{identity}", {
                        "map_id": state.get("map_id"), "x": px, "y": py, "tolerance": .03},
                        observation, horizon=10., confidence=.65)
            role = model._record_entity_role(identity, unit, state, unit_key.upper(), observation)
            if role:
                model.link(f"entity:{identity}", "has_role_relation", f"role:{role.role_id}", observation)
                if role.quest_id is not None:
                    model.link(f"role:{role.role_id}", "applies_to", f"quest:{role.quest_id}", observation)
                    model.link(f"entity:{identity}", "related_to", f"quest:{role.quest_id}", observation)
            model._record_entity_state_and_appearance(identity, unit, state, unit_key.upper(), observation)
            model.link(f"entity:{identity}", "observed_by", f"observation:{observation.observation_id}", observation)
