"""Canonical screen-space world-object use with quest-credit verification."""
from __future__ import annotations

from wowbot.runtime.skill_identity import identity_guarded

from enum import StrEnum
from dataclasses import replace

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class ObjectUsePhase(StrEnum):
    VALIDATE_MOUSEOVER = "VALIDATE_MOUSEOVER"
    WAIT_STOP = "WAIT_STOP"
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
    # Live 2026-10-07: the paged snapshot stalled 21 s; the credit arrived
    # 1.2 s after a 10 s grace.  Only while no snapshot newer than the use
    # has arrived (FAST quest_digest credits immediately from 0.9.60).
    CREDIT_GRACE_SECONDS = 25.
    # Live 2026-10-07 12:06: the cocoon's freeing cast was still running
    # (is_casting) when the attempt failed "credit not received"; the credit
    # came 1.9 s later.
    CAST_GRACE_SECONDS = 6.
    # Live 2026-10-07 12:06 (3rd cocoon): the attempt spent 7 s of its budget
    # waiting for the character to stop and the hover to settle; the credit
    # wait after the right-click was then ~1.5 s.  A click always gets this
    # long (it covers the 2 s F7 fallback and its cast).
    POST_CLICK_SECONDS = 5.
    # Live 2026-10-06 21:16: a cocoon one floor lower answered the right-click
    # and F7 with "You are too far away." and the skill waited out 8 s twice.
    # Live 21:17 (707071.9): the use began while the character still coasted
    # after a MOVE; 0.9 yd later it failed stale, the cocoon was suppressed
    # and left behind.  The cursor itself had not moved.
    MAX_VIEW_REBASES = 2
    VIEW_REBASE_WINDOW_SECONDS = 3.

    @staticmethod
    def _position_error(context: dict, world_state: dict) -> FailureReason | None:
        used_at = number(context.get("used_at"))
        error_at = number(world_state.get("ui_error_at"))
        if used_at is None or error_at is None or error_at < used_at-.1:
            return None
        if str(world_state.get("ui_error") or "").strip().casefold().rstrip(".! ") in {
                "interrupted", "megszakítva"}:
            # A real use cast was interrupted (user-run forge, 18:49:27).
            # It is not evidence that the object's reachable surface failed;
            # do not later blacklist this contact as "credit not received".
            return FailureReason.CAST_INTERRUPTED
        from wowbot.verification.interaction import classify_ui_error
        classification = classify_ui_error(world_state.get("ui_error"),
                                           world_state.get("ui_error_code"))
        return {"RANGE": FailureReason.OUT_OF_RANGE,
                "LINE_OF_SIGHT": FailureReason.LINE_OF_SIGHT,
                "FACING": FailureReason.FACING_FAILED}.get(classification)

    def __init__(self, verifier: QuestProgressVerifier | None = None, *, bindings=None, step_guard=None):
        self.verifier = verifier or QuestProgressVerifier()
        self.bindings, self.step_guard = bindings, step_guard

    def _credit_snapshot_pending(self, context: dict, world_state: dict, now: float,
                                 deadline: float) -> bool:
        used_at = number(context.get("used_at"))
        sampled = number(world_state.get("state_sample_time"))
        return (used_at is not None and sampled is not None
                and now < deadline + self.CREDIT_GRACE_SECONDS
                and sampled < used_at + self.CREDIT_SNAPSHOT_AFTER_USE_SECONDS)

    def _click_recent(self, context: dict, now: float, deadline: float) -> bool:
        clicked_at = number(context.get("click_sent_at"))
        return (clicked_at is not None and now < clicked_at + self.POST_CLICK_SECONDS
                and now < deadline + self.POST_CLICK_SECONDS)

    def _use_cast_running(self, context: dict, world_state: dict, now: float,
                          deadline: float) -> bool:
        used_at = number(context.get("used_at"))
        return (used_at is not None and world_state.get("is_casting") is True
                and now < deadline + self.CAST_GRACE_SECONDS)

    @staticmethod
    def packet_object_usable(params: dict, world_state: dict) -> bool:
        """The server still shows this object, usable for us, and nothing
        (combat, a unit soft target) would take or break the Interact press."""
        from wowbot.agent.packet_entity_facts import server_object_interactable
        if params.get("server_interaction_range") is not None:
            from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
            from wowbot.agent.packet_entity_facts import best_position, entity
            import math
            value = entity(world_state, params.get("object_guid"))
            point = best_position(value) if value else None
            player = world_state.get("player_world_position") or {}
            limit = number(params["server_interaction_range"])
            px, py = number(player.get("x")), number(player.get("y"))
            if (point is None or None in (limit, px, py) or not math.isfinite(limit) or limit <= 0
                    or str(point.get("instance_id")) != str(player.get("instance_id"))):
                return False
            spot = {**point, "guid": params["object_guid"], "distance": math.hypot(point["x"]-px, point["y"]-py)}
            if ObjectInteractionFlow().packet_interact_ready(
                    world_state, spot, number(player.get("z")), reach=limit) != "READY":
                return False
        return (server_object_interactable(world_state, params.get("object_guid"),
                                           params.get("server_use_basis"))
                and not world_state.get("is_in_combat")
                and not any(isinstance(target, dict)
                            and str(target.get("source_unit") or "").casefold() == "softinteract"
                            and target.get("unit_type") not in (None, "GAMEOBJECT")
                            for target in world_state.get("soft_targets") or ()))

    @staticmethod
    def _identity_matches(params: dict, mouse: dict) -> bool:
        from wowbot.runtime.entity_identity import check_entity_identity
        from wowbot.runtime.skill_identity import (QUEST_OBJECT_TOOLTIP, expected_identity,
                                                   quest_object_tooltip_matches)
        if params.get("identity_certification") == QUEST_OBJECT_TOOLTIP:
            return quest_object_tooltip_matches(params, mouse)
        return bool(check_entity_identity(
            expected_identity(params, include_item=True), mouse))

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

    @identity_guarded
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
            if ((not quest_ids and not objective_ids) or soft is None
                    or not self._identity_matches(params, soft)):
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True)
            state.skill_context["object_use"] = {"quest_ids": quest_ids, "objective_ids": objective_ids,
                                                 "fallback_sent": True, "used_at": getattr(state, "started_at", None)}
            state.phase = ObjectUsePhase.SEND_USE.value
            return SkillResult(SkillStatus.RUNNING,
                               commands=(Command("BIND", str(params.get("binding") or "INTERACTTARGET")),))
        if params.get("activation_source") == "INTERACT_KEY_PACKET":
            # Ymir: the server reports this exact object as usable for us; the
            # planner checked range, facing, no unit soft target and no nearer
            # object.  Re-check what can change, then one Interact press.
            if (not quest_ids and not objective_ids) or not self.packet_object_usable(params, world_state):
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True)
            state.skill_context["object_use"] = {"quest_ids": quest_ids, "objective_ids": objective_ids,
                                                 "fallback_sent": True, "used_at": getattr(state, "started_at", None),
                                                 "object_guid": params.get("object_guid")}
            if (world_state.get("movement") or {}).get("moving") is True:
                state.skill_context["object_use"].update(packet_use_pending=True, used_at=None)
                state.phase = ObjectUsePhase.WAIT_STOP.value
                return SkillResult(SkillStatus.RUNNING)
            state.phase = ObjectUsePhase.SEND_USE.value
            return SkillResult(SkillStatus.RUNNING,
                               commands=(Command("BIND", str(params.get("binding") or "INTERACTTARGET")),))
        if params.get("activation_source") == "INTERACT_KEY_AT_SPAWN":
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True,
                               metadata={"detail": "spawn/facing alone does not identify the F7 recipient"})
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
        mouse_at = number(world_state.get("mouseover_sample_time"))
        cursor_at = number(world_state.get("cursor_sample_time"))
        if (not (abs(x - cx) <= .002 and abs(y - cy) <= .002) and 0 < cx < 1 and 0 < cy < 1
                # The tooltip sample must be from the cursor's new point.
                and mouse_at is not None and cursor_at is not None and mouse_at >= cursor_at-.05
                and self._identity_matches(params, mouse)):
            # Live 2026-10-14: the pointer lock had re-aimed the cursor on the
            # same cocoon since planning; the tooltip still names it here.
            # Use the cursor's point (a new hover + fresh tooltip still gates
            # the right-click) instead of aborting as stale.
            x, y = cx, cy
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
        # Keep the already verified tooltip-to-box association while waiting
        # for the post-hover sample. No nearest-box or name-only reassignment.
        from wowbot.agent.object_interaction_flow import ObjectInteractionFlow, quest_object_candidates
        bound = ObjectInteractionFlow._confirmed_hover_box(
            params, quest_ids[0] if quest_ids else None, world_state, quest_object_candidates(world_state))
        if bound is not None:
            state.skill_context["object_use"]["track_id"] = bound.get("track_id")
        state.phase = ObjectUsePhase.VALIDATE_MOUSEOVER.value
        return SkillResult(SkillStatus.RUNNING,
                           commands=(Command("HOVER", x=x, y=y, duration=.05),))

    @identity_guarded
    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("object_use") or {}
        from .object_pull import pull_profile, step as pull_step, channel_movement_allowed
        profile = pull_profile(state.intent.parameters,world_state)
        if profile is not None:
            context['objective_ids'] = (profile['objective_id'],)
        # Quest progress is the authoritative completion signal, including
        # when it arrives while a fresh post-hover sample is still pending.
        # This can happen when the player interacts manually during our wait.
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        quest_ids=context.get("quest_ids", ()),
                                        objective_ids=context.get("objective_ids", ()))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence,
                metadata={'post_use_motion':dict(context['pull'])} if context.get('pull') else {})
        if context.get("packet_use_pending"):
            # A MOVE-to-use handoff can precede the client's stop sample.
            # Wait for a newer explicit stop; then recheck pose and GUID and
            # send exactly one F7. Waiting never consumes the credit budget.
            if now >= state.attempt.deadline:
                return SkillResult(SkillStatus.FAILURE, FailureReason.TIMEOUT,
                                   retryable=True, replan_required=True)
            sample = number(world_state.get("fast_sample_time", world_state.get("monotonic_time")))
            if ((world_state.get("movement") or {}).get("moving") is not False
                    or sample is None or sample <= state.started_at
                    or world_state.get("is_casting") or world_state.get("is_channeling")):
                state.phase = ObjectUsePhase.WAIT_STOP.value
                return SkillResult(SkillStatus.RUNNING)
            if not self.packet_object_usable(state.intent.parameters, world_state):
                return SkillResult(SkillStatus.FAILURE, FailureReason.NOT_INTERACTABLE,
                                   retryable=True, replan_required=True)
            context.update(packet_use_pending=False, used_at=now, click_sent_at=now)
            state.phase = ObjectUsePhase.SEND_USE.value
            return SkillResult(SkillStatus.RUNNING, commands=(
                Command("BIND", str(state.intent.parameters.get("binding") or "INTERACTTARGET")),))
        pulling_channel = channel_movement_allowed(state,world_state,now)
        if pulling_channel:
            context.setdefault('pull_cast_ended_at',now)
        if (world_state.get("is_casting") or world_state.get("is_channeling")) and not pulling_channel:
            if profile is not None:
                context['pull_cast_seen'] = True
                used = number(context.get('used_at'))
                if used is not None and now-used > 16.:
                    return SkillResult(SkillStatus.FAILURE,FailureReason.TIMEOUT,replan_required=True,
                        metadata={'legacy_reason':'object_pull_grab_channel_unresolved'})
            # Do not mark click/fallback sent while the control layer must
            # withhold that input. Quest credit above is still authoritative.
            state.phase = ObjectUsePhase.WAIT_QUEST_CREDIT.value
            return SkillResult(SkillStatus.RUNNING)
        position_error = self._position_error(context, world_state)
        if context.get('pull_cast_seen'):
            context.setdefault('pull_cast_ended_at',now)
        if position_error is not None:
            # Report the client error precisely.  Only OUT_OF_RANGE permits
            # the confirmed-box forward approach; LOS needs a different route.
            return SkillResult(SkillStatus.FAILURE, position_error,
                               retryable=True, replan_required=True)
        motion = pull_step(self,state,world_state,now)
        if motion is not None:
            return replace(motion,metadata={**motion.metadata,
                'post_use_motion':dict(context.get('pull') or {}),
                **({'legacy_reason':motion.metadata['reason']} if motion.metadata.get('reason') else {})})
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
            # A complete STATE_Z packet samples mouseover and cursor together,
            # but may omit the two FAST-lane per-field sample times. Live
            # 2026-10-08 (Harpy Totem): repeated fresh full snapshots carried
            # the exact tooltip under an unchanged cursor, yet the skill
            # timed out IDENTITY_UNCERTAIN without ever sending right-click.
            # Only a *newer complete* snapshot may substitute its shared
            # sample time; a reused/stale packet or missing identity cannot.
            full_sample = number(world_state.get("state_sample_time"))
            fresh_full = (
                mouse_sample is None and cursor_sample is None
                and str(world_state.get("transport_kind") or "").upper() in {"STATE", "STATE_Z"}
                and isinstance(world_state.get("mouseover"), dict)
                and isinstance(world_state.get("cursor_position"), dict)
                and full_sample is not None and full_sample > context["hover_sent_at"]
                and 0 <= now-full_sample <= 1.)
            fresh = (world_state.get("monotonic_time") is None or
                     (mouse_sample is not None and cursor_sample is not None
                      and mouse_sample > context["hover_sent_at"]
                      and cursor_sample > context["hover_sent_at"]
                      and 0 <= now-mouse_sample <= 1.
                      and abs(mouse_sample-cursor_sample) <= .1)
                     or fresh_full)
            if not (fresh and self._identity_matches(state.intent.parameters,
                                                     effective_mouseover(world_state))
                    and None not in (x, y, cx, cy) and abs(x-cx) <= .004 and abs(y-cy) <= .004):
                from wowbot.agent.pointer_tracking import follow_pointer
                command = (follow_pointer(context.setdefault("pointer_follow", {}), world_state,
                                          context.get("track_id"), now)
                           if now < state.attempt.deadline else None)
                if command is not None:
                    context.update(hover_point=(command.x, command.y), hover_sent_at=now,
                                   hover_view=cursor_view(world_state))
                    return SkillResult(SkillStatus.RUNNING, commands=(command,))
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
            if (self._credit_snapshot_pending(context, world_state, now, state.attempt.deadline)
                    or self._use_cast_running(context, world_state, now, state.attempt.deadline)
                    or self._click_recent(context, now, state.attempt.deadline)):
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
