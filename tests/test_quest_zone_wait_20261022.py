"""21:39 user run: task POI arrival followed by another pin in the same zone.

Only the recorded map geometry is replayed. No client input or quest credit
is produced, and the native walking slope policy is deliberately unchanged.
"""
from copy import deepcopy

import pytest

from wowbot.agent.models import Goal, Observation
from wowbot.agent.quest_batch_planning import QuestBatchPolicy
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.world import WorldModel


def location(quest_id, x, y, source="QUEST_POI"):
    return {"quest_id": quest_id, "map_id": 2022, "source": source,
            "coordinate_space": "NORMALIZED_MAP", "x": .65, "y": .34,
            "world_position": {"x": x, "y": y, "instance_id": 2444,
                               "ui_map_id": 2022, "z_known": False,
                               "coordinate_space": "WORLD_YARDS"}}


def state():
    vertices = [(3202, -857), (3356, -865), (3469, -761), (3631, -709),
                (3681, -684), (3827, -510), (3845, -443), (3847, -395),
                (3816, -298), (3527, -181), (3442, -248), (3155, -779)]
    return {
        "session_id": "test:quest-zone-wait", "frame_id": "zone:1",
        "timestamp": 10., "monotonic_time": 10., "map_id": 2022,
        "player_present": True, "world_map_open": False,
        "orientation": 0., "position": {"x": .64, "y": .335},
        "player_world_position": {"x": 3589.7, "y": -479.3, "z": 55.85,
                                  "z_known": True, "z_observed": True,
                                  "instance_id": 2444,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [
            *({"quest_id": qid, "is_campaign": True, "is_complete": True,
               "objectives": []} for qid in (65992, 65993, 65995)),
            {"quest_id": 65994, "is_campaign": False, "is_complete": False,
             "objectives": [{"type": "AREA", "raw_type": "progressbar",
                             "description": "Djaradin camp invaded (71%)",
                             "current": 0, "required": 1, "is_complete": False}]},
        ],
        "quest_locations": [
            *(location(qid, 3608., -344.) for qid in (65992, 65993, 65995)),
            location(65994, 3566., -560.),
            location(65994, 3589., -486., "TASK_QUEST_POI"),
        ],
        "reference_knowledge": {"quests": {"65994": {"pois": [{
            "poi_id": "65994:0:0", "objective_id": 427740, "objective_index": 2,
            "geometry_kind": "POLYGON_CANDIDATE", "world_map_id": 2444,
            "ui_map_id": 2022, "geometry_ambiguous": False,
            "geometry_mixed_build": False, "conditions": {},
            "points": [{"x": x, "y": y, "z": 0} for x, y in vertices],
        }]}}},
    }


def world(payload):
    model = WorldModel()
    model.ingest(Observation.create(payload, 10.))
    return model


def test_nearby_bonus_work_cannot_defer_completed_campaign_handins():
    batch = QuestBatchPolicy()
    assert batch.deferred_turnins(state(), 10.) == frozenset()


def test_campaign_work_in_same_area_still_batches_campaign_handins():
    payload = state()
    payload["active_quests"][-1]["is_campaign"] = True
    assert QuestBatchPolicy().deferred_turnins(payload, 10.) == {"65992", "65993", "65995"}


def test_side_quest_batching_is_preserved_without_campaign_claims():
    payload = state()
    for quest in payload["active_quests"]:
        quest["is_campaign"] = False
    assert QuestBatchPolicy().deferred_turnins(payload, 10.) == {"65992", "65993", "65995"}


def test_old_deferral_is_released_when_only_bonus_work_remains():
    payload = state()
    payload["active_quests"][-1]["is_campaign"] = True
    batch = QuestBatchPolicy()
    assert batch.deferred_turnins(payload, 10.)
    payload["active_quests"][-1]["is_campaign"] = False
    assert batch.deferred_turnins(payload, 11.) == frozenset()
    assert batch.waiting == set()


def test_quest_area_membership_does_not_require_visiting_every_poi_pin():
    payload = state()
    policy = QuestLocationPlanningPolicy()
    candidates = policy.propose_known_locations(world(payload))
    assert not [p for p in candidates if p.parameters.get("quest_id") == 65994]
    assert {p.parameters.get("quest_id") for p in candidates} == {65992, 65993, 65995}


@pytest.mark.parametrize("invalid", ["wrong_instance", "wrong_map", "ambiguous",
                                     "mixed_build", "condition", "unrelated_pin",
                                     "other_floor", "turnin_geometry", "degenerate"])
def test_unproven_area_cannot_suppress_a_real_travel_request(invalid):
    payload = state()
    poi = payload["reference_knowledge"]["quests"]["65994"]["pois"][0]
    if invalid == "wrong_instance":
        poi["world_map_id"] = 2175
    elif invalid == "wrong_map":
        poi["ui_map_id"] = 1409
    elif invalid == "ambiguous":
        poi["geometry_ambiguous"] = True
    elif invalid == "mixed_build":
        poi["geometry_mixed_build"] = True
    elif invalid == "condition":
        poi["conditions"] = {"PlayerConditionID": 42}
    elif invalid == "unrelated_pin":
        payload["quest_locations"][3] = location(65994, 2000., -1500.)
    elif invalid == "other_floor":
        for point in poi["points"]:
            point["z"] = 150.
    elif invalid == "turnin_geometry":
        poi["objective_index"] = -1
    else:
        poi["points"] = [{"x": x, "y": -560., "z": 0} for x in (3500., 3550., 3600.)]
    candidates = QuestLocationPlanningPolicy().propose_known_locations(world(payload))
    assert any(p.skill == "MOVE" and p.parameters.get("quest_id") == 65994 for p in candidates)


def test_outside_the_polygon_still_navigates_to_the_objective_area():
    payload = state()
    payload["player_world_position"].update(x=3000., y=-1000.)
    candidates = QuestLocationPlanningPolicy().propose_known_locations(world(payload))
    assert any(p.skill == "MOVE" and p.parameters.get("quest_id") == 65994 for p in candidates)


def test_domain_keeps_handin_moves_without_claiming_area_quest_completion():
    payload = state()
    before = deepcopy(payload)
    candidates = QuestDomain().propose(world(payload), Goal.parse("Questelj", 10.))
    handins = [p for p in candidates if p.skill == "MOVE"
               and p.parameters.get("purpose") == "LOCATE_TURN_IN_REGION"]
    assert {str(p.parameters["quest_id"]) for p in handins} == {"65992", "65993", "65995"}
    assert payload == before
    assert payload["active_quests"][-1]["is_complete"] is False
    assert all(p.parameters.get("require_navmesh") is True for p in handins)
