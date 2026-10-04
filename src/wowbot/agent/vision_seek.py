"""Bounded visual search feeding the shared visual servo in IDENTIFY mode.

Detection remains UNKNOWN. Only addon mouseover/target telemetry may establish
identity; this controller merely gets a persistent visual cue close enough.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import Command, number
from .models import words
from .quest_semantics import target_matches_objective
from .visual_approach import VisualApproachController, VisualApproachPhase
from .tooltip_quest import effective_mouseover


class SeekVisualCuePhase(StrEnum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    INVESTIGATING = "INVESTIGATING"
    CANDIDATE_READY = "CANDIDATE_READY"
    IDENTITY_OBSERVED = "IDENTITY_OBSERVED"
    EXHAUSTED = "EXHAUSTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SeekVisualCueAssessment:
    phase: SeekVisualCuePhase
    terminal: bool
    success: bool
    reason: str


class SeekVisualCueController:
    """Active-search coordinator; all approach commands come from the shared servo."""

    # A search pass is a slow one-way sweep.  The previous left/right/left/
    # right endpoints made the camera whip across the same scene before the
    # detector/tracker could stabilize a distant cue.  Every drag now advances
    # in the same direction by the same bounded amount; a new search attempt
    # may choose another pass, but one pass never reverses direction.
    sectors = ((.40, .45), (.40, .45), (.40, .45), (.40, .45))
    scan_step_interval = .90
    scan_drag_duration = .16

    def __init__(self, bindings=None, max_seconds: float = 22.) -> None:
        self.bindings = bindings
        self.max_seconds = max_seconds
        self.servo = VisualApproachController(bindings)
        self.reset()

    def reset(self) -> None:
        self.servo.reset()
        self.phase = SeekVisualCuePhase.IDLE
        self.intent: dict = {}
        self.started_at: float | None = None
        self.target_track_id: str | None = None
        self.target_signature_id: str | None = None
        self.last_x: float | None = None
        self.last_height: float | None = None
        self.scan_index = 0
        self.last_scan_at = -1_000_000.0
        self.last_command_observation_id: str | None = None
        self.candidate_score = 0.
        self.camera_updates = 0
        # Reaching a useful apparent scale does not itself identify the
        # subject.  The old implementation immediately reported SUCCESS at
        # that point, which returned control to the generic planner and often
        # made it inspect unrelated scenery.  Keep the cue committed long
        # enough to put the pointer on *that exact cue* and wait for the
        # addon response.  There is deliberately no expected GUID here:
        # IDENTIFY is how the GUID is discovered.
        self.identity_hover_requested_at: float | None = None
        self.identity_hover_mouse_sample_before: float | None = None
        self.identity_hover_point: tuple[float, float] | None = None

    def begin(self, parameters: dict, state: dict, now: float) -> None:
        self.reset()
        self.intent = {**parameters, "purpose": "IDENTIFY",
                       "ready_bbox_height": number(parameters.get("ready_bbox_height")) or .09}
        self.started_at = now
        self.target_track_id = parameters.get("track_id")
        self.target_signature_id = (parameters.get("visual_signature") or {}).get("signature_id")
        self.phase = (SeekVisualCuePhase.INVESTIGATING if self.target_track_id
                      else SeekVisualCuePhase.SCANNING)

    @staticmethod
    def _score(item: dict) -> float:
        # Keep rejection scores finite: controller snapshots and Proposal keys
        # are strict JSON (`allow_nan=False`). A non-viable transient target
        # must not be able to stop FULL_AI merely by entering the status tree.
        rejected_score = -1_000_000.0
        if item.get("source") != "WORLD3D" or item.get("inspectable") is False:
            return rejected_score
        lifecycle = str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
        if lifecycle in {"LOST", "REJECTED", "EXPIRED", "TERMINATED"}:
            return rejected_score
        rejection = ((item.get("active_perception") or {}).get("rejection")
                     or item.get("rejection") or {})
        if str(rejection.get("belief") or "UNKNOWN").upper() in {"SUPPRESSED", "REJECTED"}:
            return rejected_score
        kind = str(item.get("detector_kind") or item.get("kind") or "").lower()
        appearance = item.get("appearance") or {}
        labels = {str(value).lower() for value in item.get("candidate_labels") or []}
        labels.update(str(value).lower() for value in appearance.get("anchor_candidate_labels") or [])
        visual_group = item.get("visual_group") if isinstance(item.get("visual_group"), dict) else {}
        labels.update(str(value).lower() for value in visual_group.get("appearance_labels") or [])
        relations = item.get("visual_relations") or []
        overhead = any(str(edge.get("type") or "").upper() == "ABOVE" for edge in relations)
        symbol_like = ("symbol" in kind or "quest_marker_like" in labels
                       or "overhead_symbol_like" in labels)
        subject_like = "subject" in kind or kind in {"unknown_object_candidate", "object_candidate"}
        if not (subject_like or symbol_like or overhead):
            return rejected_score
        confidence = number(item.get("confidence")) or 0.
        stable = number(item.get("stable_frames")) or number(item.get("age_frames")) or 0.
        active = item.get("active_perception") or {}
        static = number(appearance.get("static_scene_score")) or 0.
        utility = number(active.get("utility")) or 0.
        body = number(appearance.get("body_geometry")) or 0.
        center = 1.-min(1., abs((number(item.get("x")) or .5)-.5)*2)
        badge = max(0., min(1., number(appearance.get("quest_badge_likeness")) or
                            (1. if "quest_badge_like" in labels else 0.)))
        group_supported = str(visual_group.get("belief") or "UNKNOWN").upper() == "SUPPORTED"
        self_avatar_hint = bool(appearance.get("self_avatar_suppression_hint"))
        visual_identity = (item.get("visual_identity")
                           if isinstance(item.get("visual_identity"), dict) else {})
        self_player_avatar = bool(
            item.get("self_player_avatar") or appearance.get("self_player_avatar")
            or visual_identity.get("kind") == "SELF_PLAYER")
        if self_player_avatar:
            return rejected_score
        # Ignore only an uncorroborated likely view of our own avatar. An
        # overhead relation/group/symbol is independent evidence that a nearby
        # subject overlaps the avatar region and must remain seekable.
        if self_avatar_hint and not (overhead or symbol_like or group_supported or badge >= .5):
            return rejected_score
        return (confidence + min(1., stable/5)*.35 + utility*.3 + body*.2
                + center*.15 + (.55 if overhead or symbol_like else 0.)
                + badge*.5 + (.25 if group_supported else 0.) - static*.35)

    def _candidate(self, state: dict) -> dict | None:
        candidates = list(state.get("visual_candidates") or [])
        if self.target_track_id:
            exact = next((item for item in candidates if item.get("track_id") == self.target_track_id), None)
            if exact is not None:
                return exact
            if self.target_signature_id:
                return next((item for item in candidates
                             if (item.get("visual_signature") or {}).get("signature_id")
                             == self.target_signature_id), None)
            return None
        viable = [(self._score(item), item) for item in candidates]
        viable = [(score, item) for score, item in viable if score >= 1.15]
        return max(viable, key=lambda pair: pair[0])[1] if viable else None

    @staticmethod
    def _phase_for_servo(phase: VisualApproachPhase) -> SeekVisualCuePhase:
        if phase == VisualApproachPhase.INTERACTION_READY:
            return SeekVisualCuePhase.CANDIDATE_READY
        if phase == VisualApproachPhase.FAILED:
            return SeekVisualCuePhase.FAILED
        return SeekVisualCuePhase.INVESTIGATING

    @staticmethod
    def _is_derived_subject_probe(item: dict) -> bool:
        """Return whether ``item`` is an invented hover region, not a body.

        A subject probe is projected below a stable symbol when no reliable
        body was detected.  Its rectangle is useful for mouseover, but its
        apparent scale must never authorize forward movement: a torch flame
        can look like an overhead symbol and would otherwise make the agent
        walk toward scenery before obtaining any identity evidence.
        """
        kind = str(item.get("detector_kind") or item.get("kind") or "").lower()
        if kind != "unknown_subject_probe":
            return False
        appearance = item.get("appearance") or {}
        labels = {str(value).lower() for value in item.get("candidate_labels") or ()}
        return bool(
            "subject_below_symbol_probe" in labels
            or appearance.get("derived_from") == "overhead_symbol_like_cue"
            or appearance.get("probe_origin") == "horizontal_overhead_cue"
        )

    def _mouseover_identifies_intent(self, mouse: dict, state: dict) -> bool:
        """Ground-truth identity gate for units and guid-less world objects."""
        object_id = self.intent.get("object_id")
        item_id = self.intent.get("item_id")
        if object_id is not None:
            return str(mouse.get("object_id")) == str(object_id)
        if item_id is not None:
            return str(mouse.get("item_id")) == str(item_id)
        expected_npc_id = self.intent.get("expected_npc_id")
        if expected_npc_id is not None:
            return str(mouse.get("npc_id")) == str(expected_npc_id)
        expected_name = words(str(self.intent.get("expected_name") or "")).strip()
        if expected_name:
            actual_name = words(str(mouse.get("name") or "")).strip()
            if actual_name == expected_name:
                if self.intent.get("require_attackable") is True:
                    return mouse.get("attackable", mouse.get("is_attackable")) is True
                return True
            if str(self.intent.get("objective_type") or "").upper() in {"KILL", "KILL_NAMED"}:
                matches = target_matches_objective(
                    mouse, {"description": self.intent.get("objective_description") or ""})
                return bool(matches and mouse.get(
                    "attackable", mouse.get("is_attackable")) is True)
            return False
        expected = [words(str(value)).strip()
                    for value in self.intent.get("expected_tooltips") or ()]
        if expected:
            tooltip = f" {words(str(mouse.get('tooltip') or '')).strip()} "
            return any(value and f" {value} " in tooltip for value in expected)
        return bool(mouse.get("guid") and mouse.get("guid") != state.get("character_guid"))

    def observe(self, state: dict, observation_id: str, now: float) -> SeekVisualCueAssessment:
        if self.started_at is not None and now-self.started_at >= self.max_seconds:
            self.phase = SeekVisualCuePhase.FAILED
            return SeekVisualCueAssessment(self.phase, True, False, "seek_visual_cue_safety_deadline")
        candidate = self._candidate(state)
        # A hover requested for this cue has priority over generic visual
        # readiness.  A *new* non-player mouseover is authoritative identity
        # evidence, regardless of which GUID it is; no visual label is
        # inferred here.
        if self.identity_hover_requested_at is not None:
            mouse = effective_mouseover(state)
            mouse_time = number(state.get("mouseover_sample_time"))
            if (self._mouseover_identifies_intent(mouse, state)
                    and mouse_time is not None
                    and mouse_time > (self.identity_hover_mouse_sample_before or -1_000_000.) + .000001
                    and 0 <= now-mouse_time <= 1.5):
                self.phase = SeekVisualCuePhase.IDENTITY_OBSERVED
                return SeekVisualCueAssessment(self.phase, True, True,
                                               "identity_available_during_visual_seek")
            # The addon can legitimately have no tooltip for an empty point.
            # Do not let a stalled export trap ownership forever: after its
            # bounded response window, release this cue for the normal
            # inspection path, but only after the pointer was actually moved
            # to it.
            if now-self.identity_hover_requested_at >= .85:
                self.phase = SeekVisualCuePhase.CANDIDATE_READY
                return SeekVisualCueAssessment(self.phase, True, True,
                                               "visual_cue_hovered_for_identification")
        if candidate is not None:
            score = self._score(candidate)
            if score > -1_000_000.0:
                self.candidate_score = score
            self.target_track_id = candidate.get("track_id") or self.target_track_id
            self.target_signature_id = ((candidate.get("visual_signature") or {}).get("signature_id")
                                        or self.target_signature_id)
            self.last_x = number(candidate.get("x"))
            self.last_height = VisualApproachController._height(candidate)
            # This is a fabricated inspection column below a visual symbol,
            # not an observed unit body.  Hover it at any distance and let
            # addon mouseover establish identity before the shared servo is
            # allowed to issue MOVEFORWARD.  Real detected subjects retain
            # the normal approach-then-hover behavior.
            if self._is_derived_subject_probe(candidate):
                self.phase = SeekVisualCuePhase.CANDIDATE_READY
                return SeekVisualCueAssessment(
                    self.phase, False, False,
                    "derived_subject_probe_ready_for_hover_identification")
            intent = {**self.intent, **candidate, "track_id": self.target_track_id,
                      "purpose": "IDENTIFY", "ready_bbox_height": .09}
            # start() is idempotent: an unchanged (guid, track_id, purpose)
            # identity just refreshes self.intent and observes normally; a
            # changed one (e.g. re-acquired under a new track_id via
            # signature match) resets missing_observations/samples instead of
            # accumulating "lost" against a track_id that no longer exists in
            # visual_candidates. Calling only .observe() here after the first
            # tick left the servo permanently pinned to the original track_id.
            assessment = self.servo.start(intent, state, observation_id, now)
            if (assessment.terminal and assessment.success
                    and assessment.reason == "identity_available_during_visual_seek"
                    and any(self.intent.get(key) not in (None, "", []) for key in (
                        "object_id", "item_id", "expected_npc_id", "expected_name",
                        "expected_tooltips"))
                    and not self._mouseover_identifies_intent(
                        effective_mouseover(state),
                        state)):
                # VisualApproach's generic IDENTIFY contract may accept any
                # non-player GUID. A quest-scoped search has a narrower
                # declared identity, so only this coordinator may complete it.
                self.phase = SeekVisualCuePhase.INVESTIGATING
                return SeekVisualCueAssessment(
                    self.phase, False, False, "mouseover_identity_does_not_match_search_intent")
            # `ready_bbox_height` is an approach threshold, not entity
            # recognition.  Prevent the servo's generic early SUCCESS from
            # handing a distant quest badge to random INSPECT selection.  A
            # direct HOVER at the associated subject/probe is the next active
            # perception action.
            if (assessment.terminal and assessment.success
                    and assessment.reason == "visual_cue_ready_for_identification"):
                x, y = number(candidate.get("x")), number(candidate.get("y"))
                if x is not None and y is not None:
                    self.phase = SeekVisualCuePhase.CANDIDATE_READY
                    return SeekVisualCueAssessment(self.phase, False, False,
                                                   "visual_cue_ready_for_hover_identification")
            terminal, assessment_success = assessment.terminal, assessment.success
            assessment_reason, assessment_phase = assessment.reason, assessment.phase
            self.phase = self._phase_for_servo(assessment_phase)
            if assessment_reason == "identity_available_during_visual_seek":
                self.phase = SeekVisualCuePhase.IDENTITY_OBSERVED
            return SeekVisualCueAssessment(self.phase, terminal, assessment_success, assessment_reason)
        if self.servo.intent is not None:
            assessment = self.servo.observe(state, observation_id, now)
            self.phase = self._phase_for_servo(assessment.phase)
            return SeekVisualCueAssessment(self.phase, assessment.terminal,
                                           assessment.success, assessment.reason)
        if (self.scan_index >= len(self.sectors)
                and now-self.last_scan_at + 1e-9 >= self.scan_step_interval):
            self.phase = SeekVisualCuePhase.EXHAUSTED
            return SeekVisualCueAssessment(self.phase, True, False,
                                           "seek_visual_cue_sectors_exhausted")
        self.phase = SeekVisualCuePhase.SCANNING
        return SeekVisualCueAssessment(self.phase, False, False, "seek_visual_cue_scanning")

    def command(self, state: dict, observation_id: str, now: float) -> tuple[Command, ...]:
        if (self.phase == SeekVisualCuePhase.CANDIDATE_READY
                and self.identity_hover_requested_at is None):
            candidate = self._candidate(state)
            x = number(candidate.get("x")) if candidate else self.last_x
            y = number(candidate.get("y")) if candidate else None
            if x is not None and y is not None:
                self.identity_hover_requested_at = now
                self.identity_hover_mouse_sample_before = number(state.get("mouseover_sample_time"))
                self.identity_hover_point = (x, y)
                self.last_command_observation_id = observation_id
                return (Command("HOVER", x=x, y=y, duration=.05),)
        if self.servo.intent is not None:
            return self.servo.command(state, observation_id, now)
        if observation_id == self.last_command_observation_id:
            return ()
        if self.phase == SeekVisualCuePhase.SCANNING and self.scan_index < len(self.sectors):
            if now-self.last_scan_at + 1e-9 < self.scan_step_interval:
                return ()
            x, y = self.sectors[self.scan_index]
            self.scan_index += 1
            self.last_scan_at = now
            self.last_command_observation_id = observation_id
            self.camera_updates += 1
            turn = "TURNRIGHT" if x >= .5 else "TURNLEFT"
            return (Command("BIND", turn, self.scan_drag_duration),)
        return ()

    def snapshot(self) -> dict:
        servo = self.servo.snapshot()
        return {"phase": self.phase.value, "intent": dict(self.intent),
                "target_track_id": self.target_track_id,
                "target_signature_id": self.target_signature_id,
                "candidate_score": round(self.candidate_score, 4),
                "last_x": self.last_x, "last_bbox_height": self.last_height,
                "identity_hover_pending": self.identity_hover_requested_at is not None,
                "identity_hover_point": self.identity_hover_point,
                "scan_index": self.scan_index, "scan_limit": len(self.sectors),
                "scan_pattern": "ONE_WAY",
                "scan_step_interval": self.scan_step_interval,
                "scan_drag_duration": self.scan_drag_duration,
                "camera_updates": self.camera_updates,
                "scan_turn_duration": self.scan_drag_duration,
                "player_turn_updates": self.camera_updates,
                "view_control_mode": "PLAYER_YAW_FOLLOW_CAMERA",
                "servo": servo,
                "control_updates": servo.get("control_updates", 0),
                "forward_updates": servo.get("forward_updates_since_probe", 0)}


# Source compatibility only. Runtime contract is SEEK_VISUAL_CUE.
VisionSeekController = SeekVisualCueController
VisionSeekPhase = SeekVisualCuePhase
VisionSeekAssessment = SeekVisualCueAssessment
