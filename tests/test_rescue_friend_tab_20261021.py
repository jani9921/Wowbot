"""Ctrl+Tab selects the rescue NPC; Interact when he is near (user 2026-10-21).

"Van olyan bind, hogy TARGETNEARESTFRIEND, Ctrl+Tab, azzal kijelöli Rellidet."
Live 10:47-10:52 Rellid stayed selected for minutes while the soft-interact
unit was him only in ~1 s windows.
"""
from types import SimpleNamespace

from wowbot.agent.rescue_object_planning import RescueTargetPolicy, open_rescue_entries
from wowbot.skills.target import TargetSkill

RELLID = "Creature-0-3769-2444-47-189055-00005824CB"


def state(*, now=100., target=None, soft=(), position=(3459., -1973.), **extra):
    return {
        "monotonic_time": now, "soft_targets_sample_time": now,
        "player_world_position": {"x": position[0], "y": position[1], "instance_id": 2444},
        "active_quests": [{"quest_id": 70122, "is_complete": False, "objectives": [
            {"description": "0/1 Archivist Rellid rescued", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"70122": {"objectives": [
            {"description": "Archivist Rellid rescued", "named_creatures": [{"entry": 189055}]}]}}},
        "target": target or {}, "soft_targets": list(soft), **extra}


SELECTED = {"guid": RELLID, "npc_id": 189055, "name": "Archivist Rellid", "attackable": False, "dead": False}


def test_open_rescue_objectives_name_their_npc():
    assert open_rescue_entries(state()) == {"189055": "70122"}


def test_friend_tab_after_a_sighting_nearby_and_not_before():
    policy = RescueTargetPolicy()
    assert policy.propose(state()) == []                                    # never seen
    policy.propose(state(now=90., soft=[{"source_unit": "softfriend", "guid": RELLID, "npc_id": 189055}]))
    (tab,) = policy.propose(state(now=95.))
    assert tab.skill == "TARGET" and tab.parameters["activation_source"] == "TAB_FRIEND_RESCUE"
    assert tab.parameters["guid"] == RELLID
    assert policy.propose(state(now=96.)) == []                            # 4 s between presses
    assert RescueTargetPolicy().propose(state(now=95., position=(3600., -1973.))) == []


def test_interact_while_he_is_selected_and_near():
    policy = RescueTargetPolicy()
    (press,) = policy.propose(state(target={**SELECTED, "interact_near": True}))
    assert press.skill == "INTERACT" and press.parameters["guid"] == RELLID and press.parameters["no_hover"]
    assert policy.propose(state(now=100.5, target={**SELECTED, "interact_near": True})) == []
    assert len(policy.propose(state(now=101.6, target={**SELECTED, "interact_near": True}))) == 1
    assert RescueTargetPolicy().propose(state(target={**SELECTED, "interact_near": False})) == []
    other_soft = [{"source_unit": "softinteract", "guid": "Creature-0-1-2444-1-1-1", "npc_id": 1}]
    assert RescueTargetPolicy().propose(state(target={**SELECTED, "interact_near": True}, soft=other_soft)) == []
    # Older addon (no distance): a press every 3 s.
    old = RescueTargetPolicy()
    assert len(old.propose(state(target=SELECTED))) == 1
    assert old.propose(state(now=102., target=SELECTED)) == []
    assert len(old.propose(state(now=103.1, target=SELECTED))) == 1


def test_target_skill_presses_ctrl_tab_and_rejects_another_friend():
    skill = TargetSkill()
    intent = SimpleNamespace(parameters={"activation_source": "TAB_FRIEND_RESCUE", "guid": RELLID})
    (command,) = skill.commands_for(intent)
    assert command.binding == "TARGETNEARESTFRIEND"
