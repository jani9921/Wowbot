"""VisualApproachController track following: live continuation, rebinding, confidence inheritance.

Split out of visual_approach.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
from .models import number
from .self_avatar import is_self_avatar_box


class VisualApproachTrackingMixin:
    """Methods of VisualApproachController (visual_approach.py); moved verbatim."""

    def _turn_corrected_x(self, state: dict, x: float, heading) -> float:
        now_heading = number(state.get("orientation"))
        if heading is None or now_heading is None:
            return x
        turned = (now_heading-heading+math.pi) % (2*math.pi) - math.pi
        return x + turned*self.TURN_SCREEN_PER_RAD     # a left turn pans the world right

    def _inherits_confidence(self, distance: float, item_height, height, confident: bool) -> bool:
        """User 2026-10-04: a weaker box (<0.30) exactly where the previously
        confident (e.g. 0.60) box was, with the same size, during camera
        motion/running is the same target -- do not drop it."""
        if not confident or distance > self.INHERIT_GATE:
            return False
        return (not height or not item_height
                or self.INHERIT_SIZE[0] <= item_height/height <= self.INHERIT_SIZE[1])

    def _live_continuation(self, state: dict, exclude_track_id, x: float | None, y: float | None,
                           height: float | None, *, heading=None, confident: bool = False) -> dict | None:
        """An unambiguous live subject box continuing a lost/coasting track.

        Live 2026-09-30: one NPC often had two alternating tracks; whenever the
        committed one coasted (OCCLUDED/LOST) the approach stopped and then
        failed with visual_track_lost although its live twin stood in the same
        place, and SEEK had no rebinding at all.  This is steering continuity
        only: addon mouseover/GUID checks stay the identity authority.
        """
        if x is None or y is None:
            return None
        x = self._turn_corrected_x(state, x, heading)
        ranked = []
        for item in state.get("visual_candidates", []):
            if (item.get("source") != "WORLD3D" or not item.get("track_id")
                    or item.get("track_id") == exclude_track_id
                    or item.get("track_id") in self.rejected_reacquire_track_ids
                    or "subject" not in str(item.get("detector_kind") or item.get("kind") or "")
                    or str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
                        not in self._LIVE_LIFECYCLES
                    or (item.get("visual_identity") or {}).get("kind") == "SELF_PLAYER"
                    or is_self_avatar_box(item)):
                continue
            ix, iy = number(item.get("x")), number(item.get("y"))
            if ix is None or iy is None:
                continue
            item_height = self._height(item)
            if (height and item_height and not .5 <= item_height/height <= 2.):
                continue
            # Live 2026-10-01: steering rebound to a .12-confidence box, lost
            # it and overshot the NPC.  Weak boxes never take over steering --
            # unless they sit exactly where the confident box was (inherited).
            distance = math.hypot(ix-x, iy-y)
            confidence = number(item.get("confidence")) or 0.
            if confidence < .30 and not (
                    confidence >= self.INHERIT_MIN_CONFIDENCE
                    and self._inherits_confidence(distance, item_height, height, confident)):
                continue
            ranked.append((distance, item))
        ranked.sort(key=lambda entry: entry[0])
        if ranked and ranked[0][0] <= .12 and (len(ranked) == 1 or ranked[1][0]-ranked[0][0] >= .035):
            return ranked[0][1]
        return None

    def _last_real_sample(self, now: float):
        return next((sample for sample in reversed(self.samples)
                     if not sample.predicted and sample.x is not None and sample.y is not None
                     and now-sample.visual_sample_time <= .85), None)

    def _vehicle_rebind(self, state: dict, now: float) -> dict | None:
        """Re-find the aimed unit after its track id vanished (vehicle aim).

        Live 2026-10-04 (Giant Boar): a far Monstrous Cadaver was a 14x26 px
        box at 0.25 confidence; it flickered out of detection, came back
        under a new id, and the >=0.30 rebind rule rejected it -> TARGET_LOST.
        A ridden vehicle turns fast, so predict where the box must be from
        the exact facing change (telemetry), then take the unambiguous
        similar-size box there, even at low confidence.
        """
        last = next((sample for sample in reversed(self.samples)
                     if not sample.predicted and sample.x is not None and sample.y is not None
                     and now-sample.visual_sample_time <= 1.5), None)
        if last is None:
            return None
        heading = number(state.get("orientation"))
        predicted_x = last.x
        if heading is not None and last.player_heading is not None:
            turned = (heading-last.player_heading+math.pi) % (2*math.pi) - math.pi
            predicted_x = last.x + turned*self.TURN_SCREEN_PER_RAD   # left turn pans the world right
        ranked = []
        for item in state.get("visual_candidates", []):
            if (item.get("source") != "WORLD3D" or not item.get("track_id")
                    or "subject" not in str(item.get("detector_kind") or item.get("kind") or "")
                    or str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
                    not in self._LIVE_LIFECYCLES
                    or is_self_avatar_box(item)
                    or str(item.get("track_id")) in self.rejected_reacquire_track_ids
                    or (number(item.get("confidence")) or 0.) < .12):
                continue
            ix, iy = number(item.get("x")), number(item.get("y"))
            height = self._height(item)
            if ix is None or iy is None:
                continue
            if last.bbox_height and height and not .6 <= height/last.bbox_height <= 1.67:
                continue
            distance = math.hypot(ix-predicted_x, (iy-last.y)*1.5)
            if distance <= .09:
                ranked.append((distance, item))
        ranked.sort(key=lambda entry: entry[0])
        if ranked and (len(ranked) == 1 or ranked[1][0]-ranked[0][0] >= .03):
            self.track_rebindings += 1
            return {**ranked[0][1], "_predicted": False, "vehicle_rebound": True}
        return None

    def _track(self, state: dict, now: float) -> dict | None:
        track_id = (self.intent or {}).get("track_id")
        if track_id and (self.intent or {}).get("purpose") in {"VEHICLE_AIM", "VEHICLE_ATTACK"}:
            present = any(item.get("track_id") == track_id
                          and item.get("lifecycle") != "TERMINATED"
                          and str(item.get("lifecycle") or "ACTIVE").upper()
                          not in {"OCCLUDED", "LOST_TEMPORARY"}
                          for item in state.get("visual_candidates", []))
            if not present:
                rebound = self._vehicle_rebind(state, now)
                if rebound is not None:
                    return rebound
        if track_id:
            match = next((item for item in state.get("visual_candidates", [])
                          if item.get("track_id") == track_id
                          and item.get("lifecycle") != "TERMINATED"), None)
            if match and is_self_avatar_box(match):
                # Live 2026-10-04: the "target box" was the ridden boar itself.
                match = None
            if match:
                lifecycle = str(match.get("lifecycle") or match.get("track_state") or "ACTIVE").upper()
                coasting = lifecycle in {"OCCLUDED", "LOST_TEMPORARY"}
                if coasting:
                    last_real = self._last_real_sample(now)
                    twin = self._live_continuation(
                        state, track_id, number(match.get("x")), number(match.get("y")),
                        self._height(match),
                        confident=bool(last_real and (last_real.confidence or 0.) >= .30))
                    if twin is not None:
                        self.track_rebindings += 1
                        return {**twin, "_predicted": False, "live_twin_rebound": True}
                return {**match, "_predicted": coasting}
            # The tracker can reassign a new track_id mid-approach (occlusion,
            # camera motion). A matching visual_signature is the same
            # re-acquisition evidence SeekVisualCueController._candidate()
            # already trusts (vision_seek.py); reuse it here so a committed
            # approach survives the same event instead of exhausting
            # missing_observations against an id that no longer exists.
            signature_id = ((self.intent or {}).get("visual_signature") or {}).get("signature_id")
            if signature_id:
                resignatured = next((item for item in state.get("visual_candidates", [])
                              if item.get("lifecycle") != "TERMINATED"
                              and (item.get("visual_signature") or {}).get("signature_id") == signature_id), None)
                if resignatured:
                    lifecycle = str(resignatured.get("lifecycle") or resignatured.get("track_state") or "ACTIVE").upper()
                    return {**resignatured, "_predicted": lifecycle in {"OCCLUDED", "LOST_TEMPORARY"}}
            # The canonical presentation tracker may assign a new id after a
            # detector refresh even though Retail still has the exact same
            # GUID selected.  Rebind only steering evidence: identity remains
            # the addon-selected GUID and is periodically rechecked by HOVER.
            # Prefer a freshly GUID-confirmed mouseover anchor; otherwise use
            # an unambiguous, nearby continuation of the last real servo
            # measurement.  This prevents a harmless track-id restart from
            # terminating W while still rejecting adjacent look-alike NPCs.
            guid = str((self.intent or {}).get("guid") or "")
            target = state.get("target") or {}
            if guid and str(target.get("guid") or "") == guid:
                candidates = [
                    item for item in state.get("visual_candidates", [])
                    if item.get("source") == "WORLD3D"
                    and item.get("track_id")
                    and item.get("track_id") != track_id
                    and not is_self_avatar_box(item)
                    and "subject" in str(
                        item.get("detector_kind") or item.get("kind") or "")
                    and str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
                        not in {"TERMINATED", "LOST_TEMPORARY"}
                    and number(item.get("x")) is not None
                    and number(item.get("y")) is not None
                ]
                anchor = (state.get("confirmed_mouseover_anchors") or {}).get(guid) or {}
                anchor_track_id = anchor.get("track_id")
                rebound = None
                if anchor_track_id and self._anchor_scene_valid(anchor, state, now):
                    rebound = next((item for item in candidates
                                    if item.get("track_id") == anchor_track_id), None)
                if rebound is None and self.samples:
                    last = next((sample for sample in reversed(self.samples)
                                 if not sample.predicted and sample.x is not None
                                 and sample.y is not None
                                 and now-sample.visual_sample_time <= .85), None)
                    if last is not None:
                        # Live 2026-10-01: steering jumped onto a gnome player
                        # standing next to Jaina.  Weak or differently sized
                        # boxes never take over.
                        last_x = self._turn_corrected_x(state, last.x, last.player_heading)

                        def compatible(item):
                            item_height = self._height(item)
                            if (number(item.get("confidence")) or 0.) < .30:
                                distance = math.hypot(float(item["x"])-last_x, float(item["y"])-last.y)
                                return ((number(item.get("confidence")) or 0.) >= self.INHERIT_MIN_CONFIDENCE
                                        and self._inherits_confidence(
                                            distance, item_height, last.bbox_height,
                                            (last.confidence or 0.) >= .30))
                            return (not last.bbox_height or not item_height
                                    or .6 <= item_height/last.bbox_height <= 1.67)
                        ranked = sorted((
                            (math.hypot(float(item["x"])-last_x,
                                        float(item["y"])-last.y), item)
                            for item in candidates if compatible(item)),
                            key=lambda entry: entry[0])
                        if (ranked and ranked[0][0] <= .12
                                and (len(ranked) == 1
                                     or ranked[1][0]-ranked[0][0] >= .035)):
                            rebound = ranked[0][1]
                if rebound is not None:
                    self.track_rebindings += 1
                    lifecycle = str(rebound.get("lifecycle")
                                    or rebound.get("track_state") or "ACTIVE").upper()
                    return {**rebound,
                            "_predicted": lifecycle == "OCCLUDED",
                            "guid_rebound": True}
            # Association can arrive one tracker frame before the matching
            # projection. A still-selected authoritative GUID plus its fresh
            # mouseover anchor is a safe first servo measurement; it is not a
            # new recognition and remains scene/age constrained.
            anchor = ((state.get("confirmed_mouseover_anchors") or {}).get(guid)
                      or (self.intent or {}).get("screen_position") or {})
            if (guid and target.get("guid") == guid
                    and number(anchor.get("x")) is not None
                    and self._anchor_scene_valid(anchor, state, now)):
                return {**anchor, "track_id": track_id,
                        "confidence": number(anchor.get("track_confidence")) or .7,
                        "lifecycle": "ACTIVE", "_predicted": False}
            # A vanished id with an unambiguous live continuation at the last
            # real measurement (same place, similar size) keeps steering; this
            # also covers SEEK, which has no selected GUID yet.
            last = self._last_real_sample(now)
            if last is not None:
                continuation = self._live_continuation(
                    state, track_id, last.x, last.y, last.bbox_height,
                    heading=last.player_heading, confident=(last.confidence or 0.) >= .30)
                if continuation is not None:
                    self.track_rebindings += 1
                    return {**continuation, "_predicted": False, "live_twin_rebound": True}
            # Once identity was associated with a Track, never fall back to
            # the frozen starting pixel. Losing the track must stop forward
            # motion and enter bounded visual reacquisition.
            return None
        guid = str((self.intent or {}).get("guid") or "")
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        if (guid and mouse.get("guid") == guid
                and mouse_time is not None and 0 <= now-mouse_time <= .75):
            cursor = state.get("cursor_position") or {}
            x, y = number(cursor.get("nx")), number(cursor.get("ny"))
            if x is not None and y is not None:
                return {"x": x, "y": y, "confidence": 1., "source": "ADDON_MOUSEOVER"}
        anchor = ((state.get("confirmed_mouseover_anchors") or {}).get(guid)
                  or ((state.get("target") or {}).get("screen_position")
                      if str((state.get("target") or {}).get("guid") or "") == guid else None)
                  or (self.intent or {}).get("screen_position") or {})
        return (anchor if number(anchor.get("x")) is not None
                and self._anchor_scene_valid(anchor, state, now) else None)

    @staticmethod
    def _anchor_scene_valid(anchor: dict, state: dict, now: float) -> bool:
        sampled = number(anchor.get("sample_time"))
        if sampled is not None and not 0 <= now-sampled <= .75:
            return False
        old = anchor.get("player_world_snapshot") or {}
        new = state.get("player_world_position") or {}
        ox, oy, nx, ny = (number(old.get("x")), number(old.get("y")),
                          number(new.get("x")), number(new.get("y")))
        if None not in (ox, oy, nx, ny) and math.hypot(nx-ox, ny-oy) > .75:
            return False
        old_heading = number(anchor.get("orientation_snapshot"))
        new_heading = number(state.get("orientation"))
        if None not in (old_heading, new_heading):
            if abs((new_heading-old_heading+math.pi) % math.tau-math.pi) > .08:
                return False
        return True
