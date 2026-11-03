"""Field semantics decide authority; sensor tier alone cannot decide it."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from collections.abc import Iterable

from .evidence_contracts import Evidence, EvidenceCompleteness, EvidenceDirection, independent_evidence


class FieldResolutionState(StrEnum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    sources: tuple[str, ...]
    sampled: bool = False
    collection: bool = False


_LOCAL = ("ADDON_UI",)
_LIVE = ("SERVER", "ADDON_STATE", "MEMORY", "REFERENCE")
POLICIES = {
    "player_world_position": FieldPolicy(("SERVER", "CLIENT_FEEDBACK", "ADDON_STATE"), sampled=True),
    "orientation": FieldPolicy(("SERVER", "CLIENT_FEEDBACK", "ADDON_STATE"), sampled=True),
    "active_quests": FieldPolicy(("SERVER", "ADDON_STATE"), collection=True),
    "inventory": FieldPolicy(("SERVER", "ADDON_STATE"), collection=True),
    "target": FieldPolicy(_LOCAL, sampled=True),
    "mouseover": FieldPolicy(_LOCAL, sampled=True),
    "soft_targets": FieldPolicy(_LOCAL, sampled=True, collection=True),
    "quest_ui": FieldPolicy(_LOCAL, sampled=True),
    "actionbar": FieldPolicy(_LOCAL, sampled=True),
    "actionbar_fast": FieldPolicy(_LOCAL, sampled=True),
    "cursor_position": FieldPolicy(_LOCAL, sampled=True),
    "health": FieldPolicy(("SERVER", "ADDON_STATE"), sampled=True),
    "max_health": FieldPolicy(("SERVER", "ADDON_STATE"), sampled=True),
    "power": FieldPolicy(("SERVER", "ADDON_STATE"), sampled=True),
    'power_type': FieldPolicy(('SERVER', 'ADDON_STATE'), sampled=True),
    'max_power': FieldPolicy(('SERVER', 'ADDON_STATE'), sampled=True),
    'class_id': FieldPolicy(('SERVER', 'ADDON_STATE'), sampled=True),
    'player_class_id': FieldPolicy(('SERVER', 'ADDON_STATE'), sampled=True),
    'race_id': FieldPolicy(('SERVER', 'ADDON_STATE'), sampled=True),
    'level': FieldPolicy(('SERVER', 'ADDON_STATE'), sampled=True),
    'quest_log_slots': FieldPolicy(('SERVER',), sampled=True, collection=True),
    "entity_position": FieldPolicy(_LIVE),
    "objective_location": FieldPolicy(_LIVE),
    "quest_definition": FieldPolicy(_LIVE),
}


def authority(evidence: Evidence, key: str) -> str:
    if evidence.source == "PACKET_TELEMETRY" and evidence.lineage is not None:
        if evidence.confidence < 1. or not evidence.lineage.payload_layout:
            return "UNKNOWN"
        if evidence.lineage.direction is EvidenceDirection.SERVER_TO_CLIENT:
            return "SERVER"
        if evidence.lineage.direction is EvidenceDirection.CLIENT_TO_SERVER:
            return "CLIENT_FEEDBACK"
    if evidence.source in {"ADDON_TELEMETRY", "MOUSEOVER", "QUEST_STATE", "PLAYER_STATE", "UI_STATE"}:
        return "ADDON_UI" if key in {"target", "mouseover", "soft_targets", "quest_ui", "actionbar",
                                      "actionbar_fast", "cursor_position"} else "ADDON_STATE"
    if evidence.source == "REFERENCE_MEMORY":
        return "REFERENCE"
    if evidence.source in {"ENTITY_MEMORY", "SPATIAL_MEMORY", "SEMANTIC_MEMORY"}:
        return "MEMORY"
    return "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FieldResolution:
    state: FieldResolutionState
    winner: Evidence | None = None
    contradictions: tuple[Evidence, ...] = ()
    reason: str = "no_eligible_evidence"

    @property
    def value(self):
        return self.winner.value if self.winner is not None else None

    def diagnostic(self):
        return {"state": self.state.value, "source": self.winner.source if self.winner else None,
                "authority": authority(self.winner, self.winner.kind) if self.winner else "UNKNOWN",
                "observed_at": self.winner.observed_at if self.winner else None,
                "completeness": self.winner.completeness.value if self.winner else "UNKNOWN",
                "reason": self.reason, "contradictions": [e.observation_id for e in self.contradictions]}


class FieldSourceResolver:
    def resolve(self, key: str, evidence: Iterable[Evidence], now: float, *, context=None) -> FieldResolution:
        policy = POLICIES.get(key)
        if policy is None and isinstance(key, str) and key.startswith(('resource_power:', 'resource_max_power:')):
            prefix, kind = key.split(':', 1)
            if kind.isascii() and kind.isdigit() and 0 <= int(kind) <= 255:
                policy = POLICIES['max_power' if prefix == 'resource_max_power' else 'power']
        if policy is None:
            return FieldResolution(FieldResolutionState.UNKNOWN, reason="unregistered_field")
        eligible = []
        for item in evidence:
            if not item.is_fresh(now) or authority(item, key) not in policy.sources:
                continue
            if context is not None:
                scope = json.loads(item.context_json)
                if any(scope.get(name) != value for name, value in context.items()):
                    continue
            value = item.value
            if policy.collection and value in ([], {}, None) and item.completeness is not EvidenceCompleteness.COMPLETE:
                continue  # an omitted/truncated list does not prove absence
            eligible.append(item)
        def rank(item):
            source = -policy.sources.index(authority(item, key))
            return ((item.observed_at, source) if policy.sampled else (source, item.observed_at))
        ranked = independent_evidence(eligible, priority_key=rank)
        ranked.sort(key=rank, reverse=True)
        if not ranked:
            return FieldResolution(FieldResolutionState.UNKNOWN)
        best = ranked[0]
        contradictions = tuple(e for e in ranked[1:] if e.value_json != best.value_json)
        if any(rank(e) == rank(best) for e in contradictions):
            return FieldResolution(FieldResolutionState.CONFLICT, None, contradictions,
                                   "same_authority_same_sample_conflict")
        partial = policy.collection and best.completeness is not EvidenceCompleteness.COMPLETE
        return FieldResolution(FieldResolutionState.PARTIAL if partial else FieldResolutionState.KNOWN,
                               best, contradictions, "field_policy")


def belief_projection(resolution: FieldResolution):
    best = resolution.winner
    if best is None:
        return {"status": "AMBIGUOUS" if resolution.state is FieldResolutionState.CONFLICT else "UNKNOWN",
                "value": None, "evidence": [], "resolution": resolution.diagnostic()}
    entries = (best, *resolution.contradictions)
    authority_kind = authority(best, best.kind)
    return {"status": "CONFIRMED" if authority_kind in {"SERVER", "ADDON_UI", "ADDON_STATE"}
            and resolution.state is FieldResolutionState.KNOWN else "SUPPORTED",
            "value": best.value, "source": best.source, "confidence": best.confidence*best.reliability,
            "sensor_tier": best.sensor_tier, "sensor_tier_rank": best.tier_rank,
            "resolution": {"status": "RESOLVED", "method": "FIELD_SOURCE_POLICY", **resolution.diagnostic()},
            "evidence": [e.observation_id for e in entries], "supporting_evidence": [best.observation_id],
            "contradictions": [e.observation_id for e in resolution.contradictions],
            "provenance": best.lineage.as_dict(limit=8) if best.lineage else None,
            "context": json.loads(best.context_json), "completeness": best.completeness.value,
            "source_reliability": {e.source: e.reliability for e in entries},
            "correlation_groups": sorted({e.correlation_id for e in entries}),
            "independence_groups": sorted({e.independence_group for e in entries}),
            "evidence_hierarchy": [{"observation_id": e.observation_id, "source": e.source,
                                    "authority": authority(e, best.kind), "tier": e.sensor_tier,
                                    "tier_rank": e.tier_rank, "observed_at": e.observed_at,
                                    "received_at": e.received_at, "completeness": e.completeness.value}
                                   for e in entries]}
