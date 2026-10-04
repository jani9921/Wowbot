"""Recognise the local player's own World3D box.

Live 2026-10-02 21:12: a killed murloc lay at the character's feet with no box
of its own; the dead-mouseover point was bound to the nearest box -- the
player's own, screen-anchored avatar -- and LOOT right-clicked the player.
The own box must never stand in for another unit (mouseover, corpse,
selected target or quest NPC).

User 2026-10-04: the former fixed lower-centre band failed as soon as the
camera was zoomed out or a vehicle camera took over (the Giant Boar + rider
box sat at y .32-.59, above that band), so the own boar became the "selected
target" box.  The identity must hold "regardless of everything", while an
NPC standing in front of the avatar stays visible -- so nothing is masked;
only the one box proven to be the avatar is named SELF_PLAYER.  Evidence,
strongest first:

* addon hover: the mouseover GUID is the player (or the ridden vehicle) while
  the cursor is inside the box;
* ego-rotation: the third-person camera follows the character, so turning
  shifts every world box sideways while the avatar stays on the same screen
  spot (zoom, mount, vehicle and model independent);
* focus geometry: the camera orbits a focus point on the character, so the
  avatar box is horizontally centred and contains that point at any zoom
  (zooming scales the box around it); a unit in front is drawn above it.

A box that moved with the world while the player turned, or that the hover
named as another unit, is vetoed.  A confirmed spot follows gradual zoom
changes; ``camera_distance`` (addon 0.9.50, ``GetCameraZoom``) rescales the
expected size when known.
"""
from __future__ import annotations

from collections import deque
import math

from .models import number


def is_self_avatar_box(item) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("self_player_avatar") is True or item.get("screen_anchored") is True:
        return True
    identity = item.get("visual_identity") if isinstance(item.get("visual_identity"), dict) else {}
    if identity.get("kind") == "SELF_PLAYER":
        return True
    appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
    return appearance.get("screen_anchored") is True or appearance.get("self_player_avatar") is True


def mark_self_avatar(candidate: dict, *, name: str, guid: str | None, source: str,
                     belief: str = "SUPPORTED") -> None:
    """Name one box as the local avatar (attention suppression, never a mask)."""
    identity = {"kind": "SELF_PLAYER", "name": name or "Local player", "guid": guid or None,
                "belief": belief, "fact": False, "source": source}
    previous_inspectable = candidate.get("inspectable", True)
    candidate["self_player_avatar"] = True
    candidate["display_name"] = identity["name"]
    candidate["visual_identity"] = identity
    candidate["inspectable"] = False
    candidate["inspection_suppressed_reason"] = "SELF_PLAYER_AVATAR"
    appearance = dict(candidate.get("appearance") or {})
    appearance.update({"self_player_avatar": True, "self_player_name": identity["name"],
                       "self_player_guid": identity["guid"], "self_avatar_source": source,
                       "self_avatar_evidence_role": "IDENTIFIED_ATTENTION_SUPPRESS_ONLY",
                       "self_avatar_prev_inspectable": previous_inspectable})
    candidate["appearance"] = appearance


def _box(item: dict) -> dict | None:
    """Normalised top-left box of a state candidate (x/y are bottom-left)."""
    x, y = number(item.get("x")), number(item.get("y"))
    w, h = number(item.get("bbox_width_fraction")), number(item.get("bbox_height_fraction"))
    if None in (x, y, w, h) or w <= 0 or h <= 0:
        return None
    cy = 1.-y
    return {"track_id": str(item.get("track_id")), "cx": x, "cy": cy, "w": w, "h": h,
            "left": x-w/2, "right": x+w/2, "top": cy-h/2, "bottom": cy+h/2}


def _angle_delta(a: float, b: float) -> float:
    return (b-a+math.pi) % (2*math.pi) - math.pi


