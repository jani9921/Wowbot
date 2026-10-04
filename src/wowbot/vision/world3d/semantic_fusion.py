"""Evidence-based World3D semantic fusion with freshness and hysteresis.

Raw CV never enters this component as ground truth.  It accepts normalized
cross-sensor evidence supplied by the WorldModel/telemetry adapters and keeps
appearance, role, type and identity distinct.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable


FIELDS = {"type", "role", "identity", "hostility", "alive", "interactability"}
TTL_SECONDS = {
    "type": 4.0, "role": 4.0, "identity": 12.0,
    "hostility": 2.0, "alive": 2.0, "interactability": 2.0,
}
SOURCE_RELIABILITY = {
    "TOOLTIP": .98,
    "MOUSEOVER_TELEMETRY": .98,
    "TARGET_TELEMETRY": .96,
    "QUEST_TELEMETRY": .95,
    "ADDON_TELEMETRY": .94,
    "COMBAT_LOG": .94,
    "MINIMAP_ASSOCIATION": .55,
    "WORLD_MAP_ASSOCIATION": .52,
    "VISUAL_MEMORY": .48,
    "WORLD3D_APPEARANCE": .42,
    "WORLD3D_CV": .38,
}
SINGLE_FRAME_RELIABLE = {
    "TOOLTIP", "MOUSEOVER_TELEMETRY", "TARGET_TELEMETRY",
    "QUEST_TELEMETRY", "ADDON_TELEMETRY", "COMBAT_LOG",
}


def _clamp(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number if math.isfinite(number) else 0.0))


@dataclass(slots=True)
class _RetainedBelief:
    label: str
    confidence: float
    last_seen: float
    evidence_refs: tuple[str, ...] = ()
    fact: bool = False


class SemanticEvidenceFusion:
    ACCEPT_THRESHOLD = .85
    RETAIN_THRESHOLD = .65
    STRONG_CONTRADICTION = .90

    def __init__(self) -> None:
        self._retained: dict[tuple[str, str], _RetainedBelief] = {}
        self._support_counts: dict[tuple[str, str, str], int] = {}

    def reset(self) -> None:
        self._retained.clear()
        self._support_counts.clear()

    def fuse(self, track_id: str, evidence: Iterable[dict[str, Any]], *, now: float
             ) -> dict[str, Any]:
        rows = self._normalize(track_id, evidence, now)
        present_keys = {(track_id, row["field"], row["label"]) for row in rows}
        for key in list(self._support_counts):
            if key[0] == track_id and key not in present_keys:
                del self._support_counts[key]
        for key in present_keys:
            self._support_counts[key] = self._support_counts.get(key, 0)+1

        output: dict[str, Any] = {
            "type_beliefs": [], "role_beliefs": [],
            "identity_belief": self._unknown("identity"),
            "hostility_belief": self._unknown("hostility"),
            "alive_belief": self._unknown("alive"),
            "interactability": self._unknown("interactability"),
            "evidence_refs": [], "field_freshness": {},
        }
        for field_name in FIELDS:
            field_rows = [row for row in rows if row["field"] == field_name]
            beliefs = self._scores(track_id, field_name, field_rows, now)
            selected, freshness = self._select(track_id, field_name, beliefs, now)
            output["field_freshness"][field_name] = freshness
            if field_name in {"type", "role"}:
                rendered = []
                for belief in beliefs:
                    rendered.append({
                        "label": belief["label"], "confidence": belief["confidence"],
                        "belief": "CONFIRMED" if selected and selected.label == belief["label"] else "CANDIDATE",
                        "source": "EVIDENCE_FUSION", "sources": belief["sources"],
                        "evidence_refs": belief["evidence_refs"],
                        "fact": bool(selected and selected.label == belief["label"] and selected.fact),
                    })
                output[f"{field_name}_beliefs"] = rendered
            else:
                key = "identity" if field_name == "identity" else "label"
                output_key = "identity_belief" if field_name == "identity" else (
                    "interactability" if field_name == "interactability" else f"{field_name}_belief")
                if selected:
                    output[output_key] = {
                        key: selected.label,
                        "state": "CONFIRMED", "confidence": round(selected.confidence, 4),
                        "evidence_refs": list(selected.evidence_refs), "fact": selected.fact,
                    }
            if selected:
                output["evidence_refs"].extend(selected.evidence_refs)
        output["evidence_refs"] = sorted(set(output["evidence_refs"]))
        return output

    def _normalize(self, track_id: str, evidence: Iterable[dict[str, Any]],
                   now: float) -> list[dict[str, Any]]:
        result = []
        for index, source_row in enumerate(evidence):
            row = dict(source_row)
            if str(row.get("track_id") or "") != track_id:
                continue
            field_name = str(row.get("field") or "").lower()
            label = str(row.get("label") or row.get("value") or "").strip()
            source = str(row.get("source") or "UNKNOWN").upper()
            if field_name not in FIELDS or not label:
                continue
            observed_at = float(row.get("observed_at", now))
            age = max(0., now-observed_at)
            ttl = TTL_SECONDS[field_name]
            if age > ttl:
                continue
            freshness = "FRESH" if age <= ttl*.5 else "STALE"
            freshness_factor = 1. if freshness == "FRESH" else max(.65, 1.-.35*age/ttl)
            reliability = _clamp(row.get("source_reliability", SOURCE_RELIABILITY.get(source, .35)))
            confidence = _clamp(row.get("confidence"))*reliability*freshness_factor
            evidence_id = str(row.get("evidence_id") or f"{source}:{field_name}:{label}:{index}")
            result.append({
                "field": field_name, "label": label, "source": source,
                "confidence": _clamp(confidence), "freshness": freshness,
                "observed_at": observed_at, "evidence_id": evidence_id,
                "fact": bool(row.get("ground_truth") or row.get("fact")),
                "single_frame_reliable": source in SINGLE_FRAME_RELIABLE,
            })
        return result

    def _scores(self, track_id: str, field_name: str, rows: list[dict[str, Any]],
                now: float) -> list[dict[str, Any]]:
        by_label: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            count = self._support_counts.get((track_id, field_name, row["label"]), 0)
            # Low-reliability single-frame hints remain visible candidates but
            # cannot cross the confirm threshold until temporally repeated.
            if not row["single_frame_reliable"] and count < 2:
                row = {**row, "confidence": min(row["confidence"], .64)}
            by_label.setdefault(row["label"], []).append(row)
        scored = []
        for label, supporting in by_label.items():
            combined_miss = 1.0
            for row in supporting:
                combined_miss *= 1.-row["confidence"]
            confidence = 1.-combined_miss
            alternatives = [row["confidence"] for other, entries in by_label.items()
                            if other != label for row in entries]
            contradiction = max(alternatives, default=0.)
            effective = _clamp(confidence*(1.-.55*contradiction))
            scored.append({
                "label": label, "confidence": round(effective, 4),
                "raw_agreement": round(confidence, 4),
                "contradiction_penalty": round(.55*contradiction, 4),
                "sources": sorted({row["source"] for row in supporting}),
                "evidence_refs": sorted({row["evidence_id"] for row in supporting}),
                "fact": any(row["fact"] for row in supporting),
                "latest": max(row["observed_at"] for row in supporting),
                "strongest": max(row["confidence"] for row in supporting),
            })
        return sorted(scored, key=lambda row: (-row["confidence"], row["label"]))

    def _select(self, track_id: str, field_name: str, beliefs: list[dict[str, Any]],
                now: float) -> tuple[_RetainedBelief | None, str]:
        key = (track_id, field_name)
        current = self._retained.get(key)
        best = beliefs[0] if beliefs else None
        current_score = next((row for row in beliefs if current and row["label"] == current.label), None)
        strong_contradiction = bool(best and current and best["label"] != current.label
                                    and best["strongest"] >= self.STRONG_CONTRADICTION)
        chosen = None
        if best and ((best["confidence"] >= self.ACCEPT_THRESHOLD and (
                current is None or best["label"] == current.label))
                or strong_contradiction):
            chosen = best
        elif current_score and current_score["confidence"] >= self.RETAIN_THRESHOLD:
            chosen = current_score
        elif current and not strong_contradiction:
            age = max(0., now-current.last_seen)
            ttl = TTL_SECONDS[field_name]
            if age <= ttl:
                retained_confidence = current.confidence*(1.-.35*age/ttl)
                if retained_confidence >= self.RETAIN_THRESHOLD:
                    retained = _RetainedBelief(current.label, retained_confidence,
                                               current.last_seen, current.evidence_refs,
                                               current.fact)
                    self._retained[key] = retained
                    return retained, "FRESH" if age <= ttl*.5 else "STALE"
        if chosen:
            retained = _RetainedBelief(
                chosen["label"], chosen["confidence"], chosen["latest"],
                tuple(chosen["evidence_refs"]), bool(chosen["fact"]))
            self._retained[key] = retained
            age = max(0., now-retained.last_seen)
            return retained, "FRESH" if age <= TTL_SECONDS[field_name]*.5 else "STALE"
        self._retained.pop(key, None)
        return None, "EXPIRED" if not beliefs else "UNCONFIRMED"

    @staticmethod
    def _unknown(field_name: str) -> dict[str, Any]:
        key = "identity" if field_name == "identity" else "label"
        return {key: None, "state": "UNKNOWN", "confidence": 0.,
                "evidence_refs": [], "fact": False}
