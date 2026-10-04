from types import SimpleNamespace

from wowbot.agent.turnin_resolver import TurnInLocationKind, TurnInResolver


def record(locations):
    return SimpleNamespace(known_locations=locations)


def test_field_completion_ui_outranks_all_location_fallbacks():
    resolver = TurnInResolver()
    result = resolver.locate(record([{"map_id": 1, "x": .2, "y": .3, "source": "QUEST_API_WAYPOINT"}]),
                             {"quest_ui_action": "COMPLETE"})
    assert result.kind is TurnInLocationKind.FIELD_UI

    reward = resolver.locate(record([]), {"quest_ui_action": "REWARD_SELECT"})
    assert reward.kind is TurnInLocationKind.FIELD_UI


def test_only_declared_turnin_or_current_quest_api_waypoint_can_locate_completed_quest():
    resolver = TurnInResolver()
    arbitrary = resolver.locate(record([{"map_id": 1, "x": .2, "y": .3, "source": "MEMORY"}]), {})
    assert arbitrary.kind is TurnInLocationKind.UNKNOWN

    declared = resolver.locate(record([{"map_id": 1, "x": .2, "y": .3, "role": "TURN_IN"}]), {})
    assert declared.kind is TurnInLocationKind.TURN_IN_LOCATION

    waypoint = resolver.locate(record([{"map_id": 1, "x": .2, "y": .3, "source": "QUEST_API_WAYPOINT"}]), {})
    assert waypoint.kind is TurnInLocationKind.QUEST_API_REGION


def test_live_turnin_role_is_entity_evidence_not_a_map_coordinate_claim():
    result = TurnInResolver().locate(record([]), {"target": {
        "guid": "npc-1", "attackable": False, "quest_role": "QUEST_TURN_IN"}}, "NPC_TURN_IN")
    assert result.kind is TurnInLocationKind.LOCAL_ENTITY
    assert result.entity_guid == "npc-1" and result.location is None


def test_current_quest_waypoint_prefers_explicit_api_world_conversion():
    result = TurnInResolver().locate(record([{
        "map_id": 1409, "x": .52, "y": .49, "source": "QUEST_API_WAYPOINT",
        "world_position": {"x": -420., "y": -2600., "instance_id": 2175,
                           "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS",
                           "source": "C_MAP_WORLD_POS", "z_known": False},
    }]), {})

    assert result.kind is TurnInLocationKind.QUEST_API_REGION
    assert result.location["coordinate_space"] == "WORLD_YARDS"
    assert result.location["instance_id"] == 2175
    assert result.location["map_id"] == 1409
    assert result.location["x"] == -420.
