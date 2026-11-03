"""WorldModel evidence, beliefs and their lifecycle events.

Split out of world.py (2026-10-05, module-size gate); unchanged.
"""
from __future__ import annotations
from collections import deque
from dataclasses import field
from .models import Observation, canonical, number
from .world_models import Belief, ContradictionRecord, Evidence
from .evidence_factory import evidence_from_observation
from wowbot.evidence_contracts import EvidenceValidity, finite_time, independent_evidence


RELIABILITY = {"ADDON_TELEMETRY": 1., "MOUSEOVER": 1., "TOOLTIP": .9,
               "ENTITY_MEMORY": .7, "SPATIAL_MEMORY": .7, "SEMANTIC_MEMORY": .7, "WORLD_MAP_CV": .6,
               "MINIMAP_CV": .55, "WORLD3D": .55, "WORLD3D_LOCAL_VIEW": .55, "UI_CV": .58, "VISION": .55,
               "CROSS_VIEW": .55, "AI": .3, "REFERENCE_MEMORY": .3,
               "QUEST_STATE": 1., "PLAYER_STATE": 1., "PACKET_TELEMETRY": 1.}


SENSOR_TIERS = {
    "GROUND_TRUTH": 4,
    "STRONG": 3,
    "PERCEPTION": 2,
    "REASONING": 1,
    "UNKNOWN": 0,
}


SOURCE_TIERS = {
    "ADDON_TELEMETRY": "GROUND_TRUTH", "MOUSEOVER": "GROUND_TRUTH",
    "TOOLTIP": "GROUND_TRUTH", "QUEST_STATE": "GROUND_TRUTH",
    "PLAYER_STATE": "GROUND_TRUTH", "WORLD_MAP": "STRONG",
    "ENTITY_MEMORY": "STRONG", "SPATIAL_MEMORY": "STRONG",
    "SEMANTIC_MEMORY": "STRONG", "MINIMAP_CV": "PERCEPTION",
    "WORLD_MAP_CV": "PERCEPTION", "WORLD3D": "PERCEPTION", "WORLD3D_LOCAL_VIEW": "PERCEPTION", "UI_CV": "PERCEPTION",
    "VISION": "PERCEPTION", "CROSS_VIEW": "PERCEPTION", "AI": "REASONING", "VLM": "REASONING",
    "PREDICTION": "REASONING",
    "REFERENCE_MEMORY": "REASONING",
    "PACKET_TELEMETRY": "STRONG",  # only typed, verified reducer claims have confidence
}

CORRELATED_FRAME_SOURCES = frozenset({
    "MINIMAP_CV", "WORLD_MAP_CV", "WORLD3D", "WORLD3D_LOCAL_VIEW", "UI_CV", "VISION",
    "CROSS_VIEW", "AI", "VLM",
})


# These fields describe a continuously changing sampled state, not durable
# semantic claims.  Comparing the last two seconds of camera positions,
# candidate lists or traversability rasters as if they were mutually exclusive
# facts manufactured thousands of BELIEF_CHANGED/CONTRADICTION events per
# minute.  They remain normal evidence and remain queryable; only the durable
# *lifecycle event* projection is suppressed.  Their real transitions already
# have dedicated events/reducers (TARGET_CHANGED, combat, UI and track events).
TEMPORAL_STATE_BELIEF_KEYS = frozenset({
    "active_perception_ranking", "camera_state", "is_in_combat",
    "local_traversability", "map_mouseover", "mouseover", "movement",
    "orientation", "player_world_position", "position", "scene_geometry",
    "soft_targets", "spawn_reference_candidates",
    "tooltip_observation", "ui_observations", "visual_candidates",
    "world_map_state", "reference_knowledge",
})


