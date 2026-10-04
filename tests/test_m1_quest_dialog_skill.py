from wowbot.agent.models import Attempt, Outcome, Prediction, Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import QuestDialogSkill
from wowbot.verification import QuestProgressVerifier


def _active(action="ACCEPT", quest_id=42, **extra):
    params = {"action": action, "quest_id": quest_id, "x": .3, "y": .4, **extra}
    attempt = Attempt("action", Proposal.make("QUEST_DIALOG", "test", params), {}, "obs", 1., 10., (),
                      Prediction("prediction", "action", "state", 1., 10., "obs"))
    runtime = ActiveSkillRuntime()
    state = runtime.start(intent=Intent("QUEST_DIALOG", params), attempt=attempt, now=1., before_snapshot={})
    return state


def test_explicit_quest_accept_click_requires_matching_open_dialog_and_ground_truth():
    skill = QuestDialogSkill()
    state = _active()
    before = {"quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 42}}
    started = skill.begin(state, before)
    assert started.status is SkillStatus.RUNNING and started.commands[0].kind == "CLICK"
    pending = skill.verify(state, before, 2.)
    assert pending.status is SkillStatus.RUNNING
    after = {"quest_ui": {"open": False}, "accepted_quest_ids": [42]}
    assert skill.verify(state, after, 3.).status is SkillStatus.SUCCESS


def test_blocking_ui_context_prevents_quest_click():
    state = _active()
    before = {
        "loading": True,
        "quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 42},
    }
    result = QuestDialogSkill().begin(state, before)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "UI_UNKNOWN"
    assert result.commands == ()
    assert result.metadata["blocking_state"] == "LOADING"


def test_turnin_and_quest_credit_require_matching_turnin_event():
    skill = QuestDialogSkill()
    state = _active("TURN_IN", 42)
    before = {"quest_ui": {"open": True, "action": "TURN_IN", "quest_id": 42},
              "active_quests": [{"quest_id": 42, "objectives": []}]}
    assert skill.begin(state, before).status is SkillStatus.RUNNING
    unmatched = {"events": [{"event_type": "QUEST_TURNED_IN", "payload": {"quest_id": 43}}]}
    assert skill.verify(state, unmatched, 2.).status is SkillStatus.RUNNING
    after = {"events": [{"event_type": "QUEST_TURNED_IN", "payload": {"quest_id": 42}}]}
    assert skill.verify(state, after, 3.).status is SkillStatus.SUCCESS
    credit = QuestProgressVerifier().evaluate(before, after, quest_ids=[42])
    assert credit.success and "quest_turned_in:42" in credit.evidence


def test_reward_is_blocked_without_explicit_reward_policy():
    state = _active("REWARD")
    result = QuestDialogSkill().begin(state, {"quest_ui": {"open": True, "action": "REWARD", "quest_id": 42}})
    assert result.status is SkillStatus.BLOCKED


def test_reward_selection_requires_the_exact_addon_exported_row_then_verifies_selection():
    skill = QuestDialogSkill()
    state = _active("REWARD_SELECT", 42, reward_choice_index=2, reward_item_id=200)
    before = {"quest_ui": {"open": True, "action": "REWARD_SELECT", "quest_id": 42,
                            "reward_choices": [
                                {"index": 1, "item_id": 100, "x": .2, "y": .3, "selected": False},
                                {"index": 2, "item_id": 200, "x": .3, "y": .4, "selected": False},
                            ]}}
    started = skill.begin(state, before)
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].kind == "CLICK"
    wrong = {"quest_ui": {"open": True, "action": "REWARD_SELECT", "quest_id": 42,
                           "reward_selected_index": 1}}
    assert skill.verify(state, wrong, 2.).status is SkillStatus.FAILURE

    state = _active("REWARD_SELECT", 42, reward_choice_index=2, reward_item_id=200)
    assert skill.begin(state, before).status is SkillStatus.RUNNING
    after = {"quest_ui": {"open": True, "action": "COMPLETE", "quest_id": 42,
                            "reward_selected_index": 2}}
    verified = skill.verify(state, after, 2.)
    assert verified.status is SkillStatus.SUCCESS
    assert verified.evidence == ("reward_selected:42:2",)


def test_gossip_row_requires_the_exact_exported_row_then_same_quest_action():
    skill = QuestDialogSkill()
    state = _active("GOSSIP_SELECT", 42, gossip_kind="AVAILABLE")
    listing = {"quest_ui": {"open": True, "entries": [
        {"kind": "AVAILABLE", "quest_id": 42, "x": .3, "y": .4},
    ]}}
    started = skill.begin(state, listing)
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].kind == "CLICK"
    # A changed dialog for another quest is not a successful row selection.
    wrong = {"quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 43}}
    assert skill.verify(state, wrong, 2.).status is SkillStatus.FAILURE

    state = _active("GOSSIP_SELECT", 42, gossip_kind="AVAILABLE")
    assert skill.begin(state, listing).status is SkillStatus.RUNNING
    selected = {"quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 42}}
    result = skill.verify(state, selected, 2.)
    assert result.status is SkillStatus.SUCCESS
    assert result.evidence == ("gossip_selected:42",)


def test_legacy_registry_refuses_to_verify_dialogs_outside_the_canonical_skill():
    """There must not be a second dialog verifier beside QuestDialogSkill."""
    state = _active()
    outcome, reason = SkillRegistry().verify(state.attempt, None, 2.)
    assert outcome is Outcome.FAILURE
    assert reason == "canonical_quest_dialog_skill_required"
