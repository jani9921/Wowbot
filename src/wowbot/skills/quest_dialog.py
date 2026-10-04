"""Canonical safe quest-dialog skill for M1 accept/turn-in transitions."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from wowbot.agent.ui_context import BlockingState, resolve_ui_context
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification.quest_dialog import QuestDialogVerifier


class QuestDialogPhase(StrEnum):
    VALIDATE_CONTEXT = "VALIDATE_CONTEXT"
    SELECT_GOSSIP_ROW = "SELECT_GOSSIP_ROW"
    SELECT_REWARD = "SELECT_REWARD"
    CLICK_EXPLICIT_ACTION = "CLICK_EXPLICIT_ACTION"
    WAIT_STATE = "WAIT_STATE"
    VERIFY = "VERIFY"


class QuestDialogSkill:
    """Act only on a telemetry-confirmed quest dialog action.

    Reward selection is admitted only for an exact planner-selected row that
    the addon exported with a valid screen coordinate.  It is never inferred
    from the generic Complete button or a display/list ordering.
    """

    _SUPPORTED_ACTIONS = frozenset({"GOSSIP_SELECT", "REWARD_SELECT", "ACCEPT", "COMPLETE", "TURN_IN", "CONTINUE"})

    def __init__(self, verifier: QuestDialogVerifier | None = None):
        self.verifier = verifier or QuestDialogVerifier()

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params = state.intent.parameters
        action = str(params.get("action") or "").upper()
        quest_id = params.get("quest_id")
        x, y = number(params.get("x")), number(params.get("y"))
        ui = world_state.get("quest_ui") or {}
        ui_context = resolve_ui_context(world_state)
        observed_action = str(ui.get("action") or world_state.get("quest_ui_action") or "").upper()
        observed_quest = ui.get("quest_id") if ui.get("quest_id") is not None else world_state.get("quest_ui_quest_id")
        opened = ui.get("open") is True or world_state.get("quest_ui_open") is True
        state.phase = QuestDialogPhase.VALIDATE_CONTEXT.value
        if ui_context.blocking_state is not BlockingState.NONE:
            return SkillResult(SkillStatus.FAILURE, FailureReason.UI_UNKNOWN,
                               retryable=True, replan_required=True,
                               metadata={"blocking_state": ui_context.blocking_state.value})
        if action not in self._SUPPORTED_ACTIONS:
            return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                               replan_required=True,
                               metadata={"unsupported_dialog_action": action or "MISSING"})
        if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                               retryable=True, replan_required=True)
        if not opened:
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                               retryable=True, replan_required=True)
        if action == "GOSSIP_SELECT":
            # A row in GossipFrame is not an Accept button.  Click only the
            # exact addon-exported row, then wait for the same quest to expose
            # a named dialog action on the next telemetry state.
            wanted_kind = str(params.get("gossip_kind") or "").upper()
            matches_row = any(
                isinstance(entry, dict)
                and str(entry.get("quest_id")) == str(quest_id)
                and str(entry.get("kind") or "").upper() == wanted_kind
                and abs((number(entry.get("x")) or -1.) - x) <= .002
                and abs((number(entry.get("y")) or -1.) - y) <= .002
                for entry in ui.get("entries", world_state.get("quest_ui_entries", ()))
            )
            if not matches_row:
                return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                                   retryable=True, replan_required=True)
            state.skill_context["quest_dialog"] = {
                "action": action, "quest_id": quest_id, "gossip_kind": wanted_kind,
            }
            state.phase = QuestDialogPhase.SELECT_GOSSIP_ROW.value
            return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=x, y=y),))
        if action == "REWARD_SELECT":
            wanted_index = params.get("reward_choice_index")
            wanted_item_id = params.get("reward_item_id")
            matches_choice = any(
                isinstance(choice, dict)
                and str(choice.get("index")) == str(wanted_index)
                and (wanted_item_id is None or str(choice.get("item_id")) == str(wanted_item_id))
                and choice.get("selected") is not True
                and abs((number(choice.get("x")) or -1.) - x) <= .002
                and abs((number(choice.get("y")) or -1.) - y) <= .002
                for choice in ui.get("reward_choices", ())
            )
            if (observed_action != "REWARD_SELECT" or wanted_index is None
                    or not matches_choice):
                return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                                   retryable=True, replan_required=True)
            if quest_id is not None and observed_quest is not None and str(quest_id) != str(observed_quest):
                return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                                   retryable=True, replan_required=True)
            state.skill_context["quest_dialog"] = {
                "action": action, "quest_id": quest_id,
                "reward_choice_index": wanted_index,
            }
            state.phase = QuestDialogPhase.SELECT_REWARD.value
            return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=x, y=y),))
        if observed_action and observed_action != action:
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                               retryable=True, replan_required=True)
        if quest_id is not None and observed_quest is not None and str(quest_id) != str(observed_quest):
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                               retryable=True, replan_required=True)
        state.skill_context["quest_dialog"] = {"action": action, "quest_id": quest_id}
        state.phase = QuestDialogPhase.CLICK_EXPLICIT_ACTION.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=x, y=y),))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("quest_dialog") or {}
        state.phase = QuestDialogPhase.VERIFY.value
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        quest_id=context.get("quest_id"),
                                        action=str(context.get("action") or ""),
                                        reward_choice_index=context.get("reward_choice_index"))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if result.reason is not None:
            return SkillResult(SkillStatus.FAILURE, result.reason,
                               retryable=result.retry_recommended, replan_required=True)
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.EXPECTED_STATE_NOT_REACHED,
                               retryable=True, replan_required=True)
        state.phase = QuestDialogPhase.WAIT_STATE.value
        return SkillResult(SkillStatus.RUNNING)