class WorldBeliefMixin:
    """Methods of WorldModel (world.py); moved verbatim."""

    def _update_track_lifecycle(self, obs: Observation):
        if "visual_candidates" not in obs.payload:
            return
        active = self.track_lifecycle.setdefault(obs.source, {})
        seen = set()
        for item in obs.payload.get("visual_candidates", []):
            track_id = item.get("track_id")
            if not track_id:
                continue
            seen.add(track_id)
            state = str(item.get("track_state") or
                        ("STABLE" if (number(item.get("stable_frames")) or 0) >= 3 else "TENTATIVE"))
            prior = active.get(track_id)
            active[track_id] = {"state": state, "misses": int(number(item.get("missing_frames")) or 0),
                                "kind": item.get("detector_kind") or item.get("kind")}
            if prior is None:
                self._emit_derived_event("VISUAL_TRACK_APPEARED",
                    {"track_id": track_id, "surface": obs.source, "state": state}, obs)
            elif prior["state"] not in {"STABLE", "ACTIVE"} and state in {"STABLE", "ACTIVE"}:
                self._emit_derived_event("VISUAL_TRACK_STABILIZED",
                    {"track_id": track_id, "surface": obs.source, "state": state}, obs)
            if prior and state == "OCCLUDED" and prior["state"] != "OCCLUDED":
                self._emit_derived_event("TRACK_OCCLUDED",
                    {"track_id": track_id, "surface": obs.source}, obs)
            if prior and state == "REACQUIRE_CANDIDATE" and prior["state"] in {"OCCLUDED", "LOST_TEMPORARY"}:
                self._emit_derived_event("TRACK_REACQUIRE_CANDIDATE",
                    {"track_id": track_id, "surface": obs.source,
                     "identity_status": "CANDIDATE"}, obs)
        for track_id in list(active):
            if track_id in seen:
                continue
            active[track_id]["misses"] += 1
            if active[track_id]["misses"] >= 3:
                self._emit_derived_event("VISUAL_TRACK_LOST",
                    {"track_id": track_id, "surface": obs.source,
                     "previous_state": active[track_id]["state"]}, obs)
                del active[track_id]

    def _update_belief_lifecycle(self, obs: Observation, keys):
        for key in keys:
            if key in TEMPORAL_STATE_BELIEF_KEYS or key.startswith("world3d_"):
                continue
            belief = self.belief(key, obs.received_at)
            identity = (belief["status"], canonical(belief.get("value")))
            prior = self.last_beliefs.get(key)
            self.last_beliefs[key] = identity
            if prior is not None and prior != identity:
                self._emit_derived_event("BELIEF_CHANGED", {
                    "belief_key": key, "previous_status": prior[0],
                    "status": identity[0], "supporting_observations": belief.get("evidence", [])}, obs)
            contradictions = tuple(belief.get("contradictions") or ())
            contradiction_status = "AMBIGUOUS" if belief["status"] == "AMBIGUOUS" else (
                "RESOLVED" if contradictions else "NONE")
            contradiction_identity = (contradiction_status, contradictions)
            old_contradiction = self.contradiction_state.get(key)
            if contradictions and contradiction_identity != old_contradiction:
                resolution = str((belief.get("resolution") or {}).get("method") or "UNRESOLVED")
                self.contradiction_history.append(ContradictionRecord(
                    key, contradiction_status, resolution, canonical(belief.get("value")),
                    tuple(belief.get("supporting_evidence") or ()), contradictions, obs.received_at))
                self._emit_derived_event(
                    "CONTRADICTION_DETECTED" if contradiction_status == "AMBIGUOUS" else "CONTRADICTION_RESOLVED",
                    {"belief_key": key, "status": contradiction_status, "resolution": resolution,
                     "support": list(belief.get("supporting_evidence") or ()),
                     "contradictions": list(contradictions)}, obs)
            elif old_contradiction and old_contradiction[0] == "AMBIGUOUS" and not contradictions:
                self.contradiction_history.append(ContradictionRecord(
                    key, "RESOLVED", "NEW_EVIDENCE", canonical(belief.get("value")),
                    tuple(belief.get("supporting_evidence") or ()), old_contradiction[1], obs.received_at))
                self._emit_derived_event("CONTRADICTION_RESOLVED", {
                    "belief_key": key, "status": "RESOLVED", "resolution": "NEW_EVIDENCE",
                    "contradictions": list(old_contradiction[1])}, obs)
            self.contradiction_state[key] = contradiction_identity

    def add_evidence(self, key: str, value, obs: Observation, confidence: float = 1., ttl: float = 5.,
                     *, observed_at: float | None = None):
        entries = self.evidence.setdefault(key, deque(maxlen=20))
        if any(e.correlation_id == obs.correlation_id and e.source == obs.source for e in entries):
            return
        dynamic = self.reliability_provider(obs.source, self.addon_state) if self.reliability_provider else None
        reliability = dynamic if dynamic is not None else RELIABILITY.get(obs.source, .4)
        reliability = max(0., min(1., float(reliability)))
        sensor_tier = SOURCE_TIERS.get(obs.source, "UNKNOWN")
        provenance = obs.payload.get("provenance") or {}
        provenance = provenance if isinstance(provenance, dict) else {}
        independence_group = str(provenance.get("independence_group") or
                                 (obs.correlation_id if obs.source in CORRELATED_FRAME_SOURCES
                                  else obs.observation_id))
        entries.append(evidence_from_observation(key, value, obs, confidence, reliability,
            sensor_tier, SENSOR_TIERS[sensor_tier], independence_group, ttl=ttl, previous=entries,
            observed_at=observed_at))

    @staticmethod
    def _diagnostic_claim_value(key: str, value):
        """Bound collection claims without discarding their typed item evidence.

        Full visual candidates stay in the source projection and each track gets
        its own evidence claim below. The aggregate collection belief only needs
        identity/type/lifecycle metadata; embedding complete 32-frame histories
        recursively inflated contradiction records.
        """
        if key == "visual_candidates" and isinstance(value, list):
            return [{field: item.get(field) for field in
                     ("track_id", "source", "detector_kind", "kind", "semantic_type",
                      "belief", "confidence", "stable_frames", "lifecycle", "inspectable")}
                    for item in value if isinstance(item, dict)]
        if key == "visual_recognition_candidates" and isinstance(value, list):
            return [{"track_id": item.get("track_id"), "surface": item.get("surface"),
                     "appearance_signature_id": item.get("appearance_signature_id"),
                     "entity_candidates": [{field: candidate.get(field) for field in
                         ("identity_key", "status", "reliability", "similarity", "match_method")}
                        for candidate in item.get("entity_candidates", []) if isinstance(candidate, dict)]}
                    for item in value if isinstance(item, dict)]
        if key == "active_perception_ranking" and isinstance(value, list):
            return [{field: item.get(field) for field in
                     ("track_id", "source", "semantic_type", "detector_kind", "utility",
                      "expected_information_gain", "cost", "recognition_candidate_count",
                      "recommended_observation", "action_authority")}
                    for item in value if isinstance(item, dict)]
        return value

    def belief(self, key: str, now: float) -> dict:
        from .packet_continuity import eligible_evidence
        entries = list(eligible_evidence(self, self.evidence.get(key, ())))
        from wowbot.field_sources import POLICIES, FieldSourceResolver, belief_projection
        if key in POLICIES and any(e.is_fresh(now) for e in entries):
            return belief_projection(FieldSourceResolver().resolve(key, entries, now,
                context={"session_id": self.session_id}))
        active = [e for e in entries if e.is_fresh(now)]
        if not active:
            return {"status": "STALE" if any(e.validity(now) is EvidenceValidity.EXPIRED for e in entries)
                    else "UNKNOWN", "value": None, "evidence": []}
        # Several visual/AI passes over one captured frame are correlated. Keep
        # only the strongest vote in such a group rather than manufacturing
        # independent support from the same pixels.
        ranked = sorted(independent_evidence(active),
                        key=lambda e: (e.tier_rank, e.reliability * e.confidence, e.at), reverse=True)
        winning_rank = ranked[0].tier_rank
        peers = [entry for entry in ranked if entry.tier_rank == winning_rank]
        value_scores: dict[str, float] = {}
        for entry in peers:
            value_scores[entry.value_json] = value_scores.get(entry.value_json, 0.) + entry.reliability*entry.confidence
        values = sorted(value_scores.items(), key=lambda item: item[1], reverse=True)
        best_value, best_score = values[0]
        best = max((entry for entry in peers if entry.value_json == best_value), key=lambda e: e.at)
        contradictions = [e for e in ranked if e.value_json != best_value]
        supporting = [e for e in ranked if e.value_json == best_value]
        peer_competitor = values[1][1] if len(values) > 1 else 0.
        ambiguous = peer_competitor > 0 and abs(best_score-peer_competitor) <= max(.1, .15*best_score)
        lower_tier_only = bool(contradictions) and all(e.tier_rank < winning_rank for e in contradictions)
        support_groups = len({entry.independence_group for entry in supporting})
        effective_tier = "STRONG" if best.sensor_tier == "PERCEPTION" and support_groups >= 3 else best.sensor_tier
        resolution = ({"status": "UNRESOLVED", "method": "EQUAL_TIER_CONFLICT"}
                      if ambiguous else
                      {"status": "RESOLVED", "method": "HIGHER_SENSOR_TIER"}
                      if lower_tier_only else
                      {"status": "RESOLVED", "method": "WEIGHTED_SUPPORT"}
                      if contradictions else {"status": "NONE", "method": "NO_CONTRADICTION"})
        import json
        return {"status": "AMBIGUOUS" if ambiguous else "CONFIRMED" if best.sensor_tier == "GROUND_TRUTH" else "SUPPORTED",
                "value": json.loads(best.value_json), "source": best.source,
                "confidence": min(1., best_score), "sensor_tier": effective_tier,
                "sensor_tier_rank": SENSOR_TIERS[effective_tier], "resolution": resolution,
                "evidence": [e.observation_id for e in ranked],
                "supporting_evidence": [e.observation_id for e in supporting],
                "contradictions": [e.observation_id for e in contradictions],
                "source_reliability": {e.source: e.reliability for e in ranked},
                "evidence_hierarchy": [{"observation_id": e.observation_id, "source": e.source,
                                        "tier": e.sensor_tier, "tier_rank": e.tier_rank,
                                        "weighted_confidence": e.reliability*e.confidence,
                                        "observed_at": e.observed_at, "received_at": e.received_at,
                                        "completeness": e.completeness.value}
                                       for e in ranked],
                "correlation_groups": sorted({e.correlation_id for e in ranked}),
                "independence_groups": sorted({e.independence_group for e in ranked}),
                # Detailed metadata once for the chosen value; all immutable
                # records remain available through WorldQuery.evidence().
                "provenance": best.lineage.as_dict(limit=8) if best.lineage else None,
                "context": json.loads(best.context_json)}

    def typed_belief(self, key: str, now: float) -> Belief:
        """Typed read projection; legacy dict callers remain source-compatible."""
        return Belief.from_projection(key, self.belief(key, now))

    def prune_expired_evidence(self, now: float) -> int:
        """Drop evidence keys with no still-active entry.

        Each key's own deque is already TTL-bounded, but the outer dict
        (one key per distinct field, plus one per distinct visual track ever
        seen this session) was never trimmed, growing for the life of a long
        session. Called periodically from runtime maintenance, not every
        tick -- snapshot()'s own beliefs projection separately skips dead
        keys on every call regardless of when this last ran.
        """
        if not finite_time(now):
            return 0
        dead = [k for k, entries in self.evidence.items() if not any(
            e.validity(now) in {EvidenceValidity.VALID, EvidenceValidity.FUTURE} for e in entries)]
        for k in dead:
            del self.evidence[k]
        return len(dead)
