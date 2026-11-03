"""Combat facing commands (REV4 CombatSkill split).

Moved out of ``CombatSkill`` (SRC_MELY_AUDIT 4.4: FacingController).  Given the
skill's GUID-checked bearing error to the selected target
(``CombatSkill._target_bearing_error``, the identity boundary stays on the
skill), it issues the bounded facing corrections:

* one exact keyboard turn toward the target's world point (bounded to one
  350 ms input step, settled between turns),
* a bounded facing sweep that probes with a known harmful action (or the
  verified INTERACTTARGET auto-attack), never a guessed binding, ending when
  the client stops answering "not in front" or the target is on screen.

The attempt state stays in the skill context; the limits and the bindings stay
on the skill so they remain overridable per skill.  It owns no target and no
movement controller.
"""
from __future__ import annotations

import math

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus


class CombatFacingController:
    def __init__(self, skill) -> None:
        self.skill = skill

    def exact_turn(self, state: ActiveSkillState, world_state: dict, now: float, *,
                   threshold: float, attack: bool) -> SkillResult | None:
        from .combat import CombatPhase
        context = state.skill_context.setdefault("combat", {})
        error = self.skill._target_bearing_error(world_state, context.get("expected_guid"))
        if error is None or abs(error) <= threshold:
            return None
        turn = "TURNLEFT" if error > 0 else "TURNRIGHT"
        if self.skill.bindings is not None and not self.skill.bindings.contains(turn):
            return None
        if now - float(context.get("exact_turn_at", -math.inf)) < self.skill.FACE_TURN_SETTLE_SECONDS:
            return SkillResult(SkillStatus.RUNNING, metadata={"facing_turn_settling": True})
        context["exact_turn_at"] = now
        state.phase = CombatPhase.RECOVER_FACING.value
        # One input step is at most 350 ms (live 17:20:07 rejected a longer
        # turn); a larger error is finished on the next tick.
        commands = [Command("BIND", turn, max(.05, min(.34, abs(error)/self.skill.KEY_TURN_RATE*.9)))]
        if attack:
            binding = self.sweep_attack_binding(context, world_state, now)
            if binding is not None:
                commands.append(Command("BIND", binding))
        return SkillResult(SkillStatus.RUNNING, commands=tuple(commands),
                           metadata={"facing_turn_radians": round(error, 3),
                                     "facing_turn_source": "TARGET_WORLD_POSITION"})

    @staticmethod
    def facing_text(world_state: dict) -> bool:
        text = str(world_state.get("ui_error") or "").casefold()
        return "front" in text or "facing" in text

    def interact_attacks_expected(self, context: dict, world_state: dict, now: float) -> bool:
        from wowbot.runtime.skill_identity import check_interaction_recipient
        expected = context.get("expected_guid")
        return bool(expected and (world_state.get("target") or {}).get("guid") == expected
                    and self.skill.bindings is not None and self.skill.bindings.contains("INTERACTTARGET")
                    and check_interaction_recipient({"guid": expected}, world_state, now))

    def sweep_attack_binding(self, context: dict, world_state: dict, now: float) -> str | None:
        if self.interact_attacks_expected(context, world_state, now):
            return "INTERACTTARGET"
        # Probe facing with a known harmful action, never an F7 directed at
        # a nearby NPC/game object. No guessed binding when none is known.
        harmful = [row.get("action") for row in self.skill.ability_rules.actionbar(world_state)
                   if row.get("kind") == "spell" and row.get("is_harmful") is True
                   and row.get("action") and (self.skill.bindings is None
                        or self.skill.bindings.contains(row["action"]))]
        previous = context.get("last_binding")
        return previous if previous in harmful else next(iter(harmful), None)

    def sweep_step(self, state: ActiveSkillState, world_state: dict,
                   now: float) -> SkillResult:
        from .combat import CombatPhase
        context = state.skill_context.setdefault("combat", {})
        sweep = context["facing_sweep"]
        if int(sweep.get("steps") or 0) >= self.skill.FACING_SWEEP_STEPS:
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
        commands = [Command("BIND", sweep["direction"], self.skill.FACING_SWEEP_TURN_SECONDS)]
        binding = self.sweep_attack_binding(context, world_state, now)
        if binding is not None:
            commands.append(Command("BIND", binding))
        return SkillResult(
            SkillStatus.RUNNING,
            commands=tuple(commands),
            metadata={"facing_sweep_step": sweep["steps"]})

    def continue_sweep(self, state: ActiveSkillState, world_state: dict,
                       now: float) -> SkillResult | None:
        """Next sweep step on a newer facing error; end it when quiet/visible."""
        context = state.skill_context.setdefault("combat", {})
        sweep = context.get("facing_sweep")
        if not sweep:
            return None
        target = world_state.get("target") or {}
        if (str(target.get("guid") or "") != str(context.get("expected_guid") or "")
                or target.get("dead", target.get("is_dead"))
                or self.skill._target_on_screen(target, now)):
            context.pop("facing_sweep", None)
            return None
        since = now - float(sweep.get("last_step_at") or now)
        if since < self.skill.FACING_SWEEP_SETTLE_SECONDS:
            return SkillResult(SkillStatus.RUNNING, metadata={"facing_sweep_settling": True})
        sequence = number(world_state.get("ui_error_sequence"))
        previous = number(sweep.get("error_sequence"))
        newer = sequence is not None and (previous is None or sequence > previous)
        if newer and self.facing_text(world_state):
            return self.sweep_step(state, world_state, now)
        if since >= self.skill.FACING_SWEEP_QUIET_SECONDS:
            # No new "not in front" answer to the last attack key: facing.
            context.pop("facing_sweep", None)
            context.pop("facing_recovery_started_at", None)
            return None
        return SkillResult(SkillStatus.RUNNING, metadata={"facing_sweep_waiting": True})
