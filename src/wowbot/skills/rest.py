"""Bounded, stationary out-of-combat regeneration (REV4 survival supplement).

Natural regeneration needs no input.  Eating does: once per attempt, while
standing still out of combat, a ready action-bar FOOD button (identified from
the client DB2, agent/consumables.py) is pressed; without one the rest stays
input-free.  No bag click is invented.  Success is observed own health at the
finish threshold, never a key press or elapsed time. No observed rise within NO_REGEN_SECONDS ends it (bounded
reevaluation, no rest/pull loop); a threat ends it as a preemption.
"""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus


class RestPhase(StrEnum):
    MONITOR = "MONITOR"
    EAT = "EAT"
    VERIFY_HEALTH = "VERIFY_HEALTH"


class RestSkill:
    NO_REGEN_SECONDS = 10.

    def __init__(self, bindings=None, consumables=None) -> None:
        from wowbot.agent.consumables import ConsumableCatalog
        self.bindings = bindings
        self.consumables = consumables if consumables is not None else ConsumableCatalog()

    @staticmethod
    def _can_eat(world_state: dict) -> bool:
        movement = world_state.get("movement") or {}
        return not (world_state.get("is_in_combat") or world_state.get("is_mounted") is True
                    or world_state.get("in_vehicle") is True or world_state.get("on_taxi") is True
                    or world_state.get("is_casting") or world_state.get("is_channeling")
                    or movement.get("moving") is True or movement.get("falling") is True
                    or movement.get("flying") is True or movement.get("swimming") is True
                    or world_state.get("loading"))

    def _eat(self, state: ActiveSkillState, world_state: dict, context: dict, fraction, now: float):
        if context.get("food_checked") or fraction is None or fraction >= float(context["end_fraction"]):
            return None
        if not self._can_eat(world_state):
            return None
        context["food_checked"] = True
        from wowbot.agent.consumables import usable_consumable
        food = usable_consumable(world_state, self.consumables, "FOOD", self.bindings)
        if food is None:
            return None
        context.update(food_item_id=food["item_id"], food_used_at=now, last_rise_at=now)
        state.phase = RestPhase.EAT.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", food["binding"]),),
                           evidence=("food_used",), metadata={"food_item_id": food["item_id"]})

    def begin(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        from wowbot.agent.survival_planning import REST_END_FRACTION, own_health_fraction
        parameters = state.intent.parameters
        fraction = own_health_fraction(world_state)
        state.skill_context["rest"] = {
            "started_at": now, "best_fraction": fraction, "last_rise_at": now,
            "end_fraction": number(parameters.get("end_fraction")) or REST_END_FRACTION}
        state.phase = RestPhase.MONITOR.value
        return SkillResult(SkillStatus.RUNNING, evidence=("stationary_regeneration_started",))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        from wowbot.agent.survival_planning import own_health_fraction, threatened
        context = state.skill_context.setdefault("rest", {"started_at": now, "last_rise_at": now,
                                                          "best_fraction": None, "end_fraction": .9})
        if world_state.get("is_dead") or world_state.get("is_ghost"):
            return SkillResult(SkillStatus.FAILURE, FailureReason.PLAYER_DEAD, replan_required=True)
        if threatened(world_state):
            # A preemption, not a failed rest: the combat policy takes over.
            return SkillResult(SkillStatus.CANCELLED, FailureReason.INTERRUPTED, replan_required=True,
                               evidence=("rest_interrupted_by_threat",))
        state.phase = RestPhase.VERIFY_HEALTH.value
        fraction = own_health_fraction(world_state)
        eating = self._eat(state, world_state, context, fraction, now)
        if eating is not None:
            return eating
        if fraction is not None:
            if fraction >= float(context["end_fraction"]):
                return SkillResult(SkillStatus.SUCCESS,
                                   evidence=("own_health_regenerated", f"health_fraction={fraction:.3f}"))
            best = context.get("best_fraction")
            if best is None or fraction > best + 1e-6:
                context.update(best_fraction=fraction, last_rise_at=now)
        if now - float(context["last_rise_at"]) >= self.NO_REGEN_SECONDS:
            return SkillResult(SkillStatus.FAILURE, FailureReason.NO_PROGRESS, retryable=True,
                               replan_required=True, evidence=("no_observed_regeneration",),
                               metadata={"reason": "no_health_regeneration",
                                         "best_fraction": context.get("best_fraction")})
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.TIMEOUT, retryable=True,
                               replan_required=True, metadata={"reason": "rest_window_expired"})
        state.phase = RestPhase.MONITOR.value
        return SkillResult(SkillStatus.RUNNING)
