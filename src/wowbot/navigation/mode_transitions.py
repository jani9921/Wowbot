"""Travel-mode transitions as a first-class state machine (design spec 30.2).

GROUND <-> MOUNTED_GROUND, MOUNTED_GROUND/GROUND -> FLIGHT, FLIGHT ->
LANDING -> GROUND (or MOUNTED_GROUND), MOUNTED -> DISMOUNTED.  Every
transition has a declared contract:

    preconditions -> action -> verification -> timeout -> recovery / replan

The action is still a proposal of the existing policies (MOUNT, DISMOUNT,
the flight controller's takeoff/landing input); this machine never issues
input.  It knows which transition was started (the executed skill), verifies
it only from the observed state -- a sent mount key is no success, the
mount state must change; a takeoff needs a flying state or a real climb; a
landing needs the client grounded and not falling -- and turns a timeout
into a typed failure with its recovery, which the travel planner reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class TravelMode(StrEnum):
    GROUND = "GROUND"
    MOUNTED_GROUND = "MOUNTED_GROUND"
    FLIGHT = "FLIGHT"
    LANDING = "LANDING"
    UNKNOWN = "UNKNOWN"


class TransitionKind(StrEnum):
    MOUNT = "MOUNT"
    DISMOUNT = "DISMOUNT"
    TAKEOFF = "TAKEOFF"
    LAND = "LAND"
    TOUCHDOWN = "TOUCHDOWN"


@dataclass(frozen=True, slots=True)
class TransitionContract:
    kind: TransitionKind
    sources: frozenset
    target: TravelMode
    preconditions: tuple[str, ...]
    action: str
    verification: str
    timeout_seconds: float
    recovery: str


CONTRACTS = {
    TransitionKind.MOUNT: TransitionContract(
        TransitionKind.MOUNT, frozenset({TravelMode.GROUND}), TravelMode.MOUNTED_GROUND,
        ("mount_capability", "mount_binding_usable", "outdoors", "not_in_combat", "not_casting",
         "not_swimming_or_falling", "not_in_vehicle_or_taxi"),
        "MOUNT", "mounted_state_observed", 4., "avoid_mount_here_then_walk"),
    TransitionKind.DISMOUNT: TransitionContract(
        TransitionKind.DISMOUNT, frozenset({TravelMode.MOUNTED_GROUND}), TravelMode.GROUND,
        ("grounded", "on_foot_action_or_combat_needs_it"),
        "DISMOUNT", "unmounted_state_observed", 3., "retry_once_then_replan"),
    TransitionKind.TAKEOFF: TransitionContract(
        TransitionKind.TAKEOFF, frozenset({TravelMode.GROUND, TravelMode.MOUNTED_GROUND}), TravelMode.FLIGHT,
        ("flying_mount", "open_sky", "flight_allowed_here", "not_in_combat"),
        "FLIGHT_CONTROL", "flying_state_or_climb_observed", 6., "walk_to_open_sky_or_ground_route"),
    TransitionKind.LAND: TransitionContract(
        TransitionKind.LAND, frozenset({TravelMode.FLIGHT}), TravelMode.LANDING,
        ("landing_spot_on_walkable_floor",), "FLIGHT_CONTROL", "descending_toward_landing_spot", 30.,
        "choose_another_landing_spot"),
    TransitionKind.TOUCHDOWN: TransitionContract(
        TransitionKind.TOUCHDOWN, frozenset({TravelMode.LANDING, TravelMode.FLIGHT}), TravelMode.GROUND,
        ("near_walkable_floor",), "FLIGHT_CONTROL", "grounded_not_falling_observed", 12.,
        "hover_down_or_replan_landing"),
}

CLIMB_YARDS = 2.          # a takeoff without a flying flag still counts when the server Z rose this much
HISTORY = 24
FAILURE_MEMORY_SECONDS = 120.


def observed_mode(state: dict) -> TravelMode:
    movement = state.get("movement") or {}
    flight = state.get("packet_flight") or {}
    flying = flight.get("flying", movement.get("flying"))
    mounted = state.get("is_mounted")
    if flying is True:
        return TravelMode.FLIGHT
    if mounted is True:
        return TravelMode.MOUNTED_GROUND
    if mounted is False:
        return TravelMode.GROUND
    return TravelMode.UNKNOWN


def _own_z(state: dict):
    point = state.get("player_world_position") or {}
    z = point.get("z")
    return z if type(z) in {int, float} and math.isfinite(z) and point.get("z_observed") is True else None


class ModeTransitionMachine:
    """Verified travel-mode transitions; bounded history; no input."""

    def __init__(self) -> None:
        self.mode = TravelMode.UNKNOWN
        self.pending: dict | None = None
        self.history: list[dict] = []
        self.failures: dict[str, dict] = {}

    # The policy that proposes the action calls begin() once it ran.
    def begin(self, kind: TransitionKind, state: dict, now: float, *, action_id=None) -> dict:
        contract = CONTRACTS[kind]
        self.pending = {"kind": kind.value, "started_at": now, "deadline": now+contract.timeout_seconds,
                        "from": observed_mode(state).value, "start_z": _own_z(state), "action_id": action_id}
        return dict(self.pending)

    def _verified(self, kind: str, state: dict) -> bool:
        mode = observed_mode(state)
        movement = state.get("movement") or {}
        if kind == TransitionKind.MOUNT:
            return state.get("is_mounted") is True
        if kind == TransitionKind.DISMOUNT:
            return state.get("is_mounted") is False
        if kind == TransitionKind.TAKEOFF:
            start, z = self.pending.get("start_z"), _own_z(state)
            return mode is TravelMode.FLIGHT or (start is not None and z is not None and z-start >= CLIMB_YARDS)
        if kind == TransitionKind.LAND:
            start, z = self.pending.get("start_z"), _own_z(state)
            return start is not None and z is not None and z < start-CLIMB_YARDS
        if kind == TransitionKind.TOUCHDOWN:
            return mode in {TravelMode.GROUND, TravelMode.MOUNTED_GROUND} and movement.get("falling") is not True
        return False

    def observe(self, state: dict, now: float) -> dict | None:
        """Advance the machine; returns the finished transition record, if any."""
        mode = observed_mode(state)
        if mode is not TravelMode.UNKNOWN:
            natural = {(TravelMode.GROUND, TravelMode.MOUNTED_GROUND): TransitionKind.MOUNT,
                       (TravelMode.MOUNTED_GROUND, TravelMode.GROUND): TransitionKind.DISMOUNT,
                       (TravelMode.GROUND, TravelMode.FLIGHT): TransitionKind.TAKEOFF,
                       (TravelMode.MOUNTED_GROUND, TravelMode.FLIGHT): TransitionKind.TAKEOFF,
                       (TravelMode.FLIGHT, TravelMode.GROUND): TransitionKind.TOUCHDOWN,
                       (TravelMode.FLIGHT, TravelMode.MOUNTED_GROUND): TransitionKind.TOUCHDOWN}.get((self.mode, mode))
            if natural is not None and (self.pending is None or self.pending["kind"] != natural.value):
                # Observed without a started action (the flight controller's
                # takeoff/landing, a user's own mount): still a verified fact.
                self._record({"kind": natural.value, "outcome": "VERIFIED",
                              "evidence": "observed_state_transition", "at": now})
            self.mode = mode
        if self.pending is None:
            return None
        kind = self.pending["kind"]
        contract = CONTRACTS[TransitionKind(kind)]
        if self._verified(kind, state):
            return self._finish("VERIFIED", contract.verification, now)
        if now >= self.pending["deadline"]:
            point = state.get("player_world_position") or {}
            self.failures[kind] = {"at": now, "x": point.get("x"), "y": point.get("y"),
                                   "recovery": contract.recovery}
            return self._finish("TIMEOUT", f"{contract.verification}_not_observed", now)
        return None

    def _finish(self, outcome: str, evidence: str, now: float) -> dict:
        kind = self.pending["kind"]
        record = {"kind": kind, "outcome": outcome, "evidence": evidence, "at": now,
                  "started_at": self.pending["started_at"], "from": self.pending["from"],
                  "recovery": None if outcome == "VERIFIED" else CONTRACTS[TransitionKind(kind)].recovery}
        self.pending = None
        if outcome == "VERIFIED":
            self.failures.pop(kind, None)
        self._record(record)
        return record

    def fail(self, kind: TransitionKind, state: dict, now: float, reason: str) -> dict:
        """A transition the executing skill reported failed (e.g. a skyriding
        takeoff that never lifted off)."""
        point = state.get("player_world_position") or {}
        contract = CONTRACTS[kind]
        self.failures[kind.value] = {"at": now, "x": point.get("x"), "y": point.get("y"),
                                     "recovery": contract.recovery}
        if self.pending is not None and self.pending["kind"] == kind.value:
            self.pending = None
        record = {"kind": kind.value, "outcome": "FAILED", "evidence": reason, "at": now,
                  "recovery": contract.recovery}
        self._record(record)
        return record

    def _record(self, record: dict) -> None:
        self.history = [*self.history[-(HISTORY-1):], record]

    def recently_failed(self, kind: TransitionKind, state: dict, now: float, *, yards: float = 30.,
                        seconds: float = FAILURE_MEMORY_SECONDS) -> bool:
        failure = self.failures.get(kind.value)
        if failure is None or not 0 <= now-failure["at"] < seconds:
            return False
        point = state.get("player_world_position") or {}
        if None in (failure.get("x"), failure.get("y"), point.get("x"), point.get("y")):
            return True
        return math.hypot(point["x"]-failure["x"], point["y"]-failure["y"]) < yards

    def allowed(self, kind: TransitionKind) -> bool:
        """The transition is defined from the current observed mode."""
        return self.mode in CONTRACTS[kind].sources

    def snapshot(self) -> dict:
        return {"mode": self.mode.value, "pending": dict(self.pending) if self.pending else None,
                "history": list(self.history[-8:]),
                "failures": {k: dict(v) for k, v in self.failures.items()},
                "contracts": {k.value: {"from": sorted(m.value for m in c.sources), "to": c.target.value,
                                        "preconditions": list(c.preconditions), "action": c.action,
                                        "verification": c.verification, "timeout_seconds": c.timeout_seconds,
                                        "recovery": c.recovery} for k, c in CONTRACTS.items()}}
