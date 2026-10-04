"""Stable presentation objects on top of source-local World3D tracks.

The raw track layer legitimately churns: a detector refresh can restart an
upstream id, a full-body box and a partial box of the same NPC can coexist,
and a short detector gap turns a track OCCLUDED/LOST for a few frames.  Live
2026-09-30 every consumer inherited that churn: the quest symbol bound to a
coasting twin, SEEK/approach failed with ``visual_track_lost`` and the viewer
boxes flickered.

This layer keeps one persistent object per visual phenomenon:

* one id for its lifetime (the id of the raw track that founded it), however
  many raw ids pass through it;
* a new raw id whose box overlaps an existing object joins that object; two
  boxes observed in the same frame stay separate unless near-identical;
* an established object (3+ live updates) is reported ACTIVE with a smoothed
  box while its raw track coasts, for at most ``hold_seconds``;
* the truthful raw state stays attached for logic (``raw_lifecycle``,
  ``coasting``, ``coasting_seconds``, ``raw_track_ids``), and inspection/click
  authority on a coasting box expires after ``inspect_hold_seconds``.

The raw layer stays the continuity authority for an id it kept, and a fresh,
never-established candidate keeps its raw lifecycle.  This is continuity of
visual evidence only; it never asserts entity identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

_LIVE = frozenset({"ACTIVE", "STABLE", "TENTATIVE", "REACQUIRE_CANDIDATE"})
_HIDDEN_RAW_FIELDS = ("missing_seconds", "occlusion_probability", "reidentification_status")


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def _bbox(item: dict) -> dict | None:
    box = item.get("bbox")
    if not isinstance(box, dict) or not all(_number(box.get(key)) is not None
                                            for key in ("left", "top", "right", "bottom")):
        return None
    if box["right"] <= box["left"] or box["bottom"] <= box["top"]:
        return None
    return box


def _area(box: dict) -> float:
    return max(0., box["right"]-box["left"]) * max(0., box["bottom"]-box["top"])


def _overlap(a: dict, b: dict) -> tuple[float, float]:
    """(IoU, intersection over the smaller box)."""
    width = max(0., min(a["right"], b["right"])-max(a["left"], b["left"]))
    height = max(0., min(a["bottom"], b["bottom"])-max(a["top"], b["top"]))
    intersection = width*height
    if intersection <= 0:
        return 0., 0.
    union = _area(a)+_area(b)-intersection
    return intersection/union if union > 0 else 0., intersection/max(1e-9, min(_area(a), _area(b)))


def _family(item: dict) -> str:
    kind = str(item.get("detector_kind") or item.get("kind") or "")
    if "symbol" in kind:
        return "symbol"
    if "subject" in kind:
        return "subject"
    if "object" in kind:
        return "object"
    return kind or "other"


def _lifecycle(item: dict) -> str:
    return str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()


@dataclass
class _Object:
    identity: str
    family: str
    first_seen: float
    last_real_at: float
    last_update_at: float
    hits: int = 0
    x: float | None = None
    y: float | None = None
    bbox: dict | None = None
    raw_ids: set[str] = field(default_factory=set)


class StableObjectLayer:
    def __init__(self, *, hold_seconds: float = 1.5, tracked_hold_seconds: float = 3.,
                 inspect_hold_seconds: float = .6, smoothing: float = .5,
                 max_objects: int = 80) -> None:
        # A blind velocity prediction (raw LOST) is held briefly; a box the
        # image patch tracker still follows between detector refreshes (raw
        # OCCLUDED) is real visual evidence and may be held longer.
        self.hold_seconds = hold_seconds
        self.tracked_hold_seconds = max(hold_seconds, tracked_hold_seconds)
        self.inspect_hold_seconds = inspect_hold_seconds
        self.smoothing = smoothing
        self.max_objects = max_objects
        self.objects: dict[str, _Object] = {}
        self.raw_to_object: dict[str, str] = {}
        self.raw_last_seen: dict[str, float] = {}
        # Detector-rate (feed) identity -> object.  The feed keeps its ids
        # through World3D intake stalls; remembering them lets a raw track
        # re-created after a stall rejoin its object (live 2026-09-30: the
        # public id changed mostly while Live Vision stuttered).  Retention
        # only; presentation still follows the hold limits.
        self.upstream_memory_seconds = 5.
        self.upstream_to_object: dict[str, tuple[str, float]] = {}
        self.upstream_rebinds = 0
        self.merges = 0

    def reset(self) -> None:
        self.objects.clear()
        self.raw_to_object.clear()
        self.raw_last_seen.clear()
        self.upstream_to_object.clear()
        self.merges = 0

    # -- association -------------------------------------------------------
    @staticmethod
    def _compatible(box: dict, obj: _Object, family: str) -> float | None:
        """Overlap score when a new raw box is the same visual phenomenon."""
        if family != obj.family or obj.bbox is None:
            return None
        iou, contained = _overlap(box, obj.bbox)
        heights = (box["bottom"]-box["top"], obj.bbox["bottom"]-obj.bbox["top"])
        if max(heights)/max(1e-9, min(heights)) > 2.5:
            return None
        if iou >= .35 or contained >= .75:
            return max(iou, contained*.9)
        return None

    def _match_new_raw(self, item: dict, box: dict,
                       live_this_update: dict[str, list[dict]],
                       observed_at: float | None = None) -> _Object | None:
        family = _family(item)
        live = _lifecycle(item) in _LIVE
        scored = []
        for candidate in self.objects.values():
            # Spatial merging only with recently updated objects; longer
            # retention exists for exact upstream-id rebinding.
            if (observed_at is not None
                    and observed_at-candidate.last_update_at > self.tracked_hold_seconds):
                continue
            score = self._compatible(box, candidate, family)
            if score is None:
                continue
            same_frame = live_this_update.get(candidate.identity) or ()
            if live and same_frame and not any(
                    _bbox(other) is not None and _overlap(box, _bbox(other))[0] >= .6
                    for other in same_frame):
                # Two simultaneously observed boxes are separate units unless
                # they are near-identical duplicates of one another.
                continue
            scored.append((score, candidate))
        scored.sort(key=lambda entry: -entry[0])
        # Two objects claiming the same box is ambiguous: never merge adjacent
        # subjects on a coin flip.
        if scored and (len(scored) == 1 or scored[0][0]-scored[1][0] >= .15):
            return scored[0][1]
        return None

    def _smooth(self, obj: _Object, item: dict, live: bool) -> None:
        box = _bbox(item)
        x, y = _number(item.get("x")), _number(item.get("y"))
        if obj.bbox is None or box is None or not live:
            # First sample, or a coasting prediction: follow the raw layer's own
            # velocity prediction for the centre without inventing motion.
            if box is not None and obj.bbox is None:
                obj.bbox = {key: float(box[key]) for key in ("left", "top", "right", "bottom")}
            if x is not None and y is not None:
                obj.x, obj.y = x, y
            return
        height = max(1., obj.bbox["bottom"]-obj.bbox["top"])
        jump = math.hypot((box["left"]+box["right"]-obj.bbox["left"]-obj.bbox["right"])/2,
                          (box["top"]+box["bottom"]-obj.bbox["top"]-obj.bbox["bottom"])/2)
        new_height = max(1., box["bottom"]-box["top"])
        # A large jump (camera turn, re-association) snaps instead of leaving a
        # trailing, actionable box behind the real subject.
        alpha = (1. if jump > .5*height or not .6 <= new_height/height <= 1.67
                 else self.smoothing)
        obj.bbox = {key: obj.bbox[key]+alpha*(float(box[key])-obj.bbox[key])
                    for key in ("left", "top", "right", "bottom")}
        if x is not None and y is not None:
            if obj.x is None or obj.y is None or alpha >= 1.:
                obj.x, obj.y = x, y
            else:
                obj.x, obj.y = obj.x+alpha*(x-obj.x), obj.y+alpha*(y-obj.y)

    def update(self, items: list[dict], observed_at: float) -> list[dict]:
        # Objects whose members all retired are remembered briefly so a nearby
        # new raw id can rejoin them, but an object is only drawn through a
        # member: the raw layer already coasts a lost track for its own grace.
        retention = max(self.tracked_hold_seconds, self.upstream_memory_seconds)
        for identity, obj in list(self.objects.items()):
            if observed_at-obj.last_update_at > retention:
                del self.objects[identity]
        for upstream, (identity, seen) in list(self.upstream_to_object.items()):
            if observed_at-seen > self.upstream_memory_seconds or identity not in self.objects:
                del self.upstream_to_object[upstream]
        order: list[tuple[int, dict]] = []
        positioned: list[tuple[int, dict]] = []
        for index, item in enumerate(items):
            if (item.get("track_id") and _number(item.get("x")) is not None
                    and _number(item.get("y")) is not None):
                positioned.append((index, item))
            else:
                order.append((index, item))
        # Live boxes claim objects first; coasting predictions join afterwards.
        positioned.sort(key=lambda entry: (_lifecycle(entry[1]) not in _LIVE,
                                           -float(entry[1].get("confidence") or 0.)))
        members: dict[str, list[dict]] = {}
        first_index: dict[str, int] = {}
        live_this_update: dict[str, list[dict]] = {}
        for index, item in positioned:
            raw_id = str(item["track_id"])
            self.raw_last_seen[raw_id] = observed_at
            # The raw layer is the continuity authority for an id it kept, even
            # across a large camera-turn jump; only new ids are merged here.
            obj = self.objects.get(self.raw_to_object.get(raw_id, ""))
            box = _bbox(item)
            upstream = str(item.get("upstream_track_id") or "")
            if obj is None and upstream and upstream in self.upstream_to_object:
                remembered = self.objects.get(self.upstream_to_object[upstream][0])
                if (remembered is not None and remembered.family == _family(item)
                        and remembered.identity not in live_this_update):
                    obj = remembered
                    self.upstream_rebinds += 1
            if obj is None and box is not None:
                obj = self._match_new_raw(item, box, live_this_update, observed_at)
                if obj is not None and obj.raw_ids and raw_id not in obj.raw_ids:
                    self.merges += 1
            if obj is None:
                identity = raw_id
                while identity in self.objects:
                    identity = f"{identity}.1"
                obj = _Object(identity, _family(item), observed_at, observed_at, observed_at)
                self.objects[identity] = obj
            obj.raw_ids.add(raw_id)
            self.raw_to_object[raw_id] = obj.identity
            if upstream:
                self.upstream_to_object[upstream] = (obj.identity, observed_at)
            members.setdefault(obj.identity, []).append(item)
            first_index[obj.identity] = min(first_index.get(obj.identity, index), index)
            if _lifecycle(item) in _LIVE:
                live_this_update.setdefault(obj.identity, []).append(item)
            if obj.bbox is None:
                self._smooth(obj, item, _lifecycle(item) in _LIVE)

        for identity, group in members.items():
            obj = self.objects[identity]
            live = [item for item in group if _lifecycle(item) in _LIVE]
            representative = max(live or group, key=lambda item: (
                float(item.get("stable_frames") or 0) >= 3, float(item.get("confidence") or 0.)))
            if live:
                obj.last_real_at = observed_at
                obj.hits += 1
            obj.last_update_at = observed_at
            self._smooth(obj, representative, bool(live))
            order.append((first_index[identity], self._present(obj, representative, group, observed_at)))
        self._forget_stale_raw_ids(observed_at)
        return [item for _, item in sorted(order, key=lambda entry: entry[0])]

    @staticmethod
    def _visually_tracked(item: dict) -> bool:
        """Image patch propagation between detector refreshes, not a blind coast.

        The raw layer labels it OCCLUDED for two missed refreshes and then
        LOST_TEMPORARY, although the patch tracker still follows the pixels; a
        blind velocity coast of an unmatched track carries ``missing_seconds``.
        """
        appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
        return (int(appearance.get("detector_miss_streak") or 0) > 0
                and "missing_seconds" not in item)

    def _present(self, obj: _Object, representative: dict, group: list[dict],
                 observed_at: float) -> dict:
        coasting_seconds = max(0., observed_at-obj.last_real_at)
        raw_lifecycle = _lifecycle(representative)
        established = obj.hits >= 3
        # Only an established object is smoothed through a gap; a fresh,
        # never-confirmed candidate keeps its truthful raw state.
        limit = (self.tracked_hold_seconds if self._visually_tracked(representative)
                 else self.hold_seconds)
        held = established and coasting_seconds <= limit
        if held:
            payload = {key: value for key, value in representative.items()
                       if key not in _HIDDEN_RAW_FIELDS}
            lifecycle, temporal_state, missing_frames = "ACTIVE", "CONFIRMED", 0
        else:
            payload = dict(representative)
            lifecycle = raw_lifecycle
            temporal_state = str(representative.get("temporal_state") or "TENTATIVE")
            missing_frames = int(representative.get("missing_frames") or 0)
        family = obj.family
        if family == "symbol":
            inspectable = False
        elif not established:
            inspectable = bool(representative.get("inspectable"))
        elif coasting_seconds <= 1e-9:
            inspectable = bool(representative.get("inspectable")) or family == "subject"
        else:
            inspectable = family == "subject" and coasting_seconds <= self.inspect_hold_seconds
        identity = str(obj.identity)
        payload.update({
            "track_id": identity if ":" in identity else f"WORLD3D:{identity}",
            "object_id": identity,
            "lifecycle": lifecycle, "track_state": lifecycle, "temporal_state": temporal_state,
            "missing_frames": missing_frames,
            "stable_frames": max(obj.hits, int(representative.get("stable_frames") or 0)),
            "first_seen": obj.first_seen, "age": max(0., observed_at-obj.first_seen),
            "last_seen": obj.last_real_at, "observed_at": observed_at,
            "inspectable": inspectable,
            "raw_lifecycle": raw_lifecycle,
            "raw_track_ids": sorted(obj.raw_ids),
            "raw_member_count": len(group),
            "duplicate_raw_tracks": max(0, len(group)-1),
            "coasting": coasting_seconds > 1e-9,
            "coasting_seconds": round(coasting_seconds, 4),
            "presentation_hold": held and coasting_seconds > 1e-9,
        })
        if obj.bbox is not None and _bbox(representative) is not None:
            box = dict(representative["bbox"])
            box.update({key: int(round(obj.bbox[key])) for key in ("left", "top", "right", "bottom")})
            payload["bbox"] = box
        if obj.x is not None and obj.y is not None:
            payload["x"], payload["y"] = obj.x, obj.y
        return payload

    def _forget_stale_raw_ids(self, observed_at: float) -> None:
        for raw_id, seen in list(self.raw_last_seen.items()):
            if observed_at-seen > 5.:
                self.raw_last_seen.pop(raw_id, None)
                identity = self.raw_to_object.pop(raw_id, None)
                if identity in self.objects:
                    self.objects[identity].raw_ids.discard(raw_id)
        if len(self.objects) > self.max_objects:
            oldest = sorted(self.objects.values(), key=lambda obj: obj.last_update_at)
            for obj in oldest[:len(self.objects)-self.max_objects]:
                self.objects.pop(obj.identity, None)

    def diagnostics(self) -> dict:
        return {"objects": len(self.objects), "raw_bindings": len(self.raw_to_object),
                "duplicate_merges": self.merges, "upstream_rebinds": self.upstream_rebinds}
