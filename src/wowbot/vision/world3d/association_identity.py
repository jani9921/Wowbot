"""UltralyticsAssociationTracker public-id continuity and conservative ReID."""
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
        """A lower-centre subject box, plausibly the third-person avatar.

        Live PID 10348: a 96-99 px tall box at 649 px frame height crossed
        the former .15-height threshold every few frames, switching between
        native and anchored ID spaces. The stronger bottom gate excludes most
        distant NPCs while allowing that small box-height variation.
        """
        rect = candidate.rect
        return ("subject" in str(candidate.kind)
                and abs((rect.left+rect.right)/2 - width/2) < .06*width
                and rect.bottom > .65*height and rect.height > .12*height)

    def _screen_anchor_indices(self, candidates, width: int, height: int,
                               timestamp: float | None = None) -> tuple[list[int], int]:
        """Only one box can be the local screen-anchored avatar.

        Live PIDs 16548/10348: flanking and upper NPCs also passed the broad
        positional gate. Anchoring them excluded them from BoT-SORT and made
        IDs alternate. Prefer the lowest plausible subject, then centrality;
        ambiguous neighbours remain ordinary world detections.
        """
        now = float(timestamp) if timestamp is not None else self.frame_index/30.
        previous = self._screen_anchor_last
        eligible = [index for index, candidate in enumerate(candidates)
                    if self._screen_anchored(candidate, width, height)]
        if previous is not None and 0. <= now-previous[1] <= .2:
            # PID 1296: the same avatar box moved from bottom=337 to 336 on
            # a 518 px frame, crossing the strict .65 gate and switching its
            # feed ID for 0.6 s. Only an almost-identical immediately prior
            # anchor may use this narrower continuation gate.
            for index, candidate in enumerate(candidates):
                if index in eligible or "subject" not in str(candidate.kind):
                    continue
                rect = candidate.rect
                if (abs((rect.left+rect.right)/2-width/2) >= .07*width
                        or rect.bottom <= .60*height or rect.height <= .10*height):
                    continue
                if self._rect_iou((rect.left, rect.top, rect.right, rect.bottom),
                                  previous[0]) >= .90:
                    eligible.append(index)
        if not eligible:
            return [], 0
        if previous is not None and now-previous[1] <= self.anchored_retention_seconds:
            overlapping = [index for index in eligible if self._rect_iou(
                (candidates[index].rect.left, candidates[index].rect.top,
                 candidates[index].rect.right, candidates[index].rect.bottom),
                previous[0]) >= .35]
            if overlapping:
                eligible_for_choice = overlapping
            elif now-previous[1] <= 1.:
                # The avatar vanished for a frame: do not immediately assign
                # its screen anchor to a different nearby NPC.
                return [], len(eligible)
            else:
                eligible_for_choice = eligible
        else:
            eligible_for_choice = eligible
        best = min(eligible_for_choice, key=lambda index: (
            -(self._rect_iou(
                (candidates[index].rect.left, candidates[index].rect.top,
                 candidates[index].rect.right, candidates[index].rect.bottom),
                previous[0]) if previous is not None and now-previous[1] <= 1. else 0.),
            -candidates[index].rect.bottom,
            abs((candidates[index].rect.left+candidates[index].rect.right)/2-width/2),
            -candidates[index].rect.height,
            -candidates[index].confidence,
            index))
        rect = candidates[best].rect
        self._screen_anchor_last = ((rect.left, rect.top, rect.right, rect.bottom), now)
        return [best], len(eligible)

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
        now = float(timestamp) if timestamp is not None else self.frame_index / 30.
        dx, dy = self._gmc_translation()
        for public_id, entry in list(self._recently_lost.items()):
            if now-entry["lost_at"] > self.reid_gallery_seconds:
                del self._recently_lost[public_id]
                continue
            entry["cx"] += dx
            entry["cy"] += dy

    @staticmethod
    def _descriptor_distance(left, right) -> float | None:
        if left is None or right is None:
            return None
        return sum(abs(a-b) for a, b in zip(left, right)) / 6.

    def _alias_compatible(self, public_id: int, descriptor,
                          timestamp: float | None) -> bool:
        """A legacy alias may bridge MOT, but cannot overrule contradictory pixels."""
        entry = self._last_boxes.get(public_id) or self._recently_lost.get(public_id)
        if entry is None:
            return False
        now = float(timestamp) if timestamp is not None else self.frame_index / 30.
        if now-entry.get("seen_at", now) > self.reid_gallery_seconds:
            return False
        visual = self._descriptor_distance(descriptor, entry.get("descriptor"))
        return visual is None or visual <= .23

    def _remember_published(self, output, timestamp: float | None,
                            descriptors=()) -> None:
        now = float(timestamp) if timestamp is not None else self.frame_index / 30.
        present = {int(item.track_id): (item, descriptor)
                   for item, descriptor in zip(output, descriptors)
                   if item.track_id is not None}
        for public_id, box in list(self._last_boxes.items()):
            if public_id not in present:
                self._recently_lost[public_id] = {**box, "lost_at": now}
                del self._last_boxes[public_id]
        for public_id, (item, descriptor) in present.items():
            rect = item.rect
            self._last_boxes[public_id] = {
                "rect": (rect.left, rect.top, rect.right, rect.bottom),
                "cx": (rect.left+rect.right)/2, "cy": (rect.top+rect.bottom)/2,
                "height": max(1., float(rect.height)),
                "family": self._family(item.kind),
                "descriptor": descriptor,
                "hits": int(item.appearance.get("track_hits") or 1),
                "seen_at": now}
            self._recently_lost.pop(public_id, None)

    @staticmethod
    def _rect_iou(left, right) -> float:
        intersection = (max(0, min(left[2], right[2])-max(left[0], right[0]))
                        * max(0, min(left[3], right[3])-max(left[1], right[1])))
        first = max(0, left[2]-left[0])*max(0, left[3]-left[1])
        second = max(0, right[2]-right[0])*max(0, right[3]-right[1])
        union = first+second-intersection
        return intersection/union if union > 0 else 0.

    def _coalesce_exact_continuation(self, candidate: WorldCandidate, public_id: int,
                                     in_use: set[int], timestamp: float | None,
                                     descriptor) -> tuple[int, int] | None:
        """Reconcile alternating native/tentative IDs for one *visible* box.

        The 2026-10-15 feed alternated V3:437/V3:445 at the same 60x100 box
        every 35-70 ms. The previous-frame spatial evidence is much stronger
        than the fallback alias, but says nothing about an NPC after it has
        gone off-screen. Never bridge a long gap or simultaneous detections.
        """
        if public_id in self._last_boxes:
            return None
        now = float(timestamp) if timestamp is not None else self.frame_index/30.
        rect = candidate.rect
        current_rect = (rect.left, rect.top, rect.right, rect.bottom)
        matches = []
        for old_id, entry in self._last_boxes.items():
            if (old_id == public_id or old_id in in_use or old_id in self._anchored
                    or entry.get("family") != self._family(candidate.kind)
                    or now-entry.get("seen_at", now) > .15):
                continue
            old_rect = entry.get("rect")
            if old_rect is None or self._rect_iou(current_rect, old_rect) < .90:
                continue
            visual = self._descriptor_distance(descriptor, entry.get("descriptor"))
            if visual is None or visual > .23:
                continue
            matches.append(old_id)
        if len(matches) != 1:
            return None
        # Continuity of the just-published box wins over native/fallback hit
        # counts: the latter may have accumulated on a hidden parallel alias.
        return matches[0], public_id

    def _merge_public_alias(self, winner: int, loser: int) -> None:
        for mapping in (self._native_to_public, self._fallback_to_public):
            for source_id, public_id in list(mapping.items()):
                if public_id == loser:
                    mapping[source_id] = winner
        old_state = self._states.pop(loser, None)
        if old_state is not None:
            if winner in self._states:
                self._states[winner].hits = max(self._states[winner].hits, old_state.hits)
            else:
                old_state.track_id = winner
                self._states[winner] = old_state
        self._last_boxes.pop(loser, None)
        self._recently_lost.pop(loser, None)

    def _reidentify(self, candidate: WorldCandidate, in_use: set[int],
                    *, timestamp: float | None = None, descriptor=None) -> int | None:
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
        now = float(timestamp) if timestamp is not None else self.frame_index / 30.
        nearby = []
        appearance_matches = []
        for public_id, entry in pool.items():
            if (public_id in in_use or public_id in self._anchored
                    or entry["family"] != family):
                continue
            ratio = max(height, entry["height"])/min(height, entry["height"])
            if ratio > 2.:
                continue
            distance = math.hypot(cx-entry["cx"], cy-entry["cy"])/max(height, entry["height"])
            visual = self._descriptor_distance(descriptor, entry.get("descriptor"))
            # A clear appearance contradiction must not be hidden by a close
            # box after two similar NPCs cross on screen.
            if visual is not None and visual > .23:
                continue
            age = max(0., now-entry.get("lost_at", entry.get("seen_at", now)))
            if age <= self.reid_seconds and distance <= self.reid_max_heights:
                nearby.append((distance + (visual or 0.)*.5, public_id))
            # After a full camera turn the GMC position is not a useful gate.
            # Only a distinctive, established visual track can reclaim its id;
            # similarity is still visual evidence, never confirmed NPC identity.
            if (age <= self.reid_gallery_seconds and visual is not None
                    and visual <= .10 and entry.get("hits", 0) >= 3):
                appearance_matches.append((visual, public_id))
        nearby.sort()
        appearance_matches.sort()
        if nearby and (len(nearby) == 1 or nearby[1][0]-nearby[0][0] >= .25):
            public_id = nearby[0][1]
        elif appearance_matches and (len(appearance_matches) == 1
                                     or appearance_matches[1][0]-appearance_matches[0][0] >= .035):
            public_id = appearance_matches[0][1]
        else:
            return None
        self._recently_lost.pop(public_id, None)
        return public_id
