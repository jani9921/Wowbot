"""Bounded association between a dispatched ability and client error evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from wowbot.agent.models import number


@dataclass(frozen=True)
class AbilityAttempt:
    attempt_id: str
    dispatched_at: float
    prior_error: str
    ability_id: object | None = None
    binding: str | None = None
    target_guid: str | None = None
    prior_event_sequence: int | None = None
    prior_cast_sequence: int | None = None
    prior_ui_error_sequence: int | None = None
    prior_resource: float | None = None
    prior_target_health: float | None = None


@dataclass(frozen=True)
class AbilityCorrelation:
    attempt_id: str
    within_window: bool
    ui_errors: tuple[str, ...] = ()
    addon_failures: tuple[str, ...] = ()
    cast_failures: tuple[str, ...] = ()
    cast_changed: bool = False
    resource_changed: bool = False
    target_damage: bool = False
    no_effect_evidence: tuple[str, ...] = ()

    @property
    def failure_evidence(self) -> tuple[str, ...]:
        return self.ui_errors + self.addon_failures + self.cast_failures + self.no_effect_evidence


class ActionErrorCorrelator:
    """Accept only new, in-window UI error evidence for a cast attempt.

    UI error text can remain exported long after the action which produced it.
    A text value already present at dispatch is therefore never attributed to
    the new cast without a newer timestamp/sequence supplied by telemetry.
    """

    def __init__(self, window_seconds: float = 1.2):
        self.window_seconds = float(window_seconds)

    @staticmethod
    def _text(state: dict) -> str:
        return str((state or {}).get("ui_error") or "").strip()

    def start(self, state: dict, now: float, *, ability_id: object | None = None,
              binding: str | None = None) -> AbilityAttempt:
        target = state.get("target") or {}
        return AbilityAttempt(
            str(uuid4()), float(now), self._text(state), ability_id, binding,
            str(target.get("guid")) if target.get("guid") else None,
            _integer(state.get("event_sequence")), _integer(state.get("cast_sequence")),
            _integer(state.get("ui_error_sequence")),
            number(state.get("power")), number(target.get("health")))

    def matches(self, attempt: AbilityAttempt | None, state: dict, now: float) -> bool:
        if attempt is None:
            return False
        if not 0 <= float(now) - attempt.dispatched_at <= self.window_seconds:
            return False
        current = self._text(state)
        if not current:
            return False
        sequence = _integer(state.get("ui_error_sequence"))
        if sequence is not None:
            # Authoritative across processes: addon GetTime() and Python's
            # monotonic clock do not need to share an epoch.
            prior = attempt.prior_ui_error_sequence
            return prior is None or sequence > prior
        timestamp = number(state.get("ui_error_at"))
        if timestamp is not None:
            return attempt.dispatched_at <= timestamp <= float(now)
        return current != attempt.prior_error

    def correlate(self, attempt: AbilityAttempt | None, state: Mapping[str, Any],
                  now: float) -> AbilityCorrelation | None:
        """Correlate only evidence inside this attempt's bounded time window."""
        if attempt is None:
            return None
        elapsed = float(now) - attempt.dispatched_at
        within = 0. <= elapsed <= self.window_seconds + 1e-9
        if not within:
            return AbilityCorrelation(attempt.attempt_id, False)
        ui_errors = (self._text(dict(state)),) if self.matches(attempt, dict(state), now) else ()
        addon_failures: list[str] = []
        cast_failures: list[str] = []
        for event in state.get("events") or ():
            if not isinstance(event, Mapping) or not _event_matches(attempt, event):
                continue
            event_type = str(event.get("event_type") or event.get("type") or "").upper()
            if event_type in {"SPELL_CAST_FAILED", "UNIT_SPELLCAST_FAILED", "ABILITY_FAILED"}:
                addon_failures.append(event_type)
        cast_failure = state.get("cast_failure") or state.get("spell_cast_failure")
        cast_failure_at = number(state.get("cast_failure_at"))
        if cast_failure and (cast_failure_at is None or attempt.dispatched_at <= cast_failure_at <= now):
            cast_failures.append(str(cast_failure))
        cast_sequence = _integer(state.get("cast_sequence"))
        cast_changed = (cast_sequence is not None and attempt.prior_cast_sequence is not None
                        and cast_sequence != attempt.prior_cast_sequence)
        resource = number(state.get("power"))
        resource_changed = (resource is not None and attempt.prior_resource is not None
                            and resource != attempt.prior_resource)
        target = state.get("target") if isinstance(state.get("target"), Mapping) else {}
        target_health = number(target.get("health"))
        target_damage = bool(
            attempt.target_guid and str(target.get("guid") or "") == attempt.target_guid
            and target_health is not None and attempt.prior_target_health is not None
            and target_health < attempt.prior_target_health)
        no_effect = ()
        if (elapsed >= self.window_seconds - 1e-9
                and not (ui_errors or addon_failures or cast_failures
                         or cast_changed or resource_changed or target_damage)):
            no_effect = ("no_cast_change", "no_resource_change", "no_target_damage")
        return AbilityCorrelation(
            attempt.attempt_id, True, tuple(ui_errors), tuple(addon_failures),
            tuple(cast_failures), cast_changed, resource_changed, target_damage,
            tuple(no_effect))


def _integer(value: object) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def _event_matches(attempt: AbilityAttempt, event: Mapping[str, Any]) -> bool:
    observed_at = number(event.get("at", event.get("timestamp")))
    if observed_at is not None and observed_at < attempt.dispatched_at:
        return False
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else event
    event_ability = payload.get("spell_id", payload.get("ability_id"))
    return not (attempt.ability_id is not None and event_ability is not None
                and str(event_ability) != str(attempt.ability_id))
