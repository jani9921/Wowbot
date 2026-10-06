"""Persistent closed-loop controller for high-level REACH intents.

The planner owns *where* to go.  This controller owns the short, bounded input
segments needed to get there and accumulates evidence before declaring a
genuine stuck condition.  A command segment ending is not a MOVE failure.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum
import math

from wowbot.navigation.arrival import ArrivalVerifier
from wowbot.navigation.arrival_evidence import ArrivalEvidence
from wowbot.navigation.progress import ProgressMonitor, ProgressPhase

from .models import Command, number


class MovementPhase(StrEnum):
    IDLE = "IDLE"
    STEERING = "STEERING"
    MOVING = "MOVING"
    NO_PROGRESS_YET = "NO_PROGRESS_YET"
    CANDIDATE_STUCK = "CANDIDATE_STUCK"
    SUPPORTED_STUCK = "SUPPORTED_STUCK"
    ARRIVED = "ARRIVED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class MovementSample:
    observation_id: str
    at: float
    x: float
    y: float
    distance: float
    orientation: float | None
    speed: float | None
    moving: bool | None
    heading_error: float | None
    progress: float


@dataclass(frozen=True, slots=True)
class MovementAssessment:
    phase: MovementPhase
    terminal: bool
    success: bool
    reason: str


class ReachMovementController:
    """Stateful movement skill; one instance is owned by AutonomousAgent."""

    map_arrival_tolerance = .003
    world_arrival_tolerance = 4.5
    map_progress_epsilon = .000025
    world_progress_epsilon = .05
    candidate_samples = 3
    supported_samples = 5
    candidate_seconds = .8
    supported_seconds = 1.6
    no_progress_sample_interval = .25
    wall_contact_seconds = 4.
    wall_contact_max_displacement = .65
    max_reach_seconds = 90.

    def __init__(self, bindings=None, *, progress_monitor: ProgressMonitor | None = None,
                 arrival_verifier: ArrivalVerifier | None = None) -> None:
        self.bindings = bindings
        self.turn_rate = 2.5
        # NavigationService supplies the shared monitor in production. The
        # local default preserves direct unit-level construction without
        # creating a second input/movement authority.
        self.progress_monitor = progress_monitor or ProgressMonitor()
        self.arrival_verifier = arrival_verifier or ArrivalVerifier()
        self.arrival_evidence = ArrivalEvidence()
        self.reset()

    def reset(self) -> None:
        self.destination: dict | None = None
        self.destination_key: tuple | None = None
        self.phase = MovementPhase.IDLE
        self.started_at: float | None = None
        self.last_observation_id: str | None = None
        self.last_position_time: float | None = None
        self.last_command_observation_id: str | None = None
        self.last_command_at: float | None = None
        self.samples: deque[MovementSample] = deque(maxlen=24)
        # Retain more than the V5 three-second hard-stuck confirmation window
        # even when observations arrive at 30-40 Hz. Samples are already
        # downsampled below, so this remains bounded and small.
        self.no_progress: deque[MovementSample] = deque(maxlen=32)
        # A separate absolute-position window survives tiny per-frame
        # improvements that would clear the ordinary no-progress score.
        self.wall_samples: deque[MovementSample] = deque(maxlen=32)
        self.forward_started_at: float | None = None
        self.evidence_sources: set[str] = set()
        self.evidence_observations: list[str] = []
        self.control_updates = 0
        self.recovery_count = 0
        self.steering_mode = "STRAIGHT"
        self.smoothed_heading: float | None = None
        self.steering_reversals = 0
        self.turn_duration_scale = 1.0
        self.overshoot_count = 0
        self.stop_start_transitions = 0
        self._last_moving_state = None
        self.follow_missing_since: float | None = None
        # One running jump per no-progress episode (user 2026-10-02: Space
        # often clears a small obstacle).  Cleared when progress resumes.
        self.jump_attempted = False
        self.command_history: deque[tuple[float, str, float]] = deque(maxlen=240)
        self.terminal_reason: str | None = None
        # Evidence helper only. It does not own or issue movement commands;
        # this controller remains the single REACH control owner.
        self.progress_monitor.clear()
        self.arrival_verifier.reset()
        self.arrival_evidence.reset()

    @staticmethod
    def _key(destination: dict) -> tuple:
        if destination.get("follow_group_leader") or destination.get("follow_quest_entity"):
            return ("FOLLOW_ENTITY", str(destination.get("follow_entity_guid") or ""),
                    destination.get("map_id"))
        if destination.get("target_guid"):
            return ("OBJECT", destination.get("target_guid"),
                    destination.get("coordinate_space", "WORLD_YARDS"))
        if destination.get("coordinate_space") == "WORLD_YARDS":
            return ("WORLD_LOCATION", destination.get("world_map_id", destination.get("instance_id")),
                    round(float(destination["x"]), 3), round(float(destination["y"]), 3))
        return (destination.get("map_id"), round(float(destination["x"]), 6),
                round(float(destination["y"]), 6),
                destination.get("coordinate_space", "NORMALIZED_MAP"))

    def start(self, destination: dict, state: dict, observation_id: str, now: float) -> None:
        key = self._key(destination)
        if key != self.destination_key:
            self.reset()
        self.destination = dict(destination)
        self.destination_key = key
        if self.started_at is None:
            self.started_at = now
        self.phase = MovementPhase.MOVING
        self.terminal_reason = None
        self.observe(state, observation_id, now, commanded=False)

    def _position(self, state: dict) -> tuple[float, float] | None:
        space = (self.destination or {}).get("coordinate_space", "NORMALIZED_MAP")
        pos = (state.get("player_world_position") if space == "WORLD_YARDS"
               else state.get("position")) or {}
        x, y = number(pos.get("x")), number(pos.get("y"))
        return (x, y) if x is not None and y is not None else None

    # Docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md §4 (2D leak): standing on a
    # bridge above the destination must not count as arrival.  Only trusted
    # heights count: the player projected onto the navmesh surface (the raw
    # client Z can be a false 0) and a route anchor's mmap polygon height
    # (``layer_z``).  2 yd of slack covers slopes and steps.
    LAYER_SLACK_YARDS = 2.

    def _vertical_excess(self, state: dict) -> float:
        player = state.get("player_world_position") or {}
        destination = self.destination or {}
        player_z, destination_z = number(player.get("z")), number(destination.get("layer_z"))
        if player_z is None or destination_z is None or player.get("z_source") != "NAVMESH_SURFACE":
            return 0.
        return max(0., abs(player_z - destination_z) - self.LAYER_SLACK_YARDS)

    def _position_sample_time(self, state: dict) -> float | None:
        """When the world position in ``state`` was measured, if known.

        Live 2026-10-02: FAST observations arrived at ~30 Hz but carried no
        world position, so the merged state repeated a 1-3 s old one.  Each
        repeat counted as "no progress" while the character ran at 7 yd/s and
        MOVE failed as stuck.  A new observation is not a new measurement."""
        if (self.destination or {}).get("coordinate_space") != "WORLD_YARDS":
            return None
        return number((state.get("player_world_position") or {}).get("sample_time"))

    def _refresh_object_destination(self, state: dict) -> bool:
        """Update a moving object's endpoint without replacing the REACH attempt."""
        if self.destination and self.destination.get("follow_group_leader"):
            group = state.get("group_state") or {}
            position = group.get("leader_position") or {}
            x, y = number(position.get("x")), number(position.get("y"))
            if x is None or y is None:
                return False
            expected = str(self.destination.get("follow_entity_guid") or "")
            observed = str(group.get("leader_guid") or (group.get("leader") or {}).get("guid") or "")
            if expected and observed and expected != observed:
                return False
            sample_time = number(position.get("sample_time", group.get("leader_position_sample_time")))
            state_time = number(state.get("monotonic_time"))
            if sample_time is not None and state_time is not None and not 0 <= state_time-sample_time <= 2.:
                return False
            self.destination.update(x=x, y=y, map_id=position.get("map_id", self.destination.get("map_id")))
            return True
        if self.destination and self.destination.get("follow_quest_entity"):
            expected = str(self.destination.get("follow_entity_guid") or "")
            candidates = [state.get("target") or {}, *(state.get("entities") or ())]
            entity = next((item for item in candidates if isinstance(item, dict)
                           and str(item.get("guid") or "") == expected), None)
            now = number(state.get("monotonic_time"))
            if entity is None:
                if self.follow_missing_since is None:
                    self.follow_missing_since = now
                return bool(now is not None and self.follow_missing_since is not None
                            and now-self.follow_missing_since <= 2.)
            self.follow_missing_since = None
            world_space = self.destination.get("coordinate_space") == "WORLD_YARDS"
            position = (entity.get("world_position") if world_space
                        else entity.get("position")) or {}
            x, y = number(position.get("x")), number(position.get("y"))
            if x is None or y is None:
                return False
            sample_time = number(position.get("sample_time", entity.get("sample_time")))
            if (sample_time is not None and now is not None
                    and not 0 <= now-sample_time <= 2.):
                return False
            self.destination.update(
                x=x, y=y, z=number(position.get("z")) or self.destination.get("z", 0.),
                map_id=position.get("map_id", self.destination.get("map_id")),
                instance_id=position.get("instance_id", self.destination.get("instance_id")))
            return True
        if not self.destination or not self.destination.get("target_guid"):
            return True
        target = state.get("target") or {}
        if target.get("guid") != self.destination["target_guid"]:
            return False
        if self.destination.get("source") == "TDB_REFERENCE":
            player = state.get("player_world_position") or {}
            return (not target.get("dead", target.get("is_dead"))
                    and target.get("npc_id") == self.destination.get("npc_id")
                    and player.get("instance_id") == self.destination.get("world_map_id"))
        position = target.get("world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        if x is None or y is None or position.get("coordinate_space") not in {None, "WORLD_YARDS"}:
            return False
        player = state.get("player_world_position") or {}
        target_instance = position.get("instance_id")
        player_instance = player.get("instance_id")
        if (target_instance is not None and player_instance is not None
                and target_instance != player_instance):
            return False
        self.destination.update(x=x, y=y, z=number(position.get("z")) or 0.,
                                instance_id=target_instance,
                                coordinate_space="WORLD_YARDS")
        return True

    @staticmethod
    def _motion(state: dict) -> tuple[float | None, bool | None]:
        movement = state.get("movement") or {}
        speed = number(movement.get("speed", state.get("movement_speed")))
        moving = movement.get("moving", state.get("is_moving"))
        return speed, moving if isinstance(moving, bool) else None

    def _geometry(self, state: dict) -> tuple[float, float, float] | None:
        if not self.destination:
            return None
        pos = self._position(state)
        if pos is None:
            return None
        dx, dy = self.destination["x"] - pos[0], self.destination["y"] - pos[1]
        if self.destination.get("coordinate_space") == "WORLD_YARDS":
            # UnitPosition and GetPlayerFacing use the same world-axis contract.
            desired = math.atan2(dy, dx) % math.tau
            distance = math.hypot(dx, dy, self._vertical_excess(state))
        else:
            dimensions = state.get("map_dimensions") or {}
            width, height = number(dimensions.get("width")), number(dimensions.get("height"))
            heading_dx, heading_dy = (dx * width, dy * height) if width and height else (dx, dy)
            desired = math.atan2(-heading_dx, -heading_dy) % math.tau
            distance = math.hypot(dx, dy)
        if self.smoothed_heading is None:
            self.smoothed_heading = desired
        else:
            delta = (desired-self.smoothed_heading+math.pi) % math.tau-math.pi
            self.smoothed_heading = (self.smoothed_heading + .35*delta) % math.tau
        desired = self.smoothed_heading
        current = number(state.get("orientation"))
        error = ((desired-current+math.pi) % math.tau-math.pi) if current is not None else 0.
        return distance, desired, error

    TERMINAL_PHASES = frozenset({MovementPhase.ARRIVED, MovementPhase.FAILED,
                                 MovementPhase.SUPPORTED_STUCK})
    AWAITING_REASONS = frozenset({"awaiting_fresh_progress_observation",
                                  "awaiting_fresh_position_sample"})

    def observe(self, state: dict, observation_id: str, now: float, *, commanded: bool = True) -> MovementAssessment:
        """One assessment; a terminal verdict is repeated until the next start().

        Live 2026-10-05 (Hrun's pit): the FAST lane consumed the arriving
        position sample, saw ARRIVED and stopped, but only the medium tick
        finishes a skill -- and on the same sample it saw no fresh position,
        so it reported "awaiting" and the MOVE never ended.
        """
        if self.terminal_reason and self.phase is MovementPhase.SUPPORTED_STUCK:
            # FAST may see another fresh, jittering position before the
            # medium skill tick records this failure. Never re-arm W until an
            # explicit start(). ARRIVED retains its evidence-update behavior.
            return MovementAssessment(self.phase, True, False, self.terminal_reason)
        assessment = self._observe_once(state, observation_id, now, commanded=commanded)
        if assessment.terminal and self.destination:
            self.terminal_reason = assessment.reason
        elif (self.terminal_reason and self.phase in self.TERMINAL_PHASES
                and assessment.reason in self.AWAITING_REASONS):
            return MovementAssessment(self.phase, True, self.phase is MovementPhase.ARRIVED,
                                      self.terminal_reason)
        return assessment

    def _observe_once(self, state: dict, observation_id: str, now: float, *,
                      commanded: bool = True) -> MovementAssessment:
        if not self.destination:
            return MovementAssessment(MovementPhase.IDLE, True, False, "no_reach_intent")
        if observation_id == self.last_observation_id:
            return MovementAssessment(self.phase, False, False, "awaiting_fresh_progress_observation")
        if not self._refresh_object_destination(state):
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "reach_object_identity_or_position_lost")
        if (self.destination.get("coordinate_space") != "WORLD_YARDS"
                and self.destination.get("map_id") is not None
                and state.get("map_id") != self.destination.get("map_id")):
            transition = self.arrival_evidence.observe(
                self.destination, state, now, float("inf"))
            assessment = self.arrival_verifier.observe(
                distance=None, tolerance=None,
                facts={"map_transition": transition.get("map_transition")})
            if assessment.arrived:
                self.phase = MovementPhase.ARRIVED
                self.no_progress.clear()
                return MovementAssessment(
                    self.phase, True, True, "reach_arrival_map_transition_verified")
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "destination_map_changed")
        geometry = self._geometry(state)
        position = self._position(state)
        if geometry is None or position is None:
            return MovementAssessment(self.phase, False, False, "position_or_orientation_missing")
        distance, _, heading_error = geometry
        position_time = self._position_sample_time(state)
        if (position_time is not None and self.last_position_time is not None
                and position_time <= self.last_position_time and self.samples):
            # Steering still runs on this observation (command() reads the
            # fresh orientation); progress/stuck evidence waits for a new
            # position measurement.
            self.last_observation_id = observation_id
            return MovementAssessment(self.phase, False, False, "awaiting_fresh_position_sample")
        if position_time is not None:
            self.last_position_time = position_time
        speed, moving = self._motion(state)
        previous = self.samples[-1] if self.samples else None
        progress = (previous.distance-distance) if previous else 0.
        sample = MovementSample(observation_id, now, position[0], position[1], distance,
                                number(state.get("orientation")), speed, moving,
                                heading_error, progress)
        self.samples.append(sample)
        self.last_observation_id = observation_id
        tolerance = number(self.destination.get("stop_distance"))
        if tolerance is None:
            tolerance = number(self.destination.get("arrival_radius"))
        if tolerance is None:
            tolerance = (self.world_arrival_tolerance
                         if self.destination.get("coordinate_space") == "WORLD_YARDS"
                         else self.map_arrival_tolerance)
        arrival_evidence = self.arrival_evidence.observe(
            self.destination, state, now, distance)
        arrival = self.arrival_verifier.observe(
            distance=distance,
            tolerance=tolerance,
            facts={
                # `_geometry` is available only after the controller has a
                # validated player/destination coordinate contract.
                "absolute_distance_reliable": True,
                "minimap_convergence": arrival_evidence.get("minimap_convergence"),
                "interaction_ready": arrival_evidence.get("interaction_ready"),
                "bbox_growth": arrival_evidence.get("bbox_growth"),
                "quest_area_state_change": arrival_evidence.get("quest_area_state_change"),
                "map_transition": arrival_evidence.get("map_transition"),
            },
        )
        if arrival.arrived:
            self.phase = MovementPhase.ARRIVED
            self.no_progress.clear()
            reason = (
                "reach_arrival_quest_state_verified"
                if "quest_area_state_change" in arrival.evidence else
                "reach_arrival_interaction_ready"
                if "interaction_ready" in arrival.evidence else
                "reach_arrival_verified"
            )
            return MovementAssessment(self.phase, True, True, reason)
        # FOLLOW is a persistent distance-band skill, not a repeated arrival
        # race against an old leader coordinate. Inside the band we retain the
        # one active movement attempt, issue no movement lease, and wait for a
        # fresh leader position. We deliberately do not reverse blindly when
        # too close; a future safe-back step requires free-space evidence.
        if self.destination.get("follow_group_leader") or self.destination.get("follow_quest_entity"):
            minimum = number(self.destination.get("follow_min_distance")) or 0.
            maximum = number(self.destination.get("follow_max_distance")) or tolerance
            if distance <= maximum:
                self.phase = MovementPhase.MOVING
                self.no_progress.clear()
                self.evidence_sources.clear()
                self.evidence_observations.clear()
                self.steering_mode = "FOLLOW_HOLD"
                return MovementAssessment(self.phase, False, False,
                                         "follow_too_close_hold" if distance < minimum else "follow_distance_band")
        if self.started_at is not None and now-self.started_at >= self.max_reach_seconds:
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "movement_safety_deadline")
        if self._forward_wall_contact(sample, position_time, tolerance, now):
            self.evidence_sources.update({"POSITION_PLATEAU", "FORWARD_COMMAND_NO_TRANSLATION",
                                          "MOTION_POSITION_MISMATCH"})
            self.evidence_observations.append(observation_id)
            self.phase = MovementPhase.SUPPORTED_STUCK
            return MovementAssessment(self.phase, True, False, "supported_stuck")
        epsilon = (self.world_progress_epsilon
                   if self.destination.get("coordinate_space") == "WORLD_YARDS"
                   else self.map_progress_epsilon)
        motion_feedback = state.get("motion_feedback") or {}
        if previous and progress >= epsilon:
            self.progress_monitor.observe_signals(
                now,
                optical_flow=number(motion_feedback.get("optical_flow_progress")),
                minimap_displacement=number(motion_feedback.get("minimap_displacement_progress")),
                landmark_parallax=number(motion_feedback.get("landmark_parallax_progress")),
                target_distance=min(1., max(0., progress / epsilon)),
                movement_state=None,
                expected_vs_observed_bearing=max(
                    0., min(1., 1. - abs(heading_error) / math.pi)),
                movement_animation=(1. if moving else 0.) if moving is not None else None,
            )
            self.phase = MovementPhase.MOVING
            self.no_progress.clear()
            self.evidence_sources.clear()
            self.evidence_observations.clear()
            self.jump_attempted = False
            return MovementAssessment(self.phase, False, False, "reach_progress_observed")
        # Turning is useful control progress. Coordinate displacement is not
        # expected yet and therefore cannot be evidence of being stuck.
        orientation_delta = 0.
        if previous and previous.orientation is not None and sample.orientation is not None:
            orientation_delta = abs((sample.orientation-previous.orientation+math.pi) % math.tau-math.pi)
            if orientation_delta > .004:
                self.turn_rate = min(6., max(.5, .8*self.turn_rate + .2*orientation_delta/.30))
        heading_improved = (previous is not None and previous.heading_error is not None
                            and abs(heading_error) < abs(previous.heading_error)-.003)
        # A slow screenshot/telemetry control loop can observe the character
        # only after a turn lease has completed.  If the error crossed zero,
        # the previous lease overshot the heading: damp subsequent turns rather
        # than issuing an equally large correction in the opposite direction.
        if (previous is not None and previous.heading_error is not None
                and previous.heading_error * heading_error < 0
                and min(abs(previous.heading_error), abs(heading_error)) > .08):
            self.steering_reversals += 1
            self.overshoot_count += 1
            self.turn_duration_scale = max(.35, self.turn_duration_scale * .65)
        elif heading_improved and abs(heading_error) > .25:
            self.turn_duration_scale = min(1., self.turn_duration_scale + .04)
        if moving is not None:
            if self._last_moving_state is not None and moving != self._last_moving_state:
                self.stop_start_transitions += 1
            self._last_moving_state = moving
        turning_in_place = self.steering_mode.startswith("TURN_")
        if ((abs(heading_error) > .28 or
             (orientation_delta > .004 and heading_improved))
                and turning_in_place):
            self.phase = MovementPhase.STEERING
            # A turn-only lease expects no translation. Preserve, but do not
            # advance, any earlier forward no-progress evidence. Clearing it
            # here let alternating soft-steer/turn corrections erase a real
            # wall collision forever after combat resume.
            return MovementAssessment(self.phase, False, False, "heading_correction_in_progress")
        if not commanded or previous is None:
            self.phase = MovementPhase.MOVING
            return MovementAssessment(self.phase, False, False, "reach_initialized")

        progress_score = self.progress_monitor.observe_signals(
            now,
            optical_flow=number(motion_feedback.get("optical_flow_progress")),
            minimap_displacement=number(motion_feedback.get("minimap_displacement_progress")),
            landmark_parallax=number(motion_feedback.get("landmark_parallax_progress")),
            target_distance=min(1., max(0., progress / epsilon)),
            # Retail's moving/speed flag describes the run animation/input
            # state, not physical translation. A positive value must never
            # outvote an unchanged authoritative position at a wall. A
            # stopped value remains useful negative evidence.
            movement_state=0. if moving is False else None,
            expected_vs_observed_bearing=max(0., min(1., 1. - abs(heading_error) / math.pi)),
            movement_animation=(1. if moving else 0.) if moving is not None else None,
        )

        # The controller can receive WORLD3D/FAST observations at 30-40 Hz.
        # A 12-entry deque filled at that rate spans only ~0.3 s and therefore
        # can never satisfy the 1.6 s supported-stuck gate: older evidence is
        # overwritten faster than wall time advances. Downsample only this
        # temporal evidence window; steering and movement commands remain on
        # the full-rate feedback path above/below.
        if (not self.no_progress
                or now-self.no_progress[-1].at >= self.no_progress_sample_interval):
            self.no_progress.append(sample)
        self.evidence_sources.add("POSITION_NO_PROGRESS")
        if speed is not None and speed <= .01 or moving is False:
            self.evidence_sources.add("MOTION_TELEMETRY_STOPPED")
        elif moving is True and speed is not None and speed > .01:
            # Independent contradiction: the client reports a running
            # animation while the world/map position fails to advance toward
            # the destination. This is the characteristic wall-contact trace.
            self.evidence_sources.add("MOTION_POSITION_MISMATCH")
        obstacle = any(item.get("source") == "WORLD3D"
            and (item.get("detector_kind") or item.get("kind")) == "obstacle_candidate"
            and (number(item.get("confidence")) or 0) >= .65
            and (number(item.get("stable_frames")) or 0) >= 3
            and .32 <= (number(item.get("x")) if number(item.get("x")) is not None else -1) <= .68
            for item in state.get("visual_candidates", []))
        if obstacle:
            self.evidence_sources.add("WORLD3D_OBSTACLE_TRACK")
        if observation_id not in self.evidence_observations:
            self.evidence_observations.append(observation_id)
        span = now-self.no_progress[0].at if self.no_progress else 0.
        count = len(self.no_progress)
        # V5 keeps `NO_PROGRESS_YET`, possible stuck, and confirmed hard stuck
        # distinct. Position evidence alone remains useful, but it must persist
        # long enough for the normalized monitor to corroborate it before this
        # controller can terminate REACH and request recovery.
        if (count >= self.supported_samples and span >= 3.0
                and len(self.evidence_sources) >= 2
                and progress_score.phase is ProgressPhase.HARD_STUCK):
            self.phase = MovementPhase.SUPPORTED_STUCK
            return MovementAssessment(self.phase, True, False, "supported_stuck")
        if (count >= self.candidate_samples and span >= self.candidate_seconds
                and progress_score.phase is ProgressPhase.POSSIBLE_STUCK):
            self.phase = MovementPhase.CANDIDATE_STUCK
            return MovementAssessment(self.phase, False, False, "candidate_stuck_collecting_evidence")
        self.phase = MovementPhase.NO_PROGRESS_YET
        return MovementAssessment(self.phase, False, False, "no_progress_yet")

    def _forward_wall_contact(self, sample: MovementSample, position_time: float | None,
                              tolerance: float, now: float) -> bool:
        """Confirm a wall despite sub-yard position jitter resetting per-frame progress.

        This only uses fresh world-position measurements, several seconds of
        uninterrupted forward commands and the client's running state. A
        turn-only lease, stale coordinate, or ordinary slow approach cannot
        establish wall contact by itself.
        """
        if ((self.destination or {}).get("coordinate_space") != "WORLD_YARDS"
                or position_time is None or self.destination.get("follow_group_leader")
                or self.destination.get("follow_quest_entity")):
            return False
        if not self.wall_samples or now-self.wall_samples[-1].at >= self.no_progress_sample_interval:
            self.wall_samples.append(sample)
        while self.wall_samples and now-self.wall_samples[0].at > self.wall_contact_seconds + .75:
            self.wall_samples.popleft()
        if (sample.distance <= tolerance + 3.
                or self.forward_started_at is None
                or now-self.forward_started_at < self.wall_contact_seconds
                or self.last_command_at is None or now-self.last_command_at > .5
                or len(self.wall_samples) < 8
                or now-self.wall_samples[0].at < self.wall_contact_seconds):
            return False
        first = self.wall_samples[0]
        if max(math.hypot(item.x-first.x, item.y-first.y)
               for item in (*self.wall_samples, sample)) > self.wall_contact_max_displacement:
            return False
        # Client speed/moving is independent from the world-position samples:
        # pressed against a wall it still reports a running animation.
        running = sum(item.moving is True and item.speed is not None and item.speed > .1
                      for item in self.wall_samples)
        return running >= .6 * len(self.wall_samples)

    def command(self, state: dict, observation_id: str, now: float) -> tuple[Command, ...]:
        # The agent loop can revisit the same merged observation while the
        # input scheduler is still holding its previous movement lease.  A
        # second command for that observation is not new feedback: besides
        # needlessly refreshing the lease, `_geometry()` would advance the
        # heading smoother again and could manufacture a steering reversal
        # from one frozen camera/player sample.  Closed-loop control permits
        # at most one lease refresh per fresh observation.
        if observation_id == self.last_command_observation_id:
            return ()
        geometry = self._geometry(state)
        if geometry is None or self.phase in {MovementPhase.ARRIVED, MovementPhase.SUPPORTED_STUCK,
                                               MovementPhase.FAILED, MovementPhase.IDLE}:
            return ()
        distance, _, error = geometry
        if self.destination.get("follow_group_leader") or self.destination.get("follow_quest_entity"):
            maximum = number(self.destination.get("follow_max_distance"))
            if maximum is not None and distance <= maximum:
                self.steering_mode = "FOLLOW_HOLD"
                return ()
        absolute_error = abs(error)
        previous_mode = self.steering_mode
        # Hysteresis prevents left/right chatter around a threshold. Large
        # errors are corrected in place before forward motion begins.
        turn_in_place = absolute_error > (.42 if previous_mode.startswith("TURN_") else .58)
        soft_steer = absolute_error > (.10 if previous_mode.startswith("SOFT_") else .16)
        turn = "TURNLEFT" if error > 0 else "TURNRIGHT"
        if (turn_in_place or soft_steer) and self.bindings and not self.bindings.contains(turn):
            raise ValueError(f"Hiányzó irányítási binding: {turn}")
        world_space = self.destination.get("coordinate_space") == "WORLD_YARDS"
        near = world_space and distance <= 8.
        if (self.phase is MovementPhase.CANDIDATE_STUCK and not self.jump_attempted
                and not turn_in_place
                and "MOTION_POSITION_MISMATCH" in self.evidence_sources
                and (not self.bindings or self.bindings.contains("JUMP"))):
            # Running, yet fresh positions show no progress: try one running
            # jump before the supported-stuck recovery ladder takes over.
            self.jump_attempted = True
            command = Command("BIND", "MOVEFORWARD", .32, simultaneous=("JUMP",))
            self.last_command_observation_id = observation_id
            self.last_command_at = now
            self.control_updates += 1
            self.command_history.append((now, "JUMP_FORWARD", .32))
            if self.forward_started_at is None:
                self.forward_started_at = now
            self.progress_monitor.record_command("MOVEFORWARD")
            return (command,)
        if turn_in_place:
            # Retail live traces showed ~0.7-0.9 rad changes from the former
            # 280 ms lease while the feedback loop ran at 1-4 Hz.  Short,
            # bounded leases preserve closed-loop control and avoid repeatedly
            # crossing the desired heading before fresh telemetry arrives.
            duration = min(.12, max(.04, absolute_error/self.turn_rate * .55))
            duration = max(.04, duration * self.turn_duration_scale)
            command = Command("BIND", turn, duration)
            self.steering_mode = "TURN_LEFT" if error > 0 else "TURN_RIGHT"
            self.phase = MovementPhase.STEERING
            self.forward_started_at = None
        elif soft_steer:
            duration = max(.04, (.06 if near else .08) * self.turn_duration_scale)
            command = Command("BIND", "MOVEFORWARD", duration, simultaneous=(turn,))
            self.steering_mode = "SOFT_LEFT" if error > 0 else "SOFT_RIGHT"
            if self.phase not in {MovementPhase.NO_PROGRESS_YET, MovementPhase.CANDIDATE_STUCK}:
                self.phase = MovementPhase.STEERING
            if self.forward_started_at is None:
                self.forward_started_at = now
        else:
            duration = .10 if near else .32
            command = Command("BIND", "MOVEFORWARD", duration)
            self.steering_mode = "STRAIGHT"
            if self.phase not in {MovementPhase.NO_PROGRESS_YET, MovementPhase.CANDIDATE_STUCK}:
                self.phase = MovementPhase.MOVING
            if self.forward_started_at is None:
                self.forward_started_at = now
        self.last_command_observation_id = observation_id
        self.last_command_at = now
        self.control_updates += 1
        self.command_history.append((now, self.steering_mode, duration))
        self.progress_monitor.record_command(command.binding or "")
        return (command,)

    def mark_recovery(self) -> None:
        self.recovery_count += 1

    def snapshot(self) -> dict:
        latest = asdict(self.samples[-1]) if self.samples else None
        elapsed = max(.001, (self.samples[-1].at-self.samples[0].at)
                      if len(self.samples) >= 2 else .001)
        error_changes = []
        for older, newer in zip(self.samples, list(self.samples)[1:]):
            if older.heading_error is not None and newer.heading_error is not None:
                error_changes.append(abs(newer.heading_error-older.heading_error))
        total_progress = sum(max(0., sample.progress) for sample in self.samples)
        return {"phase": self.phase.value, "destination": dict(self.destination) if self.destination else None,
                "control_updates": self.control_updates, "recovery_count": self.recovery_count,
                "steering_mode": self.steering_mode,
                "steering_reversals": self.steering_reversals,
                "turn_reversals_per_min": round(self.steering_reversals/elapsed*60, 3),
                "stop_start_rate_per_min": round(self.stop_start_transitions/elapsed*60, 3),
                "heading_jerk": round(sum(error_changes)/len(error_changes), 5) if error_changes else 0.,
                "overshoot_count": self.overshoot_count,
                "progress_per_second": round(total_progress/elapsed, 5),
                "false_stuck_count": self.recovery_count if self.phase == MovementPhase.MOVING else 0,
                "turn_duration_scale": self.turn_duration_scale,
                "no_progress_samples": len(self.no_progress),
                "wall_contact_samples": len(self.wall_samples),
                "forward_started_at": self.forward_started_at,
                "no_progress_span_seconds": round(
                    self.no_progress[-1].at-self.no_progress[0].at, 4)
                    if len(self.no_progress) >= 2 else 0.,
                "stuck_evidence_sources": sorted(self.evidence_sources),
                "progress": self.progress_monitor.snapshot(),
                "arrival": self.arrival_verifier.snapshot(),
                "stuck_evidence": list(self.evidence_observations[-12:]), "latest_sample": latest}
