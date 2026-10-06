"""Canonical bounded M0 combat FSM.

The skill owns only its active-attempt state.  It deliberately has no planner,
navigation, or global combat-controller state.
"""
from __future__ import annotations

from enum import StrEnum
import re

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus, world_entity_id
from wowbot.verification.combat import CombatVerifier
from wowbot.verification.combat_error_classifier import classify_combat_error
from .action_error_correlation import ActionErrorCorrelator
from .ability_rules import AbilityRuleEngine
from .combat_visual_follow import CombatVisualFollowPolicy
from .vehicle import rotation_allowed
from .target_recovery import InvalidTargetRecoveryPolicy


class CombatPhase(StrEnum):
    IDLE = "IDLE"
    SELECT_TARGET = "SELECT_TARGET"
    ACQUIRE_TARGET = "ACQUIRE_TARGET"
    APPROACH_TARGET = "APPROACH_TARGET"
    ENGAGE = "ENGAGE"
    SELECT_ABILITY = "SELECT_ABILITY"
    EXECUTE_ABILITY = "EXECUTE_ABILITY"
    VERIFY_ABILITY = "VERIFY_ABILITY"
    RECOVER_RANGE = "RECOVER_RANGE"
    RECOVER_FACING = "RECOVER_FACING"
    RECOVER_LOS = "RECOVER_LOS"
    RECOVER_TARGET = "RECOVER_TARGET"
    CONFIRM_KILL = "CONFIRM_KILL"
    POST_COMBAT = "POST_COMBAT"
    FAILED = "FAILED"


