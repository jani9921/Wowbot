"""Canonical projection of verifier results into engine terminal decisions."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import FailureReason, SkillResult, SkillStatus


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    status: SkillStatus
    reason: str | None
    typed_reason: FailureReason | None
    verifier: str | None = None
    evidence: tuple = ()

    @property
    def pending(self) -> bool:
        return self.status is SkillStatus.RUNNING

    @property
    def success(self) -> bool:
        return self.status is SkillStatus.SUCCESS


class VerificationEngine:
    """Single confirmation boundary for postcondition-verifier results.

    A skill/start routine may propose RUNNING or FAILURE, but a bare SUCCESS
    is deliberately held as pending. Only ``confirm`` accepts a result from an
    invoked postcondition verifier. This prevents command dispatch/local ACK
    or a skill's optimistic start result from authoring world success.
    """

    _SUCCESS_REASONS = {
        "TARGET": "target_identity_changed",
        "INTERACT": "interaction_verified",
        "TALK": "interaction_verified",
        "COMBAT": "target_death_verified",
        "DEFEND": "target_death_verified",
        "WAIT_EVENT": "quest_event_progress_verified",
        "LOOT": "loot_verified",
        "OBJECT_USE": "object_use_credit_verified",
        "QUEST_DIALOG": "quest_dialog_verified",
        "FIELD_TURN_IN": "field_turnin_verified",
        "EXTRA_ACTION": "extra_action_quest_credit_verified",
        "USE_ON_TARGET": "quest_item_credit_verified",
        "ASSIST": "quest_item_credit_verified",
        "FOLLOW_INSTRUCTION": "instructed_spell_credit_verified",
    }

    def project(self, skill: str, result: SkillResult,
                world_state: dict | None = None, *,
                verifier_invoked: bool = False,
                verifier: str | None = None) -> VerificationDecision:
        if result.status is SkillStatus.RUNNING:
            return VerificationDecision(result.status, None, result.reason,
                                        verifier, tuple(result.evidence))
        if result.status is SkillStatus.SUCCESS:
            if not verifier_invoked:
                return VerificationDecision(
                    SkillStatus.RUNNING, "awaiting_postcondition_verifier", None,
                    None, tuple(result.evidence))
            return VerificationDecision(
                result.status, self._SUCCESS_REASONS.get(skill, "skill_postcondition_verified"),
                result.reason, verifier or "POSTCONDITION_VERIFIER",
                tuple(result.evidence))
        if (skill in {"COMBAT", "DEFEND"}
                and result.reason is FailureReason.PATH_BLOCKED
                and (world_state or {}).get("ui_error")):
            return VerificationDecision(
                result.status, f"client_error:{world_state['ui_error']}", result.reason,
                verifier, tuple(result.evidence))
        reason = (result.metadata.get("legacy_reason")
                  or (result.reason.value.lower() if result.reason else "verification_failed"))
        return VerificationDecision(result.status, reason, result.reason,
                                    verifier, tuple(result.evidence))

    def confirm(self, skill: str, result: SkillResult,
                world_state: dict | None = None, *,
                verifier: str = "DOMAIN_POSTCONDITION_VERIFIER") -> VerificationDecision:
        """Project the result of an actually invoked postcondition verifier."""
        return self.project(skill, result, world_state,
                            verifier_invoked=True, verifier=verifier)
