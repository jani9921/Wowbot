"""Travel mode choice by comparing candidate trips (design spec 30.1 / 31).

The caller says only *where* and *with which arrival conditions*; this
planner proposes the candidate trips --

    GROUND          [GROUND]
    MOUNTED_GROUND  [MOUNT, RIDE] (+ DISMOUNT when an on-foot action follows)
    FLIGHT          [(MOUNT), TAKEOFF, FLIGHT, LAND, GROUND]
    MIXED           [GROUND to open sky, (MOUNT), TAKEOFF, FLIGHT, LAND, GROUND]

-- with explicit legs, scores each with the shared TravelCostModel (declared
estimate seconds: travel, transitions, danger exposure, failure risk) and
picks the cheapest feasible one.  Infeasible candidates keep their typed
blockers.  It plans no route and issues no input: the ground and flight
navigators stay the route providers, the policies keep proposing the
actions, the ModeTransitionMachine verifies the transitions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math

from .route_score import TravelCalibration

GROUND, MOUNTED_GROUND, FLIGHT, MIXED = "GROUND", "MOUNTED_GROUND", "FLIGHT", "MIXED"


@dataclass(frozen=True, slots=True)
class TravelCostModel:
    calibration: TravelCalibration = field(default_factory=TravelCalibration)
    mount_seconds: float = 2.5              # cast + GCD
    dismount_seconds: float = 1.
    takeoff_seconds: float = 3.
    landing_seconds: float = 4.
    ground_detour_factor: float = 1.25      # a walked path is longer than the straight line
    failure_retry_seconds: float = 20.      # a recently failed transition here costs this, weighted

    def speed(self, mode: str, flight_style: str | None) -> float:
        c = self.calibration
        if mode == GROUND:
            return c.walk_yards_per_second
        if mode == MOUNTED_GROUND:
            return c.ride_yards_per_second
        return c.skyriding_yards_per_second if flight_style == "SKYRIDING" else c.steady_yards_per_second


@dataclass(frozen=True, slots=True)
class TravelCandidate:
    mode: str
    legs: tuple[str, ...]
    feasible: bool
    blockers: tuple[str, ...]
    travel_seconds: float
    transition_seconds: float
    danger_seconds: float
    risk_seconds: float

    @property
    def total_seconds(self) -> float:
        return self.travel_seconds+self.transition_seconds+self.danger_seconds+self.risk_seconds

    def snapshot(self) -> dict:
        return {**asdict(self), "total_seconds": round(self.total_seconds, 2)}


@dataclass(frozen=True, slots=True)
class TravelDecision:
    chosen: TravelCandidate | None
    candidates: tuple[TravelCandidate, ...]
    distance_yards: float

    @property
    def mode(self) -> str | None:
        return self.chosen.mode if self.chosen else None

    def snapshot(self) -> dict:
        return {"chosen": self.mode, "distance_yards": round(self.distance_yards, 1),
                "legs": list(self.chosen.legs) if self.chosen else [],
                "candidates": [c.snapshot() for c in self.candidates],
                "units": "ESTIMATED_SECONDS"}


@dataclass(frozen=True, slots=True)
class TravelOptions:
    """What the existing capability/blocker checks found, never guessed."""
    mounted: bool = False
    airborne: bool = False
    mount_blockers: tuple[str, ...] = ()          # empty: a ground mount can be summoned
    flight_style: str | None = None               # SKYRIDING / STEADY when a flying mode exists
    flight_blockers: tuple[str, ...] = ("no_flight_capability",)
    needs_open_sky_walk: bool = False             # departure walk before a takeoff (MIXED)
    open_sky_walk_yards: float = 0.
    ground_unreachable: str | None = None          # e.g. target far above/below with no path
    on_foot_after: bool = True                    # the destination's action is on foot
    ground_danger_seconds: float = 0.             # route exposure (RouteRiskEvaluator / DangerMap)
    mount_failed_recently: bool = False
    flight_failed_recently: bool = False


class TravelPlanner:
    def __init__(self, model: TravelCostModel | None = None) -> None:
        self.model = model or TravelCostModel()

    def plan(self, distance_yards: float, options: TravelOptions) -> TravelDecision:
        m = self.model
        d = max(0., float(distance_yards))
        ground_d = d*m.ground_detour_factor
        dismount = m.dismount_seconds if options.on_foot_after else 0.
        candidates = []

        def add(mode, legs, blockers, travel, transition, danger=0., risk=0.):
            candidates.append(TravelCandidate(mode, tuple(legs), not blockers, tuple(blockers),
                                              round(travel, 3), round(transition, 3), round(danger, 3),
                                              round(risk, 3)))

        ground_blockers = [options.ground_unreachable] if options.ground_unreachable else []
        if options.airborne:
            ground_blockers.append("airborne")
        if options.mounted:
            # On a mount the walk mode is the ride; a dismount to walk is never cheaper.
            add(MOUNTED_GROUND, ["RIDE", *(["DISMOUNT"] if options.on_foot_after else [])], ground_blockers,
                ground_d/m.speed(MOUNTED_GROUND, None), dismount, options.ground_danger_seconds*.5)
        else:
            add(GROUND, ["GROUND"], ground_blockers, ground_d/m.speed(GROUND, None), 0.,
                options.ground_danger_seconds)
            add(MOUNTED_GROUND, ["MOUNT", "RIDE", *(["DISMOUNT"] if options.on_foot_after else [])],
                [*ground_blockers, *options.mount_blockers], ground_d/m.speed(MOUNTED_GROUND, None),
                m.mount_seconds+dismount, options.ground_danger_seconds*.5,
                m.failure_retry_seconds*.5 if options.mount_failed_recently else 0.)
        if options.flight_style:
            mount_leg = [] if options.mounted or options.airborne else ["MOUNT"]
            transition = (0. if options.airborne else m.takeoff_seconds) + m.landing_seconds + \
                (0. if options.mounted or options.airborne else m.mount_seconds) + dismount
            risk = m.failure_retry_seconds*.5 if options.flight_failed_recently else 0.
            flight_legs = [*mount_leg, *([] if options.airborne else ["TAKEOFF"]), "FLIGHT", "LAND", "GROUND"]
            travel = d/m.speed(FLIGHT, options.flight_style)
            if options.needs_open_sky_walk and not options.airborne:
                walk = options.open_sky_walk_yards*m.ground_detour_factor/m.speed(GROUND, None)
                add(MIXED, ["GROUND", *flight_legs], options.flight_blockers, travel+walk, transition, 0., risk)
            else:
                add(FLIGHT, flight_legs, options.flight_blockers, travel, transition, 0., risk)
        feasible = [c for c in candidates if c.feasible]
        chosen = min(feasible, key=lambda c: (c.total_seconds, c.mode)) if feasible else None
        return TravelDecision(chosen, tuple(candidates), d)


def straight_yards(state: dict, destination: dict) -> float | None:
    here = state.get("player_world_position") or {}
    try:
        flat = math.hypot(float(destination["x"])-float(here["x"]), float(destination["y"])-float(here["y"]))
    except (KeyError, TypeError, ValueError):
        return None
    return flat if math.isfinite(flat) else None
