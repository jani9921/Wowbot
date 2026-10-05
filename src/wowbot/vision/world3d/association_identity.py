"""UltralyticsAssociationTracker id continuity: unique ids, screen-anchored (own avatar) boxes, re-identification.

Split out of tracking.py (2026-10-05); unchanged.
"""
from __future__ import annotations
from dataclasses import replace
import math
from typing import Any
from .models import PixelRect, WorldCandidate


class AssociationIdentityMixin:
    """Methods of UltralyticsAssociationTracker (tracking.py); moved verbatim."""

    def _unique_ids(self, output: tuple[WorldCandidate, ...], current: dict[int, Any],
                    anchored_ids: dict[int, int]) -> tuple[WorldCandidate, ...]:
        """One public id per frame; screen-anchored ids are claimed first.

        Live 2026-10-01 06:45: the avatar (anchored id 5) and a world box
        whose legacy-bridge id was also 5 were published together; the World3D
        layer then opened a second track for "V3:5" and alternated.
        """
        claimed = set(anchored_ids.values())
        result = list(output)
        for index, item in enumerate(result):
            if index in anchored_ids or item.track_id is None:
                continue
            public = int(item.track_id)
            if public in claimed:
                public = self._next_public_id
                self._next_public_id += 1
                if index in current:
                    self._native_to_public[int(current[index].track_id)] = public
                result[index] = replace(item, track_id=public)
            claimed.add(public)
        return tuple(result)

    @staticmethod
    def _screen_anchored(candidate: WorldCandidate, width: int, height: int) -> bool:
        """A large subject box centred on the third-person avatar position."""
        rect = candidate.rect
        return ("subject" in str(candidate.kind)
                and abs((rect.left+rect.right)/2 - width/2) < .06*width
                and rect.bottom > .55*height and rect.height > .15*height)

    def _anchored_assign(self, candidates, indices: list[int],
                         timestamp: float | None, world_in_use: set[int]) -> dict[int, int]:
        """IoU association without camera warp for screen-anchored boxes.

        A box newly entering the avatar zone (an NPC walking behind the avatar)
        inherits the id it was published with on the previous frame; leaving
        the zone, ``_reidentify`` hands that id back to BoT-SORT.
        """
        now = float(timestamp) if timestamp is not None else self.frame_index/30.
        for public, entry in list(self._anchored.items()):
            if now-entry["seen"] > self.anchored_retention_seconds:
                del self._anchored[public]

        def iou(a: PixelRect, b: PixelRect) -> float:
            left, top = max(a.left, b.left), max(a.top, b.top)
            right, bottom = min(a.right, b.right), min(a.bottom, b.bottom)
            inter = max(0, right-left)*max(0, bottom-top)
            union = a.width*a.height + b.width*b.height - inter
            return inter/union if union > 0 else 0.

        def similarity(a: PixelRect, b: PixelRect) -> float:
            # IoU, or for a reshaped box (animation, mount) a centre match
            # within half a box height scored just above the IoU gate.
            overlap = iou(a, b)
            if overlap >= .3:
                return overlap
            height = max(a.height, b.height, 1)
            ratio = max(a.height, b.height)/max(1, min(a.height, b.height))
            distance = math.hypot((a.left+a.right-b.left-b.right)/2,
                                  (a.top+a.bottom-b.top-b.bottom)/2)/height
            return .3 if distance <= .5 and ratio <= 1.6 else overlap

        pairs = sorted(((similarity(candidates[index].rect, entry["rect"]), -entry["first"],
                         index, public)
                        for index in indices for public, entry in self._anchored.items()),
                       reverse=True)
        assigned: dict[int, int] = {}
        used: set[int] = set()
        for overlap, _, index, public in pairs:
            if overlap < .3:
                break
            if index in assigned or public in used:
                continue
            assigned[index] = public
            used.add(public)
        for index in indices:
            if index in assigned:
                continue
            public = self._inherit_published(candidates[index], world_in_use | used)
            if public is None:
                public = self._next_public_id
                self._next_public_id += 1
            assigned[index] = public
            used.add(public)
            self._anchored[public] = {"first": now}
        for index, public in assigned.items():
            self._anchored[public].update({"rect": candidates[index].rect, "seen": now})
        return assigned

    def _inherit_published(self, candidate: WorldCandidate, in_use: set[int]) -> int | None:
        """Id published on the previous frame at the same place (unambiguous)."""
        rect = candidate.rect
        cx, cy = (rect.left+rect.right)/2, (rect.top+rect.bottom)/2
        height = max(1., float(rect.height))
        family = self._family(candidate.kind)
        scored = []
        for public_id, box in self._last_boxes.items():
            if public_id in in_use or box["family"] != family:
                continue
            ratio = max(height, box["height"])/min(height, box["height"])
            distance = math.hypot(cx-box["cx"], cy-box["cy"])/max(height, box["height"])
            if ratio <= 1.5 and distance <= .5:
                scored.append((distance, public_id))
        scored.sort()
        if not scored or (len(scored) > 1 and scored[1][0]-scored[0][0] < .15):
            return None
        return scored[0][1]

    def _gmc_translation(self) -> tuple[float, float]:
        gmc = getattr(self._tracker, "gmc", None) if self._tracker is not None else None
        warp = getattr(gmc, "last_warp", None)
        if not warp:
            return 0., 0.
        return float(warp[0]), float(warp[1])

    def _age_recently_lost(self, timestamp: float | None) -> None:
        """Carry vanished ids with the camera and forget them after a while."""
        dx, dy = self._gmc_translation()
        for public_id, entry in list(self._recently_lost.items()):
            if (timestamp is not None and entry["lost_at"] is not None
                    and timestamp-entry["lost_at"] > self.reid_seconds):
                del self._recently_lost[public_id]
                continue
            entry["cx"] += dx
            entry["cy"] += dy

    def _remember_published(self, output, timestamp: float | None) -> None:
        present = {int(item.track_id): item for item in output if item.track_id is not None}
        for public_id, box in list(self._last_boxes.items()):
            if public_id not in present:
                self._recently_lost[public_id] = {**box, "lost_at": timestamp}
                del self._last_boxes[public_id]
        for public_id, item in present.items():
            rect = item.rect
            self._last_boxes[public_id] = {
                "cx": (rect.left+rect.right)/2, "cy": (rect.top+rect.bottom)/2,
                "height": max(1., float(rect.height)),
                "family": self._family(item.kind)}
            self._recently_lost.pop(public_id, None)

    def _reidentify(self, candidate: WorldCandidate, in_use: set[int]) -> int | None:
        """Give a newly born native track the id of a subject that just vanished.

        Live 2026-09-30 (running around an NPC): 73 % of new subject ids were
        the same subject returning after a median 0.25 s gap, displaced by a
        median 0.61 box heights (own avatar occluding it, orbiting camera);
        BoT-SORT's Kalman prediction no longer overlapped it.  Same family,
        near the camera-compensated last position, similar height and an
        unambiguous best match are required; identity semantics stay with the
        addon GUID layer.
        """
        family = self._family(candidate.kind)
        rect = candidate.rect
        cx, cy = (rect.left+rect.right)/2, (rect.top+rect.bottom)/2
        height = max(1., float(rect.height))
        # Live 2026-10-01 (PID 1712): most re-births happened within ONE frame
        # (0.04 s): the old id was published on the previous frame, so it was
        # not yet "recently lost" and was invisible here.  An id published
        # last frame and unmatched on this one is lost *now*; its box moves
        # with this frame's camera warp.
        dx, dy = self._gmc_translation()
        pool = dict(self._recently_lost)
        for public_id, box in self._last_boxes.items():
            if public_id not in pool:
                pool[public_id] = {**box, "cx": box["cx"]+dx, "cy": box["cy"]+dy}
        scored = []
        for public_id, entry in pool.items():
            if (public_id in in_use or public_id in self._anchored
                    or entry["family"] != family):
                continue
            ratio = max(height, entry["height"])/min(height, entry["height"])
            if ratio > 1.7:
                continue
            distance = math.hypot(cx-entry["cx"], cy-entry["cy"])/max(height, entry["height"])
            if distance <= self.reid_max_heights:
                scored.append((distance, public_id))
        if not scored:
            return None
        scored.sort()
        if len(scored) > 1 and scored[1][0]-scored[0][0] < .25:
            return None
        public_id = scored[0][1]
        self._recently_lost.pop(public_id, None)
        return public_id
