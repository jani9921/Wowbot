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


class DeathRecoveryPolicy:
    # A popup click needs a moment to change the state; never spam it.
    CLICK_INTERVAL_SECONDS = 3.
    # The client offers "Resurrect Now" within ~40 yd of the corpse.
    CORPSE_STOP_YARDS = 8.

    def __init__(self) -> None:
        self.last_click_at: dict[str, float] = {}

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

    def propose(self, state: dict, now: float) -> list[Proposal]:
        if not player_dead_or_ghost(state):
            return []
        if state.get("is_ghost") is not True:
            release = self._button(state, "RELEASE_SPIRIT")
            proposal = release and self._click(
                "RELEASE_SPIRIT", release, "Halál: szellem elengedése (addon által exportált gomb)", now)
            return [proposal] if proposal else [Proposal.make(
                "WAIT", "Halott: várakozás a Release Spirit gombra", {"waiting_for": ["DEATH_POPUP"]})]
        resurrect = self._button(state, "RECOVER_CORPSE")
        delay = number((state.get("death_recovery") or {}).get("recovery_delay"))
        if resurrect and (delay is None or delay <= 0):
            proposal = self._click(
                "RECOVER_CORPSE", resurrect, "Szellem a hullánál: feléledés (Resurrect Now)", now)
            if proposal:
                return [proposal]
        destination = self.corpse_destination(state)
        player = world_point(state.get("player_world_position") or {})
        if destination is not None and player is not None:
            distance = math.hypot(destination["x"]-player["x"], destination["y"]-player["y"])
            if (str(destination["instance_id"]) == str(player["instance_id"])
                    and distance > self.CORPSE_STOP_YARDS):
                return [Proposal.make(
                    "MOVE", "Szellemként vissza a hullához (C_DeathInfo hulla-pozíció)",
                    {**destination, "purpose": CORPSE_RUN_PURPOSE,
                     "stop_distance": self.CORPSE_STOP_YARDS - 2.,
                     # A ghost cannot be attacked: the killer near the
                     # corpse is no navigation danger.
                     "allow_combat": True},
                    confidence=.95, priority=150.)]
        return [Proposal.make(
            "WAIT", "Szellem: várakozás a feléledés gombra / hulla-pozícióra",
            {"waiting_for": ["RECOVER_CORPSE_POPUP"]})]
