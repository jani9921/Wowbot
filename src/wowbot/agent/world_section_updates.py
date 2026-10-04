"""Attribution of canonical WorldModel major-section updates (V5 M1.3)."""
from __future__ import annotations


class WorldSectionUpdateTracker:
    SECTIONS = (
        "PlayerState", "TargetState", "EntityMap", "CombatState",
        "NavigationState", "QuestState", "InteractionState", "UIState",
        "MapState", "EnvironmentState", "RecoveryState",
    )
    _KEY_SECTIONS = {
        "health": ("PlayerState",), "max_health": ("PlayerState",),
        "is_dead": ("PlayerState", "CombatState"),
        "is_ghost": ("PlayerState",), "is_mounted": ("PlayerState",),
        "target": ("TargetState", "EntityMap"),
        "current_target": ("TargetState", "EntityMap"),
        "mouseover": ("EntityMap", "InteractionState"),
        "is_in_combat": ("CombatState",), "is_casting": ("CombatState",),
        "actionbar": ("CombatState",), "actionbar_fast": ("CombatState",),
        "position": ("NavigationState",),
        "player_world_position": ("NavigationState",),
        "orientation": ("NavigationState",), "movement": ("NavigationState",),
        "active_quests": ("QuestState",), "quest_digest": ("QuestState",),
        "quest_state_revision": ("QuestState",), "events": ("QuestState",),
        "quest_ui": ("QuestState", "InteractionState", "UIState"),
        "quest_ui_open": ("QuestState", "InteractionState", "UIState"),
        "gossip_ui": ("InteractionState", "UIState"),
        "vendor_ui": ("InteractionState", "UIState"),
        "bags_open": ("InteractionState", "UIState"),
        "input_blocked": ("UIState", "RecoveryState"),
        "loading": ("UIState", "RecoveryState"),
        "ui_error": ("UIState", "RecoveryState"),
        "map_id": ("MapState", "NavigationState"),
        "world_map_open": ("MapState", "UIState"),
        "map_mouseover": ("MapState", "InteractionState"),
        "visual_candidates": ("EntityMap", "EnvironmentState"),
        "local_traversability": ("EnvironmentState", "NavigationState"),
        "obstacle_evidence": ("EnvironmentState", "NavigationState"),
    }
    _SOURCE_SECTIONS = {
        "WORLD3D": ("EntityMap", "EnvironmentState"),
        "WORLD3D_LOCAL_VIEW": ("EnvironmentState", "NavigationState"),
        "MINIMAP_CV": ("MapState", "NavigationState"),
        "WORLD_MAP_CV": ("MapState",),
        "AGENT_RUNTIME": ("RecoveryState", "InteractionState"),
        "AGENT_TRACE": ("RecoveryState",),
    }

    def sections_for(self, observation) -> tuple[str, ...]:
        sections = set(self._SOURCE_SECTIONS.get(observation.source, ()))
        for key in observation.payload:
            sections.update(self._KEY_SECTIONS.get(key, ()))
        if not sections:
            sections.add("EnvironmentState")
        return tuple(section for section in self.SECTIONS if section in sections)

    def record(self, model, observation) -> None:
        attribution = {
            "observation_id": observation.observation_id,
            "updated_at": observation.received_at,
            "source_timestamp": observation.timestamp,
            "source": observation.source,
            "revision": model.revision,
        }
        for section in self.sections_for(observation):
            model.section_updates[section] = dict(attribution)
