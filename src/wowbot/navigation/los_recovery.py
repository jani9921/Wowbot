"""Evidence-driven, bounded line-of-sight recovery planning.

This module never dispatches input and never owns movement.  It converts
fresh local traversability plus target-bearing evidence into one small
lateral intent.  The canonical :class:`NavigationService` remains the only
component allowed to turn that intent into a movement command.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from wowbot.agent.models import number


class LosRecoveryPhase(StrEnum):
    SAMPLE_LOCAL_GEOMETRY = "SAMPLE_LOCAL_GEOMETRY"
    TRY_LATERAL_A = "TRY_LATERAL_A"
    VERIFY_LATERAL_A = "VERIFY_LATERAL_A"
    TRY_LATERAL_B = "TRY_LATERAL_B"
    VERIFY_LATERAL_B = "VERIFY_LATERAL_B"
    LOCAL_REPLAN = "LOCAL_REPLAN"
    VERIFY_LOCAL_REPLAN = "VERIFY_LOCAL_REPLAN"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"


@dataclass(frozen=True, slots=True)
class LosRecoveryDirective:
    phase: LosRecoveryPhase
    action: str | None
    duration: float = 0.0
    chosen_side: str | None = None
    geometry_source: str = "UNAVAILABLE"
    evidence: tuple[str, ...] = ()


class LosRecoveryPlanner:
    """Select two evidence-ranked lateral probes, then require local replan.

    Attempt zero uses the highest-supported free side.  Attempt one uses the
    other side, so a retained LOS failure cannot repeat one ineffective pulse.
    Attempt two is deliberately command-free: callers may only continue by
    creating a validated ``REPOSITION_FOR_LOS`` request (normally backed by
    mmap/global geometry).  Attempts beyond the finite budget terminate.
    """

    MAX_ATTEMPTS = 3
    # The selected-PID executor accepts at most a 350 ms refresh quantum.
    # The movement watchdog holds a primary lateral lease for at most 450 ms,
    # giving the specified ~0.4 s minimum displacement while retaining an
    # early, fail-safe release on focus loss/cancellation/missed refresh.
    MIN_DURATION = 0.30
    MAX_DURATION = 0.35

    def plan(self, state: dict[str, Any], request: dict[str, Any]) -> LosRecoveryDirective:
        attempt = max(0, int(request.get("attempt") or 0))
        if attempt >= self.MAX_ATTEMPTS:
            return LosRecoveryDirective(
                LosRecoveryPhase.TARGET_UNREACHABLE, None,
                evidence=("los_recovery_budget_exhausted",))
        if attempt == 2:
            return LosRecoveryDirective(
                LosRecoveryPhase.LOCAL_REPLAN, None,
                evidence=("lateral_a_failed", "lateral_b_failed",
                          "validated_local_replan_required"))

        scores, source = self._free_space_scores(state)
        bearing = number(request.get("target_screen_x"))
        order = self._rank_sides(scores, bearing)
        side = order[attempt]
        score = scores.get(side)
        # A longer probe is justified only by positive free-space evidence.
        # Unknown geometry stays at the conservative lower bound.
        duration = self.MIN_DURATION
        if score is not None:
            duration += min(.05, max(0., score-.5) * .1)
        action = "STRAFELEFT" if side == "LEFT" else "STRAFERIGHT"
        phase = (LosRecoveryPhase.TRY_LATERAL_A if attempt == 0
                 else LosRecoveryPhase.TRY_LATERAL_B)
        evidence = [f"target_bearing:{bearing:.3f}" if bearing is not None
                    else "target_bearing:unknown"]
        if score is not None:
            evidence.append(f"{side.lower()}_free_space:{score:.3f}")
        else:
            evidence.append("free_space:unavailable")
        return LosRecoveryDirective(
            phase, action, min(self.MAX_DURATION, duration), side, source,
            tuple(evidence))

    @staticmethod
    def _rank_sides(scores: dict[str, float], bearing: float | None) -> tuple[str, str]:
        # Free-space is primary. Target bearing is a deterministic tie-break
        # that avoids the old unconditional "left first" behaviour.
        bearing_side = "LEFT" if bearing is not None and bearing < .5 else "RIGHT"
        ranked = sorted(
            ("LEFT", "RIGHT"),
            key=lambda side: (scores.get(side, -.01), side == bearing_side),
            reverse=True)
        return ranked[0], ranked[1]

    @staticmethod
    def _free_space_scores(state: dict[str, Any]) -> tuple[dict[str, float], str]:
        raw = state.get("local_traversability")
        if not isinstance(raw, dict) or raw.get("schema") != "WORLD3D_TRAVERSABILITY_V5":
            return {}, "UNAVAILABLE"
        result: dict[str, float] = {}
        for row in raw.get("sectors") or ():
            if not isinstance(row, dict):
                continue
            side = {"CENTER_LEFT": "LEFT", "CENTER_RIGHT": "RIGHT"}.get(
                str(row.get("sector") or ""))
            if side is None:
                continue
            score = number(row.get("traversability_score"))
            confidence = number(row.get("obstacle_confidence"))
            blocked = (row.get("state") == "BLOCKED"
                       and row.get("obstacle_lifecycle") == "CONFIRMED"
                       and (confidence or 0.) >= .65)
            if score is not None:
                result[side] = 0.0 if blocked else max(0., min(1., score))
        return result, "WORLD3D_TRAVERSABILITY_V5"
