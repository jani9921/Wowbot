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


def test_npc_turn_in_mode_never_uses_an_objective_point_as_hand_in():
    # Issue #89: under NPC_TURN_IN the first convertible location was used,
    # including an OBJECTIVE/MEMORY point unrelated to the hand-in NPC.
    resolver = TurnInResolver()
    objective = {"role": "OBJECTIVE", "source": "MEMORY",
                 "world_position": {"x": 10, "y": 20, "instance_id": 2175,
                                    "coordinate_space": "WORLD_YARDS"}}
    result = resolver.locate(record([objective]), {}, completion_mode="NPC_TURN_IN")
    assert result.kind is TurnInLocationKind.UNKNOWN
    waypoint = {"map_id": 1, "x": .2, "y": .3, "source": "QUEST_API_WAYPOINT"}
    result = resolver.locate(record([objective, waypoint]), {}, completion_mode="NPC_TURN_IN")
    assert result.kind is TurnInLocationKind.TURN_IN_LOCATION
    assert (result.location["x"], result.location["y"]) == (.2, .3)


def test_quest_model_tags_objective_target_locations():
    from wowbot.agent.quest_model import QuestModel
    model = QuestModel()
    model.ingest([{"quest_id": 5, "is_complete": True, "objectives": [
        {"type": "monster", "is_complete": True,
         "target_location": {"map_id": 1, "x": .4, "y": .4}}]}], "o", 1.)
    record = next(iter(model.records.values()))
    roles = [location.get("role") for location in record.known_locations]
    assert roles == ["OBJECTIVE"]
