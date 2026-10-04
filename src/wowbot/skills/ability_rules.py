"""Pure M2 ability definitions and explainable rule evaluation.

The rule engine deliberately returns a decision only.  It cannot send input,
advance combat state or infer target identity from vision.  ``CombatSkill``
owns the active attempt and ``CombatController`` owns diagnostic projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from wowbot.agent.models import number
from .combat_ability_catalog import enrich_ability


class AbilityTag(StrEnum):
    OFFENSIVE = "OFFENSIVE"
    DEFENSIVE = "DEFENSIVE"
    INTERRUPT = "INTERRUPT"
    MOVEMENT = "MOVEMENT"
    UTILITY = "UTILITY"
    AOE = "AOE"
    HEAL = "HEAL"
    RESOURCE = "RESOURCE"
    EXECUTE = "EXECUTE"


@dataclass(frozen=True, slots=True)
class AbilityDefinition:
    ability_id: object
    name: str | None
    binding: str | None
    min_range: float | None = None
    max_range: float | None = None
    cast_time_ms: int | None = None
    channel_time_ms: int | None = None
    gcd_ms: int | None = None
    cooldown_ms: int | None = None
    resource_cost: float = 0.0
    requires_target: bool = True
    requires_facing: bool = True
    requires_los: bool = True
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AbilityRuntimeState:
    ready_belief: float
    cooldown_remaining_estimate: float | None
    resource_available_belief: float
    in_range_belief: float
    facing_belief: float
    los_belief: float
    usable_confidence: float
    last_attempt_at: float | None = None
    last_result: str | None = None


@dataclass(frozen=True, slots=True)
class AbilityRule:
    rule_id: str
    ability_id: object
    priority: float
    preconditions: tuple[object, ...] = ()
    forbidden_conditions: tuple[object, ...] = ()
    expected_postconditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AbilityCandidate:
    ability_id: object
    rule_id: str
    binding: str | None
    eligible: bool
    score: float
    rejection_reasons: tuple[str, ...]
    definition: AbilityDefinition
    runtime_state: AbilityRuntimeState
    rule: AbilityRule


class AbilityRuleEngine:
    """Evaluate action-bar telemetry into an explainable, stable ranking."""

    # Live 2026-10-02: Slam was pressed once in a whole session, Shield Slam
    # ~100 times.  Retail 12 hides spell cooldowns in combat (secret values,
    # exported as 0 = ready) and IsUsableAction ignores cooldowns, so Shield
    # Slam (priority 40) always outranked Slam (20) even while cooling down.
    # Our own successful casts are observed facts: their catalog cooldown is
    # tracked locally, and a "not ready" client answer blocks briefly.
    NOT_READY_BLOCK_SECONDS = 2.0

    def __init__(self, bindings=None) -> None:
        self.bindings = bindings
        self.local_ready_at: dict = {}
        self._cast_marker = None
        self._event_sequence = None

    def _start_cooldown(self, spell_id, started_at: float) -> None:
        try:
            key = int(spell_id)
        except (TypeError, ValueError):
            return
        cooldown_ms = number(enrich_ability({"id": key}).get("cooldown_ms"))
        if cooldown_ms:
            ready_at = started_at + cooldown_ms / 1000.
            self.local_ready_at[key] = max(self.local_ready_at.get(key, ready_at), ready_at)

    def observe_casts(self, state: Mapping, now: float) -> None:
        """Start local cooldowns for newly observed own successful casts."""
        spell, at = state.get("combat_last_spell_id"), number(state.get("combat_last_cast_at"))
        if spell not in (None, 0) and at is not None and (spell, at) != self._cast_marker:
            self._cast_marker = (spell, at)
            self._start_cooldown(spell, now)
        stamp = number(state.get("timestamp"))
        newest = self._event_sequence
        for event in state.get("events") or ():
            if not isinstance(event, Mapping) or event.get("event_type") != "SPELLCAST_SUCCEEDED":
                continue
            if (event.get("payload") or {}).get("unit") == "pet":
                continue      # addon 0.9.50 also exports pet casts; not our cooldowns
            sequence = number(event.get("sequence"))
            if sequence is None:
                continue
            newest = sequence if newest is None else max(newest, sequence)
            # The first batch seen only sets the baseline: old casts are not news.
            if self._event_sequence is None or sequence <= self._event_sequence:
                continue
            event_stamp = number(event.get("timestamp"))
            late = max(0., stamp - event_stamp) if None not in (stamp, event_stamp) else 0.
            self._start_cooldown((event.get("payload") or {}).get("spell_id"), now - late)
        self._event_sequence = newest

    def note_not_ready(self, spell_id, now: float) -> None:
        try:
            key = int(spell_id)
        except (TypeError, ValueError):
            return
        ready_at = now + self.NOT_READY_BLOCK_SECONDS
        self.local_ready_at[key] = max(self.local_ready_at.get(key, ready_at), ready_at)

    def _with_local_cooldowns(self, actions: list, now: float | None) -> list:
        ready = getattr(self, "local_ready_at", None)
        if now is None or not ready:
            return actions
        output = []
        for action in actions:
            try:
                remaining = ready.get(int(action.get("id", action.get("spell_id"))), now) - now
            except (TypeError, ValueError):
                remaining = 0.
            if remaining > .1:
                reported = number(action.get("cooldown_remaining")) or 0.
                action = {**action, "cooldown_remaining": max(reported, remaining),
                          "local_cooldown": True}
            output.append(action)
        return output

    @staticmethod
    def actionbar(state: Mapping) -> list[Mapping]:
        """Overlay FAST readiness/range facts on stable action identities."""
        fresh_by_id = {}
        for entry in state.get("actionbar_fast") or ():
            if isinstance(entry, (list, tuple)) and len(entry) >= 4:
                fresh_by_id[entry[0]] = {
                    "is_usable": entry[1], "in_range": entry[2],
                    "cooldown_remaining": entry[3],
                }
            elif isinstance(entry, Mapping):
                spell_id = entry.get("id", entry.get("spell_id"))
                if spell_id is not None:
                    fresh_by_id[spell_id] = {
                        key: entry.get(key) for key in
                        ("is_usable", "in_range", "cooldown_remaining")
                        if key in entry
                    }
        output = []
        for raw in state.get("actionbar") or ():
            if not isinstance(raw, Mapping):
                continue
            spell_id = raw.get("id", raw.get("spell_id"))
            output.append(enrich_ability({**dict(raw), **fresh_by_id.get(spell_id, {})}))
        return output

    @staticmethod
    def definition(action: Mapping) -> AbilityDefinition:
        spell_id = action.get("id", action.get("spell_id"))
        raw_tags = action.get("tags") or ()
        tags = tuple(str(tag).upper() for tag in raw_tags if tag)
        return AbilityDefinition(
            ability_id=spell_id,
            name=action.get("name"),
            binding=action.get("action"),
            min_range=number(action.get("min_range")),
            max_range=number(action.get("max_range")),
            cast_time_ms=_milliseconds(action.get("cast_time_ms")),
            channel_time_ms=_milliseconds(action.get("channel_time_ms")),
            gcd_ms=_milliseconds(action.get("gcd_ms")),
            cooldown_ms=_milliseconds(action.get("cooldown_ms")),
            resource_cost=number(action.get("resource_cost")) or 0.0,
            requires_target=action.get("requires_target", action.get("is_harmful") is True) is not False,
            requires_facing=action.get("requires_facing", action.get("is_harmful") is True) is not False,
            requires_los=action.get("requires_los", action.get("is_harmful") is True) is not False,
            tags=tags,
        )

    @staticmethod
    def runtime_state(action: Mapping, state: Mapping,
                      definition: AbilityDefinition) -> AbilityRuntimeState:
        cooldown = number(action.get("cooldown_remaining"))
        usable = action.get("is_usable")
        ready = (1.0 if usable is True and cooldown is not None and cooldown <= .1
                 else 0.0 if usable is False or cooldown is not None and cooldown > .1
                 else 0.0)
        available_resource = number(state.get("power"))
        resource = (1.0 if available_resource is not None
                    and available_resource >= definition.resource_cost
                    else 0.0 if available_resource is not None else .5)
        in_range = _belief(action.get("in_range"), unknown=.5)
        facing = _belief(action.get("facing", state.get("target_facing")), unknown=.5)
        los = _belief(action.get("has_los", state.get("target_has_los")), unknown=.5)
        required = [ready, resource]
        if definition.requires_target:
            required.append(1.0 if (state.get("target") or {}).get("guid") else 0.0)
        if definition.max_range is not None or definition.min_range is not None:
            required.append(in_range)
        if definition.requires_facing:
            required.append(facing)
        if definition.requires_los:
            required.append(los)
        return AbilityRuntimeState(
            ready_belief=ready,
            cooldown_remaining_estimate=cooldown,
            resource_available_belief=resource,
            in_range_belief=in_range,
            facing_belief=facing,
            los_belief=los,
            usable_confidence=min(required) if required else 0.0,
            last_attempt_at=number(action.get("last_attempt_at")),
            last_result=(str(action.get("last_result"))
                         if action.get("last_result") is not None else None),
        )

    @staticmethod
    def rule(action: Mapping, definition: AbilityDefinition) -> AbilityRule:
        return AbilityRule(
            rule_id=str(action.get("rule_id") or f"ability:{definition.ability_id}"),
            ability_id=definition.ability_id,
            priority=number(action.get("combat_priority")) or 0.0,
            preconditions=tuple(action.get("preconditions") or ()),
            forbidden_conditions=tuple(action.get("forbidden_conditions") or ()),
            expected_postconditions=tuple(
                str(value) for value in (action.get("expected_postconditions") or ()) if value),
        )

    def evaluate(self, state: Mapping, *, uses: Mapping[object, int] | None = None,
                 now: float | None = None) -> list[AbilityCandidate]:
        """Return all action-bar spells, including ruled-out candidates.

        Candidate score is only a deterministic preference.  A later skill
        still verifies the cast result before considering a combat action done.
        """
        configured = set(state.get("combat_spell_ids") or ())
        defensive = set(state.get("defensive_spell_ids") or ())
        target = state.get("target") or {}
        target_present = bool(target.get("guid"))
        target_attackable = target.get("attackable", target.get("is_attackable")) is True
        health, maximum = number(state.get("health")), number(state.get("max_health"))
        health_fraction = health / maximum if health is not None and maximum else 1.0
        available_resource = number(state.get("power"))
        usage = uses or {}
        actions = self._with_local_cooldowns(self.actionbar(state), now)
        # IsActionInRange on a short-range offensive ability is stronger
        # evidence that the selected target is already in melee than a stale
        # Charge usability bit.  Movement abilities are openers, not the
        # complete rotation.
        melee_range_confirmed = any(
            action.get("kind") == "spell"
            and action.get("is_harmful") is True
            and action.get("in_range") is True
            and (self.definition(action).max_range or 0.) <= 5.
            and "MOVEMENT" not in self.definition(action).tags
            for action in actions if isinstance(action, Mapping)
        )
        output: list[AbilityCandidate] = []
        for order, raw in enumerate(actions):
            if not isinstance(raw, Mapping):
                continue
            action = dict(raw)
            definition = self.definition(action)
            runtime_state = self.runtime_state(action, state, definition)
            rule = self.rule(action, definition)
            spell_id = definition.ability_id
            is_defensive = health_fraction <= .35 and spell_id in defensive
            offensive = action.get("is_harmful") is True or "OFFENSIVE" in definition.tags
            allowed = offensive or spell_id in configured or is_defensive
            reasons: list[str] = []
            if action.get("kind") != "spell":
                reasons.append("not_spell")
            if not allowed:
                reasons.append("not_combat_allowed")
            if definition.requires_target and not target_present:
                reasons.append("target_missing")
            if offensive and target_present and not target_attackable:
                reasons.append("target_not_attackable")
            if action.get("is_usable") is not True:
                reasons.append("not_usable")
            if action.get("in_range") is False:
                reasons.append("out_of_range")
            cooldown = number(action.get("cooldown_remaining"))
            # Cooldown telemetry is a readiness belief, not a permission to
            # guess. An omitted/secret value must fail closed at the selected
            # bindings boundary just as an explicit cooldown does.
            if cooldown is None:
                reasons.append("cooldown_unknown")
            elif cooldown > .1:
                reasons.append("cooldown")
            if not definition.binding:
                reasons.append("binding_missing")
            elif self.bindings and not self.bindings.contains(definition.binding):
                reasons.append("binding_not_configured")
            if available_resource is not None and definition.resource_cost > available_resource:
                reasons.append("insufficient_resource")
            if "MOVEMENT" in definition.tags:
                if int(usage.get(spell_id) or 0) >= 1:
                    reasons.append("movement_opener_already_used")
                if melee_range_confirmed:
                    reasons.append("melee_range_confirmed")
            for condition in rule.preconditions:
                if not _condition_matches(condition, state, action):
                    reasons.append(f"precondition_failed:{_condition_name(condition)}")
            for condition in rule.forbidden_conditions:
                if _condition_matches(condition, state, action):
                    reasons.append(f"forbidden_condition:{_condition_name(condition)}")
            priority = rule.priority
            # Preserve a stable score in diagnostics. Tie-break behavior is
            # applied by ``choose`` and is visible through action-bar order.
            score = priority + (1000.0 if is_defensive else 0.0) - .001 * usage.get(spell_id, 0) - .000001 * order
            output.append(AbilityCandidate(spell_id, rule.rule_id,
                                           definition.binding, not reasons,
                                           score if not reasons else 0.0,
                                           tuple(reasons), definition, runtime_state, rule))
        return sorted(output, key=lambda item: (-item.score, str(item.ability_id)))

    def choose(self, state: Mapping, *, uses: Mapping[object, int] | None = None,
               now: float | None = None) -> Mapping | None:
        """Return the original action dictionary for the top eligible rule."""
        candidates = self.evaluate(state, uses=uses, now=now)
        for candidate in candidates:
            if not candidate.eligible:
                continue
            for raw in self.actionbar(state):
                if isinstance(raw, Mapping) and raw.get("id", raw.get("spell_id")) == candidate.ability_id:
                    return dict(raw)
        return None


def _milliseconds(value: object) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None and parsed >= 0 else None


def _belief(value: object, *, unknown: float) -> float:
    if value is True:
        return 1.0
    if value is False:
        return 0.0
    parsed = number(value)
    return min(1., max(0., parsed)) if parsed is not None else unknown


def _condition_matches(condition: object, state: Mapping,
                       action: Mapping) -> bool:
    if isinstance(condition, Mapping):
        scope = action if str(condition.get("scope") or "state").lower() == "action" else state
        field = str(condition.get("field") or "")
        if not field:
            return False
        actual = scope.get(field)
        if "equals" in condition:
            return actual == condition.get("equals")
        return bool(actual)
    name = str(condition)
    if name.startswith("action:"):
        return bool(action.get(name.split(":", 1)[1]))
    if name.startswith("state:"):
        return bool(state.get(name.split(":", 1)[1]))
    return bool(state.get(name, action.get(name)))


def _condition_name(condition: object) -> str:
    if isinstance(condition, Mapping):
        return str(condition.get("field") or "unnamed")
    return str(condition)
