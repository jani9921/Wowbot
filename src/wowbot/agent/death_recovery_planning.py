"""Death recovery: release spirit, run back as a ghost, resurrect (user 2026-10-03).

Live 2026-10-03 13:59 a goat killed the character and the agent could only
stop (MANUAL).  The addon (0.9.45) exports the visible death popup's confirm
button (``RELEASE_SPIRIT`` / ``RECOVER_CORPSE``) and the corpse position from
C_DeathInfo.  While the player is dead or a ghost these are the only
proposals: click the exported button, or MOVE (ordinary navigation) to the
corpse.  Nothing is clicked unless the addon names the popup kind.
"""
from __future__ import annotations

import math

from .models import Proposal, number
from .planning_types import world_point

CORPSE_RUN_PURPOSE = "CORPSE_RUN"


def player_dead_or_ghost(state: dict) -> bool:
    return state.get("is_dead") is True or state.get("is_ghost") is True


def corpse_run_matches(state: dict, parameters: dict) -> bool:
    """A current ghost's actual corpse (or a bounded safe reclaim spot).

    This verifies the destination; it never exempts a MOVE from routing.
    """
    if state.get('is_ghost') is not True or parameters.get('purpose') != CORPSE_RUN_PURPOSE:
        return False
    corpse = DeathRecoveryPolicy.corpse_destination(state)
    destination, player = world_point(parameters), world_point(state.get('player_world_position'))
    if (corpse is None or destination is None or player is None
            or str(corpse['instance_id']) != str(player['instance_id'])
            or str(destination['instance_id']) != str(player['instance_id'])):
        return False
    radius = DeathRecoveryPolicy.RECLAIM_YARDS if parameters.get('safe_resurrection_spot') is True else .5
    return math.hypot(destination['x']-corpse['x'], destination['y']-corpse['y']) <= radius


