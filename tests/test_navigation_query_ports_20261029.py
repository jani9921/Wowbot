"""REV4 P1-C: planning services belong to consumers, never world data."""
from types import SimpleNamespace

import pytest

from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.query_ports import NavigationQueryPorts


class NoInput:
    def execute(self, commands):
        raise AssertionError("Planning queries cannot send client input")

    execute_movement = execute


def test_agent_does_not_attach_navigation_capabilities_to_the_world():
    agent = AutonomousAgent(NoInput())
    hidden = {"layer_oracle", "zone_sweep", "player_layer", "hostile_units", "walk_cost", "flight_departure_walk"}
    assert not hidden.intersection(agent.world.__dict__)


def test_state_only_layer_helper_cannot_borrow_an_attached_navigation_callback():
    model = SimpleNamespace(player_layer=lambda state: 999.)
    world = SimpleNamespace(_model=model)
    assert QuestLocationPlanningPolicy.player_layer_z(world, {}) is None


def test_unconfigured_travel_policy_does_not_invoke_a_world_attached_service():
    from test_flight_travel_integration_20261029 import goal, state

    calls = []

    def forbidden(*args):
        calls.append(1)
        return None

    current = state(mounted=False, indoors=True, sky=True)
    world = SimpleNamespace(state=current, flight_departure_walk=forbidden)
    move = Proposal.make("MOVE", "quest destination", goal(500., flight=False))
    assert TravelModePolicy().apply([move], Goal.parse("Questelj", 100.), world, 100.) == [move]
    assert calls == []


@pytest.mark.parametrize("reset", [False, True])
def test_two_agents_keep_their_floor_queries_through_snapshots_and_session_reset(reset):
    from test_reference_cost_isolation_20261029 import scene
    from wowbot.agent.models import Observation
    from wowbot.navigation.z_resolver import ResolvedPosition

    first, second = AutonomousAgent(NoInput()), AutonomousAgent(NoInput())
    for agent, height in ((first, 80.), (second, 10.)):
        state = scene()
        state.update(timestamp=10., monotonic_time=10., frame_id="floor:1")
        state["active_quests"][0]["objectives"][0].update(type="KILL", total=1, description="Unit slain")
        state["player_world_position"].update(z_known=False)
        rows = state["reference_knowledge"]["quests"]["7"]["spawn_candidates"]
        rows[0]["z"], rows[1]["z"] = 80., 10.
        agent.world.ingest(Observation.create(state, 10.))
        if reset:
            state.update(session_id="next-session", frame_id="floor:2", timestamp=11., monotonic_time=11.)
            agent.world.ingest(Observation.create(state, 11.))
            agent.planner.reset_session()
        agent.navigation._z.player = ResolvedPosition(0., 0., height, .85, "MMAP", 2444,
                                                     at=state["monotonic_time"])

    def destination(agent):
        record = agent.world.quest_model.records[7]
        snapshot = agent.world.planning_snapshot(11. if reset else 10.)
        proposals = agent.planner.quest.location_policy.propose_objective(
            snapshot, record.objectives[0], record, "7")
        return next(p.parameters for p in proposals if p.skill == "MOVE")

    assert destination(first)["x"] == 20.
    assert destination(second)["x"] == 60.
    assert destination(first)["z"] == 80.
    assert first.planner.navigation_queries is first.navigation_queries
    assert second.planner.quest.location_policy.navigation_queries is second.navigation_queries


@pytest.mark.parametrize("reset", [False, True])
def test_two_agents_keep_their_flight_departure_query_after_planner_reset(monkeypatch, reset):
    from test_flight_travel_integration_20261029 import goal, state
    from wowbot.navigation.service import NavigationService

    def departure(navigation, parameters, current):
        x = navigation._navmesh.exit_x
        return {"point": {"x": x, "y": 0., "z": 0.},
                "anchors": [{"x": 0., "y": 0., "z": 0.}, {"x": x, "y": 0., "z": 0.}]}

    monkeypatch.setattr(NavigationService, "flight_departure_walk", departure)
    first = AutonomousAgent(NoInput(), navmesh=SimpleNamespace(exit_x=10.))
    second = AutonomousAgent(NoInput(), navmesh=SimpleNamespace(exit_x=-10.))
    for agent in (first, second):
        if reset:
            agent.planner.reset_session()
        agent.world.state = state(mounted=False, indoors=True, sky=True)
        move = Proposal.make("MOVE", "quest destination", goal(500., flight=False))
        result, = agent.planner.travel_mode.apply([move], Goal.parse("Questelj", 100.), agent.world, 100.)
        assert result.parameters["flight_departure"]["point"]["x"] == agent.navigation._navmesh.exit_x
        assert not result.parameters["flight"]


