from types import SimpleNamespace

from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.world import WorldModel


def _objective(*, transition=False, entity=None):
    return SimpleNamespace(
        objective_id="7:reach", type="REACH_AREA", optional=False,
        confidence=.8, target_entity=entity or {},
        target_location={"map_id": 1409, "x": .4, "y": .6,
                         "source": "QUEST_API_WAYPOINT"},
        location_candidates=(), completion_state="INCOMPLETE",
        raw={"transition_required": transition, "description": "Reach camp"})


def _record():
    return SimpleNamespace(quest_id="7", known_locations=())


def _world():
    world = WorldModel()
    world.state = {"map_id": 1409, "target": {}, "mouseover": {},
                   "active_quests": [{"quest_id": 7, "is_complete": False,
                                      "objectives": [{"objective_id": "reach",
                                                      "current": 0, "required": 1}]}]}
    return world


def test_arrived_travel_without_credit_switches_from_move_to_bounded_local_search():
    policy, world, objective = QuestLocationPlanningPolicy(), _world(), _objective()
    move = policy.propose_objective(world, objective, _record(), "7")[0]
    assert move.skill == "MOVE"
    policy.mark_reached(move.parameters, world.state)
    fallback = policy.propose_objective(world, objective, _record(), "7")[0]
    assert fallback.skill == "SEEK_VISUAL_CUE"
    assert fallback.parameters["purpose"] == "LOCALIZE_REACH_AREA_TRIGGER"
    assert fallback.parameters["scan_budget"] == 4


def test_transition_required_reach_searches_for_entrance_not_another_move():
    policy, world, objective = QuestLocationPlanningPolicy(), _world(), _objective(transition=True)
    move = policy.propose_objective(world, objective, _record(), "7")[0]
    policy.mark_reached(move.parameters, world.state)
    fallback = policy.propose_objective(world, objective, _record(), "7")[0]
    assert fallback.parameters["search_capability"] == "SEARCH_ENTRANCE"


def test_new_quest_evidence_invalidates_old_arrival_fallback():
    policy, world, objective = QuestLocationPlanningPolicy(), _world(), _objective()
    move = policy.propose_objective(world, objective, _record(), "7")[0]
    policy.mark_reached(move.parameters, world.state)
    world.state["active_quests"][0]["objectives"][0]["current"] = 1
    assert policy.propose_objective(world, objective, _record(), "7")[0].skill == "MOVE"