class DeathRecoveryPolicy:
    # A popup click needs a moment to change the state; never spam it.
    CLICK_INTERVAL_SECONDS = 3.
    # The client offers "Resurrect Now" within ~40 yd of the corpse.
    CORPSE_STOP_YARDS = 8.

    # User 2026-10-20 ("csináld meg mind", PixelBuddy's PlanResurrection): a
    # ghost revives where it stands, anywhere within the corpse range
    # (TrinityCore CORPSE_RECLAIM_RADIUS 39 yd).  With hostile creatures near
    # the corpse the ghost walks to the reachable spot in range farthest from
    # them (enough at SAFE_YARDS) and resurrects there, not among the killers.
    RECLAIM_YARDS = 34.
    SAFE_YARDS = 30.
    SPOT_RINGS = (0., 10., 20., 30.)
    SPOT_POINTS = 12
    SPOT_PATH_CHECKS = 6
    SPOT_ARRIVE_YARDS = 3.

    LOCAL_RECOVERY_YARDS = 40.

    def __init__(self) -> None:
        self.last_click_at: dict[str, float] = {}
        self.spot: dict | None = None

    @staticmethod
    def airborne(state: dict) -> bool:
        """Flying, or a ghost on a mount (only a flying ghost mount exists)."""
        return ((state.get("movement") or {}).get("flying") is True
                or (state.get("is_ghost") is True and state.get("is_mounted") is True))

    def safe_spot(self, state: dict, corpse: dict, hostiles: list[dict], walk_cost=None) -> dict | None:
        """The resurrection point: farthest from ``hostiles`` within corpse range."""
        if not hostiles:
            return None
        player = world_point(state.get("player_world_position") or {})

        def clearance(x: float, y: float) -> float:
            return min(math.hypot(x-unit["x"], y-unit["y"]) for unit in hostiles)

        cached = self.spot
        if (cached is not None and cached.get("corpse") == (corpse["x"], corpse["y"])
                and clearance(cached["x"], cached["y"]) >= min(self.SAFE_YARDS, .6*cached["clearance"])):
            return cached
        candidates = []
        for radius in self.SPOT_RINGS:
            for k in range(1 if radius == 0 else self.SPOT_POINTS):
                angle = math.tau * k / self.SPOT_POINTS
                x, y = corpse["x"] + radius*math.cos(angle), corpse["y"] + radius*math.sin(angle)
                ghost = math.hypot(x-player["x"], y-player["y"]) if player else 0.
                candidates.append((-min(clearance(x, y), self.SAFE_YARDS), ghost, x, y))
        candidates.sort()
        for negative, _ghost, x, y in candidates[:self.SPOT_PATH_CHECKS]:
            # The corpse's height is a hint for the spot's floor, not a fact.
            point = {**corpse, "x": x, "y": y, "z_estimated": True, "z_observed": False}
            if callable(walk_cost) and walk_cost(state, point) is None:
                continue
            self.spot = {**point, "clearance": -negative, "corpse": (corpse["x"], corpse["y"])}
            return self.spot
        return None

    @staticmethod
    def _button(state: dict, kind: str) -> tuple[float, float] | None:
        info = state.get("death_recovery") or {}
        if not isinstance(info, dict) or info.get("popup") != kind or info.get("enabled") is False:
            return None
        x, y = number(info.get("x")), number(info.get("y"))
        if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
            return None
        return x, y

    def _click(self, kind: str, point: tuple[float, float], reason: str,
               now: float) -> Proposal | None:
        if now - self.last_click_at.get(kind, -math.inf) < self.CLICK_INTERVAL_SECONDS:
            return None
        return Proposal.make(
            "DEATH_RECOVERY", reason,
            {"action": kind, "x": point[0], "y": point[1],
             "coordinate_space": "CLIENT_BOTTOM_LEFT"},
            confidence=1., priority=200.)

    def note_dispatched(self, proposal: Proposal, now: float) -> None:
        if proposal.skill == "DEATH_RECOVERY":
            self.last_click_at[str(proposal.parameters.get("action"))] = now

    @staticmethod
    def corpse_destination(state: dict) -> dict | None:
        corpse = (state.get("death_recovery") or {}).get("corpse")
        return world_point(corpse) if isinstance(corpse, dict) else None

    def propose(self, state: dict, now: float, *, hostile_units=None, walk_cost=None) -> list[Proposal]:
        if not player_dead_or_ghost(state):
            self.spot = None
            return []
        if state.get("is_ghost") is not True:
            release = self._button(state, "RELEASE_SPIRIT")
            proposal = release and self._click(
                "RELEASE_SPIRIT", release, "Halál: szellem elengedése (addon által exportált gomb)", now)
            return [proposal] if proposal else [Proposal.make(
                "WAIT", "Halott: várakozás a Release Spirit gombra", {"waiting_for": ["DEATH_POPUP"]})]
        resurrect = self._button(state, "RECOVER_CORPSE")
        delay = number((state.get("death_recovery") or {}).get("recovery_delay"))
        destination = self.corpse_destination(state)
        player = world_point(state.get("player_world_position") or {})
        spot = None
        far_mounted_ghost = (destination is not None and player is not None and self.airborne(state)
                             and math.hypot(destination['x']-player['x'], destination['y']-player['y'])
                             > self.LOCAL_RECOVERY_YARDS)
        if (destination is not None and player is not None and callable(hostile_units)
                and not far_mounted_ghost):
            spot = self.safe_spot(state, destination, hostile_units(state, destination), walk_cost)
        away = (spot is not None and player is not None
                and math.hypot(spot["x"]-player["x"], spot["y"]-player["y"]) > self.SPOT_ARRIVE_YARDS)
        if resurrect and (delay is None or delay <= 0) and not away:
            proposal = self._click(
                "RECOVER_CORPSE", resurrect, "Szellem a hullánál: feléledés (Resurrect Now)", now)
            if proposal:
                return [proposal]
        if away:
            return [Proposal.make(
                "MOVE", "Szellem: biztonságos feléledési pont a hulla körzetében, ellenségektől távol",
                {key: value for key, value in spot.items() if key not in {"clearance", "corpse"}}
                | {"purpose": CORPSE_RUN_PURPOSE, "require_navmesh": True,
                   "stop_distance": self.SPOT_ARRIVE_YARDS - 1., "allow_combat": True,
                   "safe_resurrection_spot": True},
                confidence=.95, priority=150.)]
        if destination is not None and player is not None:
            distance = math.hypot(destination["x"]-player["x"], destination["y"]-player["y"])
            from .flight_capability import ghost_steady_flight_available
            # A mounted ghost above an unknown-height corpse must land via
            # the shared flight planner/controller, even at the same XY.
            landing_needed = (not resurrect and (delay is None or delay <= 0)
                              and ghost_steady_flight_available(state))
            if (str(destination["instance_id"]) == str(player["instance_id"])
                    and (distance > self.CORPSE_STOP_YARDS or landing_needed)):
                return [Proposal.make(
                    "MOVE", "Szellemként vissza a hullához: közös útvonaltervezés és megközelítés",
                    {**destination, "purpose": CORPSE_RUN_PURPOSE,
                     "require_navmesh": True,
                     "stop_distance": self.CORPSE_STOP_YARDS - 2.,
                     # A ghost cannot be attacked: the killer near the
                     # corpse is no navigation danger.
                     "allow_combat": True},
                    confidence=.95, priority=150.)]
        return [Proposal.make(
            "WAIT", "Szellem: várakozás a feléledés gombra / hulla-pozícióra",
            {"waiting_for": ["RECOVER_CORPSE_POPUP"]})]
