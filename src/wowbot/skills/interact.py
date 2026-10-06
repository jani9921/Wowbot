"""Canonical bounded M0 Interact/Talk FSM backed by ActiveSkillRuntime."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command
from wowbot.agent.models import number
from wowbot.runtime import ActiveSkillState, FailureReason, Intent, SkillResult, SkillStatus, world_entity_id
from wowbot.verification import InteractionVerifier
from .interaction_result import InteractionResultClassifier
from .interaction_recovery import InteractionRecoveryPolicy


class InteractPhase(StrEnum):
    IDLE = "IDLE"
    RESOLVE_TARGET = "RESOLVE_TARGET"
    APPROACH = "APPROACH"
    FACE = "FACE"
    HOVER = "HOVER"
    VERIFY_HOVER = "VERIFY_HOVER"
    INTERACT = "INTERACT"
    WAIT_RESULT = "WAIT_RESULT"
    CLASSIFY_RESULT = "CLASSIFY_RESULT"
    RECOVER = "RECOVER"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class InteractSkill:
    def __init__(self, verifier: InteractionVerifier | None = None):
        self.verifier = verifier or InteractionVerifier()
        self.result_classifier = InteractionResultClassifier()
        self.recovery_policy = InteractionRecoveryPolicy()

    @staticmethod
    def commands_for(intent: Intent) -> tuple[Command, ...]:
        return (Command("BIND", "INTERACTTARGET"),)

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        if state.intent.parameters.get("activation_source") == "SOFT_INTERACT":
            return self._begin_soft_interact(state, world_state)
        expected = world_entity_id(state.intent.target_ref or state.intent.parameters.get("guid"))
        target = world_state.get("target") or {}
        state.skill_context["interaction"] = {
            "expected_guid": expected, "direct_interaction_retries": 0,
            "reposition_retries": 0, "reacquire_retries": 0,
            "unknown_observations": 0,
        }
        state.phase = InteractPhase.RESOLVE_TARGET.value
        if expected and target.get("guid") != expected:
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        if not target.get("guid"):
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                               retryable=True, replan_required=True)
        identity_confidence = number(target.get("identity_confidence"))
        if identity_confidence is not None and identity_confidence < .75:
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.LOW_CONFIDENCE,
                               retryable=True, replan_required=True)
        if target.get("dead", target.get("is_dead")):
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.INVALID_TARGET,
                               replan_required=True)
        if target.get("attackable", target.get("is_attackable")) is True:
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.NOT_INTERACTABLE,
                               replan_required=True)
        context = state.skill_context["interaction"]
        hover_points = self._hover_points(world_state, expected)
        # Two clocks: telemetry sample times (for hover freshness) and the
        # agent clock that verify() receives as ``now``.  Timers compared in
        # verify() must use the agent clock; a lagging telemetry timestamp
        # made a fresh INTERACT look 1+ s old and fail after 0.3-0.4 s next
        # to Lady Jaina (live 2026-09-30).
        sample_now = number(world_state.get("monotonic_time")) or state.attempt.started_at
        now = state.attempt.started_at
        if hover_points and not self._fresh_hover(world_state, expected, sample_now - .35):
            context.update({"hover_points": hover_points, "hover_index": 0,
                            "hover_sent_at": now, "hover_sample_not_before": sample_now,
                            "hover_verified": False})
            state.phase = InteractPhase.HOVER.value
            return SkillResult(SkillStatus.RUNNING, commands=(self._hover_command(hover_points[0]),))
        context["hover_verified"] = bool(hover_points)
        state.phase = InteractPhase.INTERACT.value
        context["last_interact_at"] = now
        return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent))

    def _begin_soft_interact(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        """Live 2026-10-06 22:12: at Private Cole's "!" the client's
        soft-interact unit was Private Cole, while the hard target was still
        Lady Jaina from the last turn-in; the agent tried Jaina for a minute.
        The Interact key acts on the soft-interact unit; success is the
        quest/gossip/vendor window, so no hard-target identity is compared."""
        soft_guid = str(state.intent.parameters.get("soft_guid") or "")
        soft = next((row for row in world_state.get("soft_targets") or ()
                     if isinstance(row, dict)
                     and str(row.get("source_unit") or "").casefold() == "softinteract"
                     and str(row.get("guid") or "") == soft_guid), None)
        state.skill_context["interaction"] = {
            "expected_guid": None, "soft_guid": soft_guid, "direct_interaction_retries": 0,
            "reposition_retries": 0, "reacquire_retries": 0, "unknown_observations": 0,
            "last_interact_at": state.attempt.started_at}
        if (not soft_guid or soft is None or soft.get("is_attackable") is True
                or soft.get("is_dead") is True):
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                               retryable=True, replan_required=True)
        state.phase = InteractPhase.INTERACT.value
        return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent))

    @staticmethod
    def _hover_points(world_state: dict, expected: str | None) -> tuple[tuple[float, float], ...]:
        """Return up to four ranked interaction points from one live anchor."""
        target = world_state.get("target") or {}
        anchors = world_state.get("confirmed_mouseover_anchors") or {}
        anchor = target.get("screen_position") if str(target.get("guid") or "") == str(expected or "") else None
        anchor = anchor or anchors.get(str(expected or ""))
        if not isinstance(anchor, dict):
            return ()
        x, y = number(anchor.get("x", anchor.get("nx"))), number(anchor.get("y", anchor.get("ny")))
        if x is None or y is None or not .02 < x < .98 or not .02 < y < .98:
            return ()
        points: list[tuple[float, float]] = []
        for key in ("learned_interaction_point", "interaction_point"):
            point = anchor.get(key) or target.get(key)
            if isinstance(point, dict):
                px, py = number(point.get("x")), number(point.get("y"))
                if px is not None and py is not None:
                    points.append((px, py))
        bbox = InteractSkill._normalized_bbox(anchor.get("bbox") or target.get("bbox"))
        if bbox is not None:
            left, bottom, right, top = bbox
            center_x, center_y = (left+right)/2., (bottom+top)/2.
            unit_like = (str(target.get("unit_type") or "").upper() in {"NPC", "CREATURE"}
                         or target.get("npc_id") is not None)
            if unit_like:
                points.append((center_x, bottom + (top-bottom)*.68))
            points.extend(((center_x, center_y),
                           (left+(right-left)*.32, center_y),
                           (left+(right-left)*.68, center_y)))
        else:
            points.extend(((x, y), (x, y+.018), (x-.018, y), (x+.018, y)))
        unique: list[tuple[float, float]] = []
        for px, py in points:
            point = (min(.98, max(.02, px)), min(.98, max(.02, py)))
            if point not in unique:
                unique.append(point)
            if len(unique) == 4:
                break
        return tuple(unique)

    @staticmethod
    def _normalized_bbox(raw) -> tuple[float, float, float, float] | None:
        if isinstance(raw, (list, tuple)) and len(raw) >= 4:
            values = tuple(number(value) for value in raw[:4])
            if None not in values:
                left, bottom, right, top = values
                if right <= left or top <= bottom:  # x,y,w,h form
                    right, top = left+right, bottom+top
                return (left, bottom, right, top)
        if isinstance(raw, dict):
            left = number(raw.get("left", raw.get("x")))
            bottom = number(raw.get("bottom", raw.get("y")))
            right = number(raw.get("right"))
            top = number(raw.get("top"))
            width, height = number(raw.get("width", raw.get("w"))), number(raw.get("height", raw.get("h")))
            if left is not None and bottom is not None:
                right = right if right is not None else left+(width or 0.)
                top = top if top is not None else bottom+(height or 0.)
                if right > left and top > bottom:
                    return (left, bottom, right, top)
        return None

    @staticmethod
    def _hover_command(point: tuple[float, float]) -> Command:
        return Command("HOVER", x=point[0], y=point[1])

    @staticmethod
    def _fresh_hover(world_state: dict, expected: str | None, not_before: float) -> bool:
        mouse = world_state.get("mouseover") or {}
        sample_time = number(world_state.get("mouseover_sample_time", world_state.get("monotonic_time")))
        confidence = number(mouse.get("identity_confidence"))
        target = world_state.get("target") or {}
        expected_track = ((target.get("screen_position") or {}).get("track_id")
                          or target.get("visual_track_id"))
        observed_track = (mouse.get("visual_track_id")
                          or (mouse.get("screen_position") or {}).get("track_id"))
        track_matches = not (expected_track and observed_track
                             and str(expected_track) != str(observed_track))
        return bool(expected and str(mouse.get("guid") or "") == str(expected)
                    and (confidence is None or confidence >= .75)
                    and track_matches
                    and sample_time is not None and sample_time >= not_before)

    @staticmethod
    def _visual_approach_request(world_state: dict, expected: str | None, now: float) -> dict | None:
        """Return a verified screen-space fallback, never a guessed location."""
        if not expected:
            return None
        target = world_state.get("target") or {}
        if str(target.get("guid") or "") != str(expected):
            return None
        anchor = (target.get("screen_position")
                  or (world_state.get("confirmed_mouseover_anchors") or {}).get(str(expected)))
        state_time = number(world_state.get("monotonic_time"))
        sample_time = number((anchor or {}).get("sample_time"))
        if not (isinstance(anchor, dict) and state_time is not None and sample_time is not None
                and -5. <= state_time-sample_time < 30.
                and number(anchor.get("x")) is not None and number(anchor.get("y")) is not None):
            return None
        if anchor.get("coordinate_space") not in {None, "CLIENT_BOTTOM_LEFT"}:
            return None
        # Live 2026-10-04 08:57: Austin Huxworth's screen position was a
        # GUID-bound World3D track (nameplate-confirmed); INTERACT got "need
        # to be closer" three times and never approached, then turned away.
        if anchor.get("source") not in {"NAMEPLATE_API", "CONFIRMED_MOUSEOVER",
                                         "CONFIRMED_MOUSEOVER_ANCHOR", "BOUND_WORLD3D_TRACK"}:
            return None
        return {
            "guid": str(expected), "purpose": "INTERACT",
            "track_id": anchor.get("track_id"),
            "visual_signature": anchor.get("visual_signature"),
            "screen_position": dict(anchor),
            "ready_bbox_height": .13,
            "requested_at": now,
        }

    @staticmethod
    def _world_approach_request(world_state: dict, expected: str | None) -> dict | None:
        """Gate NavigationService.move_to_entity on live target identity."""
        if not expected:
            return None
        target = world_state.get("target") or {}
        player = world_state.get("player_world_position") or {}
        position = target.get("world_position") or {}
        if str(target.get("guid") or "") != str(expected):
            return None
        if None in {number(player.get("x")), number(player.get("y")),
                    number(position.get("x")), number(position.get("y"))}:
            return None
        player_instance, target_instance = player.get("instance_id"), position.get("instance_id")
        if (player_instance is not None and target_instance is not None
                and player_instance != target_instance):
            return None
        return {"kind": "WORLD_ENTITY", "expected_guid": str(expected), "stop_distance": 4.5}

    def resume_after_approach(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        """Finish the APPROACH→FACE hand-off without replacing this attempt."""
        context = state.skill_context.setdefault("interaction", {})
        expected = context.get("expected_guid")
        target = world_state.get("target") or {}
        if expected and str(target.get("guid") or "") != str(expected):
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_LOST,
                               retryable=True, replan_required=True)
        context.pop("approach_request", None)
        context["approach_completed"] = True
        # The actual client interaction remains the authoritative range and
        # facing check.  FACE is recorded explicitly; a concrete facing error
        # below gets one bounded NavigationService correction.
        state.phase = InteractPhase.FACE.value
        state.phase = InteractPhase.INTERACT.value
        return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent),
                           metadata={"post_approach_interact": True})

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.setdefault("interaction", {})
        expected = context.get("expected_guid")
        retry_at = number(context.get("ui_retry_not_before"))
        if retry_at is not None:
            if now < retry_at:
                state.phase = InteractPhase.RECOVER.value
                return SkillResult(SkillStatus.RUNNING,
                                   metadata={"interaction_recovery": "WAIT_AND_RETRY",
                                             "retry_not_before": retry_at})
            context.pop("ui_retry_not_before", None)
            context["direct_interaction_retries"] = int(
                context.get("direct_interaction_retries") or 0) + 1
            context["last_interact_at"] = now
            state.phase = InteractPhase.INTERACT.value
            return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent),
                               metadata={"interaction_recovery": "WAIT_AND_RETRY"})
        target = world_state.get("target") or {}
        if (context.get("reacquire_pending")
                and str(target.get("guid") or "") == str(expected or "")):
            context["reacquire_pending"] = False
            context["last_interact_at"] = now
            state.phase = InteractPhase.INTERACT.value
            return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent),
                               metadata={"interaction_recovery": "REACQUIRED_EXPECTED"})
        if context.pop("await_post_los_interact", False):
            context["last_interact_at"] = now
            state.phase = InteractPhase.INTERACT.value
            return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent),
                               metadata={"interaction_recovery": "POST_LOS_RETRY"})
        hover_points = context.get("hover_points") or ()
        if hover_points and not context.get("hover_verified"):
            state.phase = InteractPhase.VERIFY_HOVER.value
            if self._fresh_hover(world_state, expected, float(
                    context.get("hover_sample_not_before", context.get("hover_sent_at", now)))):
                context["hover_verified"] = True
                state.phase = InteractPhase.INTERACT.value
                return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent),
                                   metadata={"hover_verified": True})
            # Addon mouseover is asynchronous. Do not skip across candidates
            # until the current pointer position had a bounded chance to emit.
            if now - float(context.get("hover_sent_at", now)) < .12:
                return SkillResult(SkillStatus.RUNNING)
            index = int(context.get("hover_index", 0)) + 1
            if index >= len(hover_points):
                state.phase = InteractPhase.FAILED.value
                return SkillResult(SkillStatus.FAILURE, FailureReason.LOW_CONFIDENCE,
                                   retryable=True, replan_required=True,
                                   metadata={"hover_samples": len(hover_points)})
            context["hover_index"] = index
            context["hover_sent_at"] = now
            context["hover_sample_not_before"] = number(world_state.get("monotonic_time")) or now
            state.phase = InteractPhase.HOVER.value
            return SkillResult(SkillStatus.RUNNING,
                               commands=(self._hover_command(tuple(hover_points[index])),),
                               metadata={"hover_sample": index + 1})
        if context.pop("await_post_face_interact", False):
            state.phase = InteractPhase.INTERACT.value
            return SkillResult(SkillStatus.RUNNING, commands=self.commands_for(state.intent),
                               metadata={"post_face_interact": True})
        state.phase = InteractPhase.WAIT_RESULT.value
        result = self.verifier.evaluate(
            state.before_snapshot, world_state, expected_guid=expected,
            expected_result=state.intent.parameters.get("expected_result"))
        context["result_classification"] = self.result_classifier.classify(
            result.reason, state.before_snapshot, world_state).value
        context["interaction_effect"] = self.result_classifier.classify_effect(
            state.before_snapshot, world_state).value
        state.phase = InteractPhase.CLASSIFY_RESULT.value
        if result.success:
            state.phase = InteractPhase.SUCCESS.value
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence,
                               metadata={"interaction_result": context["result_classification"],
                                         "interaction_effect": context["interaction_effect"]})
        if result.reason is FailureReason.OUT_OF_RANGE:
            if context.get("approach_attempts", 0) >= self.recovery_policy.REPOSITION_BUDGET:
                state.phase = InteractPhase.FAILED.value
                return SkillResult(SkillStatus.FAILURE, result.reason,
                                   retryable=True, replan_required=True)
            request = (self._world_approach_request(world_state, expected)
                       or self._visual_approach_request(world_state, expected, now))
            if request:
                context["approach_attempts"] = context.get("approach_attempts", 0) + 1
                context["approach_request"] = request
                state.local_retry_count += 1
                state.failure_history.append(FailureReason.OUT_OF_RANGE)
                state.phase = InteractPhase.RECOVER.value
                state.phase = InteractPhase.APPROACH.value
                return SkillResult(SkillStatus.RUNNING, metadata={"approach_request": request})
        if result.reason is FailureReason.FACING_FAILED:
            target = world_state.get("target") or {}
            screen = target.get("screen_position") or {}
            x = screen.get("x")
            if (context.get("face_recovery_attempts", 0) < self.recovery_policy.REPOSITION_BUDGET and expected
                    and target.get("guid") == expected and x is not None):
                context["face_recovery_attempts"] = context.get("face_recovery_attempts", 0) + 1
                context["await_post_face_interact"] = True
                state.local_retry_count += 1
                state.failure_history.append(FailureReason.FACING_FAILED)
                state.phase = InteractPhase.RECOVER.value
                state.phase = InteractPhase.FACE.value
                return SkillResult(SkillStatus.RUNNING, metadata={"local_face_request": {
                    "expected_guid": expected, "target_screen_x": x,
                }})
        if result.reason is FailureReason.LINE_OF_SIGHT:
            screen = (world_state.get("target") or {}).get("screen_position") or {}
            x, y = number(screen.get("x")), number(screen.get("y"))
            count = int(context.get("los_recovery_attempts") or 0)
            if (count < self.recovery_policy.REPOSITION_BUDGET and expected
                    and str((world_state.get("target") or {}).get("guid") or "") == str(expected)
                    and x is not None and y is not None):
                context["los_recovery_attempts"] = count + 1
                context["await_post_los_interact"] = True
                state.phase = InteractPhase.RECOVER.value
                return SkillResult(SkillStatus.RUNNING, metadata={"local_los_request": {
                    "reason": "LINE_OF_SIGHT", "expected_guid": expected,
                    "target_screen_x": x, "target_screen_y": y,
                    "attempt": count, "requested_at": now,
                }})
        if result.reason in {FailureReason.IDENTITY_UNCERTAIN, FailureReason.TARGET_LOST,
                             FailureReason.TARGET_NOT_FOUND}:
            count = int(context.get("reacquire_retries") or 0)
            anchor = (world_state.get("confirmed_mouseover_anchors") or {}).get(str(expected or ""))
            sample = number((anchor or {}).get("sample_time"))
            x, y = number((anchor or {}).get("x")), number((anchor or {}).get("y"))
            if (count < self.recovery_policy.REACQUIRE_BUDGET
                    and x is not None and y is not None and sample is not None
                    and 0 <= now-sample <= 1.5):
                context["reacquire_retries"] = count + 1
                context["reacquire_pending"] = True
                state.phase = InteractPhase.RECOVER.value
                return SkillResult(SkillStatus.RUNNING,
                                   commands=(Command("CLICK", x=x, y=y),),
                                   metadata={"interaction_recovery": "REACQUIRE_EXPECTED",
                                             "attempt": count})
        if result.reason is FailureReason.NO_RESPONSE:
            retries = int(context.get("direct_interaction_retries") or 0)
            if retries < self.recovery_policy.DIRECT_RETRY_BUDGET:
                context["ui_retry_not_before"] = now+self.recovery_policy.UI_WAIT_SECONDS
                state.phase = InteractPhase.RECOVER.value
                return SkillResult(SkillStatus.RUNNING,
                                   metadata={"interaction_recovery": "WAIT_AND_RETRY",
                                             "retry_not_before": context["ui_retry_not_before"]})
        if result.reason is not None:
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, result.reason,
                               retryable=result.retry_recommended, replan_required=True)
        if now >= state.attempt.deadline:
            state.phase = InteractPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.NO_RESPONSE,
                               retryable=True, replan_required=True)
        last_interact = number(context.get("last_interact_at")) or state.attempt.started_at
        if now-last_interact >= self.recovery_policy.UI_WAIT_SECONDS:
            before_frame = (state.before_snapshot or {}).get("frame_id")
            fresh = before_frame is None or world_state.get("frame_id") != before_frame
            if (not fresh or now-last_interact
                    < self.recovery_policy.RESPONSE_TIMEOUT_SECONDS):
                return SkillResult(SkillStatus.RUNNING,
                                   metadata={"interaction_recovery": "AWAIT_RESPONSE"})
            observed = int(context.get("unknown_observations") or 0)
            if observed >= self.recovery_policy.UNKNOWN_OBSERVATION_BUDGET:
                state.phase = InteractPhase.FAILED.value
                return SkillResult(SkillStatus.FAILURE, FailureReason.NO_RESPONSE,
                                   retryable=True, replan_required=True,
                                   metadata={"interaction_recovery": "UNKNOWN_ESCALATED"})
            context["unknown_observations"] = observed+1
            state.phase = InteractPhase.RECOVER.value
            return SkillResult(SkillStatus.RUNNING,
                               metadata={"interaction_recovery": "OBSERVE_ONCE"})
        return SkillResult(SkillStatus.RUNNING)
