"""Normalized immutable-ready WorldState projection for V5 M1.4."""
from __future__ import annotations

from types import MappingProxyType

from .models import number


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    return value


class WorldStateContract:
    """Pure projection; it never mutates or becomes a second world store."""

    @staticmethod
    def _updated(model, section: str):
        return (model.section_updates.get(section) or {}).get("updated_at")

    @staticmethod
    def _belief(value, evidence_ref: str | None, confidence: float | None = None):
        return {
            "Value": value,
            "Confidence": confidence if confidence is not None else (1. if value is not None else 0.),
            "EvidenceRefs": [evidence_ref] if evidence_ref else [],
        }

    def build(self, model, now: float) -> dict:
        state = model.state
        latest_id = model.latest.observation_id if model.latest else None
        dead = state.get("is_dead")
        movement = state.get("movement") or {}
        target = state.get("target") if isinstance(state.get("target"), dict) else {}
        target_ref = target.get("observation_id") or latest_id
        entity_ref = ((model.section_updates.get("EntityMap") or {}).get("observation_id")
                      or latest_id)
        entities = self._entities(state, entity_ref)
        section_times = [item.get("updated_at") for item in model.section_updates.values()
                         if item.get("updated_at") is not None]
        return {
            "Version": model.revision,
            "UpdatedAt": max(section_times, default=model.last_received or now),
            "PlayerState": {
                "AliveBelief": self._belief(None if dead is None else not dead, latest_id),
                "DeadBelief": self._belief(dead, latest_id),
                "HealthEstimate": state.get("health"),
                "ResourceEstimate": state.get("power", state.get("resource")),
                "InCombat": state.get("is_in_combat"),
                "Moving": movement.get("moving", state.get("is_moving")),
                "Casting": state.get("is_casting"),
                "Channeling": state.get("is_channeling"),
                "PositionBelief": state.get("player_world_position") or state.get("position"),
                "HeadingBelief": state.get("orientation"),
                "BuffEvidence": list(state.get("buffs") or []),
                "DebuffEvidence": list(state.get("debuffs") or []),
                "LastUpdatedAt": self._updated(model, "PlayerState"),
            },
            "TargetState": {
                "CurrentTargetId": target.get("guid"),
                "Confidence": target.get("confidence", 1. if target.get("guid") else 0.),
                "AliveBelief": self._belief(
                    None if target.get("dead") is None else not target.get("dead"), target_ref),
                "DeadBelief": self._belief(target.get("dead"), target_ref),
                "HostilityBelief": self._belief(
                    target.get("attackable", target.get("is_attackable")), target_ref),
                "DistanceEstimate": target.get("distance"),
                "BearingEstimate": target.get("bearing"),
                "LOSBelief": self._belief(target.get("line_of_sight"), target_ref),
                "FacingBelief": self._belief(target.get("facing"), target_ref),
                "CastState": target.get("cast"),
                "LastSeen": target.get("observed_at", self._updated(model, "TargetState")),
                "LastUpdatedAt": self._updated(model, "TargetState"),
            },
            "EntityMap": entities,
            "CombatState": {
                "InCombat": state.get("is_in_combat"), "Target": target.get("guid"),
                "Casting": state.get("is_casting"),
                "LastSpellId": state.get("combat_last_spell_id"),
                "LastCastAt": state.get("combat_last_cast_at"),
                "LastUpdatedAt": self._updated(model, "CombatState"),
            },
            "NavigationState": {
                "MapId": state.get("map_id"), "Position": state.get("position"),
                "WorldPosition": state.get("player_world_position"),
                "Heading": state.get("orientation"), "Movement": movement,
                "Traversability": state.get("local_traversability"),
                "LastUpdatedAt": self._updated(model, "NavigationState"),
            },
            "QuestState": {
                "ActiveQuests": list(state.get("active_quests") or []),
                "Revision": state.get("quest_state_revision"),
                "LastUpdatedAt": self._updated(model, "QuestState"),
            },
            "InteractionState": {
                "Mouseover": state.get("mouseover"), "QuestUI": state.get("quest_ui"),
                "GossipUI": state.get("gossip_ui"), "VendorUI": state.get("vendor_ui"),
                "LastUpdatedAt": self._updated(model, "InteractionState"),
            },
            "UIState": {
                "InputBlocked": state.get("input_blocked"), "Loading": state.get("loading"),
                "Error": state.get("ui_error"), "WorldMapOpen": state.get("world_map_open"),
                "LastUpdatedAt": self._updated(model, "UIState"),
            },
            "MapState": {
                "MapId": state.get("map_id"), "WorldMapOpen": state.get("world_map_open"),
                "Mouseover": state.get("map_mouseover"),
                "Markers": list(state.get("map_marker_observations") or []),
                "LastUpdatedAt": self._updated(model, "MapState"),
            },
            "EnvironmentState": {
                "VisualCandidates": list(state.get("visual_candidates") or []),
                "Traversability": state.get("local_traversability"),
                "ObstacleEvidence": state.get("obstacle_evidence"),
                "LastUpdatedAt": self._updated(model, "EnvironmentState"),
            },
            "RecoveryState": {
                "Loading": state.get("loading"), "InputBlocked": state.get("input_blocked"),
                "LastError": state.get("ui_error"),
                "RuntimeContext": dict(model.runtime_context),
                "LastUpdatedAt": self._updated(model, "RecoveryState"),
            },
        }

    @staticmethod
    def _entities(state: dict, evidence_ref: str | None) -> dict:
        result = {}
        for index, candidate in enumerate(state.get("visual_candidates") or []):
            track_id = str(candidate.get("track_id") or f"candidate:{index}")
            belief = str(candidate.get("belief") or candidate.get("recognition_belief") or "UNKNOWN").upper()
            semantic = str(candidate.get("semantic_type") or "UNKNOWN").upper()
            best_class = semantic if belief == "CONFIRMED" else "UNKNOWN"
            bbox = candidate.get("bbox")
            result[track_id] = {
                "TrackId": track_id,
                "ClassDistribution": {best_class: 1.0},
                "BestClass": best_class,
                "BBox": bbox,
                "ScreenCenter": {"x": candidate.get("x"), "y": candidate.get("y")},
                "Velocity": candidate.get("velocity"),
                "MotionState": candidate.get("motion_state"),
                "DistanceEstimate": candidate.get("distance_estimate"),
                "BearingEstimate": candidate.get("bearing"),
                "AliveBelief": candidate.get("alive_belief"),
                "HostileBelief": candidate.get("hostile_belief"),
                "FriendlyBelief": candidate.get("friendly_belief"),
                "TargetableBelief": candidate.get("targetable_belief"),
                "InteractableBelief": candidate.get("interactable_belief"),
                "LootableBelief": candidate.get("lootable_belief"),
                "ReachabilityBelief": candidate.get("reachability_belief"),
                "FirstSeen": candidate.get("first_seen"),
                "LastSeen": candidate.get("last_seen"),
                "TrackState": candidate.get("lifecycle", candidate.get("track_state", "TENTATIVE")),
                "Confidence": number(candidate.get("confidence")) or 0.,
                "EvidenceRefs": list(candidate.get("evidence_refs") or ([evidence_ref] if evidence_ref else [])),
            }
        return result