@pytest.mark.parametrize("reset", [False, True])
def test_resurrection_reads_only_the_owning_planners_queries(monkeypatch, reset):
    from test_ghost_navigation_handoff_20261028 import ghost
    from wowbot.agent.models import Observation
    from wowbot.navigation.service import NavigationService

    calls = []

    def hostiles(navigation, *args):
        calls.append((navigation._navmesh.owner, "hostiles"))
        return [{"x": -361., "y": 900.}]

    def cost(navigation, *args):
        calls.append((navigation._navmesh.owner, "cost"))
        return None

    monkeypatch.setattr(NavigationService, "hostile_units", hostiles)
    monkeypatch.setattr(NavigationService, "walk_cost", cost)
    first = AutonomousAgent(NoInput(), navmesh=SimpleNamespace(owner="first"))
    second = AutonomousAgent(NoInput(), navmesh=SimpleNamespace(owner="second"))
    for agent, owner in ((first, "first"), (second, "second")):
        agent.world.ingest(Observation.create(ghost(near=True), 100.))
        if reset:
            agent.planner.reset_session()
        calls.clear()
        result, = agent.planner.candidates(Goal.parse("Questelj", 1.), agent.world.planning_snapshot(100.), 100.)
        assert result.skill == "MOVE" and result.parameters["flight_style"] == "STEADY"
        assert set(calls) == {(owner, "hostiles"), (owner, "cost")}


@pytest.mark.parametrize("value", [None, 0., 95.])
def test_player_layer_query_preserves_unknown_zero_and_observation_flags(value):
    state = {"player_world_position": {"x": 1., "y": 2., "instance_id": 2444, "z_known": False}}
    queries = NavigationQueryPorts(player_layer=lambda _: value)
    result = QuestLocationPlanningPolicy.with_player_layer(None, state, navigation_queries=queries)
    assert state["player_world_position"].get("z") is None
    if value is None:
        assert result is state
    else:
        assert result["player_world_position"]["z"] == value
        assert result["player_world_position"]["z_known"] is True
        assert result["player_world_position"]["z_observed"] is False
        assert result["player_world_position"]["z_source"] == "NAVMESH_LAYER"


@pytest.mark.parametrize("failing", [False, True])
def test_finished_or_unavailable_sweep_does_not_restart_at_the_lowest_floor(failing):
    from test_pit_layer_and_pins_20261005 import _world, _moves

    def sweep(*args):
        if failing:
            raise RuntimeError("geometry unavailable")
        return None

    lower_calls = []

    def forbidden(*args):
        lower_calls.append(1)
        return None

    policy = QuestLocationPlanningPolicy(navigation_queries=NavigationQueryPorts(
        zone_sweep=sweep, lower_layer=forbidden))
    assert _moves(policy, _world()) == []
    assert lower_calls == []


def test_unavailable_flight_departure_does_not_crash_or_invent_an_exit():
    from test_flight_travel_integration_20261029 import goal, state

    def unavailable(*args):
        raise RuntimeError("missing geometry")

    world = SimpleNamespace(state=state(mounted=False, indoors=True, sky=True))
    move = Proposal.make("MOVE", "quest destination", goal(500., flight=False))
    policy = TravelModePolicy(departure_walk=unavailable)
    assert policy.apply([move], Goal.parse("Questelj", 100.), world, 100.) == [move]


def test_player_layer_exception_is_unknown_and_known_height_needs_no_query():
    calls = []

    def unavailable(*args):
        calls.append(1)
        raise RuntimeError("missing geometry")

    queries = NavigationQueryPorts(player_layer=unavailable)
    assert QuestLocationPlanningPolicy.player_layer_z(None, {}, navigation_queries=queries) is None
    known = {"player_world_position": {"x": 0., "y": 0., "z": 12., "z_known": True}}
    assert QuestLocationPlanningPolicy.with_player_layer(None, known, navigation_queries=queries) is known
    assert calls == [1]


def test_query_bundle_is_immutable_and_cannot_enter_the_world_snapshot():
    from dataclasses import FrozenInstanceError
    import json

    agent = AutonomousAgent(NoInput())
    with pytest.raises(FrozenInstanceError):
        agent.navigation_queries.player_layer = lambda _: 99.
    encoded = json.dumps(agent.world.state)
    assert "navigation_queries" not in encoded and "bound method" not in encoded
    assert "navigation_queries" not in agent.world.planning_snapshot(0.).state
