"""Short-lived local visual memory for World3D reacquisition evidence."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(slots=True)
class VisualMemoryEntry:
    track_id: str
    visual_signature: dict[str, Any]
    last_known_local_bearing: dict[str, Any]
    last_seen_bbox: dict[str, Any]
    confirmed_identity_linkage: dict[str, Any] | None
    remembered_at: float


class World3DVisualMemory:
    """Bounded, TTL-limited memory; never stores world coordinates."""

    def __init__(self, *, ttl_seconds: float = 12., max_entries: int = 64) -> None:
        self.ttl_seconds = max(.5, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._entries: deque[VisualMemoryEntry] = deque(maxlen=self.max_entries)

    def reset(self) -> None:
        self._entries.clear()

    def remember_track(self, track: dict[str, Any], *, now: float) -> None:
        signature = track.get("visual_signature")
        if not isinstance(signature, dict) or signature.get("invalid"):
            return
        track_id = str(track.get("track_id") or "")
        if not track_id:
            return
        identity = track.get("identity_belief") or {}
        linkage = None
        if identity.get("state") == "CONFIRMED" and identity.get("identity"):
            linkage = {"identity": identity["identity"],
                       "confidence": identity.get("confidence", 0.),
                       "fact": bool(identity.get("fact")),
                       "evidence_refs": list(identity.get("evidence_refs") or ())}
        self._entries = deque((entry for entry in self._entries
                               if entry.track_id != track_id), maxlen=self.max_entries)
        self._entries.append(VisualMemoryEntry(
            track_id, deepcopy(signature), deepcopy(track.get("bearing") or {}),
            deepcopy(track.get("bbox") or {}), linkage, float(now)))

    def expire_recent_visual_memory(self, *, now: float) -> int:
        before = len(self._entries)
        self._entries = deque((entry for entry in self._entries
                               if now-entry.remembered_at <= self.ttl_seconds),
                              maxlen=self.max_entries)
        return before-len(self._entries)

    def match_recent_signature(self, signature: dict[str, Any], *, now: float,
                               exclude_track_id: str | None = None
                               ) -> dict[str, Any] | None:
        self.expire_recent_visual_memory(now=now)
        scored = []
        for entry in self._entries:
            if exclude_track_id and entry.track_id == exclude_track_id:
                continue
            distance = self._signature_distance(entry.visual_signature, signature)
            if distance is not None and distance <= .18:
                scored.append((distance, entry))
        scored.sort(key=lambda pair: pair[0])
        if not scored or (len(scored) > 1 and scored[1][0]-scored[0][0] < .025):
            return None
        distance, entry = scored[0]
        return {
            "prior_track_id": entry.track_id,
            "visual_similarity": round(1.-distance, 4),
            "last_known_local_bearing": deepcopy(entry.last_known_local_bearing),
            "last_seen_bbox": deepcopy(entry.last_seen_bbox),
            # This is a linkage hypothesis; consumers still need current
            # ground truth before confirming the new track's identity.
            "confirmed_identity_linkage": deepcopy(entry.confirmed_identity_linkage),
            "memory_age_seconds": round(max(0., now-entry.remembered_at), 4),
            "semantic_fact": False,
        }

    def reacquire_candidate(self, candidate: dict[str, Any], *, now: float
                            ) -> dict[str, Any] | None:
        signature = candidate.get("visual_signature")
        if not isinstance(signature, dict):
            return None
        return self.match_recent_signature(
            signature, now=now, exclude_track_id=str(candidate.get("track_id") or ""))

    def update_tracks(self, tracks: Iterable[dict[str, Any]], *, now: float
                      ) -> list[dict[str, Any]]:
        self.expire_recent_visual_memory(now=now)
        output = []
        for source in tracks:
            track = deepcopy(source)
            match = self.reacquire_candidate(track, now=now)
            if match:
                track["visual_memory_match"] = match
            self.remember_track(track, now=now)
            output.append(track)
        return output

    @staticmethod
    def _signature_distance(left: dict[str, Any], right: dict[str, Any]) -> float | None:
        if (left.get("representation_space") != right.get("representation_space")
                or not isinstance(left.get("appearance"), dict)
                or not isinstance(right.get("appearance"), dict)):
            return None
        if left.get("signature_id") and left.get("signature_id") == right.get("signature_id"):
            return 0.
        values = []
        for key in ("brightness_bin", "saturation_bin", "red_bin", "green_bin",
                    "blue_bin", "fill_bin"):
            a, b = left["appearance"].get(key), right["appearance"].get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                values.append(abs(float(a)-float(b))/31.)
        left_shape, right_shape = left.get("shape") or {}, right.get("shape") or {}
        for key in ("w_bin", "h_bin"):
            a, b = left_shape.get(key), right_shape.get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                values.append(abs(float(a)-float(b))/31.)
        if len(values) < 6:
            return None
        return sum(values)/len(values)