class CombatSkill:
    # A full keyboard turn takes ~2 s: the target may be right behind the
    # character when the client reports "facing the wrong way".
    FACING_RECOVERY_TIMEOUT_SECONDS = 3.0
    RANGE_RECOVERY_TIMEOUT_SECONDS = 3.5
    RANGE_DIRECT_APPROACH_BUDGET = 2
    RANGE_SAFE_MIN = 2.0
    RANGE_SAFE_MAX = 35.0
    LOS_RECOVERY_ATTEMPTS = 3
    LOS_RECOVERY_TIMEOUT_PER_ATTEMPT = 2.5

    COMBAT_DROP_GRACE_SECONDS = 6.
    # Live 2026-10-03 13:12 (Prickly Porcupine): one 75 ms facing turn, then
    # the post-recovery cast wait never ended (nothing was usable, the target
    # stayed off-screen) and COMBAT sent no input for 4.5 min.  The wait for
    # the first post-correction cast is bounded, and an attempt that issues
    # nothing while its target is not on screen fails typed for a replan.
    POST_RECOVERY_CAST_WINDOW_SECONDS = 1.5
    IDLE_STALL_SECONDS = 6.
    FACING_SWEEP_STEPS = 10
    FACING_SWEEP_TURN_SECONDS = .2
    FACING_SWEEP_SETTLE_SECONDS = .45
    FACING_SWEEP_QUIET_SECONDS = 1.1

    @staticmethod
    def _facing_text(world_state: dict) -> bool:
        text = str(world_state.get("ui_error") or "").casefold()
        return "front" in text or "facing" in text

    def _sweep_attack_binding(self, context: dict) -> str:
        if self.bindings is None or self.bindings.contains("INTERACTTARGET"):
            return "INTERACTTARGET"
        return str(context.get("last_binding") or "INTERACTTARGET")

    def _facing_sweep_step(self, state: ActiveSkillState, world_state: dict,
                           now: float) -> SkillResult:
        context = state.skill_context.setdefault("combat", {})
        sweep = context["facing_sweep"]
        if int(sweep.get("steps") or 0) >= self.FACING_SWEEP_STEPS:
            context.pop("facing_sweep", None)
            state.phase = CombatPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.FACING_FAILED,
                               retryable=True, replan_required=True,
                               metadata={"facing_sweep_steps": sweep.get("steps")})
        sweep["steps"] = int(sweep.get("steps") or 0) + 1
        sweep["last_step_at"] = now
        sweep["error_sequence"] = number(world_state.get("ui_error_sequence"))
        context["facing_handled_sequence"] = sweep["error_sequence"]
        context["facing_recovery_started_at"] = now      # the sweep has its own bound
        state.phase = CombatPhase.RECOVER_FACING.value
        return SkillResult(
            SkillStatus.RUNNING,
            commands=(Command("BIND", sweep["direction"], self.FACING_SWEEP_TURN_SECONDS),
                      Command("BIND", self._sweep_attack_binding(context))),
            metadata={"facing_sweep_step": sweep["steps"]})

    def _continue_facing_sweep(self, state: ActiveSkillState, world_state: dict,
                               now: float) -> SkillResult | None:
        """Next sweep step on a newer facing error; end it when quiet/visible."""
        context = state.skill_context.setdefault("combat", {})
        sweep = context.get("facing_sweep")
        if not sweep:
            return None
        target = world_state.get("target") or {}
        if (str(target.get("guid") or "") != str(context.get("expected_guid") or "")
                or target.get("dead", target.get("is_dead"))
                or self._target_on_screen(target, now)):
            context.pop("facing_sweep", None)
            return None
        since = now - float(sweep.get("last_step_at") or now)
        if since < self.FACING_SWEEP_SETTLE_SECONDS:
            return SkillResult(SkillStatus.RUNNING, metadata={"facing_sweep_settling": True})
        sequence = number(world_state.get("ui_error_sequence"))
        previous = number(sweep.get("error_sequence"))
        newer = sequence is not None and (previous is None or sequence > previous)
        if newer and self._facing_text(world_state):
            return self._facing_sweep_step(state, world_state, now)
        if since >= self.FACING_SWEEP_QUIET_SECONDS:
            # No new "not in front" answer to the last attack key: facing.
            context.pop("facing_sweep", None)
            context.pop("facing_recovery_started_at", None)
            return None
        return SkillResult(SkillStatus.RUNNING, metadata={"facing_sweep_waiting": True})

    def __init__(self, bindings=None, verifier: CombatVerifier | None = None):
        self.bindings = bindings
        self.verifier = verifier or CombatVerifier()
        self.error_correlation = ActionErrorCorrelator()
        self.ability_rules = AbilityRuleEngine(bindings)
        self.visual_follow = CombatVisualFollowPolicy()
        self.target_recovery = InvalidTargetRecoveryPolicy()

    def begin(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        state.phase = CombatPhase.SELECT_TARGET.value
        expected = world_entity_id(state.intent.target_ref or state.intent.parameters.get("guid"))
        target = world_state.get("target") or {}
        state.skill_context["combat"] = {
            "expected_guid": expected,
            "last_cast_at": -float("inf"),
            "last_binding": None,
            "ability_uses": {},
            "ability_attempts": [],
            "last_action_sample": None,
            "auto_attack_started_at": None,
            "auto_attack_dispatches": 0,
            "visual_follow_armed": False,
            # A local combat correction is a bounded sub-step of this one
            # COMBAT attempt, never a new planner-owned MOVE.  The next
            # cast deliberately ignores a retained client error once, because
            # Retail can display the prior UI_ERROR_MESSAGE for several
            # seconds after the key that caused it.
            "local_recovery_attempts": {},
            # An out-of-range target with simultaneous, same-instance world
            # coordinates is approached through NavigationService.  This is
            # deliberately recorded on the *same* combat attempt; a planner
            # must not replace combat with a series of MOVE proposals.
            "approach_request": None,
            "await_post_recovery_cast": False,
            "range_recovery_started_at": None,
            "desired_range": None,
            "facing_recovery_started_at": None,
            "target_recovery_attempts": 0,
            "target_recovery_pending": False,
            # Bounded same-attempt state transitions for the canonical
            # CombatErrorClassifier (not a second combat state owner).
            "observation_history": [self._error_observation(state.before_snapshot)],
            "last_error_classification": None,
        }
        state.phase = CombatPhase.ACQUIRE_TARGET.value
        if not expected or target.get("guid") != expected:
            state.phase = CombatPhase.RECOVER_TARGET.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        if target.get("dead", target.get("is_dead")):
            state.phase = CombatPhase.POST_COMBAT.value
            return SkillResult(SkillStatus.SUCCESS, evidence=("target_already_dead",))
        if target.get("attackable", target.get("is_attackable")) is not True:
            state.phase = CombatPhase.RECOVER_TARGET.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.INVALID_TARGET,
                               replan_required=True)
        state.phase = CombatPhase.ENGAGE.value
        return self._next_action(state, world_state, now)

    def resume_after_approach(self, state: ActiveSkillState, world_state: dict,
                              now: float) -> SkillResult:
        """Resume the same committed combat attempt after canonical reach.

        Revalidate the selected entity at the authority boundary.  A movement
        completion alone is never permission to cast at whichever unit became
        selected while moving.
        """
        context = state.skill_context.setdefault("combat", {})
        expected = str(context.get("expected_guid") or "")
        target = world_state.get("target") or {}
        if (not expected or str(target.get("guid") or "") != expected
                or target.get("dead", target.get("is_dead"))
                or target.get("attackable", target.get("is_attackable")) is not True):
            state.phase = CombatPhase.RECOVER_TARGET.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_LOST,
                               retryable=True, replan_required=True)
        context["approach_request"] = None
        # Ignore the retained client range message for the first post-arrival
        # cast exactly as local recoveries do.
        context["await_post_recovery_cast"] = True
        state.phase = CombatPhase.ENGAGE.value
        return self._next_action(state, world_state, now)

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.setdefault("combat", {})
        progress_at = context.setdefault("last_progress_at", now)
        result = self._verify(state, world_state, now)
        if result.status is not SkillStatus.RUNNING:
            return result
        metadata = result.metadata or {}
        target = world_state.get("target") or {}
        if (result.commands or world_state.get("is_casting")
                or any(metadata.get(key) for key in (
                    "local_navigation_request", "approach_request",
                    "los_reposition_request", "awaiting_combat_drop",
                    "facing_sweep_settling", "facing_sweep_waiting"))
                or self._target_on_screen(target, now)
                # In melee with nothing affordable yet (rage) is a legit wait.
                or any(row.get("is_harmful") is True and row.get("in_range") is True
                       for row in self.ability_rules.actionbar(world_state))):
            context["last_progress_at"] = now
            return result
        if now-float(progress_at) >= self.IDLE_STALL_SECONDS:
            state.phase = CombatPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.FACING_FAILED,
                               retryable=True, replan_required=True,
                               metadata={"combat_stalled": True,
                                         "idle_seconds": round(now-float(progress_at), 2)})
        return result

    @staticmethod
    def _target_on_screen(target: dict, now: float) -> bool:
        screen = target.get("screen_position") or {}
        x, y = number(screen.get("x")), number(screen.get("y"))
        sampled = number(screen.get("sample_time", screen.get("observed_at")))
        return (x is not None and y is not None and .01 < x < .99 and .01 < y < .99
                and (sampled is None or 0. <= now-sampled <= 1.5))

    def _verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.setdefault("combat", {})
        # Face the selected target from the first control tick, not only
        # after the first cast (user 2026-10-01: never fight with the back to
        # it).  The launch path itself can only dispatch direct commands.
        context["visual_follow_armed"] = True
        target = world_state.get("target") or {}
        sweep = self._continue_facing_sweep(state, world_state, now)
        if sweep is not None:
            return sweep
        if (context.get("target_recovery_pending")
                and target.get("guid") == context.get("expected_guid")
                and target.get("attackable", target.get("is_attackable")) is True
                and not target.get("dead", target.get("is_dead"))):
            context["target_recovery_pending"] = False
            state.phase = CombatPhase.ENGAGE.value
            return self._next_action(state, world_state, now)
        correlation = self.error_correlation.correlate(
            context.get("ability_attempt"), world_state, now)
        if correlation is not None:
            context["ability_correlation"] = {
                "attempt_id": correlation.attempt_id,
                "within_window": correlation.within_window,
                "failure_evidence": correlation.failure_evidence,
                "cast_changed": correlation.cast_changed,
                "resource_changed": correlation.resource_changed,
                "target_damage": correlation.target_damage,
            }
        if context.get("await_post_recovery_cast"):
            # A correction was dispatched on the preceding observation.  Give
            # the same committed target one fresh cast attempt before treating
            # a still-exported UI error as a new LOS/range/facing failure.
            # The wait is bounded: when nothing becomes usable, the normal
            # verification (deadline, recoveries) takes over again.
            since = context.setdefault("await_post_recovery_since", now)
            if (now-float(since) < self.POST_RECOVERY_CAST_WINDOW_SECONDS
                    and now < state.attempt.deadline):
                next_action = self._next_action(state, world_state, now)
                if next_action.commands or next_action.status is not SkillStatus.RUNNING:
                    context["await_post_recovery_cast"] = False
                    context.pop("await_post_recovery_since", None)
                return next_action
            context["await_post_recovery_cast"] = False
            context.pop("await_post_recovery_since", None)
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        expected_guid=context.get("expected_guid"))
        # A retained UI_ERROR_MESSAGE is not evidence about this cast.  Keep
        # every other observation intact, but prevent old text from forcing a
        # false range/LOS/facing recovery.
        if result.reason in {FailureReason.OUT_OF_RANGE, FailureReason.FACING_WRONG_WAY,
                             FailureReason.LINE_OF_SIGHT, FailureReason.SPELL_NOT_READY,
                             FailureReason.PATH_BLOCKED} and not self.error_correlation.matches(
                                 context.get("ability_attempt"), world_state, now):
            sanitized = dict(world_state)
            sanitized.pop("ui_error", None)
            result = self.verifier.evaluate(state.before_snapshot, sanitized,
                                            expected_guid=context.get("expected_guid"))
        if result.reason is None and not result.success:
            classification = classify_combat_error(
                world_state, context.get("observation_history") or (),
                verifier=self.verifier)
            context["last_error_classification"] = classification.value
            # TARGET_LOST needs temporal correlation from CombatVerifier.
            # A single addon frame with no selected GUID is diagnostic
            # evidence, not permission to abandon the committed combat
            # target (or switch to an unrelated corpse).
            if classification not in {FailureReason.UI_UNKNOWN, FailureReason.TARGET_LOST}:
                result = type(result)(
                    False, max(.65, result.confidence), classification,
                    (*result.evidence, f"combat_error:{classification.value}"),
                    classification not in {
                        FailureReason.PLAYER_DEAD, FailureReason.TARGET_DEAD,
                        FailureReason.INVALID_TARGET})
        if (result.reason == FailureReason.SPELL_NOT_READY
                and context.get("ability_attempt") is not None):
            self.ability_rules.note_not_ready(
                getattr(context["ability_attempt"], "ability_id", None), now)
        history = context.setdefault("observation_history", [])
        history.append(self._error_observation(world_state))
        del history[:-12]
        state.phase = CombatPhase.VERIFY_ABILITY.value
        # Retail 12 clears the selection the moment the unit dies and exports
        # no target health (secret values), so no dead flag ever arrives.
        # Live 2026-10-01: COMBAT kept "selecting abilities" for 17-32 s after
        # the kill and LOOT started late or never; the selection vanished and
        # the player left combat in the same sample.  User rule: the fight is
        # over when the character is out of combat.  While still in combat
        # (another attacker) the existing target-loss handling applies.
        if (world_state.get("is_in_combat") is True
                or (state.before_snapshot or {}).get("is_in_combat") is True):
            context["was_in_combat"] = True
        target_now = world_state.get("target") or {}
        engaged = bool(context.get("ability_attempts")
                       or int(context.get("auto_attack_dispatches") or 0) > 0)
        if (not result.success and context.get("expected_guid")
                and engaged and context.get("was_in_combat")
                and world_state.get("is_in_combat") is False
                and not target_now.get("guid")):
            result = type(result)(True, .9, None,
                                  (*result.evidence, "player_left_combat_after_engagement"))
        if result.success:
            state.phase = CombatPhase.CONFIRM_KILL.value
            state.phase = CombatPhase.POST_COMBAT.value
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        # Live 2026-10-01 18:40: after the kill the player stays in combat for
        # ~2.5-3.5 s; with no selection every harmful action reads "out of
        # range" and COMBAT failed with out_of_range before combat dropped, so
        # the kill was never marked and nothing was looted.  Wait for the
        # drop; leave at once if our own health falls (another attacker, user:
        # fight it, loot after combat) or after the grace.
        if (context.get("expected_guid") and engaged
                and context.get("was_in_combat") and not target_now.get("guid")
                and world_state.get("is_in_combat") is True):
            vanished_at = context.setdefault("target_vanished_at", now)
            health = number(world_state.get("health"))
            if context.get("health_at_vanish") is None and health is not None:
                context["health_at_vanish"] = health
            baseline = number(context.get("health_at_vanish"))
            attacked = health is not None and baseline is not None and health < baseline
            if not attacked and now-vanished_at < self.COMBAT_DROP_GRACE_SECONDS:
                state.phase = CombatPhase.CONFIRM_KILL.value
                return SkillResult(SkillStatus.RUNNING,
                                   metadata={"awaiting_combat_drop": True})
        else:
            context.pop("target_vanished_at", None)
            context.pop("health_at_vanish", None)
        handled = number(context.get("facing_handled_sequence"))
        if (result.reason is FailureReason.FACING_WRONG_WAY and handled is not None
                and number(world_state.get("ui_error_sequence")) == handled
                and now < state.attempt.deadline):
            # The same, already-answered facing error is still displayed.
            return self._next_action(state, world_state, now)
        local_recovery = self._local_recovery_request(state, world_state, result.reason, now)
        if local_recovery is not None:
            return local_recovery
        if result.reason in {FailureReason.INVALID_TARGET, FailureReason.IDENTITY_UNCERTAIN,
                             FailureReason.TARGET_LOST}:
            recovery = self._invalid_target_recovery(state, world_state, result.reason)
            if recovery is not None:
                return recovery
        if result.reason in {FailureReason.PLAYER_DEAD, FailureReason.IDENTITY_UNCERTAIN,
                             FailureReason.TARGET_LOST, FailureReason.OUT_OF_RANGE,
                             FailureReason.FACING_WRONG_WAY, FailureReason.LINE_OF_SIGHT,
                             FailureReason.PATH_BLOCKED,
                             FailureReason.NOT_ENOUGH_RESOURCE}:
            if result.reason in {FailureReason.IDENTITY_UNCERTAIN, FailureReason.TARGET_LOST}:
                state.phase = CombatPhase.RECOVER_TARGET.value
            else:
                state.phase = CombatPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, result.reason,
                               retryable=result.retry_recommended, replan_required=True)
        if now >= state.attempt.deadline:
            state.phase = CombatPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.COMBAT_TIMEOUT,
                               retryable=True, replan_required=True)
        return self._next_action(state, world_state, now)

    @staticmethod
    def _error_observation(world_state: dict) -> dict:
        """Keep only bounded fields needed by combat error classification."""
        target = world_state.get("target") or {}
        return {
            "is_dead": world_state.get("is_dead"),
            "is_ghost": world_state.get("is_ghost"),
            "is_moving": world_state.get("is_moving"),
            "is_casting": world_state.get("is_casting"),
            "power": world_state.get("power"),
            "max_power": world_state.get("max_power"),
            "ui_error": world_state.get("ui_error"),
            "target": {key: target.get(key) for key in (
                "guid", "attackable", "is_attackable", "dead", "is_dead",
                "health", "max_health")},
        }

    def _next_action(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.setdefault("combat", {})
        state.phase = CombatPhase.SELECT_ABILITY.value
        if not rotation_allowed(world_state):
            # V4-055: do not let normal rotation fire into a vehicle
            # override state. Fail typed so the planner can switch to
            # VehicleSkill rather than silently stalling this attempt.
            state.phase = CombatPhase.FAILED.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.UNSUPPORTED_MECHANIC,
                               replan_required=True, metadata={"reason": "vehicle_override_active"})
        if world_state.get("is_casting"):
            state.phase = CombatPhase.VERIFY_ABILITY.value
            return SkillResult(SkillStatus.RUNNING)
        # The launch path can only dispatch direct commands; navigation
        # metadata is composed by CombatRuntimeRunner on subsequent control
        # ticks.  Cast the first probe normally, then keep the committed
        # target centred during its GCD and all later rotation steps.
        visual_follow = (self._visual_follow_request(state, world_state, now)
                         if ((context.get("ability_attempts")
                              or context.get("visual_follow_armed"))
                             and not context.get("await_post_recovery_cast")) else None)
        if visual_follow is not None:
            return visual_follow
        # Respect the client GCD and wait for a fresh usable action instead of
        # issuing an uncontrolled repeated keypress.
        if now - float(context.get("last_cast_at", -float("inf"))) < .9:
            state.phase = CombatPhase.VERIFY_ABILITY.value
            return SkillResult(SkillStatus.RUNNING)
        sample = self._combat_sample_key(world_state)
        if (sample is not None and context.get("last_action_sample") is not None
                and sample == context.get("last_action_sample")):
            # Never make a second combat decision from the exact same FAST
            # sample.  Live logs showed Charge being dispatched twice while
            # its pre-cast readiness state was still being replayed.
            state.phase = CombatPhase.VERIFY_ABILITY.value
            return SkillResult(SkillStatus.RUNNING)
        uses = context.setdefault("ability_uses", {})
        action = self._choose_action(world_state, uses=uses, now=now, context=context)
        if action is None:
            auto_attack = self._auto_attack_fallback(state, world_state, now)
            if auto_attack is not None:
                return auto_attack
            harmful = [row for row in self.ability_rules.actionbar(world_state)
                       if row.get("kind") == "spell" and row.get("is_harmful") is True]
            if harmful and all(row.get("in_range") is False for row in harmful):
                visual_approach = self._visual_range_approach_request(
                    state, world_state, now)
                if visual_approach is not None:
                    return visual_approach
                recovery = self._local_recovery_request(
                    state, world_state, FailureReason.OUT_OF_RANGE, now)
                if recovery is not None:
                    return recovery
                state.phase = CombatPhase.RECOVER_RANGE.value
                return SkillResult(SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                                   retryable=True, replan_required=True)
            return SkillResult(SkillStatus.RUNNING)
        context["last_cast_at"] = now
        context["last_action_sample"] = sample
        context["last_binding"] = action["action"]
        spell_id = action.get("id", action.get("spell_id"))
        uses[spell_id] = int(uses.get(spell_id) or 0)+1
        context["visual_follow_armed"] = True
        attempts = context.setdefault("ability_attempts", [])
        attempts.append({"spell_id": spell_id, "binding": action.get("action"), "at": now})
        del attempts[:-24]
        definition = self.ability_rules.definition(action)
        context["desired_range"] = (
            min(self.RANGE_SAFE_MAX,
                max(self.RANGE_SAFE_MIN, definition.max_range * .80))
            if definition.max_range is not None else 3.5)
        context["ability_attempt"] = self.error_correlation.start(
            world_state, now,
            ability_id=action.get("id", action.get("spell_id")),
            binding=action.get("action"))
        context["ability_attempt_id"] = context["ability_attempt"].attempt_id
        state.phase = CombatPhase.EXECUTE_ABILITY.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", action["action"]),),
                           metadata={"spell_id": spell_id,
                                     "cast_dispatched": True,
                                     "ability_use_count": uses[spell_id],
                                     "ability_attempt_id": context["ability_attempt_id"]})

    @staticmethod
    def _combat_sample_key(world_state: dict):
        """Identity of the freshest control-lane combat observation."""
        return (world_state.get("fast_sequence")
                or world_state.get("frame_id")
                or world_state.get("target_sample_time")
                or world_state.get("monotonic_time"))

    def _auto_attack_fallback(self, state: ActiveSkillState,
                              world_state: dict, now: float) -> SkillResult | None:
        """Start melee auto-attack when no rage/cooldown ability is usable.

        A right click is allowed only on a fresh screen position belonging to
        the exact addon-selected hostile GUID.  It is dispatched once per
        COMBAT attempt; later ticks keep evaluating Slam/Shield Slam as rage
        and cooldown telemetry changes.
        """
        context = state.skill_context.setdefault("combat", {})
        if int(context.get("auto_attack_dispatches") or 0) >= 1:
            return None
        expected = str(context.get("expected_guid") or "")
        target = world_state.get("target") or {}
        if (not expected or str(target.get("guid") or "") != expected
                or target.get("attackable", target.get("is_attackable")) is not True
                or target.get("dead", target.get("is_dead")) is True):
            return None
        actions = self.ability_rules.actionbar(world_state)
        melee_range = False
        for action in actions:
            if not isinstance(action, dict) or action.get("is_harmful") is not True:
                continue
            definition = self.ability_rules.definition(action)
            if ("MOVEMENT" not in definition.tags
                    and definition.max_range is not None
                    and definition.max_range <= 5.
                    and action.get("in_range") is True):
                melee_range = True
                break
        distance = number(target.get("distance", target.get("distance_yards")))
        # Live 13:58: in combat Retail exported no range for the goat that
        # was hitting the character; "unknown" is not "out of range".
        range_unknown = (world_state.get("is_in_combat") is True and not any(
            isinstance(action, dict) and action.get("is_harmful") is True
            and action.get("in_range") is False for action in actions))
        if (not melee_range and not (distance is not None and distance <= 5.)
                and not range_unknown):
            return None
        if self.bindings is not None and self.bindings.contains("INTERACTTARGET"):
            # Live 2026-10-03 13:37: the goat overlapped the character and the
            # right click at its box landed on our own model; no attack for
            # 15 s.  Interact-with-target attacks the selected unit itself.
            context["auto_attack_started_at"] = now
            context["auto_attack_dispatches"] = 1
            context["last_action_sample"] = self._combat_sample_key(world_state)
            state.phase = CombatPhase.EXECUTE_ABILITY.value
            return SkillResult(
                SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),),
                metadata={"auto_attack_fallback": True, "expected_guid": expected,
                          "reason": "no_usable_melee_ability", "via": "INTERACTTARGET"})
        screen = target.get("screen_position") or {}
        x, y = number(screen.get("x")), number(screen.get("y"))
        sampled = number(screen.get("sample_time", screen.get("observed_at")))
        if (x is None or y is None or not .01 < x < .99 or not .01 < y < .99
                or (sampled is not None and not 0. <= now-sampled <= .75)):
            return None
        context["auto_attack_started_at"] = now
        context["auto_attack_dispatches"] = 1
        context["last_action_sample"] = self._combat_sample_key(world_state)
        state.phase = CombatPhase.EXECUTE_ABILITY.value
        return SkillResult(
            SkillStatus.RUNNING,
            commands=(Command("CLICK", x=x, y=y, button="RIGHT"),),
            metadata={"auto_attack_fallback": True,
                      "expected_guid": expected,
                      "reason": "no_usable_melee_ability"})

    def _visual_follow_request(self, state: ActiveSkillState, world_state: dict,
                               now: float) -> SkillResult | None:
        """Request proactive facing from fresh selected-target track evidence."""
        context = state.skill_context.setdefault("combat", {})
        decision = self.visual_follow.decide(context, world_state, now)
        if decision is None:
            return None
        state.phase = (CombatPhase.APPROACH_TARGET.value
                       if decision.kind == "COMBAT_TRACK_REACQUIRE"
                       else CombatPhase.RECOVER_FACING.value)
        return SkillResult(SkillStatus.RUNNING, metadata={
            "local_navigation_request": {
                "kind": decision.kind,
                "reason": decision.kind,
                "expected_guid": decision.expected_guid,
                "target_screen_x": decision.target_screen_x,
                "target_screen_y": decision.target_screen_y,
                "visual_sample_time": decision.visual_sample_time,
                "requested_at": now,
            },
            "visual_follow_reason": decision.reason,
        })

    def _visual_range_approach_request(self, state: ActiveSkillState,
                                       world_state: dict, now: float) -> SkillResult | None:
        """Keep approaching an out-of-range selected unit on fresh visual data."""
        context = state.skill_context.setdefault("combat", {})
        expected = str(context.get("expected_guid") or "")
        target = world_state.get("target") or {}
        screen = target.get("screen_position") or {}
        x, y = number(screen.get("x")), number(screen.get("y"))
        sampled = number(screen.get("sample_time", screen.get("observed_at")))
        if (not expected or str(target.get("guid") or "") != expected
                or x is None or y is None or not .01 < x < .99 or not .01 < y < .99
                or (sampled is not None and not 0. <= now-sampled <= .50)):
            return None
        started = number(context.get("range_recovery_started_at"))
        if started is None:
            context["range_recovery_started_at"] = now
            started = now
        if now-started >= self.RANGE_RECOVERY_TIMEOUT_SECONDS:
            return None
        if (sampled is not None
                and sampled == context.get("last_range_approach_visual_sample")):
            return SkillResult(SkillStatus.RUNNING)
        context["last_range_approach_visual_sample"] = sampled
        context["visual_follow_armed"] = True
        state.phase = CombatPhase.APPROACH_TARGET.value
        return SkillResult(SkillStatus.RUNNING, metadata={
            "local_navigation_request": {
                "kind": "COMBAT_TRACK_APPROACH",
                "reason": "COMBAT_TRACK_APPROACH",
                "expected_guid": expected,
                "target_screen_x": x,
                "target_screen_y": y,
                "visual_sample_time": sampled,
                "requested_at": now,
            },
            "visual_follow_reason": "selected_target_all_harmful_abilities_out_of_range",
        })

    def _local_recovery_request(self, state: ActiveSkillState, world_state: dict,
                                reason: FailureReason | None, now: float) -> SkillResult | None:
        """Request one safe local navigation correction, or return ``None``.

        Combat owns the decision that its *current* target needs a local retry;
        NavigationService owns the resulting turn/forward command.  No blind
        movement is permitted: a current matching target and fresh normalized
        screen position are required.  Missing localization therefore remains
        a typed combat failure for the planner to resolve at a higher level.
        """
        if reason not in {FailureReason.OUT_OF_RANGE, FailureReason.FACING_WRONG_WAY,
                          FailureReason.LINE_OF_SIGHT}:
            return None
        context = state.skill_context.setdefault("combat", {})
        expected = context.get("expected_guid")
        target = world_state.get("target") or {}
        if reason is FailureReason.OUT_OF_RANGE and not context.get("approach_request"):
            started_at = context.get("range_recovery_started_at")
            if started_at is None:
                context["range_recovery_started_at"] = now
                started_at = now
            if now - float(started_at) >= self.RANGE_RECOVERY_TIMEOUT_SECONDS:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                    retryable=False, replan_required=True,
                    metadata={"target_unreachable": True,
                              "range_recovery_timeout_seconds":
                                  self.RANGE_RECOVERY_TIMEOUT_SECONDS})
            desired_range = number(context.get("desired_range")) or 3.5
            world_request = self._world_approach_request(
                world_state, expected, desired_range=desired_range)
            if world_request is not None:
                attempts = context.setdefault("world_approach_attempts", 0)
                if attempts < self.RANGE_DIRECT_APPROACH_BUDGET:
                    context["world_approach_attempts"] = attempts + 1
                    context["approach_request"] = world_request
                    state.local_retry_count += 1
                    state.failure_history.append(reason)
                    state.phase = CombatPhase.RECOVER_RANGE.value
                    return SkillResult(SkillStatus.RUNNING,
                                       metadata={"approach_request": world_request})
        screen = target.get("screen_position") or {}
        x = number(screen.get("x"))
        y = number(screen.get("y"))
        sampled = number(screen.get("sample_time"))
        current_time = number(world_state.get("monotonic_time"))
        attempts = context.setdefault("local_recovery_attempts", {})
        count = int(attempts.get(reason.value, 0))
        if reason is FailureReason.LINE_OF_SIGHT and count >= self.LOS_RECOVERY_ATTEMPTS:
            state.phase = CombatPhase.FAILED.value
            return SkillResult(
                SkillStatus.FAILURE, FailureReason.LINE_OF_SIGHT,
                retryable=True, replan_required=True,
                metadata={"target_unreachable": True,
                          "replan_scope": "LOCAL",
                          "los_recovery_phase": "TARGET_UNREACHABLE",
                          "los_recovery_attempts": count})
        # The third LOS step is not another blind screen-space pulse.  It is a
        # validated same-instance world request; NavigationService may route
        # it through Trinity mmap and its persistent movement controller.
        if reason is FailureReason.LINE_OF_SIGHT and count == 2:
            desired_range = number(context.get("desired_range")) or 4.5
            world_request = self._world_approach_request(
                world_state, expected, desired_range=desired_range)
            if world_request is None:
                attempts[reason.value] = self.LOS_RECOVERY_ATTEMPTS
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.LINE_OF_SIGHT,
                    retryable=True, replan_required=True,
                    metadata={"target_unreachable": True,
                              "replan_scope": "LOCAL",
                              "los_recovery_phase": "LOCAL_REPLAN_UNAVAILABLE",
                              "los_recovery_attempts": count})
            world_request["kind"] = "LOS_REPOSITION"
            context["approach_request"] = world_request
            attempts[reason.value] = count + 1
            state.local_retry_count += 1
            state.failure_history.append(reason)
            state.phase = CombatPhase.RECOVER_LOS.value
            return SkillResult(
                SkillStatus.RUNNING,
                metadata={"los_reposition_request": world_request,
                          "los_recovery_phase": "LOCAL_REPLAN",
                          "los_recovery_attempt": count,
                          "timeout": self.LOS_RECOVERY_TIMEOUT_PER_ATTEMPT})
        if reason is FailureReason.FACING_WRONG_WAY:
            facing_started = context.get("facing_recovery_started_at")
            if facing_started is None:
                context["facing_recovery_started_at"] = now
                facing_started = now
            if now - float(facing_started) >= self.FACING_RECOVERY_TIMEOUT_SECONDS:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.FACING_FAILED,
                    retryable=True, replan_required=True,
                    metadata={"facing_recovery_timeout_seconds":
                                  self.FACING_RECOVERY_TIMEOUT_SECONDS})
            if x is None or y is None:
                # Live 2026-10-02: the attacker was behind the character, so
                # it was not on screen and COMBAT gave up in 1.5 s.  Turn
                # toward the last bearing seen (default left); a full keyboard
                # turn takes ~2 s, within the facing timeout.
                follow = context.get("visual_follow") or {}
                last_x = number(follow.get("last_seen_x"))
                direction = follow.get("reacquire_direction")
                if direction not in {"TURNLEFT", "TURNRIGHT"}:
                    direction = ("TURNRIGHT" if last_x is not None and last_x >= .5
                                 else "TURNLEFT")
                state.phase = CombatPhase.RECOVER_FACING.value
                # Live 2026-10-03 13:57: turning blindly for 3 s without ever
                # retrying the attack ended in FACING_FAILED while a goat
                # beat the character to death.  Sweep instead: a ~35 degree
                # turn plus the attack key, repeated only while the client
                # keeps answering "not in front".
                sequence = number(world_state.get("ui_error_sequence"))
                if (not context.get("facing_sweep") and sequence is not None
                        and sequence == number(context.get("facing_handled_sequence"))):
                    # The addon keeps an error for 3 s; one already answered
                    # by a sweep step is not a new facing failure.
                    return None
                if not context.get("facing_sweep"):
                    context["facing_sweep"] = {
                        "steps": 0, "direction": direction,
                        "error_sequence": number(world_state.get("ui_error_sequence"))}
                return self._facing_sweep_step(state, world_state, now)
        if (not expected or target.get("guid") != expected or x is None or y is None
                or not .02 < x < .98 or not .02 < y < .98
                or (sampled is not None and current_time is not None
                    and not 0 <= current_time-sampled <= 1.5)):
            return None
        # One facing correction, at most two small range corrections and two
        # LOS lateral probes preserve commitment without an uncontrolled loop.
        # LOS attempt three was handled above as a geometry-backed replan.
        maximum = (1 if reason is FailureReason.FACING_WRONG_WAY else
                   self.LOS_RECOVERY_ATTEMPTS
                   if reason is FailureReason.LINE_OF_SIGHT else 2)
        if count >= maximum:
            if reason is FailureReason.OUT_OF_RANGE:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                    retryable=False, replan_required=True,
                    metadata={"target_unreachable": True,
                              "replan_scope": "LOCAL",
                              "range_recovery_attempts": {
                                  "direct": context.get("world_approach_attempts", 0),
                                  "local": count,
                              }})
            if reason is FailureReason.LINE_OF_SIGHT:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.LINE_OF_SIGHT,
                    retryable=True, replan_required=True,
                    metadata={"target_unreachable": True,
                              "replan_scope": "LOCAL",
                              "los_recovery_attempts": count})
            return None
        attempts[reason.value] = count + 1
        # CombatSkill receives the canonical mutable ActiveSkillState, not
        # the runtime façade.  Record this local retry on that sole active
        # state so the supervisor/debug snapshot sees it too.
        state.local_retry_count += 1
        state.failure_history.append(reason)
        phase = {
            FailureReason.OUT_OF_RANGE: CombatPhase.RECOVER_RANGE,
            FailureReason.FACING_WRONG_WAY: CombatPhase.RECOVER_FACING,
            FailureReason.LINE_OF_SIGHT: CombatPhase.RECOVER_LOS,
        }[reason]
        state.phase = phase.value
        context["await_post_recovery_cast"] = True
        return SkillResult(
            SkillStatus.RUNNING,
            metadata={"local_navigation_request": {
                "kind": "COMBAT_LOCAL_RECOVERY",
                "reason": reason.value,
                "expected_guid": expected,
                "target_screen_x": x,
                "target_screen_y": y,
                "attempt": count,
                "requested_at": now,
            }},
        )

    @staticmethod
    def _world_approach_request(world_state: dict, expected_guid: str | None,
                                *, desired_range: float = 3.5) -> dict | None:
        """Return a safe M0 reach request only for a live selected target."""
        target = world_state.get("target") or {}
        player = world_state.get("player_world_position") or {}
        position = target.get("world_position") or {}
        if (not expected_guid or str(target.get("guid") or "") != str(expected_guid)
                or target.get("dead", target.get("is_dead"))
                or target.get("attackable", target.get("is_attackable")) is not True):
            return None
        if None in {number(player.get("x")), number(player.get("y")),
                    number(position.get("x")), number(position.get("y"))}:
            return None
        player_instance, target_instance = player.get("instance_id"), position.get("instance_id")
        if (player_instance is not None and target_instance is not None
                and player_instance != target_instance):
            return None
        return {"kind": "WORLD_COMBAT", "expected_guid": str(expected_guid),
                "stop_distance": float(desired_range)}

    # Live 2026-10-05 (Enhanced Combat Tactics): Captain Garrick said "Charge
    # at me again to close the distance" three times; Charge is a once-per-
    # fight opener in the rotation, so the agent kept pressing Slam and the
    # user had to Charge.  A fresh NPC instruction naming an ability lifts
    # the opener limits for that ability, once per instruction; WoW's own
    # usable/range/cooldown gates still hold.
    INSTRUCTION_FRESH_SECONDS = 12.
    INSTRUCTION_WAIVED = frozenset({"movement_opener_already_used", "melee_range_confirmed"})

    @staticmethod
    def _words(text) -> str:
        return " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip() + " "

    def _pending_instruction(self, world_state: dict, context: dict) -> tuple[str, float] | None:
        events = [event for event in world_state.get("events") or ()
                  if isinstance(event, dict) and event.get("event_type") == "NPC_INSTRUCTION"]
        if not events:
            return None
        event = max(events, key=lambda item: number(item.get("sequence")) or -1.)
        sequence = number(event.get("sequence"))
        said_at, state_at = number(event.get("timestamp")), number(world_state.get("timestamp"))
        if sequence is None or sequence == context.get("followed_instruction_sequence"):
            return None
        if said_at is not None and state_at is not None and state_at - said_at > self.INSTRUCTION_FRESH_SECONDS:
            return None
        return self._words((event.get("payload") or {}).get("message")), sequence

    def _choose_action(self, world_state: dict, *, uses: dict | None = None,
                       now: float | None = None, context: dict | None = None) -> dict | None:
        if now is not None:
            self.ability_rules.observe_casts(world_state, now)
        pending = self._pending_instruction(world_state, context) if context is not None else None
        if pending is not None:
            message, sequence = pending
            candidates = {candidate.ability_id: candidate
                          for candidate in self.ability_rules.evaluate(world_state, uses=uses, now=now)}
            for raw in self.ability_rules.actionbar(world_state):
                candidate = candidates.get(raw.get("id", raw.get("spell_id")))
                name = self._words(raw.get("name"))
                if (candidate is not None and name.strip() and name in message
                        and set(candidate.rejection_reasons) <= self.INSTRUCTION_WAIVED):
                    context["followed_instruction_sequence"] = sequence
                    return dict(raw)
        return self.ability_rules.choose(world_state, uses=uses, now=now)

    def _invalid_target_recovery(self, state: ActiveSkillState,
                                 world_state: dict,
                                 original_reason: FailureReason = FailureReason.INVALID_TARGET) -> SkillResult | None:
        context = state.skill_context.setdefault("combat", {})
        count = int(context.get("target_recovery_attempts") or 0)
        if count >= 2:
            return None
        decision = self.target_recovery.assess(
            world_state, context.get("expected_guid"),
            quest_ids=state.intent.parameters.get("quest_ids") or ())
        state.phase = CombatPhase.RECOVER_TARGET.value
        if decision.kind == "REACQUIRE_INTENDED" and decision.anchor:
            commands = []
            if self.bindings is not None and self.bindings.contains("CLEARTARGET"):
                commands.append(Command("BIND", "CLEARTARGET"))
            commands.append(Command("CLICK", x=decision.anchor["x"],
                                    y=decision.anchor["y"]))
            context["target_recovery_attempts"] = count + 1
            context["target_recovery_pending"] = True
            return SkillResult(
                SkillStatus.RUNNING, commands=tuple(commands),
                metadata={"target_recovery": decision.kind,
                          "expected_guid": decision.intended_guid,
                          "attempt": count,
                          "evidence": decision.evidence})
        return SkillResult(
            SkillStatus.FAILURE, original_reason,
            retryable=True, replan_required=True,
            metadata={"target_recovery": decision.kind,
                      "expected_guid": decision.intended_guid,
                      "suggested_alternate_guid": decision.alternate_guid,
                      "evidence": decision.evidence})