class SelfAvatarIdentifier:
    """Per-WorldModel memory of which World3D box is the local avatar."""

    FOCUS = (.5, .52)              # default orbit focus (screen, top-left)
    MIN_TURN = .17                  # rad (~10 deg) of turning between two frames
    HISTORY_SECONDS = 3.5
    SPOT_SECONDS = 25.
    VETO_SECONDS = 8.
    ROTATION_CONFIRMATIONS = 2

    def __init__(self):
        self.frames: deque = deque(maxlen=90)
        self.last_frame_key: float | None = None
        self.spot: dict | None = None          # strong: last confirmed avatar box
        self.spot_at = -math.inf
        self.spot_source: str | None = None
        self.spot_camera_distance: float | None = None
        self.vetoed: dict[str, float] = {}
        self.rotation_hits: dict[str, list[float]] = {}
        self.diagnostics: dict = {}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _subjects(state: dict) -> list[tuple[dict, dict]]:
        result = []
        for item in state.get("visual_candidates") or ():
            if (not isinstance(item, dict) or item.get("source") != "WORLD3D"
                    or "subject" not in str(item.get("detector_kind") or item.get("kind") or "")
                    or str(item.get("lifecycle") or "").upper() == "TERMINATED"):
                continue
            box = _box(item)
            if box is not None:
                result.append((item, box))
        return result

    @staticmethod
    def _live(item: dict) -> bool:
        lifecycle = str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
        return (lifecycle in {"ACTIVE", "TENTATIVE", "STABLE"}
                and not (number(item.get("missing_frames")) or 0) > 0
                and item.get("coasting") is not True)

    @staticmethod
    def _same_spot(a: dict, b: dict, *, size_ratio=(.7, 1.43)) -> bool:
        if not size_ratio[0] <= b["h"]/a["h"] <= size_ratio[1]:
            return False
        return (abs(a["cx"]-b["cx"]) <= max(.02, .25*a["w"])
                and abs(a["cy"]-b["cy"]) <= max(.03, .25*a["h"]))

    def _focus(self) -> tuple[float, float]:
        spot = self.spot
        if spot is not None and not (spot["left"] <= self.FOCUS[0] <= spot["right"]
                                     and spot["top"] <= self.FOCUS[1] <= spot["bottom"]):
            # Dynamic pitch / over-shoulder camera: learn the confirmed spot.
            return spot["cx"], spot["cy"]
        return self.FOCUS

    def _expected_height(self, state: dict) -> float | None:
        distance = number(state.get("camera_distance"))
        if (self.spot is None or not distance or distance <= .5
                or not self.spot_camera_distance):
            return None
        return self.spot["h"]*self.spot_camera_distance/distance

    def _matches_spot(self, box: dict, state: dict) -> bool:
        spot = self.spot
        if spot is None:
            return False
        expected = self._expected_height(state) or spot["h"]
        if not .5 <= box["h"]/max(1e-6, expected) <= 2.:
            return False
        contains_center = (box["left"] <= spot["cx"] <= box["right"]
                           and box["top"] <= spot["cy"] <= box["bottom"])
        spot_contains = (spot["left"] <= box["cx"] <= spot["right"]
                         and spot["top"] <= box["cy"] <= spot["bottom"])
        return (contains_center or spot_contains) and abs(box["cx"]-spot["cx"]) <= max(.03, .35*spot["w"])

    def _focus_geometry(self, box: dict) -> bool:
        fx, fy = self._focus()
        return (abs(box["cx"]-fx) <= .03+.10*box["w"]
                and box["top"] <= fy-.005 and box["bottom"] >= fy+.01
                and box["h"] >= .035)

    def _confirm(self, box: dict, state: dict, source: str, now: float) -> None:
        self.spot = dict(box)
        self.spot_at = now
        self.spot_source = source
        distance = number(state.get("camera_distance"))
        self.spot_camera_distance = distance if distance and distance > .5 else None

    # ---------------------------------------------------------------- evidence
    def _hover_evidence(self, state: dict, subjects, now: float) -> None:
        mouse = state.get("mouseover") or {}
        guid = str(mouse.get("guid") or "")
        cursor = state.get("cursor_position") or {}
        nx, ny = number(cursor.get("nx")), number(cursor.get("ny"))
        sample = number(state.get("mouseover_sample_time"))
        clock = number(state.get("monotonic_time"))
        if not guid or nx is None or ny is None:
            return
        if sample is not None and clock is not None and not 0 <= clock-sample <= .75:
            return
        own = {str(state.get("character_guid") or ""), str(state.get("vehicle_guid") or "")} - {""}
        point = (nx, 1.-ny)
        inside = [(item, box) for item, box in subjects
                  if box["left"] <= point[0] <= box["right"] and box["top"] <= point[1] <= box["bottom"]]
        if not inside:
            return
        if guid in own or mouse.get("is_self") is True:
            item, box = min(inside, key=lambda pair: pair[1]["w"]*pair[1]["h"])
            self.vetoed.pop(box["track_id"], None)
            self._confirm(box, state, "ADDON_MOUSEOVER_SELF", now)
            return
        for item, box in inside:
            # Another unit's name under the cursor near the box centre.
            if (abs(point[0]-box["cx"]) <= .3*box["w"] and abs(point[1]-box["cy"]) <= .35*box["h"]):
                self.vetoed[box["track_id"]] = now

    def _rotation_evidence(self, subjects, orientation: float | None, now: float, state: dict) -> None:
        if orientation is None:
            return
        for frame_at, frame_orientation, frame_boxes in self.frames:
            if now-frame_at > self.HISTORY_SECONDS or now-frame_at < .05:
                continue
            turned = abs(_angle_delta(frame_orientation, orientation))
            if turned < self.MIN_TURN:
                continue
            expected_shift = math.tan(min(turned, 1.2))/2.
            for item, box in subjects:
                if not self._live(item):
                    continue
                previous = frame_boxes.get(box["track_id"])
                if previous is not None and abs(previous["cx"]-box["cx"]) >= .5*expected_shift:
                    self.vetoed[box["track_id"]] = now          # moved with the world
                    continue
                if any(self._same_spot(old, box) for old in frame_boxes.values()):
                    hits = self.rotation_hits.setdefault(box["track_id"], [])
                    if frame_at not in hits:
                        hits.append(frame_at)
        for track_id, hits in list(self.rotation_hits.items()):
            hits[:] = [at for at in hits if now-at <= self.HISTORY_SECONDS+2.]
            if not hits:
                del self.rotation_hits[track_id]
        for item, box in subjects:
            if (len(self.rotation_hits.get(box["track_id"], ())) >= self.ROTATION_CONFIRMATIONS
                    and box["track_id"] not in self.vetoed):
                self._confirm(box, state, "EGO_ROTATION_SCREEN_FIXED", now)

    # ------------------------------------------------------------------- update
    def update(self, state: dict) -> list[str]:
        """Mark the avatar box in ``state['visual_candidates']``; return its track ids."""
        subjects = self._subjects(state)
        if not subjects:
            self.diagnostics = {"status": "NO_SUBJECTS"}
            return []
        frame_key = max((number(item.get("observed_at")) or 0.) for item, _ in subjects)
        now = frame_key or number(state.get("monotonic_time")) or 0.
        orientation = number(state.get("orientation"))
        for track_id, at in list(self.vetoed.items()):
            if now-at > self.VETO_SECONDS:
                del self.vetoed[track_id]
        self._hover_evidence(state, subjects, now)
        if frame_key != self.last_frame_key:
            self._rotation_evidence(subjects, orientation, now, state)
            if orientation is not None:
                self.frames.append((now, orientation,
                                    {box["track_id"]: box for item, box in subjects if self._live(item)}))
            self.last_frame_key = frame_key
        while self.frames and now-self.frames[0][0] > self.HISTORY_SECONDS:
            self.frames.popleft()
        if now-self.spot_at > self.SPOT_SECONDS:
            self.spot, self.spot_source = None, None

        name = str(state.get("character_name") or "").strip()
        guid = str(state.get("character_guid") or "").strip() or None
        allowed = [(item, box) for item, box in subjects if box["track_id"] not in self.vetoed]
        chosen, source = None, None
        spot_matches = [(item, box) for item, box in allowed if self._matches_spot(box, state)]
        if spot_matches:
            chosen = max(spot_matches, key=lambda pair: pair[1]["h"])
            source = self.spot_source or "CONFIRMED_SELF_SPOT"
            if self._live(chosen[0]):
                # Follow gradual zoom / bob, keep the original evidence age.
                at, origin = self.spot_at, self.spot_source
                self._confirm(chosen[1], state, origin or source, now)
                self.spot_at = max(at, now-self.SPOT_SECONDS/2)
        else:
            focus = [(item, box) for item, box in allowed if self._focus_geometry(box)]
            if focus:
                chosen = max(focus, key=lambda pair: pair[1]["h"])
                source = "THIRD_PERSON_FOCUS_GEOMETRY"
        marked = []
        if chosen is not None:
            mark_self_avatar(chosen[0], name=name, guid=guid,
                             source=f"ADDON_LOCAL_PLAYER+{source}",
                             belief="CONFIRMED" if source != "THIRD_PERSON_FOCUS_GEOMETRY" else "SUPPORTED")
            marked.append(chosen[1]["track_id"])
        self.diagnostics = {
            "status": "IDENTIFIED" if marked else "NOT_VISIBLE",
            "track_ids": marked, "source": source,
            "spot": ({key: round(self.spot[key], 4) for key in ("cx", "cy", "w", "h")}
                     if self.spot else None),
            "spot_source": self.spot_source, "vetoed": sorted(self.vetoed),
            "rotation_candidates": {key: len(value) for key, value in self.rotation_hits.items()},
        }
        return marked

    def snapshot(self) -> dict:
        return dict(self.diagnostics)
