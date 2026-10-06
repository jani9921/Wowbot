"""Canonical screen-space world-object use with quest-credit verification."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class ObjectUsePhase(StrEnum):
    VALIDATE_MOUSEOVER = "VALIDATE_MOUSEOVER"
    SEND_USE = "SEND_USE"
    WAIT_QUEST_CREDIT = "WAIT_QUEST_CREDIT"
    VERIFY = "VERIFY"


class ObjectUseSkill:
    """Use one currently-hovered quest object, never a stale screen crop."""

    # Live 2026-10-06 20:07: the cocoon credit (0/5 -> 1/5) was visible only
    # in the next complete STATE, 2 s after the deadline; the FAST packet had
    # dropped its quest digest.  The use was booked as failed and the
    # objective suppressed for 15 s.  After a use was sent, wait (bounded)
    # for a full snapshot sampled at least this long after it.
    CREDIT_SNAPSHOT_AFTER_USE_SECONDS = 1.
    CREDIT_GRACE_SECONDS = 10.
    # Live 2026-10-06 21:16: a cocoon one floor lower answered the right-click
    # and F7 with "You are too far away." and the skill waited out 8 s twice.
    OUT_OF_RANGE_TEXTS = ("too far", "out of range")
    # Live 21:17 (707071.9): the use began while the character still coasted
    # after a MOVE; 0.9 yd later it failed stale, the cocoon was suppressed
    # and left behind.  The cursor itself had not moved.
    MAX_VIEW_REBASES = 2
    VIEW_REBASE_WINDOW_SECONDS = 3.

    @classmethod
    def _out_of_range(cls, context: dict, world_state: dict) -> bool:
        used_at = number(context.get("used_at"))
        error_at = number(world_state.get("ui_error_at"))
        text = str(world_state.get("ui_error") or "").lower()
        return (used_at is not None and error_at is not None and error_at >= used_at-.1
                and any(item in text for item in cls.OUT_OF_RANGE_TEXTS))

    def __init__(self, verifier: QuestProgressVerifier | None = None):
        self.verifier = verifier or QuestProgressVerifier()

    def _credit_snapshot_pending(self, context: dict, world_state: dict, now: float,
                                 deadline: float) -> bool:
        used_at = number(context.get("used_at"))
        sampled = number(world_state.get("state_sample_time"))
        return (used_at is not None and sampled is not None
                and now < deadline + self.CREDIT_GRACE_SECONDS
                and sampled < used_at + self.CREDIT_SNAPSHOT_AFTER_USE_SECONDS)

    @staticmethod
    def _identity_matches(params: dict, mouse: dict) -> bool:
        object_id, item_id = params.get("object_id"), params.get("item_id")
        if object_id is not None:
            return str(mouse.get("object_id")) == str(object_id)
        if item_id is not None:
            return str(mouse.get("item_id")) == str(item_id)
        expected = str(params.get("mouseover_tooltip") or "")
        if not expected:
            return False
        if str(mouse.get("tooltip") or "") == expected:
            return True
        return (str(mouse.get("name") or "") == expected.split(" ~ ", 1)[0]
                and mouse.get("quest_related") is True
                and any(str(mouse.get("quest_id")) == str(qid)
                        for qid in params.get("quest_ids") or ()))

    def _reclick_after_auto_approach(self, state, context: dict, world_state: dict,
                                     now: float) -> SkillResult | None:
        """Live 2026-10-06 21:15 (706863): the right-click turned the character
        19 deg and stepped it 1.5 yd toward the cocoon (client auto-approach),
        but the use never started; the cocoon slid away from the click point
        and the skill waited 15 s.  Once stopped, click once more where a
        fresh sample names the object under the current cursor."""
        clicked_at = number(context.get("click_sent_at"))
        if clicked_at is None or context.get("reclicked") or now < clicked_at+1.:
            return None
        from wowbot.agent.tooltip_quest import cursor_view, effective_mouseover, same_cursor_view
        x, y = context.get("hover_point") or (None, None)
        cursor = world_state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if None in (x, y, cx, cy) or not 0 < cx < 1 or not 0 < cy < 1:
            return None
        # The client turned/stepped the character; a cursor that moved on
        # its own (the user's hand) is never a reason to click.
        shifted = not same_cursor_view(context.get("hover_view"), world_state, check_camera=False)
        mouse_time = number(world_state.get("mouseover_sample_time"))
        if (not shifted or (world_state.get("movement") or {}).get("moving") is True
                or mouse_time is None or mouse_time <= clicked_at+.3 or not 0 <= now-mouse_time <= 1.
                or not self._identity_matches(state.intent.parameters, effective_mouseover(world_state))):
            return None
        context.update(reclicked=True, click_sent_at=now, used_at=now, hover_point=(cx, cy),
                       hover_view=cursor_view(world_state))
        state.phase = ObjectUsePhase.SEND_USE.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=cx, y=cy, button="RIGHT"),))

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params = state.intent.parameters
        quest_ids = tuple(params.get("quest_ids") or ())
        objective_ids = tuple(params.get("objective_ids") or
                              ((state.intent.objective_ref,) if state.intent.objective_ref else ()))
        if params.get("activation_source") == "INTERACT_KEY":
            # Addon 0.9.57 soft-interact game object (user 2026-10-06): the
            # Interact key uses it; it must still be that object now.
            soft = next((target for target in world_state.get("soft_targets") or ()
                         if isinstance(target, dict) and target.get("unit_type") == "GAMEOBJECT"
                         and str(target.get("guid")) == str(params.get("object_guid"))), None)
            if (not quest_ids and not objective_ids) or soft is None:
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True)
            state.skill_context["object_use"] = {"quest_ids": quest_ids, "objective_ids": objective_ids,
                                                 "fallback_sent": True, "used_at": getattr(state, "started_at", None)}
            state.phase = ObjectUsePhase.SEND_USE.value
            return SkillResult(SkillStatus.RUNNING,
                               commands=(Command("BIND", str(params.get("binding") or "INTERACTTARGET")),))
        x, y = number(params.get("x")), number(params.get("y"))
        # A world object's name may arrive only in the (late) mouseover
        # change event; effective_mouseover attributes it to a still cursor.
        from wowbot.agent.tooltip_quest import cursor_view, effective_mouseover
        mouse, cursor = effective_mouseover(world_state), world_state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        state.phase = ObjectUsePhase.VALIDATE_MOUSEOVER.value
        if (not quest_ids and not objective_ids) or None in (x, y, cx, cy):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.OBJECTIVE_UNKNOWN,
                               replan_required=True)
        if not (0 < x < 1 and 0 < y < 1 and abs(x - cx) <= .002 and abs(y - cy) <= .002):
            return SkillResult(SkillStatus.FAILURE, FailureReason.STALE_OBSERVATION,
                               retryable=True, replan_required=True)
        if not self._identity_matches(params, mouse):
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        # Even an exact tooltip may belong to a delayed MOUSEOVER_CHANGED.
        # Force a new hover and recheck the cursor, view and addon sample
        # before sending the irreversible right-click.
        state.skill_context["object_use"] = {
            "quest_ids": quest_ids, "objective_ids": objective_ids,
            "hover_point": (x, y), "hover_sent_at": state.started_at,
            "hover_started_at": state.started_at,
            "hover_view": cursor_view(world_state), "click_sent_at": None,
            "fallback_sent": False,
        }
        state.phase = ObjectUsePhase.VALIDATE_MOUSEOVER.value
        return SkillResult(SkillStatus.RUNNING,
                           commands=(Command("HOVER", x=x, y=y, duration=.05),))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("object_use") or {}
        # Quest progress is the authoritative completion signal, including
        # when it arrives while a fresh post-hover sample is still pending.
        # This can happen when the player interacts manually during our wait.
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        quest_ids=context.get("quest_ids", ()),
                                        objective_ids=context.get("objective_ids", ()))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if self._out_of_range(context, world_state):
            # Closer first: the planner walks/seeks to the object, then uses it.
            return SkillResult(SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                               retryable=True, replan_required=True)
        # engine.tick() marks all non-movement skills VERIFY before invoking
        # us, so the stage must live in our own context, not state.phase.
        if context.get("hover_point") and context.get("click_sent_at") is None:
            from wowbot.agent.tooltip_quest import cursor_view, effective_mouseover, same_cursor_view
            x, y = context.get("hover_point") or (None, None)
            cursor = world_state.get("cursor_position") or {}
            cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
            # A repeated old state cannot confirm the HOVER command.  Wait
            # briefly for both cursor and mouseover samples after dispatch.
            mouse_sample = number(world_state.get("mouseover_sample_time"))
            cursor_sample = number(world_state.get("cursor_sample_time"))
            fresh = (world_state.get("monotonic_time") is None or
                     (mouse_sample is not None and cursor_sample is not None
                      and mouse_sample > context["hover_sent_at"]
                      and cursor_sample > context["hover_sent_at"]
                      and 0 <= now-mouse_sample <= 1.
                      and abs(mouse_sample-cursor_sample) <= .1))
            # The optical-flow yaw estimate may be advanced repeatedly from
            # one old vision frame while the addon/character stays still
            # (live 19:17:41: -60 -> +12 in <.3 s).  It is not an authority
            # for aborting the wait.  Actual heading/position and cursor must
            # remain stable, and a fresh addon identity is still mandatory
            # before a right-click is sent.
            if None in (x, y, cx, cy) or abs(x-cx) > .004 or abs(y-cy) > .004:
                return SkillResult(SkillStatus.FAILURE, FailureReason.STALE_OBSERVATION,
                                   retryable=True, replan_required=True)
            if not same_cursor_view(context.get("hover_view"), world_state, check_camera=False):
                rebases = int(context.get("view_rebases") or 0)
                started = number(context.get("hover_started_at"))
                if (rebases >= self.MAX_VIEW_REBASES or started is None
                        or now >= started + self.VIEW_REBASE_WINDOW_SECONDS):
                    return SkillResult(SkillStatus.FAILURE, FailureReason.STALE_OBSERVATION,
                                       retryable=True, replan_required=True)
                if (world_state.get("movement") or {}).get("moving") is True:
                    return SkillResult(SkillStatus.RUNNING)      # let the character stop
                # Stopped: whatever is under the unmoved cursor now must name
                # the object again in a sample taken after a new hover.
                context.update(view_rebases=rebases+1, hover_view=cursor_view(world_state),
                               hover_sent_at=now)
                return SkillResult(SkillStatus.RUNNING,
                                   commands=(Command("HOVER", x=x, y=y, duration=.05),))
            if fresh and self._identity_matches(state.intent.parameters,
                                                effective_mouseover(world_state)):
                context["click_sent_at"] = context["used_at"] = now
                state.phase = ObjectUsePhase.SEND_USE.value
                return SkillResult(SkillStatus.RUNNING,
                                   commands=(Command("CLICK", x=x, y=y, button="RIGHT"),))
            if now < min(state.attempt.deadline, context["hover_sent_at"]+1.5):
                return SkillResult(SkillStatus.RUNNING)
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        state.phase = ObjectUsePhase.VERIFY.value
        if now >= state.attempt.deadline:
            if self._credit_snapshot_pending(context, world_state, now, state.attempt.deadline):
                state.phase = ObjectUsePhase.WAIT_QUEST_CREDIT.value
                return SkillResult(SkillStatus.RUNNING)
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED,
                               retryable=True, replan_required=True)
        # F7 / INTERACTTARGET is a one-shot fallback after a verified
        # hover/right-click, never a blind replacement for finding the cocoon.
        # The addon may export no soft GAMEOBJECT at all (live 19:17:41);
        # in that case require a *new* exact quest-object hover under the
        # unchanged cursor and no competing soft target.
        clicked_at = context.get("click_sent_at")
        reclick = self._reclick_after_auto_approach(state, context, world_state, now)
        if reclick is not None:
            return reclick
        if (clicked_at is not None and not context.get("fallback_sent")
                and now >= clicked_at+2.):
            from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
            from wowbot.agent.tooltip_quest import effective_mouseover, same_cursor_view
            params = state.intent.parameters
            identity = {"object_id": params.get("object_id") or None,
                        "expected_tooltips": params.get("expected_tooltips") or
                                             [str(params.get("mouseover_tooltip") or "").split(" ~ ", 1)[0]]}
            soft = ObjectInteractionFlow.soft_target(identity, world_state)
            cursor = world_state.get("cursor_position") or {}
            x, y = context.get("hover_point") or (None, None)
            cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
            mouse_time = number(world_state.get("mouseover_sample_time"))
            cursor_time = number(world_state.get("cursor_sample_time"))
            mouse = world_state.get("mouseover") or {}
            hover_confirmed = (not world_state.get("soft_targets")
                and isinstance(mouse, dict) and mouse.get("quest_related") is True
                and any(str(mouse.get("quest_id")) == str(qid)
                        for qid in context.get("quest_ids") or ())
                and None not in (x, y, cx, cy, mouse_time, cursor_time)
                and abs(x-cx) <= .004 and abs(y-cy) <= .004
                and mouse_time > clicked_at and cursor_time > clicked_at
                and 0 <= now-mouse_time <= 1.
                and abs(mouse_time-cursor_time) <= .1
                and same_cursor_view(context.get("hover_view"), world_state,
                                     check_camera=False)
                and self._identity_matches(params, effective_mouseover(world_state)))
            if soft is not None or hover_confirmed:
                context["fallback_sent"] = True
                context["used_at"] = now
                state.phase = ObjectUsePhase.WAIT_QUEST_CREDIT.value
                return SkillResult(SkillStatus.RUNNING,
                                   commands=(Command("BIND", "INTERACTTARGET"),))
        state.phase = ObjectUsePhase.WAIT_QUEST_CREDIT.value
        return SkillResult(SkillStatus.RUNNING)
