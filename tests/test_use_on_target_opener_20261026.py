"""Proto-Fight (66122): Tab the drake, F7 (the harpoon), then fight it.

Live 2026-10-26 16:54:49: the first COMBAT press was Charge at a drake in
the air ("No path available"); at 14:28:03 an F7 on a drake had fired the
harpoon and brought it down.  User: "odamegy, tab, F7, utána megtámadja és
megöli".
"""
from test_m0_combat_loot_skills import active
from wowbot.agent.packet_entity_facts import use_on_target_opener
from wowbot.runtime import SkillStatus
from wowbot.skills.combat import CombatSkill

DRAKE = "Creature-0-3769-2444-47-187212-00005F7335"
REFERENCE = {"quests": {"66122": {"objectives": [
    {"credit_kind": "CREATURE_CREDIT", "credit_name": "Kill Credit: Spear [DNT]", "credit_object_id": 195126,
     "description": "Use the Ruby Harpoon on a proto-dragon", "raw_type": 0, "credit_creatures": [],
     "named_creatures": []},
    {"credit_kind": "CREATURE_CREDIT", "credit_name": "Kill Credit: Q09 Proto-dragon [DNT]",
     "credit_object_id": 189618, "description": "Proto-dragons slain", "raw_type": 0,
     "credit_creatures": [{"entry": 187212, "name": "Rumbling Proto-Dragon"}],
     "named_creatures": [{"entry": 184477, "name": "Proto-dragon"}]}]}}}


def fight(**extra):
    return {"monotonic_time": 10., "is_in_combat": False,
            "target": {"guid": DRAKE, "npc_id": 187212, "attackable": True, "dead": False, "health": 100},
            "actionbar": [{"id": 100, "kind": "spell", "action": "ACTIONBUTTON1", "name": "Charge",
                           "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0}],
            "active_quests": [{"quest_id": 66122, "title": "Proto-Fight",
                               "special_item": {"item_id": 192436, "item_name": "Ruby Spear"},
                               "objectives": [
                                   {"type": "KILL", "raw_type": "monster", "is_complete": True,
                                    "description": "1/1 Use the Ruby Harpoon on a proto-dragon (Optional)"},
                                   {"type": "KILL", "raw_type": "monster", "is_complete": False,
                                    "description": "1/3 Proto-dragons slain", "current": 1, "required": 3}]}],
            "reference_knowledge": REFERENCE, **extra}


def test_the_drake_is_opened_with_interact_then_the_rotation_follows():
    state = fight()
    assert use_on_target_opener(state, DRAKE)
    skill = CombatSkill()
    running = active("COMBAT", {"guid": DRAKE, "quest_ids": [66122]}, state)
    first = skill.begin(running, state, 10.)
    assert first.status is SkillStatus.RUNNING and [c.binding for c in first.commands] == ["INTERACTTARGET"]


def test_no_opener_without_a_use_objective_or_quest_item():
    plain = fight()
    plain["active_quests"][0]["special_item"] = None
    assert not use_on_target_opener(plain, DRAKE)
    other = fight()
    assert not use_on_target_opener(other, "Creature-0-3769-2444-47-187999-00005F7335")
