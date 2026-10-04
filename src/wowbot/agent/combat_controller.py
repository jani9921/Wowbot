"""Stateful combat policy used by the shared SkillRegistry.

This is not a second brain: it owns only combat skill state and action ranking.
The Planner still selects the COMBAT/DEFEND subgoal and the normal prediction
and verification path remains authoritative.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from .models import number
from .target_manager import TargetManager
from wowbot.skills.ability_rules import AbilityCandidate, AbilityRuleEngine


class CombatPhase(StrEnum):
    IDLE = "IDLE"
    ACQUIRE = "ACQUIRE"
    CONFIRM = "CONFIRM"
    APPROACH = "APPROACH"
    RANGE_CONTROL = "RANGE_CONTROL"
    ENGAGE = "ENGAGE"
    ROTATE = "ROTATE"
    MONITOR = "MONITOR"
    REPOSITION = "REPOSITION"
    TARGET_DEAD = "TARGET_DEAD"
    LOOT = "LOOT"
    VERIFY_OBJECTIVE = "VERIFY_OBJECTIVE"


@dataclass(frozen=True)
class HealthSample:
    at: float
    guid: str
    health: float
    maximum: float | None

class CombatController:
    def __init__(self, bindings=None):
        self.bindings = bindings
        self.phase = CombatPhase.IDLE
        self.target_guid = None
        self.health = deque(maxlen=32)
        self.uses: dict[object, int] = {}
        self.last_action = None
        self.survival_interrupts = 0
        self.multi_target_peak = 0
        self.range_failures = 0
        self.last_facing_recovery_at = None
        self.last_facing_recovery_target = None
        self.target_manager = TargetManager()
        self.target_candidate = None
        self.ability_candidates: list[AbilityCandidate] = []
        self.ability_rules = AbilityRuleEngine(bindings)

    def reset(self):
        bindings = self.bindings
        self.__init__(bindings)

    def observe(self, state: dict, at: float) -> CombatPhase:
        target = state.get("target") or {}
        # Candidate ranking is advisory WorldModel evidence only. The normal
        # TARGET skill remains the sole mechanism that may select a client
        # target, so combat policy cannot bypass the input boundary.
        candidates = list(state.get("nearby_attackable_entities") or state.get("threats") or ())
        if target.get("guid"):
            candidates.append({**target, "quest_relevance": target.get("quest_relevance", 1.),
                               "hostility": target.get("hostility", 1.),
                               "reachability": target.get("reachability", 1.),
                               "visibility": target.get("visibility", 1.)})
        self.target_candidate = self.target_manager.select(candidates)
        # TargetManager is evidence/lifecycle-only.  The selected-target addon
        # record is the sole authority for ACQUIRED/ENGAGED/DEAD transitions.
        self.target_manager.observe_selected(
            target,
            in_combat=bool(state.get("is_in_combat") or state.get("combat")),
            at=at,
            visual_tracks=state.get("visual_candidates") or (),
        )
        guid = target.get("guid")
        if not guid:
            self.phase = CombatPhase.ACQUIRE
            if self.target_manager.lifecycle.value == "LOST":
                self.target_guid = None
            return self.phase
        if self.target_guid and guid != self.target_guid:
            self.health.clear()
        self.target_guid = guid
        if target.get("dead", target.get("is_dead")):
            self.phase = CombatPhase.TARGET_DEAD
            return self.phase
        if target.get("attackable", target.get("is_attackable")) is not True:
            self.phase = CombatPhase.CONFIRM
            return self.phase
        hp, maximum = number(target.get("health")), number(target.get("max_health"))
        if hp is not None:
            self.health.append(HealthSample(at, str(guid), hp, maximum))
        nearby = state.get("nearby_attackable_entities") or state.get("threats") or []
        self.multi_target_peak = max(self.multi_target_peak, len(nearby))
        actions = [action for action in state.get("actionbar", [])
                   if action.get("kind") == "spell" and action.get("is_harmful") is True]
        if actions and all(action.get("in_range") is False for action in actions):
            self.phase = CombatPhase.APPROACH
        elif state.get("is_casting"):
            self.phase = CombatPhase.MONITOR
        elif self.last_action:
            self.phase = CombatPhase.ROTATE
        else:
            self.phase = CombatPhase.ENGAGE
        return self.phase

    def choose_action(self, state: dict, *, record: bool = False) -> dict | None:
        # actionbar itself only refreshes on the slow/paged snapshot (addon-
        # side: dirty.actionbar flips on bar-layout/spell-learned events,
        # never on cooldowns ticking down) -- during active combat this can
        # be several seconds stale. Live-confirmed 2026-09-12: an ability
        # kept getting re-selected and rejected by the client (still shown
        # usable, actually on cooldown) for the rest of a fight. actionbar_
        # fast (world.py fast_keys) refreshes the first 4 action buttons
        # every FAST packet -- keyed here by spell/action id rather than
        # slot position, since ACTIONBUTTON1-12 only reflect whichever bar
        # page is currently displayed (addon-side page gating).
        fresh_by_id = {}
        for entry in state.get("actionbar_fast") or []:
            if isinstance(entry, (list, tuple)) and len(entry) == 4:
                fresh_by_id[entry[0]] = {"is_usable": entry[1], "in_range": entry[2],
                                         "cooldown_remaining": entry[3]}
        updated_actions = []
        for action in state.get("actionbar", []):
            if not isinstance(action, dict):
                continue
            spell_id = action.get("id", action.get("spell_id"))
            fresh = fresh_by_id.get(spell_id)
            if fresh:
                action = {**action, **fresh}
            updated_actions.append(action)
        evaluation_state = {**state, "actionbar": updated_actions}
        self.ability_candidates = self.ability_rules.evaluate(evaluation_state, uses=self.uses)[:5]
        self.range_failures += sum("out_of_range" in item.rejection_reasons
                                   for item in self.ability_candidates)
        chosen = self.ability_rules.choose(evaluation_state, uses=self.uses)
        if chosen is None:
            return None
        spell_id = chosen.get("id", chosen.get("spell_id"))
        if record:
            self.uses[spell_id] = self.uses.get(spell_id, 0)+1
            health, maximum = number(state.get("health")), number(state.get("max_health"))
            health_fraction = health/maximum if health is not None and maximum else 1.
            if health_fraction <= .35 and spell_id in set(state.get("defensive_spell_ids", [])):
                self.survival_interrupts += 1
            self.last_action = {"spell_id": spell_id, "binding": chosen.get("action"),
                                "phase": self.phase.value}
        return chosen

    def needs_facing_recovery(self, state: dict) -> bool:
        message = str(state.get("ui_error") or "").casefold()
        facing_error = any(token in message for token in (
            "facing the wrong way", "target needs to be in front", "not facing",
            "rossz irányba", "előtted kell"))
        target = state.get("target") or {}
        if not facing_error or not target.get("guid"):
            return False
        now = number(state.get("monotonic_time")) or 0.
        # The addon intentionally keeps UI_ERROR_MESSAGE for three seconds.
        # After one half-turn, let the next combat decision try the ability
        # instead of reacting repeatedly to that same retained message.
        return not (self.last_facing_recovery_target == target.get("guid")
                    and self.last_facing_recovery_at is not None
                    and 0 <= now-self.last_facing_recovery_at < 2.)

    @staticmethod
    def recovery_reason(state: dict) -> str | None:
        """Compatibility projection of the canonical combat classifier."""
        from wowbot.runtime import FailureReason
        from wowbot.verification import classify_combat_error
        observation = dict(state)
        observation.setdefault("target", {"guid": "compat", "attackable": True})
        reason = classify_combat_error(observation)
        return {
            FailureReason.OUT_OF_RANGE: "OUT_OF_RANGE",
            FailureReason.LINE_OF_SIGHT: "LINE_OF_SIGHT",
            FailureReason.INVALID_TARGET: "INVALID_TARGET",
            FailureReason.FACING_WRONG_WAY: "FACING_INVALID",
        }.get(reason)

    def record_facing_recovery(self, state: dict):
        target = state.get("target") or {}
        self.last_facing_recovery_target = target.get("guid")
        self.last_facing_recovery_at = number(state.get("monotonic_time")) or 0.

    def snapshot(self) -> dict:
        trend = None
        if len(self.health) >= 2 and self.health[0].guid == self.health[-1].guid:
            trend = self.health[-1].health-self.health[0].health
        return {"phase": self.phase.value, "target_guid": self.target_guid,
                "target_health_trend": trend, "ability_uses": dict(self.uses),
                "last_action": self.last_action, "survival_interrupts": self.survival_interrupts,
                "multi_target_peak": self.multi_target_peak, "range_failures": self.range_failures,
                "last_facing_recovery_at": self.last_facing_recovery_at,
                "last_facing_recovery_target": self.last_facing_recovery_target,
                "target_candidate": (self.target_candidate.entity_id if self.target_candidate else None),
                "target_candidate_score": (self.target_candidate.total_score if self.target_candidate else None),
                "target_lifecycle": self.target_manager.lifecycle.value,
                "target_manager": self.target_manager.snapshot(),
                "recovery_reason": self.recovery_reason({"ui_error": self.last_action.get("ui_error")}) if self.last_action else None,
                "ability_candidates": [{"spell_id": item.ability_id, "rule_id": item.rule_id,
                                        "binding": item.binding,
                                        "eligible": item.eligible, "score": item.score,
                                        "rejection_reasons": item.rejection_reasons}
                                       for item in self.ability_candidates]}
