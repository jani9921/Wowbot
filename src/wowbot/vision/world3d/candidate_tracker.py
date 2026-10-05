"""Conservative IoU/appearance World3D candidate tracker (legacy association, BoT-SORT bridge).

Split out of tracking.py (2026-10-05); unchanged and re-exported there.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any
from .models import PixelRect, WorldCandidate
from .association import linear_sum_assignment


@dataclass(slots=True)
class _TrackState:
    track_id: int
    kind: str
    center_x: float
    center_y: float
    relation: str | None
    class_name: str | None
    last_seen: int
    misses: int = 0
    width: float = 1.0
    height: float = 1.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    hits: int = 1
    appearance: dict[str, object] | None = None
    residual_history: tuple[float, ...] = ()
    observed_at: float | None = None
    lost_since: float | None = None


class WorldCandidateTracker:
    """Camera-aware UNKNOWN visual tracker.

    Association combines predicted position, scale and appearance evidence.
    A match only preserves visual identity; it never recognizes an entity.
    """

    def __init__(self, max_distance: float = 45.0, max_misses: int = 2) -> None:
        self.max_distance = float(max_distance)
        self.max_misses = int(max_misses)
        self._next_id = 1
        self._tracks: dict[int, _TrackState] = {}
        self._lost: dict[int, _TrackState] = {}
        self.frame_index = 0

    @staticmethod
    def _snapshot(track: _TrackState) -> dict[str, object]:
        return {
            "track_id": track.track_id, "kind": track.kind,
            "position": {"x": track.center_x, "y": track.center_y},
            "velocity": {"x": track.velocity_x, "y": track.velocity_y},
            "bbox": {"width": track.width, "height": track.height},
            "appearance_signature": dict(track.appearance or {}),
            "confidence": min(1., .35 + .1 * track.hits),
            "hits": track.hits, "missing_frames": track.misses,
            "last_seen_frame": track.last_seen, "observed_at": track.observed_at,
            "lost_since": track.lost_since,
        }

    def get_track(self, track_id: int) -> dict[str, object] | None:
        track = self._tracks.get(int(track_id)) or self._lost.get(int(track_id))
        return self._snapshot(track) if track else None

    def recent_tracks(self) -> tuple[dict[str, object], ...]:
        return tuple(self._snapshot(track) for track in self._tracks.values())

    def lost_tracks(self) -> tuple[dict[str, object], ...]:
        return tuple(self._snapshot(track) for track in self._lost.values())

    def invalidate_all(self, reason: str) -> None:
        for track in self._tracks.values():
            track.lost_since = track.observed_at
            self._lost[track.track_id] = track
        self._tracks.clear()
        # Diagnostics only: keep the latest bounded set and never reuse these
        # identities after an explicit context invalidation.
        self._lost = dict(list(self._lost.items())[-64:])

    @staticmethod
    def _center(rect: PixelRect) -> tuple[float, float]:
        return ((rect.left + rect.right) / 2.0, (rect.top + rect.bottom) / 2.0)

    @staticmethod
    def _family(kind: str) -> str:
        if "subject" in kind:
            return "subject"
        if "symbol" in kind:
            return "symbol"
        return kind

    @staticmethod
    def _appearance_distance(a: dict[str, object] | None, b: dict[str, object]) -> float:
        if not a:
            return .5
        keys = ("foreground_contrast", "edge_density", "body_geometry", "residual_motion")
        values = []
        for key in keys:
            av, bv = a.get(key), b.get(key)
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                values.append(abs(float(av) - float(bv)))
        return sum(values) / len(values) if values else .5

    def update(self, candidates: tuple[WorldCandidate, ...] | list[WorldCandidate],
               timestamp: float | None = None, *, raw: bytes | None = None,
               width: int | None = None,
               height: int | None = None, gray: Any | None = None,
               gray_step: int | None = None) -> tuple[WorldCandidate, ...]:
        # ``gray``/``gray_step`` feed camera-motion compensation of the MOT
        # adapter; this appearance/centroid tracker does not use them.
        self.frame_index += 1
        active = [t for t in self._tracks.values() if t.misses <= self.max_misses]
        unmatched = set(t.track_id for t in active)
        updates: list[WorldCandidate] = []

        ordered = sorted(candidates, key=lambda c: (0 if c.kind == "unknown_subject_candidate" else 1, -c.confidence))
        costs: list[list[float]] = []
        for cand in ordered:
            cx, cy = self._center(cand.rect)
            row = []
            for track in active:
                if self._family(track.kind) != self._family(cand.kind):
                    row.append(math.inf)
                    continue
                appearance = cand.appearance or {}
                camera_dx = float(appearance.get("camera_motion_dx", 0) or 0)
                camera_dy = float(appearance.get("camera_motion_dy", 0) or 0)
                predicted_x = track.center_x + camera_dx + track.velocity_x
                predicted_y = track.center_y + camera_dy + track.velocity_y
                dist = math.hypot(cx - predicted_x, cy - predicted_y)
                scale = abs(math.log(max(1., cand.rect.width) / max(1., track.width))) + \
                        abs(math.log(max(1., cand.rect.height) / max(1., track.height)))
                visual = self._appearance_distance(track.appearance, appearance)
                cost = dist / max(1., self.max_distance) + .22 * min(2., scale) + .28 * visual
                allowed = self.max_distance * (1.0 + .35 * track.misses)
                row.append(cost if dist <= allowed else math.inf)
            costs.append(row)
        assigned = {candidate_index: active[track_index]
                    for candidate_index, track_index in linear_sum_assignment(costs)}

        for candidate_index, cand in enumerate(ordered):
            cx, cy = self._center(cand.rect)
            best = assigned.get(candidate_index)
            created = best is None
            if best is None:
                best = _TrackState(
                    track_id=self._next_id,
                    kind=cand.kind,
                    center_x=cx,
                    center_y=cy,
                    relation=cand.relation,
                    class_name=cand.class_name,
                    last_seen=self.frame_index,
                    width=cand.rect.width,
                    height=cand.rect.height,
                    appearance=dict(cand.appearance),
                    observed_at=timestamp,
                )
                self._next_id += 1
                self._tracks[best.track_id] = best
            else:
                unmatched.discard(best.track_id)

            previous_relation = best.relation
            old_x, old_y = best.center_x, best.center_y
            camera_dx = float(cand.appearance.get("camera_motion_dx", 0) or 0)
            camera_dy = float(cand.appearance.get("camera_motion_dy", 0) or 0)
            if not created:
                best.velocity_x = .65 * best.velocity_x + .35 * (cx - old_x - camera_dx)
                best.velocity_y = .65 * best.velocity_y + .35 * (cy - old_y - camera_dy)
            best.center_x, best.center_y = cx, cy
            best.last_seen = self.frame_index
            best.observed_at = timestamp
            best.lost_since = None
            best.misses = 0
            if not created:
                best.hits += 1
            best.width, best.height = cand.rect.width, cand.rect.height
            best.appearance = dict(cand.appearance)
            residual = cand.appearance.get("residual_motion")
            if isinstance(residual, (int, float)):
                best.residual_history = (*best.residual_history, float(residual))[-12:]
            best.relation = cand.relation
            best.class_name = cand.class_name
            updates.append(_with_tracking(cand, best, previous_relation, cand.relation))

        # Tracking an unknown blob does not confirm that it is an entity.
        for track_id in list(unmatched):
            track = self._tracks.get(track_id)
            if track is not None:
                track.misses += 1
                if track.misses > self.max_misses:
                    track.lost_since = timestamp
                    self._lost[track_id] = track
                    self._lost = dict(list(self._lost.items())[-64:])
                    del self._tracks[track_id]

        # Preserve original detector order for all hypotheses, including obstacles.
        by_identity = {id(src): updates[i] for i, src in enumerate(ordered)}
        result: list[WorldCandidate] = []
        for cand in candidates:
            result.append(by_identity.get(id(cand), cand))
        return tuple(result)


def _with_tracking(cand: WorldCandidate, track: _TrackState, previous_relation: str | None, relation: str | None) -> WorldCandidate:
    evidence = cand.evidence
    if previous_relation is not None and relation is not None and previous_relation != relation:
        evidence = f"{evidence}; relation_transition={previous_relation}->{relation}"
    appearance = dict(cand.appearance)
    if track.residual_history:
        mean_residual = sum(track.residual_history) / len(track.residual_history)
        appearance["residual_motion_trend"] = round(mean_residual, 4)
        # Static is a soft evidence penalty, never a semantic rejection.  It
        # becomes meaningful only after several temporally associated frames.
        appearance["static_scene_score"] = round(
            min(1.0, float(appearance.get("static_scene_score", 0)) +
                (0.18 if track.hits >= 4 and mean_residual < .12 else 0.0)), 4)
    appearance["track_association"] = "position+camera+motion+scale+appearance"
    appearance["track_hits"] = track.hits
    return WorldCandidate(
        kind=cand.kind,
        rect=cand.rect,
        confidence=cand.confidence,
        evidence=evidence,
        relation=cand.relation,
        class_name=cand.class_name,
        class_color=cand.class_color,
        track_id=track.track_id,
        previous_relation=previous_relation,
        relation_changed=(previous_relation is not None and previous_relation != relation),
        appearance=appearance,
        candidate_labels=tuple(cand.candidate_labels),
    )
