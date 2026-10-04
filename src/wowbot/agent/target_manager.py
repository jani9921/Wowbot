"""M2 target scoring, lifecycle and sticky selection.

This component ranks evidence only. It cannot click a candidate, mutate the
WorldModel, or turn an NPC template/visual track into a selectable target.
Only a current live addon GUID is actionable at the later TargetSkill boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable, Mapping

from wowbot.runtime import WorldEntityId, world_entity_id


class TargetLifecycle(StrEnum):
    NONE = "NONE"
    CANDIDATE = "CANDIDATE"
    ACQUIRING = "ACQUIRING"
    ACQUIRED = "ACQUIRED"
    ENGAGED = "ENGAGED"
    OCCLUDED = "OCCLUDED"
    REACQUIRING = "REACQUIRING"
    DEAD = "DEAD"
    LOST = "LOST"
    UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True, slots=True)
class TargetScoringPolicy:
    quest_relevance: float = 2.0
    hostility: float = 1.5
    reachability: float = 1.0
    visibility: float = .8
    threat: float = .6
    distance_preference: float = .5
    recent_failure_penalty: float = 1.5
    unreachable_penalty: float = 2.0
    switch_margin: float = .20


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    entity_id: WorldEntityId
    hostility_score: float
    quest_relevance_score: float
    distance_score: float
    visibility_score: float
    reachability_score: float
    threat_score: float
    recent_failure_penalty: float
    unreachable_penalty: float
    total_score: float
    components: Mapping[str, float] = field(default_factory=dict)
    evidence: Mapping[str, float] = field(default_factory=dict)


class TargetManager:
    """Sticky target ranking with an explicit evidence-driven lifecycle."""

    def __init__(self, switch_margin: float | None = None,
                 policy: TargetScoringPolicy | None = None) -> None:
        self.policy = policy or TargetScoringPolicy()
        self.switch_margin = self.policy.switch_margin if switch_margin is None else float(switch_margin)
        self.current_id: WorldEntityId | None = None
        self.current_score = 0.
        self.lifecycle = TargetLifecycle.NONE
        self.last_candidates: tuple[TargetCandidate, ...] = ()
        self.last_transition_reason = "initialized"
        self.current_track_id: str | None = None
        self.first_missing_at: float | None = None
        self.missing_observations = 0
        self.occlusion_seconds = .35
        self.reacquire_seconds = 1.5

    @staticmethod
    def _unit(value: object) -> float:
        try:
            return min(1., max(0., float(value or 0.)))
        except (TypeError, ValueError):
            return 0.

    def _candidate(self, raw: Mapping) -> TargetCandidate | None:
        entity_id = world_entity_id(raw.get("guid"))
        if entity_id is None:
            return None
        evidence = {
            "quest_relevance": self._unit(raw.get("quest_relevance")),
            "hostility": self._unit(raw.get("hostility", raw.get("attackable"))),
            "reachability": self._unit(raw.get("reachability", 1.)),
            "visibility": self._unit(raw.get("visibility", 1.)),
            "threat": self._unit(raw.get("threat")),
            "distance_preference": self._unit(raw.get("distance_preference")),
            "recent_failure_penalty": self._unit(raw.get("recent_failure_penalty")),
            "unreachable_penalty": self._unit(raw.get("unreachable_penalty")),
        }
        policy = self.policy
        components = {
            "quest_relevance": policy.quest_relevance * evidence["quest_relevance"],
            "hostility": policy.hostility * evidence["hostility"],
            "reachability": policy.reachability * evidence["reachability"],
            "visibility": policy.visibility * evidence["visibility"],
            "threat": policy.threat * evidence["threat"],
            "distance_preference": policy.distance_preference * evidence["distance_preference"],
            "recent_failure_penalty": -policy.recent_failure_penalty * evidence["recent_failure_penalty"],
            "unreachable_penalty": -policy.unreachable_penalty * evidence["unreachable_penalty"],
        }
        return TargetCandidate(
            entity_id=entity_id,
            hostility_score=evidence["hostility"],
            quest_relevance_score=evidence["quest_relevance"],
            distance_score=evidence["distance_preference"],
            visibility_score=evidence["visibility"],
            reachability_score=evidence["reachability"],
            threat_score=evidence["threat"],
            recent_failure_penalty=evidence["recent_failure_penalty"],
            unreachable_penalty=evidence["unreachable_penalty"],
            total_score=sum(components.values()),
            components=components,
            evidence=evidence,
        )

    def select(self, entities: Iterable[Mapping]) -> TargetCandidate | None:
        """Rank only live GUID candidates and preserve target hysteresis."""
        candidates = [candidate for raw in entities if isinstance(raw, Mapping)
                      if (candidate := self._candidate(raw)) is not None]
        candidates.sort(key=lambda item: (-item.total_score, str(item.entity_id)))
        self.last_candidates = tuple(candidates)
        current = next((item for item in candidates if item.entity_id == self.current_id), None)
        best = candidates[0] if candidates else None
        if current is not None and (best is None or best.entity_id == current.entity_id
                                    or best.total_score <= current.total_score+self.switch_margin):
            chosen = current
            reason = "hysteresis_retained" if best and best.entity_id != current.entity_id else "current_best"
        else:
            chosen = best
            reason = "new_best" if chosen else "no_live_guid_candidate"
        if chosen is None:
            # Candidate feeds are advisory and may omit a selected unit for a
            # frame.  Do not destroy the committed identity here; the
            # selected-target + temporal-track observation below owns the
            # OCCLUDED/REACQUIRING/LOST transition.
            if self.current_id is None:
                self.lifecycle = TargetLifecycle.NONE
            elif self.lifecycle not in {TargetLifecycle.DEAD, TargetLifecycle.UNREACHABLE,
                                        TargetLifecycle.LOST}:
                reason = "candidate_feed_missing_identity_preserved"
            self.last_transition_reason = reason
            return None
        if chosen.entity_id != self.current_id:
            self.current_id, self.current_score = chosen.entity_id, chosen.total_score
            self.lifecycle = TargetLifecycle.CANDIDATE
        else:
            self.current_score = chosen.total_score
            if self.lifecycle in {TargetLifecycle.NONE, TargetLifecycle.LOST}:
                self.lifecycle = TargetLifecycle.CANDIDATE
        self.last_transition_reason = reason
        return chosen

    def observe_selected(self, unit: Mapping | None, *, in_combat: bool = False,
                         at: float | None = None,
                         visual_tracks: Iterable[Mapping] = ()) -> TargetLifecycle:
        """Advance state from selected-target telemetry, never from CV alone."""
        unit = unit if isinstance(unit, Mapping) else {}
        guid = world_entity_id(unit.get("guid"))
        if guid is None:
            if self.current_id is None or self.lifecycle in {TargetLifecycle.NONE, TargetLifecycle.DEAD,
                                                              TargetLifecycle.UNREACHABLE,
                                                              TargetLifecycle.LOST}:
                return self.lifecycle
            self.missing_observations += 1
            if self.first_missing_at is None:
                self.first_missing_at = at
            track = next((row for row in visual_tracks
                          if isinstance(row, Mapping)
                          and self.current_track_id is not None
                          and str(row.get("track_id") or "") == self.current_track_id), None)
            track_state = str((track or {}).get("lifecycle")
                              or (track or {}).get("track_state") or "").upper()
            elapsed = ((float(at) - self.first_missing_at)
                       if at is not None and self.first_missing_at is not None else 0.)
            if track_state in {"LOST", "TERMINATED"} or elapsed >= self.reacquire_seconds:
                self.lifecycle = TargetLifecycle.LOST
                self.last_transition_reason = "committed_track_lost_or_reacquire_timeout"
            elif track_state in {"REACQUIRED", "REACQUIRE_CANDIDATE", "ACTIVE", "CONFIRMED"}:
                # The visual track is back, but CV is not allowed to promote it
                # to selected-unit ground truth.  Preserve the exact GUID and
                # request reacquisition through the normal TargetSkill path.
                self.lifecycle = TargetLifecycle.REACQUIRING
                self.last_transition_reason = "committed_track_reappeared_requires_target_reacquire"
            elif track_state in {"OCCLUDED", "PARTIALLY_OCCLUDED", "LOST_TEMPORARY"}:
                self.lifecycle = TargetLifecycle.OCCLUDED
                self.last_transition_reason = "committed_track_temporarily_occluded"
            elif elapsed < self.occlusion_seconds:
                self.lifecycle = TargetLifecycle.OCCLUDED
                self.last_transition_reason = "selected_target_short_gap"
            else:
                self.lifecycle = TargetLifecycle.REACQUIRING
                self.last_transition_reason = "selected_target_missing_reacquire_window"
            return self.lifecycle
        if self.current_id is not None and guid != self.current_id:
            self.lifecycle = TargetLifecycle.REACQUIRING
            self.last_transition_reason = "selected_guid_changed"
            return self.lifecycle
        self.current_id = guid
        observed_track_id = (unit.get("visual_track_id")
                             or (unit.get("screen_position") or {}).get("track_id"))
        if observed_track_id:
            self.current_track_id = str(observed_track_id)
        self.first_missing_at = None
        self.missing_observations = 0
        if unit.get("dead", unit.get("is_dead")) is True:
            self.lifecycle = TargetLifecycle.DEAD
            self.last_transition_reason = "selected_target_dead"
        elif unit.get("occluded") is True or unit.get("visible") is False:
            self.lifecycle = TargetLifecycle.OCCLUDED
            self.last_transition_reason = "selected_target_occluded"
        elif unit.get("reachable") is False:
            self.lifecycle = TargetLifecycle.UNREACHABLE
            self.last_transition_reason = "selected_target_unreachable"
        elif in_combat and unit.get("attackable", unit.get("is_attackable")) is True:
            self.lifecycle = TargetLifecycle.ENGAGED
            self.last_transition_reason = "selected_target_engaged"
        else:
            self.lifecycle = TargetLifecycle.ACQUIRED
            self.last_transition_reason = "selected_target_confirmed"
        return self.lifecycle

    def mark_acquiring(self, entity_id: str | None) -> bool:
        """Record a forthcoming TargetSkill request without selecting input."""
        guid = world_entity_id(entity_id)
        if guid is None or (self.current_id is not None and guid != self.current_id):
            return False
        self.current_id = guid
        self.lifecycle = TargetLifecycle.ACQUIRING
        self.last_transition_reason = "target_skill_requested"
        return True

    def snapshot(self) -> dict:
        return {
            "current_guid": self.current_id, "current_score": self.current_score,
            "current_track_id": self.current_track_id,
            "lifecycle": self.lifecycle.value, "reason": self.last_transition_reason,
            "first_missing_at": self.first_missing_at,
            "missing_observations": self.missing_observations,
            "switch_margin": self.switch_margin,
            "candidates": [{"guid": item.entity_id, "score": item.total_score,
                            "hostility_score": item.hostility_score,
                            "quest_relevance_score": item.quest_relevance_score,
                            "distance_score": item.distance_score,
                            "visibility_score": item.visibility_score,
                            "reachability_score": item.reachability_score,
                            "threat_score": item.threat_score,
                            "recent_failure_penalty": item.recent_failure_penalty,
                            "unreachable_penalty": item.unreachable_penalty,
                            "components": dict(item.components), "evidence": dict(item.evidence)}
                           for item in self.last_candidates],
        }
