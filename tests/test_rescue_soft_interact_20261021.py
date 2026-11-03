"""Rescue a passenger of a circling drake by clicking it (live 2026-10-21).

10:34:42 (Explorers in Peril): Archivist Rellid (189055) rode a circling
Primal Proto-Drake; the server sent him once from 100 yd only.  When the drake
passed, the client's soft-interact unit was Rellid while the agent searched
the screen.  User: "rá kell kattintani" -- Interact at once.
"""
from types import SimpleNamespace

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.agent.rescue_object_planning import SoftInteractRescuePolicy, rescue_soft_target

RELLID = "Creature-0-3769-2444-47-189055-00005824CB"


def state(*, now=100., soft=None, complete=False, objective="0/1 Archivist Rellid rescued", **extra):
    return {
        "monotonic_time": now, "soft_targets_sample_time": now,
        "active_quests": [{"quest_id": 70122, "is_complete": False, "objectives": [
            {"description": objective, "is_complete": complete, "type": "KILL", "raw_type": "monster"}]}],
        "reference_knowledge": {"quests": {"70122": {"objectives": [
            {"description": "Archivist Rellid rescued", "credit_kind": "CREATURE_CREDIT",
             "named_creatures": [{"entry": 189055}, {"entry": 189061}]}]}}},
        "soft_targets": [soft if soft is not None else {
            "source_unit": "softinteract", "guid": RELLID, "name": "Archivist Rellid", "npc_id": 189055,
            "is_attackable": False, "is_dead": False, "unit_type": "NPC"}],
        **extra}


def test_the_rescue_npc_under_soft_interact_is_recognised():
    found = rescue_soft_target(state())
    assert found["guid"] == RELLID and found["quest_id"] == "70122"
    assert rescue_soft_target(state(complete=True)) is None
    assert rescue_soft_target(state(objective="0/1 Something else rescued")) is None
    hostile = {"source_unit": "softinteract", "guid": RELLID, "npc_id": 189055, "is_attackable": True}
    assert rescue_soft_target(state(soft=hostile)) is None
    other = {"source_unit": "softinteract", "guid": "Creature-0-1-2444-1-192103-01", "npc_id": 192103}
    assert rescue_soft_target(state(soft=other)) is None


def test_interact_is_pressed_at_once_and_not_spammed():
    policy = SoftInteractRescuePolicy()
    (press,) = policy.propose(state())
    assert press.skill == "INTERACT" and press.priority > 120
    assert press.parameters["activation_source"] == "SOFT_INTERACT" and press.parameters["soft_guid"] == RELLID
    assert policy.propose(state(now=100.5)) == []                   # 1.5 s between presses
    assert len(policy.propose(state(now=101.6))) == 1
    stale = {**state(now=200.), "soft_targets_sample_time": 190.}
    assert SoftInteractRescuePolicy().propose(stale) == []
    assert SoftInteractRescuePolicy().propose(state(is_in_combat=True)) == []


def test_a_running_move_stops_for_the_passing_rescue_npc():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "zone", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "coordinate_space": "WORLD_YARDS",
                         "instance_id": 2444, "x": 3450., "y": -1970.}))
    handoff = movement_visual_interrupt(attempt, state(), identity_only=True)
    assert handoff["kind"] == "RESCUE_NPC_SOFT_INTERACT" and handoff["guid"] == RELLID
    no_soft = state(soft={"source_unit": "softenemy", "guid": "x"})
    assert movement_visual_interrupt(attempt, no_soft, identity_only=True) is None
