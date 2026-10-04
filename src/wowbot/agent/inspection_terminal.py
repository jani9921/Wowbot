"""Learning effects for a completed INSPECT attempt."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .models import Attempt, Outcome, VerificationRecord, number


@dataclass(frozen=True)
class InspectionTerminalAssessment:
    quality: dict
    events: tuple[tuple[str, dict], ...]


class InspectionTerminalProcessor:
    """Update rejection/sensor memory from evidence; never selects another action."""

    @staticmethod
    def process(attempt: Attempt, outcome: Outcome, reason: str, state: dict,
                *, latest_observation_id: str | None, last_received: float,
                session_id: str | None, memory, now: float,
                verification: VerificationRecord) -> InspectionTerminalAssessment:
        marker = attempt.proposal.parameters
        map_id = state.get("map_id")
        cursor = state.get("cursor_position") or {}
        cursor_x, cursor_y = number(cursor.get("nx")), number(cursor.get("ny"))
        marker_x, marker_y = number(marker.get("x")), number(marker.get("y"))
        cursor_distance = (math.hypot(cursor_x-marker_x, cursor_y-marker_y)
                           if None not in (cursor_x, cursor_y, marker_x, marker_y) else None)
        at_probe = cursor_distance is not None and cursor_distance <= .02
        stable = number(marker.get("stable_frames")) or 0.
        lifecycle = str(marker.get("lifecycle") or marker.get("track_state") or "ACTIVE")
        new_observation = bool(latest_observation_id and
            (latest_observation_id != attempt.observation_id or last_received > attempt.started_at))
        hover_quality = ((.5 if at_probe else 0.)
                         + (.2 if stable >= 3 or marker.get("source") in {"WORLD_MAP_CV", "MINIMAP_CV"} else 0.)
                         + (.2 if new_observation else 0.)
                         + (.1 if lifecycle not in {"LOST", "REJECTED"} else 0.))
        valid_zero_information = (at_probe and new_observation
            and lifecycle not in {"LOST", "REJECTED"}
            and (stable >= 3 or marker.get("source") in {"WORLD_MAP_CV", "MINIMAP_CV"}))
        quality = {
            "valid_zero_information": valid_zero_information,
            "hover_quality": round(hover_quality, 3), "cursor_distance": cursor_distance,
            "at_probe": at_probe, "stable_frames": stable,
            "new_observation": new_observation, "lifecycle": lifecycle,
        }
        if outcome == Outcome.SUCCESS:
            memory.record_rejection_contradiction(marker, map_id=map_id, at=now)
        elif reason == "expected_observation_missing" and valid_zero_information:
            memory.record_rejection(
                marker, map_id=map_id, reason="valid_hover_no_information", at=now,
                evidence_group=f"{session_id}:{marker.get('source')}:{int(now // 30)}",
                hover_quality=hover_quality)
        source = str(marker.get("source") or "UNKNOWN")
        detector = str(marker.get("detector_kind") or marker.get("kind") or "UNKNOWN")
        sensor_context = memory.learning_context(state, "SENSOR")
        provenance = {"track_id": marker.get("track_id"), "action_id": attempt.action_id,
                      "verification_id": verification.verification_id}
        memory.record_sensor_outcome(
            source, "*", sensor_context, correct=outcome == Outcome.SUCCESS, at=now,
            latency=max(0., now-attempt.started_at),
            error="" if outcome == Outcome.SUCCESS else reason, provenance=provenance)
        expected = {"quest_giver": "QUEST_GIVER", "quest_turn_in": "QUEST_TURN_IN",
                    "quest_objective": "QUEST_OBJECTIVE", "hostile": "HOSTILE_ENTITY",
                    "resource": "RESOURCE_NODE"}.get(detector)
        mouseover = state.get("map_mouseover") or state.get("mouseover") or {}
        observed = mouseover.get("semantic_type") or mouseover.get("quest_role")
        if expected and observed and str(observed).upper() != "UNKNOWN":
            correct = outcome == Outcome.SUCCESS and str(observed).upper() == expected
            memory.record_sensor_outcome(
                source, detector, sensor_context, correct=correct, at=now,
                latency=max(0., now-attempt.started_at),
                error="" if correct else "semantic_mismatch",
                provenance={**provenance, "expected_semantic": expected,
                            "observed_semantic": observed},
                predicted_label=expected, actual_label=observed)
        return InspectionTerminalAssessment(
            quality, (("INSPECTION_QUALITY", {"action_id": attempt.action_id, **quality}),))
