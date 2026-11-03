"""Who Lurks in the Pit, live 2026-10-20 09:59:23-10:00:34 (offline).

The minimap floor-cue MOVE failed three times in 0.34 s
(``no_layer_matching_floor_cue``).  Its goal task was keyed by the bare quest
id "55639", so every quest-level MOVE of 55639 was blocked for 120 s.  The
Ride objective completed at 09:59:32; the turn-in walk ("Szerver: leadó NPC
pontos helye") was filtered out and FULL_AI waited on WAIT until the user
stopped it.
"""
from types import SimpleNamespace

from wowbot.agent.goal_manager import GoalManager
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.skills import SkillRegistry


def _quest(*counts, state="IN_PROGRESS"):
    return SimpleNamespace(records={"55639": SimpleNamespace(
        quest_id=55639, current_state=state, objectives=[
            SimpleNamespace(objective_id=f"55639:{index}", current_count=count,
                            completion_state="COMPLETE" if count else "PENDING")
            for index, count in enumerate(counts)])})


def _move(purpose, reason):
    return Proposal.make("MOVE", reason, {"quest_id": 55639, "purpose": purpose,
                                          "x": 109., "y": -2271., "map_id": 1409},
                         confidence=.85, priority=90)


def test_a_failed_floor_cue_walk_blocks_neither_the_turn_in_nor_other_walks():
    manager, contracts = GoalManager(), SkillRegistry().contracts
    manager.set_goal(Goal.parse("Questelj", 1), 1)
    floor_cue = _move("REACH_CUED_FLOOR", "Minimap fel/le quest-jel")
    turn_in = _move("LOCATE_TURN_IN_REGION", "Szerver: leadó NPC ('?') pontos helye (GUID)")
    assert manager.filter([floor_cue], contracts, 10.)
    for at in (10.1, 10.2, 10.3):
        manager.outcome(floor_cue, False, "no_layer_matching_floor_cue", at)
    assert manager.filter([floor_cue, turn_in], contracts, 11.) == [turn_in]


def test_quest_progress_lifts_the_block_of_that_quest():
    manager, contracts = GoalManager(), SkillRegistry().contracts
    manager.set_goal(Goal.parse("Questelj", 1), 1)
    walk = Proposal.make("MOVE", "quest-level walk", {"quest_id": 55639, "x": 1., "y": 2.},
                         confidence=.85, priority=90)       # no purpose: keyed "55639"
    manager.sync_world(_quest(5, 1, 0), 9.)
    assert manager.filter([walk], contracts, 10.)
    for at in (10.1, 10.2, 10.3):
        manager.outcome(walk, False, "no_layer_matching_floor_cue", at)
    assert manager.filter([walk], contracts, 11.) == []
    manager.sync_world(_quest(5, 1, 0), 12.)                # nothing new: still blocked
    assert manager.filter([walk], contracts, 12.) == []
    manager.sync_world(_quest(5, 1, 1, state="COMPLETE"), 20.)   # the Ride credit
    assert manager.filter([walk], contracts, 20.) == [walk]
    assert manager.goal.status != "RECOVERING"
