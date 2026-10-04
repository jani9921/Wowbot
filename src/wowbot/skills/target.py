"""Canonical bounded M0 target acquisition FSM.

The instance is stateless. Its phase and all per-attempt details live in the
caller supplied ActiveSkillState, keeping ActiveSkillRuntime the only running
skill authority.
"""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from .hover_confirm import hover_confirm_step, valid_point
from wowbot.runtime import (ActiveSkillState, FailureReason, Intent, SkillResult,
                            SkillStatus, world_entity_id)


class TargetPhase(StrEnum):
    CONFIRM_HOVER = "CONFIRM_HOVER"
    ACQUIRE_CANDIDATES = "ACQUIRE_CANDIDATES"
    VALIDATE_IDENTITY = "VALIDATE_IDENTITY"
    SELECT_TARGET = "SELECT_TARGET"
    APPLY_TARGET = "APPLY_TARGET"
    VERIFY_TARGET = "VERIFY_TARGET"


class TargetSkill:
    def commands_for(self, intent: Intent) -> tuple[Command, ...]:
        params = intent.parameters
        if params.get("restore_last_target"):
            return (Command("BIND", "TARGETLASTTARGET"),)
        if params.get("click_current_cursor"):
            # A fresh ground-truth handoff has already positioned the actual
            # OS pointer over the identified unit. Do not move it again using
            # UI-space telemetry: UI scale/capture transforms are separate
            # from the physical pointer position. SkillRegistry only admits
            # this form while that mouseover/cursor sample is still fresh.
            return (Command("CLICK_CURRENT_CURSOR"),)
        x, y = number(params.get("x")), number(params.get("y"))
        if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
            return ()
        return (Command("CLICK", x=x, y=y),)

    def begin(self, state: ActiveSkillState) -> SkillResult:
        intent = state.intent
        state.skill_context.setdefault("target", {
            "expected_guid": world_entity_id(intent.target_ref or intent.parameters.get("guid")),
            "expected_name": str(intent.parameters.get("expected_name") or "").casefold().strip(),
            "restore_last_target": bool(intent.parameters.get("restore_last_target")),
        })
        state.phase = TargetPhase.ACQUIRE_CANDIDATES.value
        context = state.skill_context["target"]
        hover = valid_point(intent.parameters.get("hover_x"), intent.parameters.get("hover_y"))
        if (hover is not None and intent.parameters.get("click_current_cursor")
                and context.get("expected_guid")):
            # The runtime rewrites state.phase every tick (live 2026-10-03:
            # "VERIFY"), so the pending hover lives in the skill context.
            context.update(hover_point=hover, track_id=intent.parameters.get("track_id"),
                           hovers=1, hovered_at=state.started_at, hover_pending=True)
            state.phase = TargetPhase.CONFIRM_HOVER.value
            return SkillResult(SkillStatus.RUNNING,
                               commands=(Command("HOVER", x=hover[0], y=hover[1], duration=.05),))
        commands = self.commands_for(intent)
        if not commands:
            return SkillResult(SkillStatus.FAILURE, FailureReason.LOW_CONFIDENCE,
                               replan_required=True,
                               metadata={"detail": "target intent has no safe click or configured restore binding"})
        state.phase = TargetPhase.APPLY_TARGET.value
        return SkillResult(SkillStatus.RUNNING, commands=commands)

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("target") or {}
        target = world_state.get("target") or {}
        expected_guid = context.get("expected_guid")
        expected_name = context.get("expected_name") or ""
        observed_guid = target.get("guid")
        observed_name = str(target.get("name") or "").casefold().strip()
        if context.get("hover_pending") and observed_guid != expected_guid:
            outcome, commands = hover_confirm_step(context, world_state, now,
                                                   expected_guid=str(expected_guid or ""))
            if outcome == "CLICK":
                context["hover_pending"] = False
                state.phase = TargetPhase.APPLY_TARGET.value
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "HOVER":
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "WAIT" and now < state.attempt.deadline:
                return SkillResult(SkillStatus.RUNNING)
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                               retryable=True, replan_required=True,
                               metadata={"detail": "hovered box never showed the expected GUID"})
        state.phase = TargetPhase.VERIFY_TARGET.value
        if expected_guid:
            if observed_guid == expected_guid:
                return SkillResult(SkillStatus.SUCCESS, metadata={"target_guid": observed_guid})
            previous_guid = ((state.before_snapshot or {}).get("target") or {}).get("guid")
            if (observed_guid and observed_guid == previous_guid
                    and now < state.attempt.deadline):
                # Live 2026-10-04 (Giant Boar): verify ran ~0.1 s after the
                # click while the addon still reported the *previous* target
                # and failed IDENTITY_UNCERTAIN every time.  The old target is
                # not evidence of a wrong click until the deadline.
                return SkillResult(SkillStatus.RUNNING)
            if observed_guid and observed_guid != expected_guid:
                return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                                   replan_required=True,
                                   metadata={"expected_guid": expected_guid, "observed_guid": observed_guid})
        elif observed_guid and (not expected_name or observed_name == expected_name):
            return SkillResult(SkillStatus.SUCCESS, metadata={"target_guid": observed_guid})
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                               retryable=True, replan_required=True)
        return SkillResult(SkillStatus.RUNNING)
