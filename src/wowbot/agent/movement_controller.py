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

# User 2026-10-20 ("csináld meg mind", after reading PixelBuddy's controller,
# which leans 40 % toward the next waypoint within 15 yd of a bend): inside a
# route bend's window the heading leans up to this share of the way toward
# the following waypoint, so the run curves through the bend.  The
# navigation service grants a window only where this very law, simulated,
# stays on walkable ground (never over the pit spiral's drop).
CORNER_BLEND_MAX = .4


def corner_heading(position: tuple[float, float], corner: tuple[float, float],
                   following: tuple[float, float], window: float) -> float:
    """Heading to ``corner``, leaning toward ``following`` inside ``window``."""
    px, py = position
    to_corner = math.atan2(corner[1]-py, corner[0]-px)
    distance = math.hypot(corner[0]-px, corner[1]-py)
    if window <= 0 or distance >= window:
        return to_corner % math.tau
    to_next = math.atan2(following[1]-py, following[0]-px)
    weight = CORNER_BLEND_MAX * (1. - distance/window)
    return (to_corner + weight*((to_next-to_corner+math.pi) % math.tau - math.pi)) % math.tau


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
        self.last_forward_at: float | None = None
        self.follow_missing_since: float | None = None
        self.face_started_at: float | None = None
        self.face_progress_at: float | None = None
        self.face_best_error: float | None = None
        self.face_geometry: dict | None = None
        self._interaction_forward_pose: tuple | None = None
        # One running jump per no-progress episode (user 2026-10-02: Space
        # often clears a small obstacle).  Cleared when progress resumes.
        self.jump_attempted = False
        self.strafe_credit = 0.
        self.strafe_side: str | None = None
        self.strafe_at: float | None = None
        # Steady Flight along a FlightPlan (user 2026-10-25); None on foot.
        self.flight = None
        self.locomotion_phase = "GROUND"
        self.strafe_held = False
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

    # User 2026-10-20: "very choppy: it reaches a point, turns to where it
    # wants to go, then starts again".  Each route waypoint restarted the
    # controller, and any next-leg bearing beyond 0.58 rad stopped the run
    # for a turn in place.  While running, a bend up to ~77 deg is taken with
    # forward + turn held together; sharper ones still stop and turn.  No
    # corner is cut early (the pit spiral's inside is the drop, 2026-10-06):
    # a running turn can only swing slightly wide.
    RUN_CARRY_SECONDS = .6
    RUNNING_TURN_IN_PLACE = 1.35
    RUNNING_TURN_IN_PLACE_HOLD = 1.15
    RUNNING_TURN_MIN_YARDS = 4.
    RUNNING_TURN_MAX_LEASE = .16

    def start(self, destination: dict, state: dict, observation_id: str, now: float, *,
              continuing: bool = False) -> None:
        key = self._key(destination)
        if destination.get('entity_route_anchor') and destination.get('route_id'):
            key+=('CORRIDOR',destination['route_id'],destination.get('route_waypoint_index'))
        # Two intents may land at the same XY while requiring different air
        # paths, heights or phases. Never retain the previous flight's index
        # just because its final horizontal point happens to match.
        for name in ("flight_path", "flight_plan"):
            if destination.get(name):
                import json
                key += (name, json.dumps(destination[name], sort_keys=True, separators=(",", ":")))
        if key != self.destination_key:
            last_forward = self.__dict__.get("last_forward_at")
            scale = self.turn_duration_scale
            self.reset()
            if (continuing and last_forward is not None
                    and 0 <= now-last_forward <= self.RUN_CARRY_SECONDS):
                # The next route leg of the same walk: still running.
                self.last_forward_at = last_forward
                self.turn_duration_scale = scale
        self.destination = dict(destination)
        self.destination_key = key
        plan = self.destination.get("flight_plan")
        course = self.destination.get("flight_path")
        hover = self.destination.get("hover_point")
        if not plan and not course and not hover:
            self.flight = None
        elif self.flight is None and hover and not plan and not course:
            # A flying quest vehicle to a point in the air (2026-10-26).
            from .hover_control import HoverControl
            self.flight = HoverControl(hover, number(self.destination.get("stop_distance")) or 4., self.bindings,
                                       face=self.destination.get("face_towards"),
                                       aim=self.destination.get("aim_pitch") is True,
                                       tab_guid=(self.destination.get("server_entity_guid")
                                                 if self.destination.get("purpose") == "VEHICLE_ATTACK_APPROACH"
                                                 else None))
        elif self.flight is None and course:
            from .skyriding_control import SkyridingControl
            from wowbot.navigation.flight_path import FlightPath
            self.flight = SkyridingControl(FlightPath.from_dict(course), self.bindings)
        elif self.flight is None and self.destination.get("flight_style") == "SKYRIDING":
            # Travel (user 2026-10-25: quest to quest): the terrain plan flown
            # by the same Skyriding loop as the lesson rings.
            from .skyriding_control import SkyridingControl
            from wowbot.navigation.flight_path import FlightPath
            from wowbot.navigation.flight_route import FlightPlan, skyriding_path
            self.flight = SkyridingControl(
                FlightPath.from_dict(skyriding_path(FlightPlan.from_dict(plan))), self.bindings)
        elif self.flight is None:
            from wowbot.navigation.flight_route import FlightPlan
            from .flight_control import FlightControl
            self.flight = FlightControl(FlightPlan.from_dict(plan), self.bindings)
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
        if (self.destination or {}).get('entity_route_anchor') is True:
            return True  # NavigationService owns the corridor; identity/facing remain live.
        recipient = (self.destination or {}).get("interaction_recipient_guid")
        if recipient:
            from .packet_entity_facts import interaction_position
            point = interaction_position(state, recipient, allow_dead=self.destination.get('allow_dead') is True)
            if point is None:
                return False
            if ((self.destination or {}).get("interaction_identity_source") == "TARGET"
                    and str((state.get("target") or {}).get("guid") or "") != str(recipient)):
                return False
            self.destination.update({key: point[key] for key in ("x", "y", "z", "instance_id")})
            self.destination.update(layer_z=point["z"], z_known=True, z_source="PACKET_ENTITY")
            return True
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
        live_z = number(position.get("z"))
        trusted_z = (live_z is not None and position.get("z_known") is not False
                     and position.get("source") != "UNIT_POSITION")
        self.destination.update(x=x, y=y, instance_id=target_instance, coordinate_space="WORLD_YARDS")
        if trusted_z:
            self.destination["z"] = live_z
        else:
            self.destination.pop("z", None)
            self.destination.pop("layer_z", None)
            self.destination["z_known"] = False
        if "layer_z" in self.destination and trusted_z:
            # Issue #101: a moving target's trusted height keeps the arrival
            # layer current (ramps/stairs) instead of the start-time value.
            self.destination["layer_z"] = live_z
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
            following = self.destination.get("corner_next") or {}
            window = number(self.destination.get("corner_blend_yards")) or 0.
            fx, fy = number(following.get("x")), number(following.get("y"))
            if window > 0 and fx is not None and fy is not None:
                desired = corner_heading(pos, (self.destination["x"], self.destination["y"]),
                                         (fx, fy), window)
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

    # User 2026-10-14: "go there by the minimap, face it, soft target, then
    # interact".  The client's soft-interact target is the object/NPC in
    # front of the character; a destination with ``face_on_arrival`` turns
    # the character toward its point before the arrival is reported.
    FACE_ON_ARRIVAL_RADIANS = .30
    FACE_ON_ARRIVAL_SECONDS = 2.5
    FACE_ON_ARRIVAL_MAX_SECONDS = 8.
    FACE_MIN_DISTANCE_YARDS = 1.

    def _arrival_facing_error(self, state: dict) -> tuple[float, float] | None:
        from wowbot.navigation.facing_geometry import assess
        assessment=assess(self.destination or {},state,self._position(state))
        self.face_geometry=assessment.snapshot()
        return ((assessment.distance,assessment.error) if assessment.reason=='KNOWN' else None)

    OTHER_LEVEL_YARDS = 12.

    def _level_distance(self, state: dict, distance: float) -> float:
        """Live 2026-10-26 17:22-17:23: the turn-in point at z 95, the agent
        landed on a ledge at z 185.6 straight above; the flat test "arrived"
        ~20 times in a row.  A known destination height more than
        OTHER_LEVEL_YARDS away is not arrival."""
        from .destination_distance import observed_height
        player = state.get("player_world_position") or {}
        z, pz = number(self.destination.get("z")), observed_height(player)
        if pz is None and player.get("z_source") == "NAVMESH_SURFACE":
            # Surface evidence can veto arrival on a different requested
            # floor even when this addon page omitted the measured own Z.
            # It is not promoted to a server measurement.
            pz = number(player.get("z"))
        if (self.destination.get("z_known") is True and z is not None and pz is not None
                and abs(z-pz) > self.OTHER_LEVEL_YARDS):
            return max(distance, abs(z-pz))
        return distance

    def _facing_after_arrival(self, state: dict, now: float) -> MovementAssessment | None:
        destination = self.destination or {}
        if (not destination.get("face_on_arrival")
                or destination.get("route_waypoint_final") is False
                or destination.get("coordinate_space") != "WORLD_YARDS"):
            return None
        if self._level_distance(state, 0.) > self.OTHER_LEVEL_YARDS:
            # Straight above/below us: no bearing to face (live 16:41-16:42).
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "arrived_on_other_level")
        if self.face_started_at is None:
            self.face_started_at = now
        geometry = self._arrival_facing_error(state)
        face_reason=(self.face_geometry or {}).get('reason')
        if geometry is None and face_reason in {
                'ENTITY_UNKNOWN_OR_REMOVED','ENTITY_POSITION_UNKNOWN','SELECTED_IDENTITY_CHANGED',
                'WORLD_UNKNOWN','WORLD_MISMATCH'}:
            self.phase=MovementPhase.FAILED
            return MovementAssessment(self.phase,True,False,'reach_object_identity_or_position_lost')
        if geometry is not None and (self.face_best_error is None or abs(geometry[1]) < self.face_best_error-.05):
            self.face_best_error = abs(geometry[1])
            self.face_progress_at = now
        if geometry is not None and (geometry[0] < self.FACE_MIN_DISTANCE_YARDS
                                     or abs(geometry[1]) <= self.FACE_ON_ARRIVAL_RADIANS):
            if self.steering_mode == "FACE_ON_ARRIVAL":
                self.steering_mode = "STRAIGHT"
            return None
        if (now-self.face_started_at >= self.FACE_ON_ARRIVAL_MAX_SECONDS
                or now-(self.face_progress_at if self.face_progress_at is not None else self.face_started_at)
                >= self.FACE_ON_ARRIVAL_SECONDS):
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "facing_failed")
        self.phase = MovementPhase.STEERING
        self.steering_mode = "FACE_ON_ARRIVAL"
        return MovementAssessment(self.phase, False, False, "facing_destination_after_arrival")

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
        if (self.terminal_reason in {"facing_failed","reach_object_identity_or_position_lost"}
                and self.phase is MovementPhase.FAILED):
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
        if self.flight is not None:
            return self._observe_flight(state, observation_id, now, distance)
        position_time = self._position_sample_time(state)
        if (position_time is not None and self.last_position_time is not None
                and position_time <= self.last_position_time and self.samples):
            # Steering still runs on this observation (command() reads the
            # fresh orientation); progress/stuck evidence waits for a new
            # position measurement.
            self.last_observation_id = observation_id
            if self.steering_mode == "FACE_ON_ARRIVAL":
                facing = self._facing_after_arrival(state, now)
                if facing is not None:
                    return facing
                self.phase = MovementPhase.ARRIVED
                return MovementAssessment(self.phase, True, True, "reach_arrival_verified")
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
            distance=self._level_distance(state, distance),
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
            facing = self._facing_after_arrival(state, now)
            if facing is not None:
                return facing
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

    # A flight crosses up to ~1300 yd and climbs first (FlightPlan.MAX_SAMPLES).
    max_flight_seconds = 240.

    def _tolerance(self) -> float:
        tolerance = number(self.destination.get("stop_distance"))
        if tolerance is None:
            tolerance = number(self.destination.get("arrival_radius"))
        if tolerance is None:
            tolerance = (self.world_arrival_tolerance
                         if self.destination.get("coordinate_space") == "WORLD_YARDS"
                         else self.map_arrival_tolerance)
        return tolerance

    def _observe_flight(self, state: dict, observation_id: str, now: float,
                        distance: float) -> MovementAssessment:
        """Flight replaces the ground progress/stuck evidence (2D, wall
        contact) with the FlightControl's 3D watchdog and landing check."""
        self.last_observation_id = observation_id
        if getattr(self.flight, "path", None) is not None:
            verdict, reason = self.flight.assess(state, now)
        else:
            verdict, reason = self.flight.assess(state, distance, self._tolerance(), now)
        self.locomotion_phase = self.flight.phase
        partial_air = (getattr(getattr(self.flight, 'path', None), 'end_in_air', False)
                       or getattr(getattr(self.flight, 'plan', None), 'truncated', False))
        if verdict == "ARRIVED" and not partial_air and self._level_distance(state, 0.) > self.OTHER_LEVEL_YARDS:
            # Live 2026-10-26 18:05:15: a Skyriding MOVE to z 188 "arrived"
            # with the agent landed at z 259.  Not arrival: replan from here
            # (the next flight lands on the destination's layer).
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "arrived_on_other_level")
        if verdict == "ARRIVED":
            self.phase = MovementPhase.ARRIVED
            return MovementAssessment(self.phase, True, True, reason)
        if verdict == "FAILED":
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, reason)
        if self.started_at is not None and now-self.started_at >= self.max_flight_seconds:
            self.phase = MovementPhase.FAILED
            return MovementAssessment(self.phase, True, False, "movement_safety_deadline")
        self.phase = MovementPhase.MOVING
        return MovementAssessment(self.phase, False, False, reason)

    def ground_transition_required(self, state: dict, now: float) -> bool:
        """Movement phase selection is independent of tasks and quest IDs.

        Required air checkpoints must be verified before a path can finish
        on foot. A steady-flight controller can walk after actual touchdown
        following its CRUISE/LANDING phase. A flying mount alone never takes off.
        """
        from wowbot.navigation.flight_path import grounded
        if self.flight is None or not grounded(state, now):
            return False
        plan = getattr(self.flight, 'plan', None)
        if plan is not None and (plan.truncated or plan.landing.get('navmesh') is False
                                or getattr(self.flight, 'waypoint_index', 0) < len(plan.waypoints)):
            return False
        contact = getattr(self.flight, 'ground_contact', None)
        if callable(contact) and not contact(state, now):
            return False
        path = getattr(self.flight, "path", None)
        if path is not None and not path.landing_on_navmesh:
            return False      # no walkable ground there: the flight loop itself arrives
        if path is not None:
            return path.air_segment_complete(state, min(self.flight.index, len(path.waypoints)))
        return self.flight.phase in {"CRUISE", "LANDING", "LANDED"}

    HEIGHT_PROBE_COOLDOWN_SECONDS = 30.

    def _interaction_forward_duration(self, state: dict, now: float, distance: float,
                                      duration: float) -> float:
        """Brake before a final interaction anchor, including between pose samples.

        Vision/orientation observations can refresh a W lease while the same
        older player coordinate is held. At 14 yd/s a 0.5 s-old point is
        already 7 yd behind the player (live fragment turn-in 18:09:51).
        This is only a command limit, never evidence of arrival.
        """
        destination = self.destination or {}
        if (destination.get("coordinate_space") != "WORLD_YARDS"
                or not destination.get("face_on_arrival")
                or destination.get("route_waypoint_final") is False):
            return duration
        speed, moving = self._motion(state)
        if moving is not True or speed is None or speed <= .1:
            if distance <= self._tolerance()+8.:
                # A held pre-movement sample still says "stopped" after W
                # starts. Permit one short pulse, not repeated W renewals
                # against that same old pose until the speed arrives.
                pose = (self.destination_key, self._position_sample_time(state), self._position(state))
                if pose == self._interaction_forward_pose:
                    return 0.
                self._interaction_forward_pose = pose
                return min(duration, .1)
            return duration
        remaining = max(0., distance-self._tolerance())
        if remaining > max(8., speed):
            return duration
        sampled = self._position_sample_time(state)
        if moving is True and sampled is not None:
            remaining -= speed * max(0., now-sampled)
        if remaining <= 0.:
            return 0.
        # A positive gap smaller than one legal pulse still needs a step.
        # Returning nothing on every fresh stopped-near-arrival sample can
        # otherwise hold MOVE just outside its arrival envelope forever.
        return min(duration, max(.04, remaining/speed))

    HEIGHT_PROBE_TURN_SECONDS = .06

    def prepare_position_probe(self, destination: dict, now: float) -> None:
        """Prepare only a measurement tap; never test arrival or start walking."""
        self.reset()
        self.destination = dict(destination)
        self.destination_key = self._key(destination)
        self.started_at = now
        self.phase = MovementPhase.NO_PROGRESS_YET
        self.steering_mode = "ACQUIRE_POSITION"

    # Live 2026-10-31 02:09-02:12 (Fargodeep Mine entrance): after one
    # unanswered tap every MOVE in the next 30 s waited its 3 s for a server
    # height without tapping and timed out (server_position_probe_timeout in
    # a loop).  A timed-out wait releases the cooldown, at most this many
    # times per cooldown window.
    HEIGHT_PROBE_RETRIES = 3

    def release_height_probe(self, now: float) -> bool:
        retries = [at for at in self.__dict__.get("_height_probe_retries", ())
                   if 0 <= now-at < self.HEIGHT_PROBE_COOLDOWN_SECONDS]
        released = len(retries) < self.HEIGHT_PROBE_RETRIES
        if released:
            retries.append(now)
            self.__dict__.pop("_height_probe_at", None)
        self.__dict__["_height_probe_retries"] = retries
        return released

    def height_probe_available(self, now: float) -> bool:
        last = self.__dict__.get("_height_probe_at")
        return last is None or not 0 <= now-last < self.HEIGHT_PROBE_COOLDOWN_SECONDS

    def position_probe_command(self, state: dict, observation_id: str, now: float):
        if observation_id == self.last_command_observation_id:
            return ()
        return self._height_probe(state, observation_id, now)

    def _height_probe(self, state: dict, observation_id: str, now: float,
                      error: float = 0.) -> tuple[Command, ...]:
        """One short turn tap for a server height before walking a 3D route.

        Live 2026-10-27 16:39:18-16:39:28 (Obsidian Citadel wall): the agent
        started with the character standing still, so the client had sent no
        own movement packet and our height was unknown; the route was planned
        on the courtyard floor 44 yd below until the user jumped.  A jump
        sends CMSG_MOVE_JUMP with the server position at once.  Only while
        the packet lane is live, at most once per 30 s.

        Live 2026-10-28 10:53:42 (Obsidian Citadel, mounted): the jump was
        skipped on the mount and the route was planned 10 yd under us; the
        walk's first 0.12 s TURNLEFT alone brought the own movement packet
        (z 387.6, x/y unchanged) with the next sample.  A turn tap toward the
        heading works mounted too and moves nobody off a ledge."""
        position = state.get("player_world_position") or {}
        last = self.__dict__.get("_height_probe_at")
        if (position.get("z_observed") is True or not state.get("packet_telemetry")
                or self.destination.get("coordinate_space") != "WORLD_YARDS"
                or not (self.destination.get("require_navmesh") or self.destination.get("z_known"))
                or (last is not None and 0 <= now-last < self.HEIGHT_PROBE_COOLDOWN_SECONDS)
                or (state.get("movement") or {}).get("flying") is True
                or state.get("in_vehicle") is True or state.get("is_in_combat")):
            return ()
        turn = "TURNLEFT" if error >= 0 else "TURNRIGHT"
        if self.bindings and not self.bindings.contains(turn):
            return ()
        self.__dict__["_height_probe_at"] = now
        self.last_command_observation_id = observation_id
        self.last_command_at = now
        self.control_updates += 1
        self.command_history.append((now, "HEIGHT_PROBE_TURN", self.HEIGHT_PROBE_TURN_SECONDS))
        return (Command("BIND", turn, self.HEIGHT_PROBE_TURN_SECONDS),)

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
        if self.flight is not None:
            commands = (self.flight.commands(state, now) if getattr(self.flight, "path", None) is not None
                        else self.flight.commands(state, distance, error, self._tolerance(), now))
            self.last_command_observation_id = observation_id
            self.last_command_at = now
            if commands:
                self.control_updates += 1
                self.steering_mode = f"FLIGHT_{self.flight.phase}"
                self.command_history.append((now, self.steering_mode, commands[0].duration))
                if commands[0].binding == "MOVEFORWARD":
                    self.last_forward_at = now
                self.progress_monitor.record_command(commands[0].binding or "")
            return commands
        if self.destination.get("follow_group_leader") or self.destination.get("follow_quest_entity"):
            maximum = number(self.destination.get("follow_max_distance"))
            if maximum is not None and distance <= maximum:
                self.steering_mode = "FOLLOW_HOLD"
                return ()
        if self.steering_mode == "FACE_ON_ARRIVAL" and self.phase is MovementPhase.STEERING:
            # Arrived: turn in place only, never forward.
            facing = self._arrival_facing_error(state)
            if facing is None or abs(facing[1]) <= self.FACE_ON_ARRIVAL_RADIANS:
                return ()
            error = facing[1]
            turn = "TURNLEFT" if error > 0 else "TURNRIGHT"
            if self.bindings and not self.bindings.contains(turn):
                return ()
            duration = max(.04, min(.12, abs(error)/self.turn_rate*.55) * self.turn_duration_scale)
            self.strafe_held, self.strafe_credit = False, 0.
            self.last_command_observation_id = observation_id
            self.last_command_at = now
            self.control_updates += 1
            self.command_history.append((now, "FACE_ON_ARRIVAL", duration))
            return (Command("BIND", turn, duration),)
        probe = self._height_probe(state, observation_id, now, error)
        if probe:
            return probe
        absolute_error = abs(error)
        previous_mode = self.steering_mode
        world_space = self.destination.get("coordinate_space") == "WORLD_YARDS"
        near = world_space and distance <= 8.
        last_forward = self.__dict__.get("last_forward_at")
        running = last_forward is not None and 0 <= now-last_forward <= self.RUN_CARRY_SECONDS
        intermediate = self.destination.get("route_waypoint_final") is False
        # Close to a final point a running turn could circle it; there the
        # former turn-in-place rule stays.
        running_turn = (running and world_space
                        and (distance > self.RUNNING_TURN_MIN_YARDS
                             or (intermediate and distance > 2.5)))
        # Hysteresis prevents left/right chatter around a threshold. Large
        # errors are corrected in place before forward motion begins.
        if running_turn:
            turn_in_place = absolute_error > (self.RUNNING_TURN_IN_PLACE_HOLD if previous_mode.startswith("TURN_")
                                              else self.RUNNING_TURN_IN_PLACE)
        else:
            turn_in_place = absolute_error > (.42 if previous_mode.startswith("TURN_") else .58)
        soft_steer = absolute_error > (.10 if previous_mode.startswith("SOFT_") else .16)
        turn = "TURNLEFT" if error > 0 else "TURNRIGHT"
        if (turn_in_place or soft_steer) and self.bindings and not self.bindings.contains(turn):
            raise ValueError(f"Hiányzó irányítási binding: {turn}")
        jump_guard = self.__dict__.get("jump_guard")
        if (self.phase is MovementPhase.CANDIDATE_STUCK and not self.jump_attempted
                and not turn_in_place
                and "MOTION_POSITION_MISMATCH" in self.evidence_sources
                and (not self.bindings or self.bindings.contains("JUMP"))
                # Live 2026-10-13 17:57 (user screenshot): stuck at the pit
                # spiral's fence, the running jump cleared it into the pit.
                and not (callable(jump_guard) and jump_guard(state))):
            # Running, yet fresh positions show no progress: try one running
            # jump before the supported-stuck recovery ladder takes over.
            self.jump_attempted = True
            self.strafe_held, self.strafe_credit = False, 0.
            command = Command("BIND", "MOVEFORWARD", .32, simultaneous=("JUMP",))
            self.last_command_observation_id = observation_id
            self.last_command_at = now
            self.control_updates += 1
            self.command_history.append((now, "JUMP_FORWARD", .32))
            if self.forward_started_at is None:
                self.forward_started_at = now
            self.last_forward_at = now
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
            if running_turn and absolute_error > .30:
                # Bend while running: turn as long as the error needs (the
                # turn key keeps its rate while W is held).
                base = min(self.RUNNING_TURN_MAX_LEASE, max(.06, absolute_error/self.turn_rate*.6))
            else:
                base = .06 if near else .08
            duration = max(.04, base * self.turn_duration_scale)
            command = Command("BIND", "MOVEFORWARD", duration, simultaneous=(turn,))
            self.steering_mode = "SOFT_LEFT" if error > 0 else "SOFT_RIGHT"
            if self.phase not in {MovementPhase.NO_PROGRESS_YET, MovementPhase.CANDIDATE_STUCK}:
                self.phase = MovementPhase.STEERING
            if self.forward_started_at is None:
                self.forward_started_at = now
        else:
            duration = .10 if near else .32
            strafe = self._strafe_trim(error, now, world_space and running
                                       and distance > self.STRAFE_TRIM_YARDS)
            command = Command("BIND", "MOVEFORWARD", duration,
                              simultaneous=(strafe,) if strafe else ())
            self.steering_mode = {"STRAFELEFT": "STRAFE_LEFT",
                                  "STRAFERIGHT": "STRAFE_RIGHT"}.get(strafe, "STRAIGHT")
            if self.phase not in {MovementPhase.NO_PROGRESS_YET, MovementPhase.CANDIDATE_STUCK}:
                self.phase = MovementPhase.MOVING
            if self.forward_started_at is None:
                self.forward_started_at = now
        if self.steering_mode != "STRAIGHT" and not self.steering_mode.startswith("STRAFE_"):
            # A turning lease lifts any strafe: no time budget is carried over.
            self.strafe_held, self.strafe_credit = False, 0.
        if command.binding == "MOVEFORWARD":
            duration = self._interaction_forward_duration(state, now, distance, command.duration)
            if duration <= 0.:
                return ()  # let the old forward lease expire; await a fresh pose
            final_interaction = (self.destination.get("face_on_arrival")
                                 and self.destination.get("coordinate_space") == "WORLD_YARDS"
                                 and self.destination.get("route_waypoint_final") is not False
                                 and distance <= max(8., (self._motion(state)[0] or 0.)+self._tolerance()))
            if duration != command.duration or final_interaction:
                command = Command(command.kind, command.binding, duration, simultaneous=command.simultaneous,
                                  forward_duration=duration if final_interaction else None)
        self.last_command_observation_id = observation_id
        self.last_command_at = now
        if command.binding == "MOVEFORWARD":
            self.last_forward_at = now
        self.control_updates += 1
        self.command_history.append((now, self.steering_mode, duration))
        self.progress_monitor.record_command(command.binding or "")
        return (command,)

    # User 2026-10-20 (PixelBuddy strafes small errors instead of turning):
    # below the soft-steer threshold the run is trimmed by strafing, so the
    # facing and camera stay still.  W + strafe moves 45 deg off the facing;
    # holding the strafe for |error| / 45 deg of the running time (a time
    # budget kept across leases -- the scheduler keeps W down and lifts the
    # strafe at the next lease without it) bends the path onto the bearing.
    STRAFE_TRIM_MIN = .035
    STRAFE_TRIM_YARDS = 8.
    STRAFE_CREDIT_LIMIT = .2

    def _strafe_trim(self, error: float, now: float, allowed: bool) -> str | None:
        last = self.strafe_at
        dt = min(.3, max(0., now-last)) if last is not None else 0.
        side = "STRAFELEFT" if error > 0 else "STRAFERIGHT"
        if self.strafe_held:
            self.strafe_credit -= dt          # it was down since the last lease
        if (not allowed or abs(error) < self.STRAFE_TRIM_MIN or side != self.strafe_side
                or (self.bindings and not self.bindings.contains(side))):
            self.strafe_credit = 0.
        else:
            self.strafe_credit = min(self.STRAFE_CREDIT_LIMIT, max(
                -self.STRAFE_CREDIT_LIMIT, self.strafe_credit + abs(error)/(math.pi/4)*dt))
        self.strafe_side, self.strafe_at = side, now
        self.strafe_held = allowed and self.strafe_credit > 0 and abs(error) >= self.STRAFE_TRIM_MIN
        return side if self.strafe_held else None

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
                "locomotion_phase": self.flight.phase if self.flight is not None else "GROUND",
                "flight_mode": (getattr(getattr(self.flight, "path", None), "mode", "STEADY")
                                if self.destination is not None and self.flight is not None else None),
                "flight_waypoint_index": getattr(self.flight, "index", None),
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
                "final_facing": {"started_at": self.face_started_at,
                                 "last_progress_at": self.face_progress_at,
                                 "best_error_radians": self.face_best_error,
                                 "geometry": dict(self.face_geometry) if self.face_geometry else None,
                                 "last_command_at": self.last_command_at,
                                 "recent_commands": list(self.command_history)[-6:],
                                 "no_progress_timeout_seconds": self.FACE_ON_ARRIVAL_SECONDS,
                                 "total_budget_seconds": self.FACE_ON_ARRIVAL_MAX_SECONDS},
                "no_progress_span_seconds": round(
                    self.no_progress[-1].at-self.no_progress[0].at, 4)
                    if len(self.no_progress) >= 2 else 0.,
                "stuck_evidence_sources": sorted(self.evidence_sources),
                "progress": self.progress_monitor.snapshot(),
                "arrival": self.arrival_verifier.snapshot(),
                "stuck_evidence": list(self.evidence_observations[-12:]), "latest_sample": latest}
