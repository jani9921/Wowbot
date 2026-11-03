"""One shared target cost (user 2026-10-27, Obsidian Citadel 16:10): the
player stood on the wall (server z 260) beside the usable South Siege
Arbalest (z 256, 60 yd); the kill hunt walked for a courtyard Qalashi 45 yd
below and the committed walk hid the arbalest."""
from wowbot.agent.autonomy_loop import AutonomousLoop
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.objective_choice import (ObjectiveContext, better_than_commitment, effective_yards,
                                           objective_adjustment)
from wowbot.agent.world import WorldModel

from test_agent_core import state as base

ARBALEST = "GameObject-0-1461-2534-147807-376253-000060A8EF"


def citadel(**changes):
    return {"monotonic_time": 100.,
            "player_world_position": {"x": 2242.2, "y": 2521.2, "z": 260.6, "z_observed": True,
                                      "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
            "active_quests": [
                {"quest_id": 65939, "is_complete": False, "objectives": [
                    {"description": "1/1 Speak with Wrathion", "is_complete": True, "required": 1, "type": "KILL"},
                    {"description": "1/1 Obsidian Citadel entered", "is_complete": True, "required": 1},
                    {"description": "3/12 Qalashi Forces slain", "is_complete": False, "required": 12,
                     "type": "KILL"}]},
                {"quest_id": 66044, "is_complete": False, "objectives": [
                    {"description": "1/1 Assist Wrathion", "is_complete": True, "required": 1},
                    {"description": "0/1 South Siege Arbalest destroyed", "is_complete": False, "required": 1}]}],
            "packet_entities": {ARBALEST: {"guid": ARBALEST, "kind": "GAMEOBJECT", "entry_id": 376253,
                                           "position": {"x": 2183.07, "y": 2512.03, "z": 256.21}}},
            **changes}


QALASHI = Proposal.make("MOVE", "kill", {
    "purpose": "APPROACH_SERVER_KILL_TARGET", "quest_id": "65939", "objective_id": "65939:2",
    "x": 2203.37, "y": 2516.62, "z": 214.4, "z_known": True, "coordinate_space": "WORLD_YARDS",
    "server_entity_guid": "Creature-0-1461-2534-147807-186892-0002E0A8EF"}, priority=116)
ARBALEST_MOVE = Proposal.make("MOVE", "linked object", {
    "purpose": "APPROACH_QUEST_OBJECT_SPAWN", "quest_id": "66044", "x": 2183.07, "y": 2512.03,
    "z": 256.21, "z_known": True, "coordinate_space": "WORLD_YARDS", "server_entity_guid": ARBALEST},
    priority=103)


def test_route_cost_counts_the_height_to_the_courtyard():
    state = citadel()
    assert round(effective_yards(state, {"x": 2183.07, "y": 2512.03, "z": 256.21})) == 61   # same level
    assert effective_yards(state, {"x": 2203.37, "y": 2516.62, "z": 214.4}) > 160     # 39 flat + 3x42


def test_the_same_level_object_beats_the_counted_courtyard_kill():
    state, context = citadel(), {"landing": None, "quests_seen": {}}
    kill = objective_adjustment(QALASHI, state, context, 100.)
    arbalest = objective_adjustment(ARBALEST_MOVE, state, context, 100.)
    assert kill["route"] == -8. and kill["counted"] == -3.
    assert arbalest["route"] == -4.07 and arbalest["counted"] == 0.
    # The policies' own priorities in the 16:10:41 state (campaign +4 each):
    # kill hunt 104, linked object 107.
    assert 104. + kill["total"] < 107. + arbalest["total"] - 6.


def test_placed_here_and_fresh_quest_bonuses():
    state = citadel()
    context = {"landing": {"x": 2240., "y": 2520., "z": 260.2, "at": 90., "reason": "VEHICLE_EXITED"},
               "quests_seen": {"66044": 80., "65939": float("-inf")}}
    arbalest = objective_adjustment(ARBALEST_MOVE, state, context, 100.)
    assert arbalest["landing"] == 6. and arbalest["fresh"] == 1.5
    kill = objective_adjustment(QALASHI, state, context, 100.)
    assert kill["landing"] == 0. and kill["fresh"] == 0.               # 46 yd below the landing
    assert objective_adjustment(ARBALEST_MOVE, state, context, 300.)["landing"] == 0.   # 2 min later


def test_the_context_sees_landings_and_new_quests():
    context = ObjectiveContext()
    riding = citadel(in_vehicle=True)
    context.observe(riding, 10.)
    assert context.snapshot()["quests_seen"] == {"65939": float("-inf"), "66044": float("-inf")}
    context.observe(citadel(), 11.)                                     # off Wrathion's back
    landing = context.snapshot()["landing"]
    assert landing["reason"] == "VEHICLE_EXITED" and landing["z"] == 260.6
    accepted = citadel()
    accepted["active_quests"].append({"quest_id": 66045, "objectives": []})
    context.observe(accepted, 12.)
    assert context.snapshot()["quests_seen"]["66045"] == 12.
    jumped = citadel()
    jumped["player_world_position"] = {**jumped["player_world_position"], "x": 2400.}
    context.observe(jumped, 13.)
    assert context.snapshot()["landing"]["reason"] == "TELEPORTED"


def test_a_clearly_better_target_releases_the_committed_walk():
    scores = {QALASHI.key: {"total": 104. - 8.45}, ARBALEST_MOVE.key: {"total": 107. - 4.45}}
    assert better_than_commitment(ARBALEST_MOVE, [QALASHI], scores)
    assert not better_than_commitment(ARBALEST_MOVE, [QALASHI], {**scores, ARBALEST_MOVE.key: {"total": 100.}})

    payload = base(100., **{k: v for k, v in citadel().items() if k != "monotonic_time"})
    world = WorldModel()
    world.ingest(Observation.create(payload, 100.))
    loop, goal = AutonomousLoop(), Goal.parse("Questelj", 1.)
    assert loop.choose([QALASHI], QALASHI, goal, world, 100.) is QALASHI                # committed walk
    kept = loop.choose([QALASHI, ARBALEST_MOVE], ARBALEST_MOVE, goal, world, 101., scores=scores)
    assert kept is QALASHI                                              # too soon to switch (3 s)
    chosen = loop.choose([QALASHI, ARBALEST_MOVE], ARBALEST_MOVE, goal, world, 104., scores=scores)
    assert chosen is ARBALEST_MOVE
    assert any(event["event"] == "COMMITMENT_RELEASED" and event.get("trigger") == "BETTER_OBJECTIVE"
               for event in loop.lifecycle)
