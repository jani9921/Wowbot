from types import SimpleNamespace

from wowbot.agent.models import Proposal
from wowbot.agent.navigation_situation import NavigationSituationPolicy
from wowbot.navigation import NavigationService


class World:
    def __init__(self, state, distance=None):
        self.state = state
        self._distance = distance

    def distance(self, destination):
        return self._distance


def adapt(proposal, state, *, distance=None, last_result=None,
          map_relocalization_exhausted=False):
    return NavigationSituationPolicy().adapt(
        proposal, world=World(state, distance), navigation=NavigationService(),
        last_result=last_result or {},
        map_relocalization_exhausted=map_relocalization_exhausted)


def test_movement_intent_is_annotated_with_evidence_only_context():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .7, "y": .4}),
        {"map_id": 1, "is_indoors": True}, distance=.3)
    assert result.skill == "MOVE"
    assert result.parameters["navigation_context"] == "INDOOR"
    assert result.parameters["route_expectation"] == "TOPOLOGY_CONSTRAINED"


def test_active_loading_transition_holds_stale_route():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .7, "y": .4}),
        {"map_id": 1, "loading": True}, distance=.3)
    assert result.skill == "WAIT"
    assert result.parameters["navigation_context"] == "TRANSITION"


def test_supported_cave_boundary_starts_bounded_entrance_search():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .52, "y": .50}),
        {"map_id": 1, "area_type": "Cave", "cave_entrance_detected": True,
         "repeated_local_route_blockage": True}, distance=.01)
    assert result.skill == "SEEK_VISUAL_CUE"
    assert result.parameters["purpose"] == "SEARCH_ENTRANCE"
    assert result.parameters["search_capability"] == "SEARCH_ENTRANCE"
    assert result.parameters["transition_kind"] == "FIND_CAVE_ENTRANCE"
    assert result.parameters["scan_budget"] == 6


def test_unknown_boundary_also_searches_instead_of_repeating_wall_move():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .52, "y": .50}),
        {"map_id": 1, "repeated_local_route_blockage": True}, distance=.01)
    assert result.skill == "SEEK_VISUAL_CUE"
    assert result.parameters["transition_kind"] == "UNKNOWN_TRANSITION"


def test_exhausted_transition_search_escalates_to_map_relocalization():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .52, "y": .50}),
        {"map_id": 1, "repeated_local_route_blockage": True,
         "world_map_open": False}, distance=.01,
        last_result={"skill": "SEEK_VISUAL_CUE", "purpose": "SEARCH_ENTRANCE",
                     "outcome": "FAILURE", "reason": "target_not_found"})
    assert result.skill == "OPEN_MAP"
    assert result.parameters["purpose"] == "RELOCALIZE_TRANSITION"


def test_near_map_marker_without_3d_identity_is_transition_evidence():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .52, "y": .50,
                                      "quest_id": 7}),
        {"map_id": 1, "target": {}, "mouseover": {}}, distance=.002)
    assert result.skill == "SEEK_VISUAL_CUE"
    assert "map_distance_low_target_absent" in result.evidence


def test_generic_user_move_near_destination_does_not_invent_transition():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .52, "y": .50}),
        {"map_id": 1, "target": {}, "mouseover": {}}, distance=.002)
    assert result.skill == "MOVE"


def test_plain_quest_objective_arrival_does_not_invent_unknown_transition():
    result = adapt(
        Proposal.make(
            "MOVE", "Quest objective region",
            {"x": 104., "y": 100., "instance_id": 2175,
             "coordinate_space": "WORLD_YARDS", "stop_distance": 8.,
             "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "require_navmesh": True,
             "quest_id": 55122, "objective_type": "COLLECT"}),
        {"map_id": 1409, "target": {}, "mouseover": {},
         "player_world_position": {
             "x": 100., "y": 100., "instance_id": 2175,
             "coordinate_space": "WORLD_YARDS"}})

    assert result.skill == "MOVE"
    assert result.parameters["purpose"] == "LOCATE_QUEST_OBJECTIVE_REGION"


def test_plain_turnin_arrival_does_not_invent_unknown_transition_or_open_map():
    result = adapt(
        Proposal.make(
            "MOVE", "Quest turn-in region",
            {"x": 104., "y": 100., "instance_id": 2175,
             "coordinate_space": "WORLD_YARDS", "stop_distance": 8.,
             "purpose": "LOCATE_TURN_IN_REGION", "require_navmesh": True,
             "quest_id": 55173}),
        {"map_id": 1409, "target": {}, "mouseover": {},
         "player_world_position": {
             "x": 100., "y": 100., "instance_id": 2175,
             "coordinate_space": "WORLD_YARDS"}})

    assert result.skill == "MOVE"
    assert result.parameters["purpose"] == "LOCATE_TURN_IN_REGION"


def test_exhausted_map_relocalization_is_not_reopened_without_new_context():
    result = adapt(
        Proposal.make("MOVE", "go", {"map_id": 1, "x": .52, "y": .50}),
        {"map_id": 1, "repeated_local_route_blockage": True,
         "world_map_open": False}, distance=.01,
        last_result={"skill": "SEEK_VISUAL_CUE", "purpose": "SEARCH_ENTRANCE",
                     "outcome": "FAILURE", "reason": "target_not_found"},
        map_relocalization_exhausted=True)

    assert result.skill == "WAIT"
    assert result.parameters["replan_scope"] == "MAP_OR_QUEST_EVIDENCE"
    assert "MAP_CONTEXT_CHANGED" in result.parameters["waiting_for"]
