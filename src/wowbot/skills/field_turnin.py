"""Mode-guarded field quest completion under the canonical dialog executor."""
from __future__ import annotations

from enum import StrEnum

from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from .quest_dialog import QuestDialogSkill


class FieldTurnInPhase(StrEnum):
    DETECT_PROMPT = "DETECT_PROMPT"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    REWARD_IF_NEEDED = "REWARD_IF_NEEDED"
    VERIFY_COMPLETED = "VERIFY_COMPLETED"


class FieldTurnInSkill:
    """Specialize field completion without owning a second click path."""

    ACTIONS = frozenset({"COMPLETE", "TURN_IN", "REWARD_SELECT"})

    def __init__(self, dialog: QuestDialogSkill) -> None:
        self.dialog = dialog

    @staticmethod
    def detect_prompt(world_state: dict) -> dict | None:
        ui = world_state.get("quest_ui") or {}
        action = str(ui.get("action") or world_state.get("quest_ui_action") or "").upper()
        opened = ui.get("open") is True or world_state.get("quest_ui_open") is True
        return ui if opened and action in FieldTurnInSkill.ACTIONS else None

    def open(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        result = self.dialog.begin(state, world_state)
        state.phase = FieldTurnInPhase.OPEN.value
        return result

    def complete(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        result = self.dialog.begin(state, world_state)
        state.phase = FieldTurnInPhase.COMPLETE.value
        return result

    def reward_if_needed(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        result = self.dialog.begin(state, world_state)
        state.phase = FieldTurnInPhase.REWARD_IF_NEEDED.value
        return result

    def verify_completed(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        result = self.dialog.verify(state, world_state, now)
        state.phase = FieldTurnInPhase.VERIFY_COMPLETED.value
        return result

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        state.phase = FieldTurnInPhase.DETECT_PROMPT.value
        params = state.intent.parameters
        mode = str(params.get("completion_mode") or world_state.get("quest_completion_mode")
                   or (world_state.get("primary_quest") or {}).get("completion_mode") or "").upper()
        prompt = self.detect_prompt(world_state)
        if mode != "FIELD_TURN_IN":
            return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                               replan_required=True,
                               metadata={"reason": "field_turnin_mode_not_confirmed"})
        if prompt is None:
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                               retryable=True, replan_required=True)
        action = str(params.get("action") or "").upper()
        if action == "REWARD_SELECT":
            state.phase = FieldTurnInPhase.REWARD_IF_NEEDED.value
            return self.reward_if_needed(state, world_state)
        state.phase = FieldTurnInPhase.COMPLETE.value
        return self.complete(state, world_state)

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        state.phase = FieldTurnInPhase.VERIFY_COMPLETED.value
        return self.verify_completed(state, world_state, now)
