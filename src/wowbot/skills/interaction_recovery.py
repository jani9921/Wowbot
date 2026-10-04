"""Finite M2.14 interaction recovery matrix; policy only, no input."""
from __future__ import annotations

from dataclasses import dataclass

from .interaction_result import InteractionResultKind


@dataclass(frozen=True, slots=True)
class InteractionRecoveryRule:
    action: str
    budget: int


class InteractionRecoveryPolicy:
    DIRECT_RETRY_BUDGET = 3
    REPOSITION_BUDGET = 2
    REACQUIRE_BUDGET = 2
    UNKNOWN_OBSERVATION_BUDGET = 1
    UI_WAIT_SECONDS = .25
    # A silent INTERACT is only "no response" after the server, the addon
    # export and the pixel transport had time to show a dialog (live
    # 2026-09-30: failures were declared 0.22-0.32 s after the key press on
    # the pre-press observation itself, even next to the NPC).
    RESPONSE_TIMEOUT_SECONDS = 1.2

    RULES = {
        InteractionResultKind.TOO_FAR: InteractionRecoveryRule("APPROACH", REPOSITION_BUDGET),
        InteractionResultKind.FACING: InteractionRecoveryRule("FACE", REPOSITION_BUDGET),
        InteractionResultKind.LOS: InteractionRecoveryRule("LOCAL_REPOSITION", REPOSITION_BUDGET),
        InteractionResultKind.CURSOR_MISS: InteractionRecoveryRule("HOVER_RESAMPLE", 4),
        InteractionResultKind.WRONG_ENTITY: InteractionRecoveryRule("REACQUIRE_EXPECTED", REACQUIRE_BUDGET),
        InteractionResultKind.ENTITY_MOVED: InteractionRecoveryRule("REFRESH_AND_APPROACH", REPOSITION_BUDGET),
        InteractionResultKind.UI_NOT_READY: InteractionRecoveryRule("WAIT_AND_RETRY", DIRECT_RETRY_BUDGET),
        InteractionResultKind.TARGET_LOST: InteractionRecoveryRule("REACQUIRE_EXPECTED", REACQUIRE_BUDGET),
        InteractionResultKind.UNKNOWN: InteractionRecoveryRule("OBSERVE_ONCE", UNKNOWN_OBSERVATION_BUDGET),
    }

    def rule(self, kind: InteractionResultKind) -> InteractionRecoveryRule:
        return self.RULES[kind]

    @staticmethod
    def available(rule: InteractionRecoveryRule, attempts: int) -> bool:
        return int(attempts) < rule.budget
