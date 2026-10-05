"""Persistent screen-space servo for a committed visual target.

This controller never recognizes an entity.  It consumes a Track↔Entity
association already supported by addon mouseover and maintains a bounded
closed-loop approach when exact world coordinates are unavailable.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict
import os

from .models import number
from .visual_approach_types import (  # noqa: F401  (re-exported)
    VisualApproachAssessment, VisualApproachPhase, VisualApproachSample, VisualServoMeasurement,
)
from .visual_approach_identity import VisualApproachIdentityMixin
from .visual_approach_tracking import VisualApproachTrackingMixin
from .visual_approach_geometry import VisualApproachGeometryMixin
from .visual_approach_command import VisualApproachCommandMixin


class VisualApproachController(VisualApproachCommandMixin, VisualApproachGeometryMixin, VisualApproachTrackingMixin, VisualApproachIdentityMixin):
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

    RANGE_ERROR_STEPS = (5, 3, 2)          # forward pulses after the 1st/2nd/later range error (user)

    # Horizontal screen fraction one radian of turning moves the world
    # (~90 degree horizontal field of view).
    TURN_SCREEN_PER_RAD = .64

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
