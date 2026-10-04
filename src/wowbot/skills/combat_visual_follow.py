"""Pure visual-follow policy for the currently selected combat target.

The policy owns no input and performs no recognition.  Identity remains the
addon-selected GUID; World3D contributes only a fresh screen-space bearing.
CombatSkill consumes the decision and NavigationService remains the sole
movement/facing command authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from wowbot.agent.models import number


@dataclass(frozen=True, slots=True)
class CombatVisualFollowDecision:
    kind: str
    expected_guid: str
    target_screen_x: float | None
    target_screen_y: float | None
    visual_sample_time: float | None
    reason: str


class CombatVisualFollowPolicy:
    """Turn toward a fresh committed track and reacquire brief occlusions."""

    STALE_AFTER = .50
    CENTER_ENTER = .075
    CENTER_EXIT = .12
    # A full keyboard turn takes ~2 s; the user requires the character never
    # to keep its back to the selected target (2026-10-01).
    REACQUIRE_TIMEOUT = 3.0
    # Older bearing of the same selected unit (e.g. seen before COMBAT began)
    # still tells which way to turn when it is now behind the character.
    BEARING_MEMORY = 6.0
    COMMAND_INTERVAL = .055

    @staticmethod
    def _context(context: dict) -> dict:
        return context.setdefault("visual_follow", {
            "centered": False,
            "last_seen_x": None,
            "last_seen_y": None,
            "last_visual_sample_time": None,
            "last_command_visual_sample_time": None,
            "last_command_at": -float("inf"),
            "lost_since": None,
            "reacquire_direction": None,
            "control_updates": 0,
            "reacquire_updates": 0,
        })

    def decide(self, context: dict, state: dict, now: float) -> CombatVisualFollowDecision | None:
        follow = self._context(context)
        expected = str(context.get("expected_guid") or "")
        target = state.get("target") or {}
        if (not expected or str(target.get("guid") or "") != expected
                or target.get("dead", target.get("is_dead"))
                or target.get("attackable", target.get("is_attackable")) is not True):
            return None
        if state.get("is_casting"):
            return None

        screen = target.get("screen_position") or {}
        x, y = number(screen.get("x")), number(screen.get("y"))
        sampled = number(screen.get("sample_time", screen.get("observed_at")))
        fresh = (x is not None and y is not None and .01 < x < .99 and .01 < y < .99
                 and (sampled is None or 0. <= now-sampled <= self.STALE_AFTER))
        if fresh:
            follow["last_seen_x"], follow["last_seen_y"] = x, y
            follow["last_visual_sample_time"] = sampled
            follow["lost_since"] = None
            # Live 2026-10-03 (Coastal Goat): last seen at x=.49 -- straight
            # ahead -- then its box was lost and the character kept turning
            # left away from it.  Only a target last seen well off to one
            # side is searched by turning; a centred one stays ahead.
            follow["reacquire_direction"] = (None if abs(x-.5) < .15
                                             else "TURNRIGHT" if x >= .5 else "TURNLEFT")
            error = abs(x-.5)
            centered = bool(follow.get("centered"))
            if centered and error <= self.CENTER_EXIT:
                return None
            if not centered and error <= self.CENTER_ENTER:
                follow["centered"] = True
                return None
            follow["centered"] = False
            # Do not produce multiple commands from the same frozen visual
            # measurement, even if FAST telemetry repeats it many times.
            if (sampled is not None
                    and sampled == follow.get("last_command_visual_sample_time")):
                return None
            if now-float(follow.get("last_command_at", -float("inf"))) < self.COMMAND_INTERVAL:
                return None
            follow["last_command_at"] = now
            follow["last_command_visual_sample_time"] = sampled
            follow["control_updates"] = int(follow.get("control_updates") or 0)+1
            return CombatVisualFollowDecision(
                "COMBAT_TRACK_FOLLOW", expected, x, y, sampled,
                "selected_target_off_center")

        # The exact selected GUID is still authoritative, but its associated
        # visual track is temporarily off-screen/occluded.  Continue only a
        # bounded turn in the last observed direction; never walk blindly.
        lost_since = number(follow.get("lost_since"))
        if lost_since is None:
            follow["lost_since"] = now
            lost_since = now
        if now-lost_since > self.REACQUIRE_TIMEOUT:
            return None
        direction = follow.get("reacquire_direction")
        if direction not in {"TURNLEFT", "TURNRIGHT"}:
            # Never seen during this attempt (it may be behind the character).
            # Use an older bearing of the same selected unit.
            stale_x = number(screen.get("x"))
            stale_at = number(screen.get("sample_time", screen.get("observed_at")))
            # Without any bearing there is no evidence it is off-screen at
            # all: keep fighting and let a client facing error drive the
            # existing facing recovery instead of spinning blindly.
            # A centred old bearing means it was in front: no reason to turn.
            if (stale_x is None or stale_at is None or abs(stale_x-.5) < .30
                    or not 0. <= now-stale_at <= self.BEARING_MEMORY):
                return None
            direction = "TURNRIGHT" if stale_x >= .5 else "TURNLEFT"
            follow["reacquire_direction"] = direction
        if now-float(follow.get("last_command_at", -float("inf"))) < .11:
            return None
        follow["last_command_at"] = now
        follow["reacquire_updates"] = int(follow.get("reacquire_updates") or 0)+1
        return CombatVisualFollowDecision(
            "COMBAT_TRACK_REACQUIRE", expected,
            number(follow.get("last_seen_x")), number(follow.get("last_seen_y")),
            number(follow.get("last_visual_sample_time")),
            "selected_target_visual_track_temporarily_missing")

