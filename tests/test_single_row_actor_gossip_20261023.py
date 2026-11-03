"""A quest NPC to talk to whose window holds one row (live 2026-10-23 01:10).

A Last Hope (66001), "Meet Sendrax by the ritual site": the TDB credit is
Sendrax himself (190269); his window held one row, "I am ready." with no
"(Quest)" mark, and nothing was chosen.  User: a quest NPC to talk to with a
single row -- choose that row.
"""
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy

SENDRAX = "Creature-0-3769-2444-47-190269-00005824CB"


def option(option_id, name, y):
    return {"available": True, "display_name": name, "flags": 0, "icon": 132053, "id": option_id,
            "name": name, "quest_label_prepend": False, "x": .081, "y": y}


def state(options, *, target=SENDRAX, objective="0/1 Meet Sendrax by the ritual site"):
    return {
        "monotonic_time": 100.,
        "quest_ui": {"open": True, "action": "GOSSIP_OPTION_SELECT", "npc_guid": False, "quest_id": 0,
                     "gossip_options": options},
        "target": {"guid": target, "name": "Sendrax", "attackable": False, "dead": False,
                   "sample_time": 100.},
        "target_sample_time": 100.,
        "active_quests": [{"quest_id": 66001, "is_complete": False, "objectives": [
            {"description": objective, "is_complete": False, "raw_type": "monster", "type": "KILL"}]}],
        "reference_knowledge": {"quests": {"66001": {"objectives": [
            {"credit_kind": "CREATURE_CREDIT", "credit_name": "Sendrax", "credit_object_id": 190269,
             "description": "Meet Sendrax by the ritual site", "objective_id": 427620,
             "named_creatures": [{"entry": 187406, "name": "Sendrax"}]},
            {"credit_kind": "CREATURE_CREDIT", "credit_name": "Kill Credit: Pick Up Egg [DNT]",
             "credit_object_id": 191888, "description": "Pick up the Infused Dragon Egg",
             "objective_id": 427836}]}}},
    }


def test_the_one_row_of_the_objective_npc_is_chosen():
    pick = QuestDialogPlanningPolicy._talk_gossip(state([option(55259, "I am ready.", .634)]), True)
    assert pick is not None and pick.parameters["gossip_option_id"] == 55259
    assert pick.parameters["gossip_selection_basis"] == "SINGLE_ROW_OBJECTIVE_ACTOR"
    assert pick.parameters["quest_id"] == 66001


def test_no_guess_with_several_rows_another_npc_or_a_done_objective():
    two = [option(55259, "I am ready.", .634), option(55260, "Tell me about the eggs.", .60)]
    assert QuestDialogPlanningPolicy._talk_gossip(state(two), True) is None
    other = "Creature-0-3769-2444-47-190171-00005824CB"
    assert QuestDialogPlanningPolicy._talk_gossip(state([option(1, "Hello.", .6)], target=other), True) is None
    done = state([option(55259, "I am ready.", .634)], objective="0/1 Carry the egg to safety")
    assert QuestDialogPlanningPolicy._talk_gossip(done, True) is None
