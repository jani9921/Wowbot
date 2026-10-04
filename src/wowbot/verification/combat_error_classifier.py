"""Combat error classification (DESIGN-041).

The spec names an 11-value combat error taxonomy and a `classify(observations,
combat_history)` function. `FailureReason` (`runtime/contracts.py`) is this
codebase's one actual failure taxonomy -- eight of the eleven spec names
already exist there verbatim (OUT_OF_RANGE, FACING_WRONG_WAY, LINE_OF_SIGHT,
SPELL_NOT_READY, TARGET_DEAD, TARGET_LOST, INVALID_TARGET, PLAYER_DEAD); the
remaining three map onto its closest real equivalents rather than a second,
competing enum: RESOURCE_LOW -> NOT_ENOUGH_RESOURCE, MOVING_CAST ->
CAST_INTERRUPTED, UNKNOWN -> UI_UNKNOWN.

`classify_combat_error()` composes the already-validated `CombatVerifier`
(its `ui_error` text matching and dead-evidence fusion) rather than
duplicating or re-guessing its string patterns.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from wowbot.agent.models import number
from wowbot.runtime import FailureReason

from .combat import CombatVerifier

_DELEGATED_REASONS = frozenset({
    FailureReason.OUT_OF_RANGE, FailureReason.FACING_WRONG_WAY,
    FailureReason.LINE_OF_SIGHT, FailureReason.SPELL_NOT_READY,
    FailureReason.PLAYER_DEAD, FailureReason.TARGET_LOST,
})


def classify_combat_error(observations: Mapping, combat_history: Sequence[Mapping] | None = None,
                          *, verifier: CombatVerifier | None = None) -> FailureReason:
    """Classify one combat attempt's current blocking condition.

    `observations` is the current world/target snapshot (target dict,
    is_dead/is_ghost, power/max_power, is_moving/is_casting, ui_error).
    `combat_history` is the sequence of prior observations for this same
    attempt, oldest first; used only for the one reason (MOVING_CAST) that
    genuinely needs a state transition rather than a single snapshot.
    """
    if observations.get("is_dead") or observations.get("is_ghost"):
        return FailureReason.PLAYER_DEAD
    target = observations.get("target") or {}
    guid = str(target.get("guid") or "") or None
    if guid is None:
        return FailureReason.TARGET_LOST
    if target.get("attackable") is False or target.get("is_attackable") is False:
        return FailureReason.INVALID_TARGET
    ui_error = str(observations.get("ui_error") or "").casefold()
    if any(token in ui_error for token in (
        "invalid target", "no target", "érvénytelen cél", "nincs célpont",
    )):
        return FailureReason.INVALID_TARGET

    result = (verifier or CombatVerifier()).evaluate({}, dict(observations), expected_guid=guid)
    if result.success:
        return FailureReason.TARGET_DEAD
    if result.reason in _DELEGATED_REASONS:
        return result.reason

    power, max_power = number(observations.get("power")), number(observations.get("max_power"))
    if power is not None and max_power and float(max_power) > 0 and float(power) <= 0:
        return FailureReason.NOT_ENOUGH_RESOURCE

    if observations.get("is_moving") and combat_history:
        previous = combat_history[-1]
        if isinstance(previous, Mapping) and previous.get("is_casting") and not observations.get("is_casting"):
            return FailureReason.CAST_INTERRUPTED

    return FailureReason.UI_UNKNOWN
