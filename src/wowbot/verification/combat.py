"""Pure combat outcome evaluation with evidence-based kill confirmation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from wowbot.agent.models import number
from wowbot.runtime import FailureReason, VerificationResult


@dataclass(frozen=True, slots=True)
class DeadEvidence:
    source: str
    confidence: float


class CombatVerifier:
    """Evaluate combat evidence; never press keys or select a recovery."""

    DEAD_THRESHOLD = .85

    def evaluate(self, before: dict, after: dict, *, expected_guid: str | None) -> VerificationResult:
        if after.get("is_dead") is True or after.get("is_ghost") is True:
            return VerificationResult(False, 1.0, FailureReason.PLAYER_DEAD)
        target = after.get("target") or {}
        observed_guid = str(target.get("guid") or "")
        if expected_guid and observed_guid and observed_guid != expected_guid:
            return VerificationResult(False, .95, FailureReason.IDENTITY_UNCERTAIN)

        evidence = self.dead_evidence(before, after, expected_guid=expected_guid)
        dead_confidence = self.fuse_dead_evidence(evidence)
        if dead_confidence >= self.DEAD_THRESHOLD:
            labels = tuple(item.source for item in evidence)
            return VerificationResult(True, dead_confidence, None, ("target_dead", *labels))

        error = str(after.get("ui_error") or "").casefold()
        if any(text in error for text in ("out of range", "need to be closer", "too far away", "túl messze", "közelebb")):
            return VerificationResult(False, .9, FailureReason.OUT_OF_RANGE, retry_recommended=True)
        if any(text in error for text in ("facing the wrong way", "target needs to be in front", "not facing", "rossz irányba", "előtted kell")):
            return VerificationResult(False, .9, FailureReason.FACING_WRONG_WAY, retry_recommended=True)
        if any(text in error for text in ("line of sight", "no line of sight", "not in line")):
            return VerificationResult(False, .9, FailureReason.LINE_OF_SIGHT, retry_recommended=True)
        if any(text in error for text in ("not ready", "cooldown", "még nem")):
            return VerificationResult(False, .7, FailureReason.SPELL_NOT_READY, retry_recommended=True)
        if any(text in error for text in ("no path", "cannot reach", "nem talál útvonalat")):
            return VerificationResult(False, .9, FailureReason.PATH_BLOCKED, retry_recommended=True)
        if expected_guid and not observed_guid and before.get("is_in_combat") and after.get("is_in_combat"):
            return VerificationResult(False, .6, FailureReason.TARGET_LOST, retry_recommended=True)
        return VerificationResult(False, dead_confidence, None,
                                  tuple(item.source for item in evidence))

    def dead_evidence(self, before: Mapping, after: Mapping,
                      *, expected_guid: str | None) -> tuple[DeadEvidence, ...]:
        """Collect evidence from distinct sources for the intended live GUID."""
        expected = str(expected_guid or "")
        if not expected:
            return ()
        target = after.get("target") or {}
        observed_guid = str(target.get("guid") or "")
        evidence: list[DeadEvidence] = []
        if observed_guid == expected and target.get("dead", target.get("is_dead")) is True:
            evidence.append(DeadEvidence("target_dead_flag", .85))
        if observed_guid == expected and (number(target.get("health")) is not None
                                          and number(target.get("health")) <= 0):
            evidence.append(DeadEvidence("target_hp_zero", .70))
        for event in after.get("events") or ():
            if not isinstance(event, Mapping):
                continue
            payload = event.get("payload") or {}
            if not isinstance(payload, Mapping):
                continue
            tooltip_data = payload.get("tooltip_data") or {}
            guid = str(payload.get("guid") or payload.get("unit_guid")
                       or (tooltip_data.get("guid") if isinstance(tooltip_data, Mapping) else "") or "")
            if guid != expected:
                continue
            event_type = str(event.get("event_type") or "").upper()
            if event_type in {"UNIT_DIED", "TARGET_DIED", "COMBAT_LOG_UNIT_DIED"}:
                evidence.append(DeadEvidence("unit_died_event", 1.0))
            elif "corpse" in str(payload.get("tooltip") or "").casefold():
                evidence.append(DeadEvidence("same_guid_corpse", .80))
        objective_changed = self._objective_signature(before) != self._objective_signature(after)
        if objective_changed:
            evidence.append(DeadEvidence("objective_credit_support", .25))
        if before.get("is_in_combat") and after.get("is_in_combat") is False:
            evidence.append(DeadEvidence("combat_ended_support", .25))
        before_target = before.get("target") or {}
        if (objective_changed and str(before_target.get("guid") or "") == expected
                and not observed_guid and before.get("is_in_combat")
                and after.get("is_in_combat") is False):
            # This is not credit by itself: it is the correlated combination
            # of a just-selected expected entity disappearing, combat ending,
            # and the linked objective advancing in the same observation
            # window.  It supports the normal target/corpse evidence path for
            # clients that clear selection immediately on death.
            evidence.append(DeadEvidence("target_disappeared_after_credit", .75))
        return tuple(evidence)

    @staticmethod
    def fuse_dead_evidence(evidence: tuple[DeadEvidence, ...]) -> float:
        """Noisy-OR fusion, deduplicated by independent source category."""
        independent: dict[str, float] = {}
        for item in evidence:
            independent[item.source] = max(independent.get(item.source, 0.0), item.confidence)
        remaining = 1.0
        for confidence in independent.values():
            remaining *= 1.0 - min(1.0, max(0.0, confidence))
        return 1.0 - remaining

    @staticmethod
    def _objective_signature(state: Mapping) -> tuple:
        rows = []
        for quest in state.get("active_quests") or ():
            if not isinstance(quest, Mapping):
                continue
            for objective in quest.get("objectives") or ():
                if not isinstance(objective, Mapping):
                    continue
                rows.append((str(quest.get("quest_id")), str(objective.get("objective_id") or objective.get("description")),
                             objective.get("current"), objective.get("required"), bool(objective.get("is_complete"))))
        return tuple(sorted(rows))
