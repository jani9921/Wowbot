from wowbot.agent.planner import QuestDomain


def quest_state(current=0):
    return {
        "active_quests": [{
            "quest_id": 101,
            "is_complete": False,
            "objectives": [{"current": current, "is_complete": current >= 1}],
        }]
    }


def test_uncredited_combat_target_waits_for_delayed_quest_export_then_suppresses():
    quest = QuestDomain()
    assert quest.record_uncredited_target("Creature-0-1", [101], ["101:0"], quest_state(), 10.0)

    # A success result alone is not grounds for calling the target wrong: the
    # addon is allowed a short bounded window to export the objective update.
    assert quest.credit_gate("Creature-0-1", [101], ["101:0"], quest_state(), 11.0) == "AWAITING_QUEST_CREDIT"
    assert quest.credit_gate("Creature-0-1", [101], ["101:0"], quest_state(), 12.1) == "NO_QUEST_CREDIT"


def test_quest_credit_change_clears_only_the_matching_target_memory():
    quest = QuestDomain()
    assert quest.record_uncredited_target("Creature-0-1", [101], ["101:0"], quest_state(), 10.0)

    # The new objective value is ground truth; the same target can be used
    # again for the next required kill instead of remaining globally banned.
    assert quest.credit_gate("Creature-0-1", [101], ["101:0"], quest_state(1), 10.5) is None
    assert not quest.no_credit_targets


def test_uncredited_memory_requires_a_guid_and_objective_not_a_generic_combat_target():
    quest = QuestDomain()
    assert not quest.record_uncredited_target("Creature-0-1", [101], [], quest_state(), 10.0)
    assert not quest.record_uncredited_target(None, [101], ["101:0"], quest_state(), 10.0)
    assert quest.credit_gate("Creature-0-1", [101], [], quest_state(), 12.1) is None
