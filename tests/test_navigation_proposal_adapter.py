from types import SimpleNamespace

from wowbot.agent.models import Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter


class Navigation:
    def __init__(self, *, permitted=True, waypoint=None, search_waypoint=None):
        self.permitted, self._waypoint = permitted, waypoint
        self.search_waypoint, self.search_started = search_waypoint, None

    def permits(self, world, parameters, now): return self.permitted
    def waypoint(self, world, parameters): return self._waypoint or parameters
    def begin_search_region(self, region_id, area): self.search_started = (region_id, area)
    def observe_search_region(self, *args, **kwargs): pass
    def next_search_waypoint(self, region_id, state): return self.search_waypoint


def test_local_search_area_becomes_one_navigation_waypoint():
    nav = Navigation(search_waypoint={"map_id": 1409, "instance_id": 2175,
                                      "world_map_id": 2175, "x": -366., "y": -2559.,
                                      "coordinate_space": "WORLD_YARDS",
                                      "require_navmesh": True})
    proposal = Proposal.make("SEEK_VISUAL_CUE", "search", {
        "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "quest_id": 7,
        "objective_id": 2, "search_area": {"map_id": 1409, "instance_id": 2175,
                                             "coordinate_space": "WORLD_YARDS",
                                             "x": -366., "y": -2559.}})
    result = NavigationProposalAdapter(nav).adapt(
        proposal, [proposal], SimpleNamespace(state={
            "player_world_position": {"instance_id": 2175, "x": -370., "y": -2560.}}), 1.)
    assert result.skill == "MOVE"
    assert result.parameters["quest_id"] == 7
    assert nav.search_started[0] == "7:2:1409"


def test_unpermitted_move_falls_back_without_starting_movement():
    nav = Navigation(permitted=False)
    proposal = Proposal.make("MOVE", "blocked", {"x": .4, "y": .5})
    result = NavigationProposalAdapter(nav).adapt(
        proposal, [proposal], SimpleNamespace(state={}), 1.)
    assert result.skill == "WAIT"
    assert result.parameters["blocked_reason"] == "NAVIGATION_DESTINATION_TEMPORARILY_BLOCKED"
    assert "ALTERNATIVE_ROUTE" in result.parameters["waiting_for"]
    assert result.parameters["next_action"] == "REPLAN_ALTERNATIVE_OR_RETRY"


def test_permitted_move_receives_navigation_owned_waypoint():
    nav = Navigation(waypoint={"x": 11., "y": 12., "instance_id": 2175,
                               "coordinate_space": "WORLD_YARDS", "require_navmesh": True})
    proposal = Proposal.make("MOVE", "go", {"x": 20., "y": 12., "instance_id": 2175,
                                               "coordinate_space": "WORLD_YARDS"})
    result = NavigationProposalAdapter(nav).adapt(
        proposal, [proposal], SimpleNamespace(state={
            "player_world_position": {"instance_id": 2175, "x": 10., "y": 12.}}), 1.)
    assert result.skill == "MOVE"
    assert result.parameters["x"] == 11.
    assert result.parameters["require_navmesh"] is True


def test_normalized_or_cross_instance_move_is_fail_closed():
    nav = Navigation()
    normalized = Proposal.make("MOVE", "unsafe", {
        "x": .4, "y": .5, "coordinate_space": "NORMALIZED_MAP", "map_id": 1409})
    world = SimpleNamespace(state={
        "player_world_position": {"instance_id": 2175, "x": -1., "y": -2.}})
    assert NavigationProposalAdapter(nav).adapt(normalized, [normalized], world, 1.).skill == "WAIT"
    other = Proposal.make("MOVE", "cross-zone", {
        "x": 10., "y": 20., "coordinate_space": "WORLD_YARDS", "instance_id": 1})
    assert NavigationProposalAdapter(nav).adapt(other, [other], world, 1.).skill == "WAIT"
