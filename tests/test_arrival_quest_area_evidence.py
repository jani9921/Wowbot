from wowbot.agent.movement_controller import ReachMovementController
from wowbot.navigation.arrival_evidence import ArrivalEvidence


DESTINATION = {"map_id": 1, "x": .7, "y": .5, "quest_id": 7,
               "objective_id": "7:reach", "purpose": "REACH_AREA"}


def state(current, *, required=3, objective_complete=False, quest_complete=False):
    return {"map_id": 1, "position": {"x": .5, "y": .5}, "orientation": 0.,
            "active_quests": [{"quest_id": 7, "is_complete": quest_complete,
                "objectives": [{"objective_id": "reach", "current": current,
                                "required": required, "is_complete": objective_complete}]}]}


def test_same_objective_credit_confirms_reach_area_arrival():
    controller = ReachMovementController()
    controller.start(DESTINATION, state(0), "o1", 1.)
    result = controller.observe(state(1), "o2", 2.)
    assert result.terminal and result.success
    assert result.reason == "reach_arrival_quest_state_verified"
    assert "quest_area_state_change" in controller.snapshot()["arrival"]["evidence"]


def test_quest_ready_for_turnin_confirms_area_arrival():
    evidence = ArrivalEvidence()
    assert evidence.observe(DESTINATION, state(2), 1., .2) == {}
    assert evidence.observe(DESTINATION, state(2, quest_complete=True), 2., .2) == {
        "quest_area_state_change": True}


def test_missing_or_regressing_objective_never_confirms_area_arrival():
    evidence = ArrivalEvidence()
    evidence.observe(DESTINATION, state(2), 1., .2)
    assert evidence.observe(DESTINATION, state(1), 2., .2) == {}
    assert evidence.observe(DESTINATION, {"active_quests": []}, 3., .2) == {}


def test_changed_requirement_is_not_progress():
    evidence = ArrivalEvidence()
    evidence.observe(DESTINATION, state(1, required=3), 1., .2)
    assert evidence.observe(DESTINATION, state(2, required=4), 2., .2) == {}


def test_fresh_exact_target_ui_transition_is_interaction_ready_evidence():
    evidence = ArrivalEvidence()
    destination = {"target_guid": "npc"}
    initial = {"target": {"guid": "npc", "sample_time": 1.}}
    opened = {"target": {"guid": "npc", "sample_time": 1.2},
              "quest_ui": {"open": True}}
    assert evidence.observe(destination, initial, 1., 10.) == {}
    assert evidence.observe(destination, opened, 1.2, 10.) == {"interaction_ready": True}


def test_interaction_ui_transition_finishes_target_reach():
    controller = ReachMovementController()
    destination = {"target_guid": "npc", "coordinate_space": "WORLD_YARDS",
                   "x": 20., "y": 0., "stop_distance": 4.5}
    initial = {"player_world_position": {"x": 0., "y": 0.}, "orientation": 0.,
               "target": {"guid": "npc", "sample_time": 1.,
                          "world_position": {"x": 20., "y": 0.}}}
    controller.start(destination, initial, "o1", 1.)
    opened = {**initial, "target": {**initial["target"], "sample_time": 1.2},
              "quest_ui": {"open": True}}
    result = controller.observe(opened, "o2", 1.2)
    assert result.terminal and result.success
    assert result.reason == "reach_arrival_interaction_ready"


def test_retained_ui_wrong_target_and_stale_target_are_not_interaction_ready():
    for changed in (
        {"target": {"guid": "npc", "sample_time": 1.}, "quest_ui": {"open": True}},
        {"target": {"guid": "other", "sample_time": 2.}, "gossip_ui": {"open": True}},
        {"target": {"guid": "npc", "sample_time": 1.}, "merchant_ui": {"open": True}},
    ):
        evidence = ArrivalEvidence()
        destination = {"target_guid": "npc"}
        baseline = ({"target": {"guid": "npc", "sample_time": 1.},
                     "quest_ui": {"open": True}}
                    if changed.get("quest_ui") else
                    {"target": {"guid": "npc", "sample_time": 1.}})
        evidence.observe(destination, baseline, 1., 10.)
        assert evidence.observe(destination, changed, 3., 10.) == {}


def test_unrelated_objective_change_is_ignored():
    evidence = ArrivalEvidence()
    evidence.observe(DESTINATION, state(0), 1., .2)
    other = state(0)
    other["active_quests"][0]["objectives"].append(
        {"objective_id": "other", "current": 1, "required": 3})
    assert evidence.observe(DESTINATION, other, 2., .2) == {}


def test_quest_credit_terminates_full_route_instead_of_advancing_waypoint():
    from wowbot.navigation import ArrivalEnvelope, NavigationRequest, NavigationService

    class Route:
        route_id = "route"
        anchors = ({"x": .5, "y": .5}, {"x": .6, "y": .5}, {"x": .7, "y": .5})
        regions = ()
        cost = 1.
        confidence = 1.
        created_at = 0.
        valid_until = 99.

    service = NavigationService()
    service._global_planner.plan = lambda *args, **kwargs: Route()
    request = NavigationRequest(
        request_id="reach-area", correlation_id="attempt", mode="MOVE_TO_LOCATION",
        destination=dict(DESTINATION), arrival=ArrivalEnvelope(radius=.003))
    service.start_request(request, state(0), 1.)
    assert service.snapshot(1.)["route_waypoint_index"] == 1
    result = service.observe(state(1), "credit", 2.)
    assert result.terminal and result.reason == "reach_arrival_quest_state_verified"
    assert service.snapshot(2.)["route_waypoint_index"] == 1
