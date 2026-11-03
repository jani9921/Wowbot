"""Canonical safe quest-dialog skill for M1 accept/turn-in transitions."""
from __future__ import annotations

from wowbot.runtime.skill_identity import identity_guarded

from enum import StrEnum

from wowbot.agent.models import Command, number
from wowbot.agent.ui_context import BlockingState, resolve_ui_context
from wowbot.agent.quest_ui_evidence import dialog_evidence_allows, dialog_recipient, quest_option_marked
from wowbot.agent.quest_semantics import friendly_live_npc
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

    _SUPPORTED_ACTIONS = frozenset({"GOSSIP_SELECT", "GOSSIP_OPTION_SELECT", "GOSSIP_VENDOR", "REWARD_SELECT",
                                    "ACCEPT", "COMPLETE", "TURN_IN", "CONTINUE", "GOSSIP_CONFIRM"})
    GOSSIP_CONFIRM_MAX_COPPER = 100

    def __init__(self, verifier: QuestDialogVerifier | None = None):
        self.verifier = verifier or QuestDialogVerifier()

    @identity_guarded
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
        if not dialog_evidence_allows(world_state, params, received_now=state.started_at):
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                               retryable=True, replan_required=True,
                               metadata={"reason": "stale_dialog_evidence"})
        if action == "GOSSIP_CONFIRM":
            # Addon 0.9.81: the exact visible GOSSIP_CONFIRM Accept button, a small known sum.
            confirm = ui.get("gossip_confirm") or {}
            money = number(confirm.get("money"))
            cx, cy = number(confirm.get("x")), number(confirm.get("y"))
            if (confirm.get("open") is not True or confirm.get("enabled") is False or money is None
                    or not 0 < money <= self.GOSSIP_CONFIRM_MAX_COPPER or cx is None or cy is None
                    or abs(cx-x) > .02 or abs(cy-y) > .02):
                return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                                   retryable=True, replan_required=True,
                                   metadata={"reason": "gossip_confirm_not_current"})
            state.skill_context["quest_dialog"] = {"action": action, "quest_id": quest_id, "money": int(money)}
            state.phase = QuestDialogPhase.CLICK_EXPLICIT_ACTION.value
            return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=cx, y=cy),))
        if action == "GOSSIP_VENDOR":
            # User 2026-10-21 (Cataloger Jakes): the shop behind a gossip row.
            # Click only that exact exported row of the selected vendor NPC.
            target = world_state.get("target") or {}
            option = next((row for row in ui.get("gossip_options") or () if isinstance(row, dict)
                           and str(row.get("id")) == str(params.get("gossip_option_id"))), None)
            exact = (option is not None and friendly_live_npc(target) and bool(target.get("guid"))
                     and str(target.get("guid")) == str(params.get("target_guid") or "")
                     and str(option.get("name") or "") == str(params.get("gossip_option_name") or "")
                     and abs((number(option.get("x")) or -1.) - x) <= .002
                     and abs((number(option.get("y")) or -1.) - y) <= .002)
            if not exact:
                return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                                   retryable=True, replan_required=True)
            state.skill_context["quest_dialog"] = {"action": action, "quest_id": quest_id,
                                                   "target_guid": target["guid"],
                                                   "gossip_option_id": option["id"]}
            state.phase = QuestDialogPhase.SELECT_GOSSIP_ROW.value
            return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=x, y=y),))
        if action == "GOSSIP_OPTION_SELECT":
            option = ui.get("gossip_option") or world_state.get("quest_ui_gossip_option") or {}
            listed = next((row for row in ui.get("gossip_options") or () if isinstance(row, dict)
                           and str(row.get("id")) == str(params.get("gossip_option_id"))), None)
            if str(option.get("id")) != str(params.get("gossip_option_id")) and listed is not None:
                # One row of several (addon 0.9.73): the window has no single action.
                option, observed_action = listed, action
            elif listed is not None:
                # The singleton summary omits icon/cost/availability fields.
                # The same current full row supplies those dispatch checks.
                option = {**option, **listed}
            target = dialog_recipient(world_state)
            active = any(str(quest.get("quest_id")) == str(quest_id)
                         for quest in world_state.get("active_quests") or ()
                         if isinstance(quest, dict))
            from wowbot.agent.gossip_trials import safe_chat
            exact = (observed_action == action and active and bool(target)
                     and (not params.get('gossip_trial') or safe_chat(option))
                     and option.get("available") is not False
                     and (params.get("gossip_selection_basis") != "UNIQUE_QUEST_MARKED_OPTION"
                          or quest_option_marked(option))
                     and str(target.get("guid") or "") == str(params.get("target_guid") or "")
                     and bool(target.get("guid"))
                     and str(option.get("id")) == str(params.get("gossip_option_id"))
                     and str(option.get("name") or "") == str(params.get("gossip_option_name") or "")
                     and abs((number(option.get("x")) or -1.) - x) <= .002
                     and abs((number(option.get("y")) or -1.) - y) <= .002)
            if not exact:
                return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_QUEST_UI,
                                   retryable=True, replan_required=True)
            state.skill_context["quest_dialog"] = {"action": action,
                "quest_id": quest_id, "target_guid": target["guid"],
                "gossip_option_id": option["id"],
                "gossip_transition": params.get("gossip_transition", "SCRIPTED_COMBAT")}
            state.phase = QuestDialogPhase.SELECT_GOSSIP_ROW.value
            return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=x, y=y),))
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

    @identity_guarded
    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("quest_dialog") or {}
        state.phase = QuestDialogPhase.VERIFY.value
        if context.get("action") == "GOSSIP_CONFIRM":
            confirm = (world_state.get("quest_ui") or {}).get("gossip_confirm") or {}
            if confirm.get("open") is not True:
                return SkillResult(SkillStatus.SUCCESS, evidence=("gossip_confirm_accepted",))
            if now >= state.attempt.deadline:
                return SkillResult(SkillStatus.FAILURE, FailureReason.EXPECTED_STATE_NOT_REACHED,
                                   retryable=True, replan_required=True)
            return SkillResult(SkillStatus.RUNNING)
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        quest_id=context.get("quest_id"),
                                        action=str(context.get("action") or ""),
                                        reward_choice_index=context.get("reward_choice_index"),
                                        target_guid=context.get("target_guid"),
                                        gossip_option_id=context.get("gossip_option_id"),
                                        gossip_transition=context.get("gossip_transition", "SCRIPTED_COMBAT"))
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
