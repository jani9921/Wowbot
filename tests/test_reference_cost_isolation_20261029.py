"""REV4 P1-A: each agent ranks locations with its own navigation service."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from wowbot.agent.engine import AutonomousAgent
from wowbot.agent import tdb_locations
from wowbot.navigation.service import NavigationService


class NoInput:
    def execute(self, commands):
        raise AssertionError("Location queries cannot dispatch client input")

    execute_movement = execute


@pytest.fixture
def agents(monkeypatch):
    def walk_cost(navigation, state, destination):
        return navigation._navmesh.costs[destination["x"]]

    monkeypatch.setattr(NavigationService, "walk_cost", walk_cost)

    def make(costs):
        return AutonomousAgent(NoInput(), navmesh=SimpleNamespace(costs=costs))

    return make


def scene():
    return {
        "session_id": "first-session", "map_id": 2023,
        "player_world_position": {"x": 0., "y": 0., "z": 10., "z_known": True,
                                  "coordinate_space": "WORLD_YARDS", "instance_id": 2444},
        "active_quests": [{"quest_id": 7, "is_complete": False,
                           "objectives": [{"is_complete": False, "current": 0}]}],
        "reference_knowledge": {"quests": {"7": {"spawn_candidates": [
            {"spawn_id": 1, "role": "OBJECTIVE", "objective_id": "7:0",
             "entity_kind": "CREATURE", "entry": 99, "world_map_id": 2444,
             "x": 20., "y": 0., "z": 10.},
            {"spawn_id": 2, "role": "OBJECTIVE", "objective_id": "7:0",
             "entity_kind": "CREATURE", "entry": 99, "world_map_id": 2444,
             "x": 60., "y": 0., "z": 10.},
        ]}}},
    }


def choose(agent):
    objective = SimpleNamespace(objective_id="7:0", description="",
                                target_entity={}, target_location=None,
                                completion_state="INCOMPLETE")
    record = SimpleNamespace(quest_id=7)
    return agent.planner.quest.objective_locator.locate(objective, record, scene()).coordinates


def test_second_agent_cannot_replace_the_first_agents_location_cost(agents):
    first = agents({20.: 300., 60.: 62.})
    assert choose(first)["x"] == 60.
    second = agents({20.: 20., 60.: 500.})
    assert choose(second)["x"] == 20.
    assert choose(first)["x"] == 60.


def test_session_reset_keeps_each_agents_navigation_query(agents):
    first = agents({20.: 300., 60.: 62.})
    second = agents({20.: 20., 60.: 500.})
    first.planner.reset_session()
    first._reset_quest_runtime()
    assert choose(first)["x"] == 60.
    assert choose(second)["x"] == 20.


def test_pure_location_query_without_a_provider_does_not_borrow_an_agents_navigation(agents):
    agents({20.: 300., 60.: 62.})
    candidates = [{"x": 20., "y": 0., "z": 10.},
                  {"x": 60., "y": 0., "z": 10.}]
    assert tdb_locations._nearest(scene(), candidates) is candidates[0]


@pytest.mark.parametrize("consumer", ["quest_runtime", "turnin", "pickup",
                                     "agenda_work", "agenda_offer", "vehicle"])
def test_location_consumers_use_the_owning_cost_after_another_agent_starts(agents, consumer):
    from wowbot.agent.models import Goal, Observation
    from wowbot.agent.vehicle_prerequisites import resume_proposals

    first = agents({20.: 300., 60.: 62.})
    second = agents({20.: 20., 60.: 500.})
    for agent, expected in ((first, 60.), (second, 20.)):
        state = scene()
        state.update(monotonic_time=10., frame_id="cost-query", player_present=True,
                     orientation=0., position={"x": .5, "y": .5})
        quest = state["active_quests"][0]
        quest.update(title="Quest", is_accepted=True)
        quest["objectives"][0].update(objective_id="7:0", type="KILL",
                                      description="Creatures slain", required=1)
        reference = state["reference_knowledge"]["quests"]["7"]

        if consumer == "turnin":
            quest["is_complete"] = True
            for spawn in reference["spawn_candidates"]:
                spawn["role"] = "QUEST_ENDER"
        elif consumer in {"pickup", "agenda_offer"}:
            state["active_quests"] = []
            for spawn in reference["spawn_candidates"]:
                spawn["role"] = "QUEST_STARTER"
            state["map_pois"] = {"available_quests": [{
                "quest_id": 7, "is_campaign": True, "map_id": 2023,
                "world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2444,
                                   "map_id": 2023, "x": 40., "y": 0., "z": 10.}}]}

        if consumer == "quest_runtime":
            objective = SimpleNamespace(objective_id="7:0", description="", target_entity={},
                                        target_location=None, completion_state="INCOMPLETE")
            point = agent.quest_runtime.locator.locate(
                objective, SimpleNamespace(quest_id=7), state).coordinates
        elif consumer == "turnin":
            point = agent.planner.quest.location_policy.turnin_resolver.locate(
                SimpleNamespace(quest_id=7, known_locations=[]), state).location
        elif consumer == "pickup":
            (_, _, point), = agent.planner.quest.location_policy.map_pois._giver_candidates(state)
        elif consumer == "vehicle":
            state["in_vehicle"] = False
            state["vehicle_requirements"] = [{"quest_id": "7", "boarding_objective_id": "7:0",
                                              "npc_ids": ["99"]}]
            (move,) = resume_proposals(state, agent.planner.quest.server_npcs,
                                       travel_cost=agent.planner.travel_cost)
            assert move.skill == "MOVE"
            point = move.parameters
        else:
            agent.world.ingest(Observation.create(state, 10.))
            agent.planner.refresh_agenda(Goal.parse("Questelj", 10.), agent.world, 10.)
            key = "work:7" if consumer == "agenda_work" else "accept:7"
            point = next(step["location"] for step in agent.planner.agenda.snapshot()["steps"]
                         if step["key"] == key)
        assert point["x"] == expected


def test_cost_provider_is_not_serialized_with_locations_or_agenda(agents):
    import json

    first = agents({20.: 300., 60.: 62.})
    payload = {"location": choose(first), "world": first.world.state,
               "agenda": first.planner.agenda.snapshot(),
               "quest_runtime": first.quest_runtime.snapshot(10.)}
    assert json.loads(json.dumps(payload))["location"]["x"] == 60.


def test_unavailable_cost_query_preserves_the_geometric_fallback():
    candidates = [{"x": 20., "y": 0., "z": 10.},
                  {"x": 60., "y": 0., "z": 10.}]

    def unavailable(state, destination):
        raise RuntimeError("No geometry available")

    assert tdb_locations._nearest(scene(), candidates, travel_cost=unavailable) is candidates[0]

