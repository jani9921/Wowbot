"""Persistent screen-space servo for a committed visual target.

This controller never recognizes an entity.  It consumes a Track↔Entity
association already supported by addon mouseover and maintains a bounded
closed-loop approach when exact world coordinates are unavailable.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum
import math
import os

from .models import Command, number
from .self_avatar import is_self_avatar_box


class VisualApproachPhase(StrEnum):
    IDLE = "IDLE"
    CENTERING = "CENTERING"
    ADVANCING = "ADVANCING"
    OCCLUDED = "OCCLUDED"
    INTERACTION_READY = "INTERACTION_READY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class VisualServoMeasurement:
    """Timestamped fusion input consumed by the persistent movement skill.

    Vision remains measurement-only. Identity comes from the committed intent;
    telemetry fields may be stale between addon snapshots and are therefore
    carried with their own sample timestamp instead of being counted again on
    every visual frame.
    """
    observation_id: str
    at: float
    track_id: str | None
    x: float | None
    y: float | None
    bbox_height: float | None
    bbox_scale_delta: float | None
    center_error: float | None
    confidence: float
    source: str
    lifecycle: str
    predicted: bool
    camera_motion_x: float | None
    camera_motion_y: float | None
    player_x: float | None
    player_y: float | None
    player_heading: float | None
    player_speed: float | None
    player_moving: bool | None
    telemetry_sample_time: float | None
    obstacle_evidence: float
    visual_sample_time: float


# Public compatibility name used by earlier diagnostics/imports.
VisualApproachSample = VisualServoMeasurement


@dataclass(frozen=True, slots=True)
class VisualApproachAssessment:
    phase: VisualApproachPhase
    terminal: bool
    success: bool
    reason: str


class VisualApproachController:
    max_seconds = 30.0
    max_missing_observations = 8
    # Live-observed 2026-09-14: max_missing_observations counts *ticks*, not
    # wall-clock time. Tuned on a slower dev machine (~10-15 Hz addon rate),
    # 8 ticks meant roughly half a second; on a faster machine producing many
    # more ticks per second, the same 8-count threshold is reached far
    # sooner in real time, declaring visual_track_lost prematurely. This
    # floor only adds a second, independent condition alongside the existing
    # count -- it can only make FAILED harder to reach than before, never
    # easier, so it is safe without its own live re-validation.
    max_missing_seconds = 1.0
    # A World3D track associated with an entity by one mouseover is useful
    # steering evidence, but it is not identity evidence forever.  Camera
    # motion and detector drift can keep the same track id attached to a
    # visually similar foreground patch after the actual unit left it.  Check
    # the current screen point at this cadence before extending a committed
    # friendly interaction approach.  This is a HOVER only -- no click and no
    # semantic decision is made from CV.
    identity_recheck_forward_updates = 3
    # This waits for the addon detail lane, not for a detector frame.  Live
    # PID 1468 on 2026-09-29 produced the exact Jaina mouseover update 1.48 s
    # after our HOVER.  The old .85 s deadline therefore rejected a correct
    # GUID before the exporter could possibly answer and no forward command
    # was ever issued.  Movement remains released throughout this bounded
    # wait, and a fresh contradictory GUID still fails immediately.
    identity_recheck_timeout_seconds = 2.0

    range_probe_enabled = os.environ.get("AIPC_VA_RANGE_PROBE", "0") == "1"
    # Keep the pointer on the approached unit while walking (pointer-only
    # HOVER does not release the forward lease in the executor).
    pointer_tracking = os.environ.get("AIPC_VA_POINTER_TRACK", "1") != "0"
    POINTER_INTERVAL = .5
    POINTER_TOLERANCE = .03

    def __init__(self, bindings=None):
        self.bindings = bindings
        self.reset()

    def reset(self):
        self.intent = None
        self.started_at = None
        self.phase = VisualApproachPhase.IDLE
        self.samples = deque(maxlen=32)
        self.last_observation_id = None
        self.missing_observations = 0
        self.missing_observations_since = None
        self.reacquire_count = 0
        self.control_updates = 0
        self.last_command_at = None
        self.steering_reversals = 0
        self.overshoot_count = 0
        self._last_error = None
        self._last_turn = None
        self.reacquire_actions = 0
        self.last_interaction_probe_at = None
        # In range but not yet facing the NPC: stop and turn in place first
        # (user 2026-10-01: the character must face the NPC/mob it uses).
        self.final_align_started_at: float | None = None
        self.last_pointer_hover_at = -float("inf")
        self.pointer_hovers = 0
        self.wrong_track_rejections = 0
        # Last *observed* box edges (normalised, top-left origin) and time:
        # which screen edge the unit left by tells what went wrong (user
        # 2026-10-01): bottom = ran past it, left/right = over-turned,
        # top = backed off / camera pitched down.
        self.last_edges: tuple[float, float, float, float] | None = None
        self.last_edges_at: float | None = None
        self.edge_corrections = 0
        self.last_edge_command_at = -float("inf")
        self.edge_recovery_started_at: float | None = None
        self.last_self_edges: tuple[float, float, float, float] | None = None
        self.last_command_visual_sample_time = None
        self.forward_updates_since_probe = 0
        self.visual_progress_samples = 0
        self.visual_no_progress_samples = 0
        self.stuck_evidence_sources = set()
        self.last_distinct_visual_sample_time = None
        self.identity_rechecks = 0
        self.identity_reconfirmations = 0
        self.identity_recheck_requested_at = None
        self.identity_recheck_mouse_sample_before = None
        self.identity_recheck_track_id: str | None = None
        # Live 2026-10-01: after a successful re-hover the servo still stopped
        # every three forward updates to re-hover the same track (W released
        # each time, 2-4 pauses per approach, failures when the addon sample
        # was late).  One confirmation per bound track is enough.
        self.identity_confirmed_track_id: str | None = None
        self.rejected_reacquire_track_ids: set[str] = set()
        self.last_confirmed_hover_point = None
        self.last_occluded_reacquire_at = None
        self.track_rebindings = 0

    def _matching_fresh_mouseover(self, state: dict, now: float,
                                  *, after: float | None = None) -> bool:
        """Whether a *new* addon hover confirms the committed identity.

        The cursor and mouseover are sampled independently by the exporter;
        requiring both to be recent prevents an older tooltip from validating
        a HOVER that has already moved to another screen point.
        """
        expected = str((self.intent or {}).get("guid") or "")
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        cursor_time = number(state.get("cursor_sample_time"))
        if not expected or str(mouse.get("guid") or "") != expected:
            return False
        if mouse_time is None or not 0 <= now-mouse_time <= .75:
            return False
        if cursor_time is not None and not 0 <= now-cursor_time <= .75:
            return False
        return after is None or mouse_time > after + .000001

    def _pointer_names_other_unit(self, state: dict, now: float) -> str | None:
        """Track id under the pointer when a fresh mouseover names another GUID.

        Only evaluated after our own POINTER put the cursor on the followed
        box and the cursor is still there; a confirming sample marks the
        track as identity-confirmed instead.
        """
        expected = str((self.intent or {}).get("guid") or "")
        track_id = (self.intent or {}).get("track_id")
        if not expected or not track_id or self.last_pointer_hover_at == -float("inf"):
            return None
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        if (mouse_time is None or mouse_time <= self.last_pointer_hover_at + .03
                or not 0 <= now-mouse_time <= .75):
            return None
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        sample = self.samples[-1] if self.samples else None
        if (sample is None or None in (cx, cy, sample.x, sample.y)
                or math.hypot(cx-sample.x, cy-sample.y) > 2*self.POINTER_TOLERANCE):
            return None
        guid = str(mouse.get("guid") or "")
        if not guid:
            return None
        if guid == expected:
            self.identity_confirmed_track_id = track_id
            return None
        return str(track_id)

    def _identity_recheck_failed(self, state: dict, now: float) -> bool:
        """Return true only after a requested hover had time to answer."""
        requested = self.identity_recheck_requested_at
        if requested is None:
            return False
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        expected = str((self.intent or {}).get("guid") or "")
        # A new, different GUID is direct contradictory evidence.  A missing
        # sample is allowed only for the bounded addon-latency window.
        if (mouse_time is not None and mouse_time > (self.identity_recheck_mouse_sample_before or -math.inf) + .000001
                and mouse.get("guid") and str(mouse.get("guid")) != expected):
            return True
        return now-requested >= self.identity_recheck_timeout_seconds

    def _requires_identity_recheck(self) -> bool:
        """Only re-hover a one-shot mouseover↔World3D association.

        A direct `NAMEPLATE_API` target position and the generic unit-test
        servo already have their own tracking authority.  The live failure
        involved precisely the weaker `CANDIDATE` association created from a
        cursor hover, so keep the extra probe scoped to that case.
        """
        screen = (self.intent or {}).get("screen_position") or {}
        track_id = (self.intent or {}).get("track_id")
        if track_id is not None and track_id == self.identity_confirmed_track_id:
            return False
        return (self.intent or {}).get("purpose") == "INTERACT" and (
            screen.get("source") in {"CONFIRMED_MOUSEOVER", "CONFIRMED_MOUSEOVER_ANCHOR"}
            and screen.get("track_association") == "CANDIDATE")

    def _reacquire_hover_candidate(self, state: dict) -> dict | None:
        """Choose a plausible new visual track to verify with addon hover.

        This does not reassign identity.  It only chooses where to put the
        pointer while the exact selected GUID remains authoritative.  The
        track is adopted later only if that hover returns the same GUID.
        """
        current_id = str((self.intent or {}).get("track_id") or "")
        previous_height = next((sample.bbox_height for sample in reversed(self.samples)
                                if not sample.predicted and sample.bbox_height is not None), None)
        ranked = []
        for item in state.get("visual_candidates", []):
            kind = str(item.get("detector_kind") or item.get("kind") or "")
            lifecycle = str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
            appearance = item.get("appearance") or {}
            identity = item.get("visual_identity") or {}
            if (item.get("source") != "WORLD3D" or not item.get("track_id")
                    or str(item.get("track_id")) == current_id
                    or str(item.get("track_id")) in self.rejected_reacquire_track_ids
                    or "subject" not in kind or lifecycle in {
                        "TERMINATED", "LOST", "LOST_TEMPORARY", "OCCLUDED"}
                    or item.get("self_player_avatar") is True
                    or identity.get("kind") == "SELF_PLAYER"
                    or appearance.get("self_player_avatar") is True
                    or number(item.get("x")) is None or number(item.get("y")) is None):
                continue
            relations = item.get("visual_relations") or ()
            overhead_supported = any(
                str(edge.get("type") or "").upper() == "ABOVE"
                and str(edge.get("belief") or "").upper() == "SUPPORTED"
                for edge in relations)
            group = item.get("visual_group") or {}
            group_supported = str(group.get("belief") or "").upper() == "SUPPORTED"
            height = self._height(item)
            scale_similarity = (1.-min(1., abs(height-previous_height)/max(.03, previous_height))
                                if height is not None and previous_height is not None else 0.)
            real_body = kind != "unknown_subject_probe"
            score = (3. if overhead_supported else 0.) + (2. if group_supported else 0.)
            score += (1. if real_body else 0.) + scale_similarity
            score += (number(appearance.get("body_geometry")) or 0.)
            score += (number(item.get("confidence")) or 0.)*.25
            ranked.append((score, item))
        if not ranked:
            return None
        score, candidate = max(ranked, key=lambda entry: entry[0])
        # A replacement without either an overhead relation/group or strong
        # body evidence is too ambiguous to probe in a crowded NPC cluster.
        appearance = candidate.get("appearance") or {}
        relations = candidate.get("visual_relations") or ()
        supported = any(str(edge.get("belief") or "").upper() == "SUPPORTED"
                        for edge in relations)
        supported = supported or str((candidate.get("visual_group") or {}).get(
            "belief") or "").upper() == "SUPPORTED"
        return candidate if supported or (number(appearance.get("body_geometry")) or 0.) >= .82 else None

    def start(self, intent: dict, state: dict, observation_id: str, now: float):
        identity = (intent.get("guid"), intent.get("track_id"), intent.get("purpose"))
        current = ((self.intent or {}).get("guid"), (self.intent or {}).get("track_id"),
                   (self.intent or {}).get("purpose"))
        if identity != current or self.phase == VisualApproachPhase.FAILED:
            # A prior terminal FAILED phase (e.g. visual_approach_safety_deadline)
            # otherwise survives unchanged when the same identity restarts:
            # started_at stays in the past, so observe() re-hits the deadline
            # immediately, command() keeps returning no commands, and the
            # caller never creates a new Attempt to retry through -- a live
            # 2026-09-13 run froze on one target for 9+ minutes this way, with
            # neither the outcome() retry-block nor the approach_counts budget
            # able to fire since no attempt ever completed to trigger them.
            # Restarting the same identity is always a fresh attempt; give it
            # its own full safety-deadline window instead of an inherited one.
            self.reset()
        self.intent = dict(intent)
        self.started_at = now if self.started_at is None else self.started_at
        self.forward_commands_total = 0          # advance required per attempt
        # The proposal's starting point came from an exact addon mouseover
        # association. Preserve it as the first bounded re-hover point; live
        # PID 1468 showed that leaving this unset made a detector gap issue
        # only INTERACTTARGET probes until visual_track_lost, so the WorldModel
        # never got a fresh cursor sample with which to bind a replacement
        # track id to the same selected GUID.
        screen = self.intent.get("screen_position") or {}
        sx, sy = number(screen.get("x")), number(screen.get("y"))
        if (self._requires_identity_recheck() and sx is not None and sy is not None
                and self._anchor_scene_valid(screen, state, now)):
            self.last_confirmed_hover_point = {"x": sx, "y": sy, "at": now}
        if self.intent.get("purpose") == "INTERACT" and self.last_interaction_probe_at is None:
            # The approach normally starts immediately after an explicit
            # out-of-range INTERACT failure; do not repeat that same probe in
            # the same feedback window.
            self.last_interaction_probe_at = now
        return self.observe(state, observation_id, now)

    _LIVE_LIFECYCLES = frozenset({"ACTIVE", "STABLE", "TENTATIVE", "REACQUIRE_CANDIDATE"})

    INHERIT_GATE = .05          # same place (screen fraction, after turn correction)
    INHERIT_SIZE = (.75, 1.33)  # same size
    INHERIT_MIN_CONFIDENCE = .10

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

    RANGE_ERROR_STEPS = (5, 3, 2)          # forward pulses after the 1st/2nd/later range error (user)

    # Horizontal screen fraction one radian of turning moves the world
    # (~90 degree horizontal field of view).
    TURN_SCREEN_PER_RAD = .64

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

    @staticmethod
    def _height(track: dict) -> float | None:
        value = number(track.get("servo_scale_fraction"))
        if value is not None:
            return value
        value = number(track.get("bbox_height_fraction"))
        if value is not None:
            return value
        history = track.get("bbox_history") or []
        bbox = track.get("bbox") or (history[-1] if history else {})
        top, bottom = number(bbox.get("top")), number(bbox.get("bottom"))
        frame_height = number(track.get("frame_height"))
        return (bottom-top)/frame_height if None not in (top, bottom, frame_height) and frame_height else None

    @staticmethod
    def _edges(track: dict) -> tuple[float, float, float, float] | None:
        """Normalised (left, top, right, bottom) of a track box, top-left origin."""
        bbox = track.get("bbox") or {}
        left, top = number(bbox.get("left")), number(bbox.get("top"))
        right, bottom = number(bbox.get("right")), number(bbox.get("bottom"))
        frame_h = number(track.get("frame_height"))
        frame_w = number(track.get("frame_width"))
        fraction_h = number(track.get("bbox_height_fraction"))
        fraction_w = number(track.get("bbox_width_fraction"))
        if None in (left, top, right, bottom) or bottom <= top or right <= left:
            return None
        if not frame_h and fraction_h:
            frame_h = (bottom-top)/fraction_h
        if not frame_w and fraction_w:
            frame_w = (right-left)/fraction_w
        if not frame_h or not frame_w:
            return None
        return left/frame_w, top/frame_h, right/frame_w, bottom/frame_h

    @classmethod
    def _self_edges(cls, state: dict) -> tuple[float, float, float, float] | None:
        """Edges of the own avatar's box (self identity or screen-anchored)."""
        for item in state.get("visual_candidates", []):
            appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
            identity = item.get("visual_identity") if isinstance(item.get("visual_identity"), dict) else {}
            if (item.get("self_player_avatar") is True or identity.get("kind") == "SELF_PLAYER"
                    or appearance.get("self_player_avatar") is True
                    or appearance.get("screen_anchored") is True):
                edges = cls._edges(item)
                if edges is not None:
                    return edges
        return None

    @staticmethod
    def _beside_self(target: tuple[float, float, float, float],
                     own: tuple[float, float, float, float], *, lying: bool = False) -> bool:
        """User 2026-10-01: arrived when the unit's box stands next to / overlaps
        the own avatar's box by roughly a quarter to a third.  Similar height
        and feet at a similar screen level keep a distant unit standing
        *behind* the avatar from counting."""
        tl, tt, tr, tb = target
        sl, st, sr, sb = own
        t_h, s_h = tb-tt, sb-st
        if t_h <= 0 or s_h <= 0 or abs(tb-sb) > (.10 if lying else .12):
            return False
        if not lying and not .6 <= t_h/s_h <= 1.8:
            return False
        overlap_w = max(0., min(tr, sr)-max(tl, sl))
        gap = max(0., max(tl, sl)-min(tr, sr))
        narrower = max(1e-6, min(tr-tl, sr-sl))
        return overlap_w/narrower >= .25 or gap <= .5*(sr-sl)

    def _edge_recovery_pending(self, now: float) -> bool:
        if self._exit_edge(now) is None:
            return False
        started = self.edge_recovery_started_at
        return started is None or now-started <= 1.5

    def _exit_edge(self, now: float) -> str | None:
        """Screen edge the committed box was last seen touching (≤1.2 s ago)."""
        if self.last_edges is None or self.last_edges_at is None or now-self.last_edges_at > 2.0:
            return None
        left, top, right, bottom = self.last_edges
        if bottom >= .90:
            return "BOTTOM"
        own = self.last_self_edges
        if own is not None:
            sl, st, sr, sb = own
            overlap = max(0., min(right, sr)-max(left, sl))
            near_feet = bottom >= sb-.20*(sb-st)
            if overlap > 0. and near_feet and (bottom-top) >= .5*(sb-st):
                return "BOTTOM"   # ran into/past it: it vanished at the avatar
        if left <= .04:
            return "LEFT"
        if right >= .96:
            return "RIGHT"
        if top <= .04:
            return "TOP"
        return None

    @staticmethod
    def _obstacle_evidence(state: dict) -> float:
        """Return visual support only; this is never a proven blocked path."""
        values = []
        for item in state.get("visual_candidates", []):
            if (item.get("source") == "WORLD3D"
                    and (item.get("detector_kind") or item.get("kind")) == "obstacle_candidate"
                    and (number(item.get("stable_frames")) or 0) >= 3):
                x = number(item.get("x"))
                if x is not None and .32 <= x <= .68:
                    values.append(number(item.get("confidence")) or 0.)
        return max(values, default=0.)

    def _measurement(self, state: dict, observation_id: str, now: float,
                     track: dict, *, predicted: bool) -> VisualServoMeasurement:
        if not predicted:
            edges = self._edges(track)
            if edges is not None:
                self.last_edges, self.last_edges_at = edges, now
                self.edge_recovery_started_at = None
                own = self._self_edges(state)
                if own is not None:
                    self.last_self_edges = own
        x, y = number(track.get("x")), number(track.get("y"))
        height = self._height(track)
        previous_height = next((item.bbox_height for item in reversed(self.samples)
                                if not item.predicted and item.bbox_height is not None), None)
        scale_delta = height-previous_height if height is not None and previous_height is not None else None
        appearance = track.get("appearance") or {}
        player = state.get("player_world_position") or {}
        movement = state.get("movement") or {}
        moving = movement.get("moving", state.get("is_moving"))
        return VisualServoMeasurement(
            observation_id=observation_id, at=now,
            track_id=str(track.get("track_id")) if track.get("track_id") is not None else None,
            x=x, y=y, bbox_height=height, bbox_scale_delta=scale_delta,
            center_error=x-.5 if x is not None else None,
            confidence=number(track.get("confidence")) or .5,
            source=str(track.get("source") or "UNKNOWN"),
            lifecycle=str(track.get("lifecycle") or track.get("track_state") or "ACTIVE").upper(),
            predicted=predicted,
            camera_motion_x=number(appearance.get("camera_motion_dx")),
            camera_motion_y=number(appearance.get("camera_motion_dy")),
            player_x=number(player.get("x")), player_y=number(player.get("y")),
            player_heading=number(state.get("orientation")),
            player_speed=number(movement.get("speed", state.get("movement_speed"))),
            player_moving=moving if isinstance(moving, bool) else None,
            telemetry_sample_time=number(state.get("monotonic_time")),
            obstacle_evidence=self._obstacle_evidence(state),
            visual_sample_time=(number(track.get("observed_at", track.get("last_seen")))
                                or number(track.get("sample_time")) or now))

    def observe(self, state: dict, observation_id: str, now: float) -> VisualApproachAssessment:
        if not self.intent:
            return VisualApproachAssessment(VisualApproachPhase.IDLE, True, False, "no_visual_approach_intent")
        if observation_id == self.last_observation_id:
            return VisualApproachAssessment(self.phase, False, False, "awaiting_fresh_visual_observation")
        self.last_observation_id = observation_id
        target = state.get("target") or {}
        guid = self.intent.get("guid")
        identify = self.intent.get("purpose") == "IDENTIFY"
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        cursor_time = number(state.get("cursor_sample_time"))
        if (identify and mouse.get("guid")
                and mouse.get("guid") != state.get("character_guid")
                and mouse_time is not None and 0 <= now-mouse_time <= 1.5
                and (cursor_time is None or 0 <= now-cursor_time <= 1.5)):
            self.phase = VisualApproachPhase.INTERACTION_READY
            return VisualApproachAssessment(
                self.phase, True, True, "identity_available_during_visual_seek")
        if not identify and guid and target and target.get("guid") != guid:
            self.phase = VisualApproachPhase.FAILED
            return VisualApproachAssessment(self.phase, True, False, "target_identity_changed")
        if (not identify and self.intent.get("purpose") != "LOOT"
                and target.get("dead", target.get("is_dead"))):
            self.phase = VisualApproachPhase.FAILED
            return VisualApproachAssessment(self.phase, True, False, "target_dead")
        wrong = self._pointer_names_other_unit(state, now)
        if wrong is not None:
            # The box being followed belongs to another unit (live
            # 2026-10-01: a gnome player beside Jaina).  Drop it; the
            # occluded/rebinding logic searches for the selected unit again.
            self.rejected_reacquire_track_ids.add(wrong)
            self.wrong_track_rejections += 1
            if self.intent.get("track_id") == wrong:
                self.intent["track_id"] = None
                self.phase = VisualApproachPhase.OCCLUDED
                return VisualApproachAssessment(
                    self.phase, False, False, "pointer_identity_names_another_unit")
        if self.identity_recheck_requested_at is not None:
            if self._matching_fresh_mouseover(
                    state, now, after=self.identity_recheck_mouse_sample_before):
                cursor = state.get("cursor_position") or {}
                x, y = number(cursor.get("nx")), number(cursor.get("ny"))
                if x is not None and y is not None:
                    self.last_confirmed_hover_point = {"x": x, "y": y, "at": now}
                self.identity_recheck_requested_at = None
                self.identity_recheck_mouse_sample_before = None
                if (self.identity_recheck_track_id
                        and self.identity_recheck_track_id != self.intent.get("track_id")):
                    self.intent["track_id"] = self.identity_recheck_track_id
                    self.track_rebindings += 1
                self.identity_recheck_track_id = None
                self.identity_reconfirmations += 1
                self.identity_confirmed_track_id = self.intent.get("track_id")
                # A validated current hover starts a fresh bounded advance
                # segment.  It does not turn the visual candidate into an
                # entity fact; the addon hover remains the authority.
                self.forward_updates_since_probe = 0
            elif self._identity_recheck_failed(state, now):
                # A speculative replacement-track hover is allowed to be
                # wrong: reject that steering hypothesis and try another
                # while stationary.  The selected addon GUID remains the
                # identity authority.  Only failure of a direct recheck of
                # the already-bound track terminates this approach attempt.
                if self.identity_recheck_track_id:
                    self.rejected_reacquire_track_ids.add(
                        self.identity_recheck_track_id)
                    self.identity_recheck_requested_at = None
                    self.identity_recheck_mouse_sample_before = None
                    self.identity_recheck_track_id = None
                    self.phase = VisualApproachPhase.OCCLUDED
                    return VisualApproachAssessment(
                        self.phase, False, False,
                        "replacement_visual_track_identity_not_confirmed")
                # User 2026-10-01: a pointer that slid off the NPC (camera
                # turns move it) must not abort the approach.  This direct
                # re-hover happens only in range; the selected GUID stays the
                # INTERACT authority and a wrong spot surfaces as a client
                # range error, so proceed instead of failing.
                self.identity_recheck_track_id = None
                self.identity_recheck_requested_at = None
                self.identity_recheck_mouse_sample_before = None
                self.identity_confirmed_track_id = self.intent.get("track_id")
                self.identity_recheck_unconfirmed = getattr(
                    self, "identity_recheck_unconfirmed", 0) + 1
                return VisualApproachAssessment(
                    self.phase, False, False,
                    "identity_rehover_unconfirmed_proceeding_with_selected_guid")
            else:
                # Do not refresh W while the physical pointer is waiting for
                # the addon's next mouseover sample.
                return VisualApproachAssessment(
                    self.phase, False, False, "awaiting_visual_identity_reconfirmation")
        if (self.intent.get("purpose") == "INTERACT"
                and ((state.get("quest_ui") or {}).get("open")
                     or (state.get("gossip_ui") or {}).get("open")
                     or state.get("quest_ui_open") or state.get("gossip_open"))):
            self.phase = VisualApproachPhase.INTERACTION_READY
            return VisualApproachAssessment(self.phase, True, True,
                                            "interaction_ui_opened_during_approach")
        rejected_binding = (self.intent or {}).get("rejected_binding")
        harmful_in_range = any(
            action.get("is_harmful") is True and action.get("in_range") is True
            and (not rejected_binding or action.get("action") != rejected_binding)
            for action in state.get("actionbar", []))
        if not identify and harmful_in_range:
            self.phase = VisualApproachPhase.INTERACTION_READY
            return VisualApproachAssessment(self.phase, True, True,
                                            "combat_range_supported_during_approach")
        previous_track_id = (self.intent or {}).get("track_id")
        track = self._track(state, now)
        if track and track.get("track_id") and track.get("track_id") != previous_track_id:
            # _track() just re-resolved this identity via visual_signature
            # after the tracker reassigned its id. Adopt the new id so later
            # ticks match it directly instead of re-running the fallback (and
            # accumulating missing_observations) on every single tick.
            self.intent["track_id"] = track.get("track_id")
        if not track:
            if not self.missing_observations:
                self.missing_observations_since = now
            self.missing_observations += 1
            self.phase = VisualApproachPhase.OCCLUDED
            if (self.missing_observations > self.max_missing_observations
                    and now - self.missing_observations_since >= self.max_missing_seconds
                    and not self._edge_recovery_pending(now)):
                self.phase = VisualApproachPhase.FAILED
                return VisualApproachAssessment(self.phase, True, False, "visual_track_lost")
            return VisualApproachAssessment(self.phase, False, False, "visual_track_temporarily_occluded")
        predicted = bool(track.get("_predicted"))
        measurement = self._measurement(state, observation_id, now, track, predicted=predicted)
        if predicted:
            # Keep the committed identity and predicted bearing, but release W;
            # only a bounded camera correction may use an occluded measurement.
            if not self.missing_observations:
                self.missing_observations_since = now
            self.missing_observations += 1
            self.samples.append(measurement)
            self.phase = VisualApproachPhase.OCCLUDED
            if (self.missing_observations > self.max_missing_observations
                    and now - self.missing_observations_since >= self.max_missing_seconds
                    and not self._edge_recovery_pending(now)):
                self.phase = VisualApproachPhase.FAILED
                return VisualApproachAssessment(self.phase, True, False, "visual_track_lost")
            return VisualApproachAssessment(self.phase, False, False,
                                            "visual_track_predicted_during_occlusion")
        if self.missing_observations:
            self.reacquire_count += 1
        self.missing_observations = 0
        self.missing_observations_since = None
        x, y = measurement.x, measurement.y
        confidence = measurement.confidence
        height = measurement.bbox_height
        error = measurement.center_error
        if error is not None and self._last_error is not None and error*self._last_error < 0:
            self.overshoot_count += 1
        self._last_error = error
        distinct_visual = measurement.visual_sample_time != self.last_distinct_visual_sample_time
        self.samples.append(measurement)
        if distinct_visual:
            self.last_distinct_visual_sample_time = measurement.visual_sample_time
        if distinct_visual and measurement.bbox_scale_delta is not None:
            if measurement.bbox_scale_delta >= .0015:
                self.visual_progress_samples += 1
            elif abs(error or 0.) <= .18:
                self.visual_no_progress_samples += 1
        if measurement.obstacle_evidence >= .65:
            self.stuck_evidence_sources.add("WORLD3D_OBSTACLE_CANDIDATE")
        if measurement.player_speed is not None and measurement.player_speed <= .01:
            self.stuck_evidence_sources.add("MOVEMENT_TELEMETRY_STOPPED")
        if self.visual_no_progress_samples >= 3:
            self.stuck_evidence_sources.add("TARGET_SCALE_NO_PROGRESS")
        centered = error is not None and abs(error) <= .055
        ready_height = number(self.intent.get("ready_bbox_height") or .13)
        # The forward lease is continuous now, so stopping lags one control
        # update: stop when the current growth would reach the target height
        # by the next sample (live 2026-10-01: overshoot past the NPC).
        growth = max(0., number(measurement.bbox_scale_delta) or 0.)
        scale_ready = height is not None and height + growth >= ready_height
        reach_purpose = self.intent.get("purpose") in {"INTERACT", "LOOT"}
        bottom_reached = (reach_purpose
                          and self.last_edges is not None and self.last_edges_at == now
                          and self.last_edges[3] >= .93)
        own_edges = self._self_edges(state) if reach_purpose else None
        beside_self = (own_edges is not None and self.last_edges is not None
                       and self.last_edges_at == now
                       and self._beside_self(self.last_edges, own_edges,
                                             lying=self.intent.get("purpose") == "LOOT"))
        # Live 2026-10-04 (Wrathion): the box "looked" in range (scale / screen
        # bottom / beside the avatar) yet INTERACT answered "You need to be
        # closer" again and again without one step.  User rule: whatever the
        # box says, after a client range error really walk closer -- 5 steps,
        # then 3, then 2 (the edge correction steps back on overshoot).
        range_failures = int(number(self.intent.get("range_failures")) or 0)
        scale_ready = scale_ready or (range_failures == 0 and (bottom_reached or beside_self))
        advanced = (range_failures == 0
                    or getattr(self, "forward_commands_total", 0)
                    >= self.RANGE_ERROR_STEPS[min(range_failures, len(self.RANGE_ERROR_STEPS))-1])
        scale_ready = scale_ready and advanced
        # Retail NPC interaction needs range, not exact facing; the arc
        # approach rarely arrives dead-centre.
        interact_aligned = error is not None and abs(error) <= .20
        if self.intent.get("purpose") == "VEHICLE_AIM" and error is not None:
            # Live 2026-10-04 (Giant Boar): Trample dashes ~30 yd straight
            # along the facing and tramples what is in the way; walking into a
            # Monstrous Cadaver without it knocks the boar back.  So this
            # approach only *aims*: once the box is on the centre line, hand
            # over to VEHICLE_ABILITY (any distance -- the dash is the move).
            from .vehicle_abilities import aim_tolerance
            if abs(error) <= aim_tolerance(number(track.get("bbox_width_fraction"))):
                self.phase = VisualApproachPhase.INTERACTION_READY
                return VisualApproachAssessment(self.phase, True, True, "vehicle_attack_aligned")
        if self.intent.get("purpose") == "VEHICLE_ATTACK" and error is not None:
            # Close-range / targeted vehicle ability: walk until the client
            # reports range, or the box is close and roughly centred.
            vehicle_in_range = any(
                isinstance(action, dict) and action.get("source") == "VEHICLE_BAR"
                and action.get("in_range") is True for action in state.get("actionbar") or ())
            if vehicle_in_range or (scale_ready and abs(error) <= .10):
                self.phase = VisualApproachPhase.INTERACTION_READY
                return VisualApproachAssessment(self.phase, True, True, "vehicle_ability_range_supported")
        if identify and scale_ready:
            self.phase = VisualApproachPhase.INTERACTION_READY
            return VisualApproachAssessment(
                self.phase, True, True, "visual_cue_ready_for_identification")
        # This is a confidence-bearing proxy, never an exact yard assertion.
        if (reach_purpose and scale_ready
                and (not centered or self._requires_identity_recheck())):
            if self.final_align_started_at is None:
                self.final_align_started_at = now
            # An approach that *starts* in range must still turn: command()
            # emits nothing while the phase is IDLE.
            self.phase = VisualApproachPhase.ADVANCING
            if (self._requires_identity_recheck()
                    or not (interact_aligned and (centered
                                                  or now-self.final_align_started_at >= .8))):
                return VisualApproachAssessment(self.phase, False, False,
                                                "in_range_turning_to_face_target")
        if reach_purpose and interact_aligned and scale_ready:
            self.phase = VisualApproachPhase.INTERACTION_READY
            return VisualApproachAssessment(self.phase, True, True, "visual_interaction_range_supported")
        if self.started_at is not None and now-self.started_at >= self.max_seconds:
            self.phase = VisualApproachPhase.FAILED
            return VisualApproachAssessment(self.phase, True, False, "visual_approach_safety_deadline")
        self.phase = VisualApproachPhase.CENTERING if error is None or abs(error) > .18 else VisualApproachPhase.ADVANCING
        return VisualApproachAssessment(self.phase, False, False, "visual_target_tracked")

    def command(self, state: dict, observation_id: str, now: float) -> tuple[Command, ...]:
        # HOVER has moved the physical pointer and the movement lease was
        # deliberately released by the executor.  Do not issue another W
        # refresh until a *new* addon mouseover sample either confirms or
        # disproves the visual association.
        if self.identity_recheck_requested_at is not None:
            return ()
        if self.phase == VisualApproachPhase.OCCLUDED:
            edge = self._exit_edge(now)
            if edge is not None:
                if self.edge_recovery_started_at is None:
                    self.edge_recovery_started_at = now
                if (now-self.edge_recovery_started_at <= 1.5
                        and now-self.last_edge_command_at >= .15):
                    self.last_edge_command_at = now
                    self.edge_corrections += 1
                    self.control_updates += 1
                    self.last_command_at = now
                    binding, duration = {
                        "BOTTOM": ("MOVEBACKWARD", .20),   # ran past it: step back
                        "LEFT": ("TURNLEFT", .08),         # over-turned: turn back
                        "RIGHT": ("TURNRIGHT", .08),
                        "TOP": ("MOVEFORWARD", .12),       # fell behind: close in
                    }[edge]
                    return (Command("BIND", binding, duration),)
            # Purposeful widening scan around the last screen bearing. With
            # follow-camera enabled this is a bounded player-yaw pulse, so the
            # character and camera rotate together without changing identity.
            predicted = bool(self.samples and self.samples[-1].predicted)
            scan_steps = {1, 3, 5} if predicted else {2, 4, 6}
            target = state.get("target") or {}
            committed_guid = str((self.intent or {}).get("guid") or "")
            # While the exact committed GUID is still selected, never rotate
            # or move blindly. The prior implementation sent only
            # INTERACTTARGET here. In a live Jaina run the World3D projection
            # briefly dropped despite the NPC still being visibly selected;
            # those probes could neither restore a visual anchor nor safely
            # advance. First re-hover the last *freshly GUID-confirmed* point
            # while stationary. That lets the WorldModel bind any newly
            # published candidate to the selected identity again. It is a
            # bounded perception action, never a click or a guessed move.
            if committed_guid and target.get("guid") == committed_guid:
                candidate = self._reacquire_hover_candidate(state)
                if (candidate is not None and self._requires_identity_recheck()
                        and (self.last_occluded_reacquire_at is None
                             or now-self.last_occluded_reacquire_at >= .40)):
                    self.last_occluded_reacquire_at = now
                    self.identity_recheck_requested_at = now
                    self.identity_recheck_mouse_sample_before = number(
                        state.get("mouseover_sample_time"))
                    self.identity_recheck_track_id = str(candidate.get("track_id"))
                    self.identity_rechecks += 1
                    self.control_updates += 1
                    self.last_command_at = now
                    return (Command("HOVER", x=float(candidate["x"]),
                                    y=float(candidate["y"]), duration=.05),)
                point = self.last_confirmed_hover_point
                if (point and self._requires_identity_recheck()
                        and (self.last_occluded_reacquire_at is None
                             or now-self.last_occluded_reacquire_at >= .40)):
                    self.last_occluded_reacquire_at = now
                    self.identity_recheck_requested_at = now
                    self.identity_recheck_mouse_sample_before = number(
                        state.get("mouseover_sample_time"))
                    self.identity_recheck_track_id = None
                    self.identity_rechecks += 1
                    self.control_updates += 1
                    self.last_command_at = now
                    return (Command("HOVER", x=point["x"], y=point["y"], duration=.05),)
                # A bounded INTERACTTARGET probe remains authoritative after a
                # reacquisition try: it opens the UI at real client range and
                # otherwise returns the same explicit range feedback.
                if (self.intent.get("purpose") == "INTERACT"
                        and (self.last_interaction_probe_at is None
                             or now-self.last_interaction_probe_at >= 1.2)):
                    self.last_interaction_probe_at = now
                    self.control_updates += 1
                    self.last_command_at = now
                    return (Command("BIND", "INTERACTTARGET", .05),)
                return ()
            identify_scan = (self.intent or {}).get("purpose") == "IDENTIFY"
            if identify_scan:
                # SEEK_VISUAL_CUE owns an UNKNOWN cue, not a confirmed unit.
                # Reacquire it with the same slow one-way sweep used by the
                # outer search controller.  Alternating at successive missing
                # frames made the camera whip before a new detector result
                # could arrive and repeatedly threw distant quest badges out
                # of view.
                if (self.last_occluded_reacquire_at is not None
                        and now-self.last_occluded_reacquire_at + 1e-9 < .90):
                    return ()
                self.last_occluded_reacquire_at = now
                self.reacquire_actions += 1
                return (Command("BIND", "TURNLEFT", .16),)
            if self.missing_observations in scan_steps:
                last_x = self.samples[-1].x if self.samples and self.samples[-1].x is not None else .5
                direction = -1 if self.missing_observations % 4 == 0 else 1
                endpoint = max(.32, min(.68, .5 + direction*max(.06, abs(last_x-.5)*.35)))
                self.reacquire_actions += 1
                turn = "TURNRIGHT" if endpoint >= .5 else "TURNLEFT"
                return (Command("BIND", turn, .07),)
            return ()
        if self.phase in {VisualApproachPhase.IDLE,
                          VisualApproachPhase.INTERACTION_READY, VisualApproachPhase.FAILED}:
            return ()
        sample = self.samples[-1] if self.samples else None
        if not sample or sample.center_error is None:
            return ()
        # FAST_STATE telemetry can arrive many times while the pixel-strip
        # projection is unchanged.  It may update range/UI facts, but it must
        # never keep refreshing W from one frozen visual measurement.
        # A brief gap between distinct visual samples must not release the
        # forward lease (live 2026-10-01: 1.5 s of stop-and-go); a still
        # fresh measurement may re-lease W every .25 s, never a stale one.
        if (now-sample.visual_sample_time > .45
                or (sample.visual_sample_time == self.last_command_visual_sample_time
                    and now-(self.last_command_at or -1e9) < .25)):
            return ()
        error = sample.center_error
        # Generic proposal height is not calibrated entity distance. The live
        # Jaina track measured ~.093 while still roughly sixteen yards away,
        # so treating .085 as "near" caused MOVE/probe alternation after every
        # single update. Only a much stronger scale cue shortens the probe
        # cadence; the authoritative INTERACT result remains the range check.
        near = sample.bbox_height is not None and sample.bbox_height >= .12
        closing_fast = (sample.bbox_scale_delta is not None
                        and sample.bbox_scale_delta >= .003)
        probe_updates = 3 if near or closing_fast else 5
        probe_interval = .8 if near or closing_fast else 1.2
        # User 2026-10-01: approach continuously until arrival, no separate
        # click to learn "out of range".  Each INTERACTTARGET probe (and its
        # lease release) made the walk stop-and-go; arrival is decided by the
        # visual scale (learned per GUID from real client range errors).
        if (self.range_probe_enabled and self.intent.get("purpose") == "INTERACT"
                and self.forward_updates_since_probe >= probe_updates
                and (self.last_interaction_probe_at is None
                     or now-self.last_interaction_probe_at >= probe_interval)):
            # The selected GUID makes this a safe, authoritative range probe.
            # It opens the interaction immediately at real client range and
            # avoids estimating yards solely from apparent bbox scale.
            self.last_interaction_probe_at = now
            self.forward_updates_since_probe = 0
            self.control_updates += 1
            self.last_command_at = now
            self.last_command_visual_sample_time = sample.visual_sample_time
            return (Command("BIND", "INTERACTTARGET", .05),)
        # User 2026-10-01: approach without the pointer on the NPC; only once
        # in range re-hover it.  Mid-approach re-hovers released W.
        if (self._requires_identity_recheck()
                and self.final_align_started_at is not None):
            # Freeze the movement lease while this exact, live visual point is
            # checked.  Without this checkpoint a stale mouseover↔track
            # association can drive several yards past a selected NPC.
            self.identity_recheck_requested_at = now
            self.identity_recheck_mouse_sample_before = number(state.get("mouseover_sample_time"))
            # This is a direct checkpoint of the already-bound track.  A
            # failure remains terminal; only speculative replacement-track
            # probes populate identity_recheck_track_id and may be skipped.
            self.identity_recheck_track_id = None
            self.identity_rechecks += 1
            self.control_updates += 1
            self.last_command_at = now
            self.last_command_visual_sample_time = sample.visual_sample_time
            if not (sample.x is not None and sample.y is not None
                    and 0. < sample.x < 1. and 0. < sample.y < 1.):
                return ()
            return (Command("HOVER", x=sample.x, y=sample.y, duration=.05),)
        cursor = state.get("cursor_position") or {}
        cursor_x, cursor_y = number(cursor.get("nx")), number(cursor.get("ny"))
        if (self.pointer_tracking and self.final_align_started_at is None
                and self.control_updates > 0
                and sample.x is not None and sample.y is not None
                and .02 < sample.x < .98 and .02 < sample.y < .98
                and cursor_x is not None and cursor_y is not None
                and now-self.last_pointer_hover_at >= self.POINTER_INTERVAL
                and math.hypot(cursor_x-sample.x, cursor_y-sample.y) > self.POINTER_TOLERANCE):
            # Turning moves the camera and slides the pointer off the unit
            # (user 2026-10-01); put it back without stopping the approach.
            self.last_pointer_hover_at = now
            self.pointer_hovers += 1
            self.last_command_at = now
            self.last_command_visual_sample_time = sample.visual_sample_time
            return (Command("POINTER", x=sample.x, y=sample.y, duration=.02),)
        turn = "TURNRIGHT" if error > 0 else "TURNLEFT"
        if self._last_turn and turn != self._last_turn and abs(error) > .055:
            self.steering_reversals += 1
        if abs(error) > .055:
            self._last_turn = turn
        if self.intent.get("purpose") == "VEHICLE_AIM":
            # Aim only (see observe): walking into a cadaver gets knocked back.
            command = Command("BIND", turn, min(.10, max(.04, abs(error)*.25)))
        elif self.final_align_started_at is not None:
            # In range: face the NPC without walking past it.
            # The executor accepts movement leases of .04-.35 s only (live
            # 2026-10-01: a .03 s face-align turn was rejected and failed the
            # whole approach with executor_failure).
            command = Command("BIND", turn, min(.08, max(.04, abs(error)*.25)))
        elif abs(error) > .35:
            # Only a target far off-centre turns in place; otherwise keep the
            # forward lease and steer while walking (one continuous arc).
            command = Command("BIND", turn, min(.10, max(.04, abs(error)*.28)))
        elif abs(error) > .055:
            command = Command("BIND", "MOVEFORWARD", min(.08, max(.04, abs(error)*.22)),
                              simultaneous=(turn,))
        else:
            command = Command("BIND", "MOVEFORWARD", .06 if near else .16)
        if command.binding == "MOVEFORWARD":
            self.forward_updates_since_probe += 1
            self.forward_commands_total = getattr(self, "forward_commands_total", 0)+1
        self.control_updates += 1
        self.last_command_at = now
        self.last_command_visual_sample_time = sample.visual_sample_time
        return (command,)

    def snapshot(self) -> dict:
        latest = asdict(self.samples[-1]) if self.samples else None
        heights = [sample.bbox_height for sample in self.samples if sample.bbox_height is not None]
        scale_trend = heights[-1]-heights[0] if len(heights) >= 2 else None
        return {"phase": self.phase.value, "intent": dict(self.intent) if self.intent else None,
                "missing_observations": self.missing_observations,
                "reacquire_count": self.reacquire_count, "control_updates": self.control_updates,
                "reacquire_actions": self.reacquire_actions,
                "screen_center_error": latest.get("center_error") if latest else None,
                "target_scale_trend": scale_trend,
                "visual_progress_samples": self.visual_progress_samples,
                "visual_no_progress_samples": self.visual_no_progress_samples,
                "forward_updates_since_probe": self.forward_updates_since_probe,
                "identity_rechecks": self.identity_rechecks,
                "pointer_hovers": self.pointer_hovers,
                "wrong_track_rejections": self.wrong_track_rejections,
                "edge_corrections": self.edge_corrections,
                "last_exit_edge": self._exit_edge(self.last_edges_at or 0.)
                if self.last_edges_at is not None else None,
                "identity_reconfirmations": self.identity_reconfirmations,
                "track_rebindings": self.track_rebindings,
                "rejected_reacquire_tracks": len(self.rejected_reacquire_track_ids),
                "identity_recheck_pending": self.identity_recheck_requested_at is not None,
                "last_confirmed_hover_point": dict(self.last_confirmed_hover_point)
                if self.last_confirmed_hover_point else None,
                "stuck_evidence_sources": sorted(self.stuck_evidence_sources),
                "target_track_confidence": latest.get("confidence") if latest else None,
                "steering_reversals": self.steering_reversals,
                "overshoot_count": self.overshoot_count,
                "reacquire_success_rate": round(self.reacquire_count/max(1, self.reacquire_count+self.missing_observations), 3),
                "interaction_range_confidence": (1. if self.phase == VisualApproachPhase.INTERACTION_READY
                                                 else .65 if latest and latest.get("bbox_height", 0) and
                                                 latest["bbox_height"] >= .10 else .25 if latest else 0.),
                "latest_sample": latest}
