"""V5 M3 offline acceptance: evidence-driven multi-step quest lifecycle.

This is intentionally not a prerecorded input macro.  It replays authoritative
quest observations through the normalized model/runtime/verifier boundaries and
proves that attempted actions alone cannot manufacture quest progress.
"""
from types import SimpleNamespace

from wowbot.agent.next_quest_resolver import NextQuestResolver
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_runtime import QuestExecutionRuntime
from wowbot.agent.quest_state import QuestState
from wowbot.verification import QuestProgressVerifier


QUEST_ID = 101
FOLLOW_UP_ID = 102


def _quest(*, state: str, kill_count: int = 0, loot_count: int = 0,
           is_campaign: bool = True) -> dict:
    return {
        "quest_id": QUEST_ID,
        "title": "A Test Beginning",
        "state": state,
        "is_campaign": is_campaign,
        "objectives": [
            {
                "objective_id": f"{QUEST_ID}:kill",
                "type": "KILL",
                "description": "Defeat one training enemy",
                "current": kill_count,
                "required": 1,
                "is_complete": kill_count >= 1,
                "branch_type": "SEQUENTIAL",
            },
            {
                "objective_id": f"{QUEST_ID}:loot",
                "type": "COLLECT",
                "description": "Collect one quest item",
                "current": loot_count,
                "required": 1,
                "is_complete": loot_count >= 1,
                "branch_type": "SEQUENTIAL",
            },
        ],
    }


def _ingest(model: QuestModel, quest: dict, observation_id: str, at: float) -> None:
    model.ingest([quest], observation_id, at)


def _projection(quest: dict, *, events=()) -> dict:
    return {"active_quests": [quest], "events": list(events)}


def test_multi_step_questline_requires_authoritative_progress_and_finds_follow_up():
    model = QuestModel()
    runtime = QuestExecutionRuntime()
    verifier = QuestProgressVerifier()
    goal = SimpleNamespace(
        domain="QUEST",
        parameters={"quest_id": QUEST_ID, "mode": "MAIN_CAMPAIGN"},
    )

    # Availability is a lifecycle fact, not an automatic acceptance fact.
    available = _quest(state="AVAILABLE")
    _ingest(model, available, "available", 1.0)
    assert model.records[QUEST_ID].lifecycle_state is QuestState.AVAILABLE

    # The addon-confirmed active quest is the acceptance proof.
    active = _quest(state="ACTIVE")
    acceptance = verifier.evaluate(
        {"active_quests": []},
        {"active_quests": [active], "accepted_quest_ids": [QUEST_ID]},
        quest_ids=[QUEST_ID],
    )
    assert acceptance.success
    assert {"quest_active:101", "quest_accepted:101"} <= set(acceptance.evidence)
    _ingest(model, active, "accepted", 2.0)
    first = runtime.observe(goal, model, {}, 2.0)
    assert first.status == "ACTIVE"
    assert first.objective_id == f"{QUEST_ID}:kill"
    assert first.objective_type == "KILL"

    # A successful combat attempt is not quest credit.  With identical quest
    # telemetry the verifier must reject progress and the model must remain at
    # the same objective/count.
    no_credit = verifier.evaluate(
        _projection(active), _projection(active),
        quest_ids=[QUEST_ID], objective_ids=[f"{QUEST_ID}:kill"],
    )
    assert not no_credit.success
    _ingest(model, active, "combat-action-succeeded-without-credit", 3.0)
    unchanged = runtime.observe(goal, model, {}, 3.0)
    assert unchanged.objective_id == f"{QUEST_ID}:kill"
    assert model.records[QUEST_ID].objectives[0].current_count == 0

    # Only the authoritative objective counter advances the stage.
    killed = _quest(state="ACTIVE", kill_count=1)
    kill_credit = verifier.evaluate(
        _projection(active), _projection(killed),
        quest_ids=[QUEST_ID], objective_ids=[f"{QUEST_ID}:kill"],
    )
    assert kill_credit.success
    assert kill_credit.evidence == (f"objective_changed:{QUEST_ID}:kill",)
    _ingest(model, killed, "kill-credit", 4.0)
    second = runtime.observe(goal, model, {}, 4.0)
    assert second.objective_id == f"{QUEST_ID}:loot"
    assert second.objective_type == "COLLECT"
    assert second.stage_revision >= 1

    # The collect stage follows the same rule: a LOOT action without an addon
    # count change is not completion.
    no_loot_credit = verifier.evaluate(
        _projection(killed), _projection(killed),
        quest_ids=[QUEST_ID], objective_ids=[f"{QUEST_ID}:loot"],
    )
    assert not no_loot_credit.success

    objectives_complete = _quest(
        state="OBJECTIVES_COMPLETE", kill_count=1, loot_count=1,
    )
    loot_credit = verifier.evaluate(
        _projection(killed), _projection(objectives_complete),
        quest_ids=[QUEST_ID], objective_ids=[f"{QUEST_ID}:loot"],
    )
    assert loot_credit.success
    _ingest(model, objectives_complete, "loot-credit", 5.0)
    completion = runtime.observe(
        goal, model, {"quest_completion_mode": "NPC_TURN_IN"}, 5.0,
    )
    assert completion.status == "OBJECTIVES_COMPLETE"
    assert completion.phase == "LOCATE_TURNIN"

    ready = _quest(state="READY_TO_TURN_IN", kill_count=1, loot_count=1)
    _ingest(model, ready, "ready-to-turn-in", 6.0)
    turnin = runtime.observe(
        goal, model, {"quest_completion_mode": "NPC_TURN_IN"}, 6.0,
    )
    assert turnin.status == "READY_TO_TURN_IN"
    assert turnin.phase == "LOCATE_TURNIN"

    # Turn-in is verified by the matching event, then retained as history.
    turned_in_event = {
        "event_type": "QUEST_TURNED_IN",
        "payload": {"quest_id": QUEST_ID},
    }
    turned_in = verifier.evaluate(
        _projection(ready), {"active_quests": [], "events": [turned_in_event]},
        quest_ids=[QUEST_ID],
    )
    assert turned_in.success
    assert turned_in.evidence == (f"quest_turned_in:{QUEST_ID}",)
    model.apply_event(SimpleNamespace(
        event_type="QUEST_TURNED_IN",
        quest_ids=(QUEST_ID,),
        received_at=7.0,
        observation_id="turned-in",
        event_id="event-turned-in",
    ))
    assert model.records[QUEST_ID].lifecycle_state is QuestState.TURNED_IN

    # Follow-up preference is evidence-bound: exactly one addon-marked active
    # campaign quest can be selected, an arbitrary side quest cannot.
    _ingest(model, {
        "quest_id": FOLLOW_UP_ID,
        "title": "The Next Step",
        "state": "ACTIVE",
        "is_campaign": True,
        "dependencies": [str(QUEST_ID)],
        "objectives": [],
    }, "follow-up", 8.0)
    resolution = NextQuestResolver().resolve(
        model.records.values(), main_campaign=True,
    )
    assert resolution.quest_id == str(FOLLOW_UP_ID)
    assert resolution.source == "ADDON_CAMPAIGN_FLAG"

