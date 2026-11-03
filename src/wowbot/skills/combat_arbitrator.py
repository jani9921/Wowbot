"""Per-tick combat action choice (REV4 CombatSkill split).

Moved out of ``CombatSkill`` (SRC_MELY_AUDIT 4.4: CombatArbitrator) with an
unchanged order of decisions for the current, identity-checked target:

1. no rotation into a vehicle override (typed UNSUPPORTED_MECHANIC),
2. wait while casting, an exact facing pre-turn,
3. the one-time "use X on the target" opener,
4. proactive visual follow (legacy profile only), the client GCD, never two
   decisions from the same fast sample,
5. the best usable ability; else a mobility settle, the bounded auto-attack
   fallback (INTERACTTARGET / STARTATTACK / a verified hover), or the
   out-of-range recovery / typed OUT_OF_RANGE.

The skill keeps the FSM, the attempt state (skill context), the ability rules
and every collaborator; this owns no state, no target and no movement.
"""
from __future__ import annotations

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus


class CombatArbitrator:
    def __init__(self, skill) -> None:
        self.skill = skill

    def next_action(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        from .combat import CombatPhase, rotation_allowed
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
        preturn = self.skill._exact_facing_turn(state, world_state, now,
                                          threshold=self.skill.FACE_PRETURN_RADIANS, attack=False)
        if preturn is not None:
            return preturn
        if not context.get("opener_done"):
            from wowbot.agent.packet_entity_facts import use_on_target_opener
            context["opener_done"] = True
            if use_on_target_opener(world_state, context.get("expected_guid")):
                # "Use the X on a <mob>" quests (Proto-Fight's harpoon): F7 on
                # the selected unit first, then the rotation.
                context["last_cast_at"] = now
                state.phase = CombatPhase.VERIFY_ABILITY.value
                return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),),
                                   metadata={"opener": "INTERACTTARGET"})
        # The launch path can only dispatch direct commands; navigation
        # metadata is composed by CombatRuntimeRunner on subsequent control
        # ticks.  Cast the first probe normally, then keep the committed
        # target centred during its GCD and all later rotation steps.
        visual_follow = (self.skill._visual_follow_request(state, world_state, now)
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
        sample = self.skill._combat_sample_key(world_state)
        if (sample is not None and context.get("last_action_sample") is not None
                and sample == context.get("last_action_sample")):
            # Never make a second combat decision from the exact same FAST
            # sample.  Live logs showed Charge being dispatched twice while
            # its pre-cast readiness state was still being replayed.
            state.phase = CombatPhase.VERIFY_ABILITY.value
            return SkillResult(SkillStatus.RUNNING)
        uses = context.setdefault("ability_uses", {})
        action = self.skill._choose_action(world_state, uses=uses, now=now, context=context)
        if action is None:
            from wowbot.combat.mobility import settling_deadline
            deadline=settling_deadline(world_state,self.skill.ability_rules.actionbar(world_state),
                                       context.get('expected_guid'),now)
            if deadline is not None:
                # A successful Charge can precede its actual arrival/range
                # update. Keep this attempt; do not start walking or fail it
                # during that short, original-cast-time-bounded transition.
                return SkillResult(SkillStatus.RUNNING,
                                   metadata={'mobility_settling_until':deadline})
            auto_attack = self.skill._auto_attack_fallback(state, world_state, now)
            if auto_attack is not None:
                return auto_attack
            harmful = [row for row in self.skill.ability_rules.actionbar(world_state)
                       if row.get("kind") == "spell" and row.get("is_harmful") is True]
            if harmful and all(row.get("in_range") is False for row in harmful):
                visual_approach = self.skill._visual_range_approach_request(
                    state, world_state, now)
                if visual_approach is not None:
                    return visual_approach
                recovery = self.skill._local_recovery_request(
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
        definition = self.skill.ability_rules.definition(action)
        from wowbot.combat.positioning.range import engagement_range
        context["desired_range"] = engagement_range(self.skill.ability_rules.actionbar(world_state),definition)
        context["ability_attempt"] = self.skill.error_correlation.start(
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

    def auto_attack_fallback(self, state: ActiveSkillState,
                             world_state: dict, now: float) -> SkillResult | None:
        """Start melee auto-attack when no rage/cooldown ability is usable.

        A right click is allowed only on a fresh screen position belonging to
        the exact addon-selected hostile GUID.  It is dispatched once per
        COMBAT attempt; later ticks keep evaluating Slam/Shield Slam as rage
        and cooldown telemetry changes.
        """
        from .combat import CombatPhase
        context = state.skill_context.setdefault("combat", {})
        if int(context.get("auto_attack_dispatches") or 0) >= 1:
            return None
        expected = str(context.get("expected_guid") or "")
        target = world_state.get("target") or {}
        if (not expected or str(target.get("guid") or "") != expected
                or target.get("attackable", target.get("is_attackable")) is not True
                or target.get("dead", target.get("is_dead")) is True):
            return None
        actions = self.skill.ability_rules.actionbar(world_state)
        melee_range = False
        for action in actions:
            if not isinstance(action, dict) or action.get("is_harmful") is not True:
                continue
            definition = self.skill.ability_rules.definition(action)
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
        if self.skill._interact_attacks_expected(context, world_state, now):
            # Live 2026-10-03 13:37: the goat overlapped the character and the
            # right click at its box landed on our own model; no attack for
            # 15 s.  Interact-with-target attacks the selected unit itself.
            context["auto_attack_started_at"] = now
            context["auto_attack_dispatches"] = 1
            context["last_action_sample"] = self.skill._combat_sample_key(world_state)
            state.phase = CombatPhase.EXECUTE_ABILITY.value
            return SkillResult(
                SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),),
                metadata={"auto_attack_fallback": True, "expected_guid": expected,
                          "reason": "no_usable_melee_ability", "via": "INTERACTTARGET"})
        if self.skill.bindings is not None and self.skill.bindings.contains("STARTATTACK"):
            # Live 2026-10-21 15:24:47-50: no rage, and the soft-interact unit
            # was the first whelp's corpse, so F7 was rightly withheld and
            # nothing attacked for 3 s.  A Start Attack key the user bound
            # acts on the selected unit only.
            context["auto_attack_started_at"] = now
            context["auto_attack_dispatches"] = 1
            context["last_action_sample"] = self.skill._combat_sample_key(world_state)
            state.phase = CombatPhase.EXECUTE_ABILITY.value
            return SkillResult(
                SkillStatus.RUNNING, commands=(Command("BIND", "STARTATTACK"),),
                metadata={"auto_attack_fallback": True, "expected_guid": expected,
                          "reason": "no_usable_melee_ability", "via": "STARTATTACK"})
        screen = target.get("screen_position") or {}
        x, y = number(screen.get("x")), number(screen.get("y"))
        sampled = number(screen.get("sample_time", screen.get("observed_at")))
        from .hover_confirm import hover_confirm_step, pointer_acquisition_retired
        if (x is None or y is None or not .01 < x < .99 or not .01 < y < .99
                or (sampled is not None and not 0. <= now-sampled <= .75)
                or pointer_acquisition_retired(world_state)):
            return None
        hover = context.setdefault("auto_attack_hover", {
            "hover_point": (x, y), "hovers": 0,
            "track_id": screen.get("track_id") or target.get("visual_track_id")})
        outcome, commands = hover_confirm_step(
            hover, world_state, now, expected_guid=expected, click_button="RIGHT",
            deadline=state.attempt.deadline)
        if outcome == "CLICK":
            context["auto_attack_started_at"] = now
            context["auto_attack_dispatches"] = 1
            context["last_action_sample"] = self.skill._combat_sample_key(world_state)
        elif outcome not in {"HOVER", "WAIT"}:
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        state.phase = CombatPhase.EXECUTE_ABILITY.value
        return SkillResult(
            SkillStatus.RUNNING,
            commands=commands,
            metadata={"auto_attack_fallback": True,
                      "expected_guid": expected,
                      "reason": "no_usable_melee_ability"})
