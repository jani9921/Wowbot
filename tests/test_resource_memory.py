from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def state(**overrides):
    value = {"session_id": "s", "frame_id": "f", "timestamp": 1,
             "map_id": 1609, "position": {"x": .1, "y": .1}, "orientation": 0,
             "game_build": "12.1.0", "addon_version": "0.8.1", "ui_scale": 1,
             "client_dimensions": {"width": 1600, "height": 900},
             "player_present": True, "is_in_combat": False, "is_casting": False,
             "actionbar": [], "resource_observations": []}
    value.update(overrides)
    return value


def test_resource_site_requires_repeated_verified_success(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    location = {"map_id": 1609, "x": .4, "y": .6}
    memory.record_resource_site(state(), "HERB", location, True, 1, {"verification_id": "v1"})
    assert memory.resource_sites(state(), "HERB") == []
    memory.record_resource_site(state(), "HERB", location, True, 2, {"verification_id": "v2"})
    memory.record_resource_site(state(), "HERB", location, True, 3, {"verification_id": "v3"})
    sites = memory.resource_sites(state(), "HERB")
    assert len(sites) == 1 and sites[0]["stage"] == "SUPPORTED"
    assert sites[0]["successes"] == 3 and sites[0]["provenance"]["verification_id"] == "v3"


def test_supported_resource_site_returns_through_shared_planner(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    location = {"map_id": 1609, "x": .4, "y": .6}
    for index in range(3):
        memory.record_resource_site(state(), "MINE", location, True, index, {"verification_id": str(index)})
    world = WorldModel(memory.sensor_weight)
    world.ingest(Observation.create(state(), 1))
    proposals = Planner(SkillRegistry(), memory).candidates(Goal.parse("Farmolj ore-t", 1), world, 1)
    assert proposals[0].skill == "MOVE"
    assert proposals[0].parameters["resource_type"] == "MINE"


def test_confirmed_herb_uses_typed_interaction_skill():
    world = WorldModel()
    node = {"id": "n1", "kind": "HERB", "confirmed": True, "map_id": 1609,
            "x": .2, "y": .3, "x_client": .55, "y_client": .6}
    world.ingest(Observation.create(state(resource_observations=[node]), 1))
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Gyógynövényeket gyűjts", 1), world, 1)
    assert proposals[0].skill == "HERB"
    assert proposals[0].parameters["node_id"] == "n1"


def test_registry_exposes_generic_interaction_and_combat_capabilities():
    names = SkillRegistry().contracts
    assert {"TALK", "USE", "OBJECT_USE", "HERB", "MINE", "DEFEND", "ESCAPE"} <= set(names)


def test_legacy_generic_use_is_fail_closed_in_favor_of_canonical_object_use():
    import pytest
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    with pytest.raises(ValueError, match="canonical quest skill"):
        SkillRegistry().commands(Proposal.make("USE", "legacy", {"x": .4, "y": .6}), world)


def test_low_health_prefers_configured_defensive_spell():
    registry = SkillRegistry()
    harmful = {"kind": "spell", "id": 1, "action": "ACTIONBUTTON1", "is_harmful": True,
               "is_usable": True, "in_range": True, "cooldown_remaining": 0}
    defensive = {"kind": "spell", "id": 2, "action": "ACTIONBUTTON2", "is_harmful": False,
                 "is_usable": True, "cooldown_remaining": 0}
    assert registry.combat_action({"health": 20, "max_health": 100,
        "defensive_spell_ids": [2], "actionbar": [harmful, defensive]})["id"] == 2


def test_full_inventory_blocks_gathering_without_safe_item_policy():
    node = {"id": "n1", "kind": "HERB", "confirmed": True, "map_id": 1609,
            "x": .2, "y": .3, "x_client": .55, "y_client": .6}
    current = world = WorldModel()
    current.ingest(Observation.create(state(resource_observations=[node],
        inventory={"items": [], "free_slots": 0}), 1))
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Gyógynövényeket gyűjts", 1), world, 1)
    assert proposals[0].skill == "WAIT"
    assert proposals[0].parameters["constraint"] == "INVENTORY_FULL"
    assert not any(item.skill == "HERB" for item in proposals)


def test_full_inventory_can_route_only_to_explicit_destination():
    current = WorldModel()
    current.ingest(Observation.create(state(inventory={"items": [], "free_slots": 0}), 1))
    goal = Goal.parse("Farmolj ore-t", 1, {"inventory_destination": {"map_id": 1609, "x": .8, "y": .7}})
    proposal = Planner(SkillRegistry()).candidates(goal, current, 1)[0]
    assert proposal.skill == "MOVE" and proposal.parameters["inventory_subgoal"] == "RETURN"


def test_fishing_lifecycle_cast_wait_bite_then_shared_loot():
    action = {"kind": "spell", "name": "Fishing", "action": "ACTIONBUTTON1", "is_usable": True,
              "cooldown_remaining": 0}
    goal = Goal.parse("Fishingelj", 1)
    casting = WorldModel(); casting.ingest(Observation.create(state(actionbar=[action], fishing={}), 1))
    assert Planner(SkillRegistry()).candidates(goal, casting, 1)[0].skill == "FISH"
    waiting = WorldModel(); waiting.ingest(Observation.create(state(actionbar=[action], fishing={"active": True}), 2))
    assert Planner(SkillRegistry()).candidates(goal, waiting, 2)[0].skill == "WAIT"
    bite = WorldModel(); bite.ingest(Observation.create(state(actionbar=[action],
        fishing={"active": True, "bite_confirmed": True, "x": .4, "y": .6}), 3))
    assert Planner(SkillRegistry()).candidates(goal, bite, 3)[0].skill == "GATHER"
