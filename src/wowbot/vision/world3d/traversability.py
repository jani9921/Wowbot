"""Temporal, evidence-only local traversability fusion.

This module deliberately answers *where forward traversal looks safe*, not
what a pictured object is.  It is owned by World3D perception and publishes no
movement command.  Navigation may consume its costs only through the canonical
WorldModel/NavigationService boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class TraversabilityConfig:
    """Starting values for V5 M4.8; callers may inject a tuned config."""

    temporal_weight: float = 0.42
    blocked_confirmation: float = 0.65
    traversable_confirmation: float = 0.62
    confirmation_frames: int = 2
    decay_seconds: float = 1.5
    stale_seconds: float = 3.0
    collision_weight: float = 0.20
    boundary_weight: float = 0.20
    free_space_weight: float = 0.35
    free_space_violation_weight: float = 0.20
    depth_discontinuity_weight: float = 0.15
    ego_motion_mismatch_weight: float = 0.20
    collision_evidence_weight: float = 0.15
    danger_drop_threshold: float = 0.72


class TemporalTraversabilityFusion:
    """Converts per-frame sector hints into decaying temporal beliefs.

    One ambiguous frame can create ``SUSPECTED`` evidence but cannot produce a
    hard ``BLOCKED`` navigation state.  Motion mismatch is accepted only when
    the context explicitly says forward translation was commanded; camera
    rotation therefore cannot masquerade as a collision.
    """

    def __init__(self, config: TraversabilityConfig | None = None) -> None:
        self.config = config or TraversabilityConfig()
        self._history: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        self._history.clear()

    def update(self, raw: dict[str, Any], *, observed_at: float,
               ego_motion: dict[str, Any] | None = None,
               motion_feedback: dict[str, Any] | None = None) -> dict[str, Any]:
        ego_motion = ego_motion or {}
        motion_feedback = motion_feedback or {}
        output: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        for sector in raw.get("sectors") or ():
            item = dict(sector)
            sector_id = str(item.get("sector") or "UNKNOWN")
            previous = self._history.get(sector_id)
            dt = max(0.0, observed_at - _number((previous or {}).get("at"), observed_at))
            age_weight = (self.config.temporal_weight * max(0.0, 1.0 - dt / self.config.decay_seconds)
                          if previous is not None else 0.0)

            free_raw = _clamp(_number(item.get("free_probability")))
            blocked_raw = _clamp(_number(item.get("blocked_probability")))
            unknown_raw = _clamp(_number(item.get("unknown_probability")))
            boundary = _clamp(_number(item.get("boundary_confidence"), blocked_raw))
            free_space = _clamp(_number(item.get("free_space_confidence"), free_raw))
            collision = self._collision_evidence(sector_id, motion_feedback, ego_motion)
            previous_blocked = _number((previous or {}).get("blocked"))
            previous_free = _number((previous or {}).get("free"))
            blocked = _clamp((1.0 - age_weight) * blocked_raw + age_weight * previous_blocked)
            free = _clamp((1.0 - age_weight) * free_raw + age_weight * previous_free)
            # Current boundary/block evidence remains primary.  Temporal
            # history smooths it, but cannot manufacture a blocker after the
            # scene becomes clear.
            has_depth = "depth_discontinuity_confidence" in item
            has_mismatch = "motion_mismatch_confidence" in item or collision > 0
            depth = _clamp(_number(item.get("depth_discontinuity_confidence")))
            mismatch = _clamp(_number(item.get("motion_mismatch_confidence"), collision))
            current_obstacle = self._fuse_obstacle_evidence(
                boundary=boundary,
                free_space_violation=1.0-free_space,
                depth=depth if has_depth else None,
                motion_mismatch=mismatch if has_mismatch else None,
                collision=collision if collision > 0 else None,
            )
            obstacle = _clamp((1.0 - age_weight) * current_obstacle
                              + age_weight * _number((previous or {}).get("obstacle")))
            dynamic = _clamp(_number(item.get("dynamic_probability")))
            drop = _clamp(_number(item.get("drop_confidence")))
            persistence = int((previous or {}).get("persistence", 0)) + 1 if blocked_raw >= .35 else 0
            drop_persistence = (int((previous or {}).get("drop_persistence", 0)) + 1
                                if drop >= self.config.danger_drop_threshold else 0)
            prior_lifecycle = str((previous or {}).get("lifecycle") or "NEW")
            if dynamic >= .55:
                # A moving obstruction is useful local evidence, but must not
                # become a durable static blacklist entry.
                lifecycle = "DYNAMIC"
            elif blocked_raw < .20 and previous and previous_blocked >= .35:
                lifecycle = "DECAYING"
            elif persistence >= self.config.confirmation_frames and obstacle >= self.config.blocked_confirmation:
                lifecycle = "CONFIRMED"
            elif blocked_raw >= .35 or collision >= .35:
                lifecycle = "SUSPECTED"
            elif prior_lifecycle == "DECAYING":
                lifecycle = "CLEARED"
            else:
                lifecycle = "NEW"

            if drop >= self.config.danger_drop_threshold:
                state = "DANGEROUS"
            elif (lifecycle == "CONFIRMED" and persistence >= self.config.confirmation_frames
                    and dynamic < .55):
                state = "BLOCKED"
            elif dynamic >= .55:
                # Even if the ground behind it looks free, an independently
                # moving blocker remains a temporary local uncertainty/cost.
                state = "UNCERTAIN"
            elif free >= self.config.traversable_confirmation and obstacle < .45:
                state = "TRAVERSABLE"
            else:
                state = "UNCERTAIN" if unknown_raw >= .20 or obstacle >= .30 else "UNKNOWN"
            traversability = _clamp(free * (1.0 - obstacle))
            evidence = list(item.get("evidence") or ())
            if collision:
                evidence.append("motion_conditioned_collision_evidence")
            terrain_transition = self._terrain_transition(item)
            if terrain_transition is not None:
                evidence.append("terrain_transition_evidence")
            item.update({
                "traversability_score": round(traversability, 4),
                "obstacle_confidence": round(obstacle, 4),
                "ground_confidence": round(free_space, 4),
                "free_space_confidence": round(free_space, 4),
                "boundary_confidence": round(boundary, 4),
                "depth_discontinuity_confidence": round(depth, 4),
                "motion_mismatch_confidence": round(mismatch, 4),
                "collision_evidence_confidence": round(collision, 4),
                "danger_confidence": round(drop, 4),
                "dynamic_probability": round(dynamic, 4),
                "persistence_score": round(min(1.0, persistence / max(1, self.config.confirmation_frames)), 4),
                "state": state,
                "obstacle_lifecycle": lifecycle,
                "terrain_transition": terrain_transition,
                "last_updated_at": observed_at,
                "evidence": list(dict.fromkeys(evidence)),
                "fact": False,
            })
            self._history[sector_id] = {"at": observed_at, "blocked": blocked,
                                        "free": free, "obstacle": obstacle,
                                        "persistence": persistence,
                                        "drop_persistence": drop_persistence,
                                        "lifecycle": lifecycle}
            output.append(item)
            if lifecycle != prior_lifecycle and lifecycle in {"SUSPECTED", "CONFIRMED", "CLEARED"}:
                events.append({"event_type": f"OBSTACLE_{lifecycle}", "sector": sector_id,
                               "confidence": round(obstacle, 4), "timestamp": observed_at,
                               "evidence": tuple(item["evidence"])})
            if lifecycle == "DYNAMIC":
                events.append({"event_type": "DYNAMIC_OBSTACLE_UPDATED", "sector": sector_id,
                               "confidence": round(dynamic, 4), "timestamp": observed_at,
                               "evidence": tuple(item["evidence"])})
            if collision >= .35:
                events.append({"event_type": "COLLISION_EVIDENCE_UPDATED", "sector": sector_id,
                               "confidence": round(collision, 4), "timestamp": observed_at,
                               "evidence": tuple(item["evidence"])})
            if mismatch >= .35:
                events.append({"event_type": "EGO_MOTION_MISMATCH", "sector": sector_id,
                               "confidence": round(mismatch, 4), "timestamp": observed_at,
                               "evidence": tuple(item["evidence"])})
            if drop >= self.config.danger_drop_threshold:
                cliff_event = ("CLIFF_CONFIRMED" if
                               drop_persistence >= self.config.confirmation_frames
                               else "CLIFF_SUSPECTED")
                events.append({"event_type": cliff_event, "sector": sector_id,
                               "confidence": round(drop, 4), "timestamp": observed_at,
                               "evidence": tuple(item["evidence"])})
            if terrain_transition is not None:
                events.append({"event_type": "TERRAIN_TRANSITION_UPDATED", "sector": sector_id,
                               "confidence": terrain_transition["confidence"],
                               "timestamp": observed_at,
                               "evidence": tuple(item["evidence"])})
            events.append({"event_type": "TRAVERSABILITY_UPDATED", "sector": sector_id,
                           "confidence": round(traversability, 4), "timestamp": observed_at,
                           "evidence": tuple(item["evidence"])})
        self._prune(observed_at)
        confidence = _clamp(sum(_number(item.get("traversability_score")) for item in output) / max(1, len(output)))
        return {"schema": "WORLD3D_TRAVERSABILITY_V5", "coordinate_space": raw.get("coordinate_space"),
                "sectors": output, "events": events, "confidence": round(confidence, 4), "fact": False}

    @staticmethod
    def _terrain_transition(item: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize explicit terrain evidence without inventing semantics.

        Water is deliberately not equivalent to blocked terrain.  Perception
        reports the transition and its uncertainty; the goal/navigation policy
        decides whether swimming is permitted.  An upstream sensor may provide
        an explicit traversability belief, otherwise it stays UNKNOWN.
        """
        supplied = item.get("terrain_transition")
        transition = dict(supplied) if isinstance(supplied, dict) else {}
        water_confidence = _clamp(_number(item.get("water_confidence")))
        transition_type = str(transition.get("type") or
                              ("WATER" if water_confidence > 0 else "UNKNOWN")).upper()
        confidence = _clamp(_number(transition.get("confidence"), water_confidence))
        if not transition and confidence <= 0:
            return None
        belief = str(transition.get("traversability_belief") or "UNKNOWN").upper()
        if belief not in {"TRAVERSABLE", "NON_TRAVERSABLE", "UNKNOWN"}:
            belief = "UNKNOWN"
        return {
            "type": transition_type,
            "traversability_belief": belief,
            "risk": round(_clamp(_number(transition.get("risk"))), 4),
            "confidence": round(confidence, 4),
            "evidence": list(transition.get("evidence") or ()),
            "fact": False,
        }

    def _fuse_obstacle_evidence(self, *, boundary: float | None, free_space_violation: float | None,
                                depth: float | None, motion_mismatch: float | None,
                                collision: float | None) -> float:
        """Fuse only present evidence channels, renormalizing configurable weights.

        There is intentionally no object-class input here: a visually unknown
        but repeatedly non-traversable region is still navigation evidence.
        ``0`` is a valid observed value, while unavailable depth/motion are
        omitted by the caller through their zero/default confidence.
        """
        sources = (
            (boundary, self.config.boundary_weight),
            (free_space_violation, self.config.free_space_violation_weight),
            (depth, self.config.depth_discontinuity_weight),
            (motion_mismatch, self.config.ego_motion_mismatch_weight),
            (collision, self.config.collision_evidence_weight),
        )
        available = tuple((value, weight) for value, weight in sources if value is not None and weight > 0)
        total_weight = sum(weight for _, weight in available)
        return _clamp(sum(value * weight for value, weight in available) / total_weight) if total_weight else 0.0

    def _collision_evidence(self, sector_id: str, feedback: dict[str, Any], ego_motion: dict[str, Any]) -> float:
        if sector_id not in {"CENTER_LEFT", "CENTER", "CENTER_RIGHT"}:
            return 0.0
        commanded = str(feedback.get("commanded_motion") or "").upper()
        if not commanded:
            movement = ego_motion.get("forward_motion_belief")
            commanded = "FORWARD" if movement is True else ""
        if commanded not in {"FORWARD", "FORWARD_TRANSLATION"}:
            return 0.0
        # A camera rotation/uncertain global flow is not translational failure.
        if str(ego_motion.get("motion_kind") or "").upper() in {"ROTATION", "LEFT_ROTATION", "RIGHT_ROTATION"}:
            return 0.0
        progress = feedback.get("progress_score")
        if progress is None:
            return _clamp(_number(feedback.get("collision_evidence")))
        return _clamp(max(_number(feedback.get("collision_evidence")), .55 - _clamp(_number(progress))))

    def _prune(self, observed_at: float) -> None:
        self._history = {key: value for key, value in self._history.items()
                         if observed_at - _number(value.get("at"), observed_at) <= self.config.stale_seconds}
