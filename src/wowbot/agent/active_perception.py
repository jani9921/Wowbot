"""Select observations by expected information gain divided by total cost."""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .models import number


_PROBE_STATES = frozenset({"REQUESTED", "SELECT_ACTION", "EXECUTE_PROBE",
                           "WAIT_OBSERVATION", "EVALUATE_GAIN", "SUCCESS", "FAILED"})
_PROBE_ACTIONS = frozenset({"SMALL_CAMERA_TURN", "SMALL_PLAYER_TURN", "HOVER_CANDIDATE",
                            "APPROACH_SLIGHTLY", "OPEN_MAP", "CLOSE_MAP", "RECENTER_CAMERA",
                            "WAIT_TOOLTIP"})


@dataclass(slots=True)
class _Probe:
    probe_id: str
    track_id: str | None
    requested_at: float
    baseline_confidence: float
    state: str = "REQUESTED"
    action: str | None = None
    deadline: float | None = None
    history: list[dict] = field(default_factory=list)

    def transition(self, state: str, at: float, **details: object) -> None:
        if state not in _PROBE_STATES:
            raise ValueError(f"unknown active-perception state: {state}")
        self.state = state
        self.history.append({"state": state, "at": float(at), **details})
        self.history[:] = self.history[-24:]


class ActivePerception:
    SOURCE_COST = {"MINIMAP_CV": .25, "WORLD_MAP_CV": .45, "WORLD3D": .35,
                   "ENTITY_MEMORY": .1, "AI": 1.5}

    def __init__(self, memory=None):
        self.memory = memory
        self._probe: _Probe | None = None

    # ---------------------- M4.13 bounded probe state machine ------------
    # This model deliberately has no executor import and no input method.
    # Runtime/skills may translate an emitted *requested action* through the
    # single existing active-skill/input boundary, or decline it for safety.
    def request_probe(self, *, probe_id: str, track_id: str | None,
                      baseline_confidence: float, at: float) -> dict:
        if self._probe and self._probe.state not in {"SUCCESS", "FAILED"}:
            if self._probe.probe_id == probe_id:
                return self.probe_snapshot()
            return {**self.probe_snapshot(), "accepted": False,
                    "reason": "active_probe_already_owned"}
        probe = _Probe(str(probe_id), str(track_id) if track_id is not None else None,
                       float(at), max(0., min(1., float(baseline_confidence))))
        probe.transition("REQUESTED", at, reason="information_gap")
        self._probe = probe
        return {**self.probe_snapshot(), "accepted": True}

    def select_probe_action(self, action: str, *, at: float) -> dict:
        probe = self._require_probe("REQUESTED")
        normalized = str(action).upper()
        if normalized not in _PROBE_ACTIONS:
            raise ValueError(f"unsupported active-perception action: {action}")
        probe.action = normalized
        probe.transition("SELECT_ACTION", at, action=normalized)
        return self.probe_snapshot()

    def mark_probe_dispatched(self, *, at: float, timeout: float = 1.5) -> dict:
        probe = self._require_probe("SELECT_ACTION")
        probe.transition("EXECUTE_PROBE", at, action=probe.action)
        probe.deadline = float(at) + max(.1, float(timeout))
        probe.transition("WAIT_OBSERVATION", at, deadline=probe.deadline)
        return self.probe_snapshot()

    def evaluate_probe(self, *, at: float, confidence: float | None,
                       combat_preempted: bool = False, higher_priority_preempted: bool = False) -> dict:
        probe = self._require_probe("WAIT_OBSERVATION")
        if combat_preempted or higher_priority_preempted:
            reason = "combat_safety_preemption" if combat_preempted else "higher_priority_preemption"
            probe.transition("FAILED", at, reason=reason)
            return self.probe_snapshot()
        if confidence is None:
            if probe.deadline is not None and at >= probe.deadline:
                probe.transition("FAILED", at, reason="observation_timeout")
            return self.probe_snapshot()
        current = max(0., min(1., float(confidence)))
        gain = current-probe.baseline_confidence
        probe.transition("EVALUATE_GAIN", at, observed_confidence=current,
                         information_gain=round(gain, 6))
        # A probe can be useful by reducing confidence in a tempting false
        # positive as well as by confirming it.  Both outcomes end the bounded
        # attempt; zero gain is explicit failure rather than an inspect loop.
        if abs(gain) >= .05:
            probe.transition("SUCCESS", at,
                             result="confidence_increased" if gain > 0 else "confidence_reduced")
        elif probe.deadline is not None and at >= probe.deadline:
            probe.transition("FAILED", at, reason="insufficient_information_gain")
        else:
            probe.transition("WAIT_OBSERVATION", at, reason="awaiting_more_evidence")
        return self.probe_snapshot()

    def probe_snapshot(self) -> dict:
        if self._probe is None:
            return {"state": "IDLE", "action_authority": "NONE", "input_sent": False}
        return {"probe_id": self._probe.probe_id, "track_id": self._probe.track_id,
                "state": self._probe.state, "action": self._probe.action,
                "baseline_confidence": self._probe.baseline_confidence,
                "deadline": self._probe.deadline, "history": list(self._probe.history),
                "action_authority": "NONE", "input_sent": False}

    def _require_probe(self, state: str) -> _Probe:
        if self._probe is None or self._probe.state != state:
            actual = self._probe.state if self._probe is not None else "IDLE"
            raise RuntimeError(f"active-perception transition requires {state}, got {actual}")
        return self._probe

    def evaluate(self, marker: dict, world, goal=None, *, recognition_candidates=None) -> dict:
        semantic = str(marker.get("semantic_type") or "UNKNOWN")
        uncertainty = 1. if semantic == "UNKNOWN" else .8 if semantic == "AMBIGUOUS" else .2
        hits = max(0., number(marker.get("stable_frames")) or 0.)
        stability = min(1., hits/3.)
        hypotheses = marker.get("detection_hypotheses") or {}
        contradiction = 1. if len(hypotheses) > 1 else 0.
        recognition = (recognition_candidates if recognition_candidates is not None
                       else world.query.recognition_candidates(marker.get("track_id")))
        novelty = 0. if recognition else 1.
        # EntityMemory can only offer an appearance-based hypothesis here. It
        # must improve which UNKNOWN track deserves a tooltip probe, never
        # change the track's semantic type or establish a live GUID.
        recognition_matches = [candidate for item in recognition
                               for candidate in item.get("entity_candidates", [])
                               if isinstance(candidate, dict)]
        recognition_strength = max((max(0., min(1., number(candidate.get("similarity")) or 0.))
                                    * min(1., (number(candidate.get("temporal_support_frames")) or 0.)/3.)
                                    for candidate in recognition_matches), default=0.)
        recognition_tracks = max((number(candidate.get("temporal_support_frames")) or 0.
                                  for candidate in recognition_matches), default=0.)
        detector = str(marker.get("detector_kind") or marker.get("kind") or "UNKNOWN")
        source = str(marker.get("source") or "UNKNOWN")
        relations = marker.get("visual_relations") or []
        overhead_relations = [r for r in relations if r.get("type") == "ABOVE"]
        supported_overhead = any(str(r.get("belief", "")).upper() == "SUPPORTED"
                                 for r in overhead_relations)
        candidate_overhead = bool(overhead_relations)
        appearance = marker.get("appearance") if isinstance(marker.get("appearance"), dict) else {}
        labels = {str(value).lower() for value in marker.get("candidate_labels") or ()}
        labels.update(str(value).lower() for value in appearance.get("anchor_candidate_labels") or ())
        visual_group = marker.get("visual_group") if isinstance(marker.get("visual_group"), dict) else {}
        labels.update(str(value).lower() for value in visual_group.get("appearance_labels") or ())
        badge_likeness = max(0., min(1., number(appearance.get("quest_badge_likeness")) or
                                     (1. if "quest_badge_like" in labels else 0.)))
        group_supported = str(visual_group.get("belief") or "UNKNOWN").upper() == "SUPPORTED"
        residual_motion = max(0., min(1., number(appearance.get("residual_motion_trend"))
                                      or number(appearance.get("residual_motion")) or 0.))
        geometry = max(0., min(1., number(appearance.get("body_geometry")) or 0.))
        foreground = max(0., min(1., number(appearance.get("foreground_contrast")) or 0.))
        center_relevance = max(0., min(1., number(appearance.get("screen_center_relevance")) or 0.))
        static_scene = max(0., min(1., number(appearance.get("static_scene_score")) or 0.))
        visual_scale = (number(marker.get("servo_scale_fraction"))
                        or number(marker.get("bbox_height_fraction")) or 0.)
        # This is screen-space approach evidence only. The Planner retains the
        # existing minimum-scale guard, and no world coordinate is inferred.
        interaction_readiness = (max(0., min(1., (visual_scale-.09)/.18))
                                 if source == "WORLD3D" else 0.)
        never_inspected = 1.0 if marker.get("last_inspected_at") is None else 0.0
        goal_relevance = .0
        if goal is not None:
            domain = str(getattr(goal, "domain", "") or "")
            if domain in {"QUEST", "COMBAT", "GATHER"} and source == "WORLD3D":
                goal_relevance = .6
        # A supported ABOVE relation says "something is over this subject",
        # not automatically "quest marker".  Preserve its value, but reserve
        # the full quest-directed boost for independently badge-like
        # appearance evidence.  This prevents a generic overhead fragment
        # from displacing a high-precision temporal memory probe.
        overhead_specificity = max(badge_likeness,
                                   1.0 if {"quest_badge_like", "quest_marker_like"} & labels else 0.0)
        overhead_value = (1.0 if supported_overhead and overhead_specificity >= .5
                          else .70 if supported_overhead else .45 if candidate_overhead
                          else .8 if marker.get("information_value") == "HIGH" else 0.0)
        self_avatar_hint = bool(appearance.get("self_avatar_suppression_hint"))
        visual_identity = (marker.get("visual_identity")
                           if isinstance(marker.get("visual_identity"), dict) else {})
        self_player_avatar = bool(
            marker.get("self_player_avatar") or appearance.get("self_player_avatar")
            or visual_identity.get("kind") == "SELF_PLAYER")
        self_avatar_suppressed = bool(
            self_player_avatar or (
                self_avatar_hint and not (candidate_overhead or group_supported
                                          or badge_likeness >= .5)))
        memory_probe_value = recognition_strength * (.35 + .65*goal_relevance)
        # Per-quest visual prototypes (user 2026-10-04): closer to this
        # quest's hover-confirmed targets than to rejected looks (corpses,
        # unrelated units) -> probe first; the reverse -> probe later.
        prototype_lift = max(-1., min(1., number(appearance.get("prototype_lift")) or 0.))
        # Remembered quest creatures (quest_creature_memory, user 2026-10-05):
        # looks like the giver/ender/objective creature the situation wants.
        creature_lift = max(-1., min(1., number(appearance.get("creature_memory_lift")) or 0.))
        sensor_weight, sensor_health = .5, "UNKNOWN"
        rejection = {"belief": "UNKNOWN", "confidence": 0.}
        if self.memory:
            profile = self.memory.sensor_profile(source, detector,
                self.memory.learning_context(world.state, "SENSOR"))
            if not profile["samples"]:
                profile = self.memory.sensor_profile(source, "*",
                    self.memory.learning_context(world.state, "SENSOR"))
            sensor_weight = profile["weight"] if profile["samples"] else .5
            sensor_health = profile["health"]
            rejection = self.memory.rejection_status(
                marker, map_id=world.state.get("map_id"),
                at=number(world.state.get("monotonic_time")) or world.last_received)
            if rejection.get("last_seen") is not None or rejection.get("failures", 0):
                never_inspected = 0.0
        # Information-gain ranking.  Appearance features improve which UNKNOWN
        # track to inspect; none of them establish its semantic identity.
        raw_gain = (.25*uncertainty + .13*stability + .12*novelty + .08*contradiction +
                    .13*overhead_value + .08*residual_motion + .06*geometry +
                    .05*foreground + .07*center_relevance + .045*goal_relevance +
                    .16*badge_likeness*goal_relevance + .08*float(group_supported) +
                    # A stable visual-memory match is not a reason to stop
                    # looking.  It is a high-value opportunity to resolve a
                    # current UNKNOWN track with a fresh mouseover.  The
                    # earlier .12 term merely cancelled the novelty loss and
                    # let generic overhead cues always win in live ranking.
                    .40*memory_probe_value + .07*interaction_readiness +
                    .03*never_inspected - .16*static_scene +
                    .30*prototype_lift*goal_relevance + .25*creature_lift*goal_relevance)
        if source in {"MINIMAP_CV", "WORLD_MAP_CV"}:
            # Preserve the established map-inspection priority. This is a
            # surface/context cue, not semantic marker recognition.
            raw_gain += .25
        gain = min(1., max(0., raw_gain) * (.6 + .4*sensor_weight))
        gain *= 1.-float(rejection.get("confidence", 0.))
        # The observation and UNKNOWN track survive. Only the attention cost
        # is suppressed for a probable self-avatar view; independent evidence
        # keeps an overlapping nearby NPC fully eligible.
        if self_avatar_suppressed:
            gain *= 0. if self_player_avatar else .03
        cursor = world.state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        mx, my = number(marker.get("x")), number(marker.get("y"))
        cursor_cost = .15 * math.hypot(mx-cx, my-cy) if None not in (cx, cy, mx, my) else .1
        cost = self.SOURCE_COST.get(source, .6) + .3 + cursor_cost
        if sensor_health == "DEGRADED":
            cost += .6
        utility = gain/max(.05, cost)
        return {"expected_information_gain": round(gain, 4), "cost": round(cost, 4),
                "utility": round(utility, 4), "uncertainty": uncertainty,
                "novelty": novelty, "stability": stability,
                "contradiction": contradiction, "sensor_weight": round(sensor_weight, 4),
                "sensor_health": sensor_health, "rejection": rejection,
                "world3d_features": {"residual_motion": round(residual_motion, 4),
                                     "body_geometry": round(geometry, 4),
                                     "foreground_contrast": round(foreground, 4),
                                     "screen_center_relevance": round(center_relevance, 4),
                                     "overhead_relation": bool(overhead_value),
                                     "overhead_relation_belief": ("SUPPORTED" if supported_overhead
                                                                  else "CANDIDATE" if candidate_overhead
                                                                  else "UNKNOWN"),
                                     "overhead_specificity": round(overhead_specificity, 4),
                                     "goal_context_relevance": round(goal_relevance, 4),
                                     "quest_badge_likeness": round(badge_likeness, 4),
                                     "visual_group_supported": group_supported,
                                     "self_avatar_region_overlap": round(
                                         number(appearance.get("self_avatar_region_overlap")) or 0., 4),
                                     "self_avatar_suppressed": self_avatar_suppressed,
                                     "self_player_avatar": self_player_avatar,
                                     "self_player_name": (appearance.get("self_player_name")
                                                          or marker.get("display_name")),
                                     "static_scene_score": round(static_scene, 4),
                                     "visual_scale": round(visual_scale, 4),
                                     "interaction_readiness": round(interaction_readiness, 4),
                                     "memory_recognition_strength": round(recognition_strength, 4),
                                     "memory_recognition_temporal_frames": int(recognition_tracks),
                                     "memory_probe_value": round(memory_probe_value, 4),
                                     "prototype_lift": round(prototype_lift, 4),
                                     "creature_memory_lift": round(creature_lift, 4),
                                     "never_inspected": bool(never_inspected)},
                "recommended_observation": "MOUSEOVER"}

    def rank_world3d(self, markers: list[dict], world, goal=None,
                     *, recognition_by_track: dict[str, list[dict]] | None = None,
                     limit: int = 5) -> list[dict]:
        """Return a passive, traceable World3D attention order.

        This is deliberately not a Planner proposal and has no action
        authority.  It exists so MANUAL-mode validation can inspect exactly
        which UNKNOWN tracks would be preferred for a future mouseover probe.
        """
        rows = []
        for marker in markers:
            if marker.get("source") != "WORLD3D":
                continue
            kind = str(marker.get("detector_kind") or marker.get("kind") or "")
            if "subject" not in kind or marker.get("inspectable") is False:
                continue
            track_id = str(marker.get("track_id") or "")
            recognition = ((recognition_by_track or {}).get(track_id)
                           if track_id else None)
            active = self.evaluate(marker, world, goal,
                                   recognition_candidates=recognition)
            rejection = active.get("rejection") or {}
            if str(rejection.get("belief") or "").upper() in {"REJECTED", "SUPPRESSED"}:
                continue
            rows.append({
                "track_id": track_id or None,
                "source": "WORLD3D",
                "semantic_type": "UNKNOWN",
                "detector_kind": kind,
                "utility": active["utility"],
                "expected_information_gain": active["expected_information_gain"],
                "cost": active["cost"],
                "world3d_features": active["world3d_features"],
                "recognition_candidate_count": len(recognition or []),
                "recommended_observation": active["recommended_observation"],
                "action_authority": "NONE",
            })
        return sorted(rows, key=lambda item: (-item["utility"], -item["expected_information_gain"],
                                               str(item["track_id"])))[:max(0, int(limit))]
