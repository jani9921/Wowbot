"""Verified camera-as-a-sensor state for purposeful visual search."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import Command, number


CAMERA_ACTIONS = ("LOOK_LEFT", "LOOK_RIGHT", "LOOK_UP", "LOOK_DOWN",
                  "CENTER_TARGET", "SCAN_ARC", "SCAN_SECTOR", "LOOK_AHEAD",
                  "REACQUIRE_TRACK", "INSPECT_REGION", "RECENTER")


def camera_gesture(parameters: dict) -> dict:
    """Resolve a named camera intent to one bounded normalized drag.

    Explicit x/y always wins. Presets are deterministic, so visual search is
    reproducible and verifiable rather than random.
    """
    action = str(parameters.get("camera_action") or "SCAN_SECTOR").upper()
    if action not in CAMERA_ACTIONS:
        raise ValueError(f"Unknown camera action: {action}")
    presets = {
        "LOOK_LEFT": (.40, .45), "LOOK_RIGHT": (.60, .45),
        "LOOK_UP": (.50, .36), "LOOK_DOWN": (.50, .54),
        "LOOK_AHEAD": (.50, .43), "RECENTER": (.50, .43),
        "SCAN_ARC": (.36, .45), "SCAN_SECTOR": (.64, .45),
    }
    x, y = number(parameters.get("x")), number(parameters.get("y"))
    if x is None or y is None:
        target_x = number(parameters.get("target_x"))
        target_y = number(parameters.get("target_y"))
        if action in {"CENTER_TARGET", "REACQUIRE_TRACK", "INSPECT_REGION"}:
            if target_x is None or target_y is None:
                raise ValueError(f"{action} requires explicit target_x/target_y or x/y")
            x = .5 + (.5-target_x)*.7
            y = .45 + (.5-target_y)*.7
        else:
            x, y = presets[action]
    return {**parameters, "camera_action": action,
            "x": max(.05, min(.95, x)), "y": max(.05, min(.95, y)),
            "duration": min(.14, max(.04, number(parameters.get("duration")) or .10))}


def view_control_command(parameters: dict) -> Command:
    """Resolve a view intent to player yaw when yaw can satisfy it.

    Retail's follow-camera mode recentres yaw behind the character. Horizontal
    mouse drags then fight that setting, while a bounded TURNLEFT/TURNRIGHT
    pulse moves the player and camera together. Pitch-only intents retain a
    camera drag because player yaw cannot look up or down.
    """
    resolved = camera_gesture(parameters)
    action = resolved["camera_action"]
    if action in {"LOOK_UP", "LOOK_DOWN", "LOOK_AHEAD", "RECENTER"}:
        return Command("CAMERA_PAN", x=resolved["x"], y=resolved["y"],
                       button="LEFT", duration=resolved["duration"])

    if action in {"LOOK_LEFT", "SCAN_ARC"}:
        direction = "TURNLEFT"
    elif action in {"LOOK_RIGHT", "SCAN_SECTOR"}:
        direction = "TURNRIGHT"
    elif action in {"CENTER_TARGET", "REACQUIRE_TRACK", "INSPECT_REGION"}:
        target_x = number(parameters.get("target_x"))
        if target_x is None:
            # Direct inspection parameters describe the observed screen point,
            # unlike camera-drag endpoints whose direction is inverted.
            target_x = number(parameters.get("x"))
        direction = "TURNRIGHT" if (target_x or .5) >= .5 else "TURNLEFT"
    else:  # guarded by camera_gesture, kept fail-closed for future actions
        raise ValueError(f"Unsupported view action: {action}")
    duration = min(.18, max(.05, number(parameters.get("turn_duration"))
                            or number(parameters.get("duration")) or .10))
    return Command("BIND", direction, duration)


@dataclass
class CameraEstimate:
    yaw_estimate: float = 0.0
    pitch_estimate: float = 0.0
    zoom_estimate: float | None = None
    relative_to_player_heading: float = 0.0
    motion_confidence: float = 0.0
    status: str = "ESTIMATED"
    last_action: dict | None = None
    last_observation: dict | None = None


class CameraController:
    """Accumulates only estimated camera state from command + frame motion.

    It is not an input authority. SkillRegistry creates the bounded command;
    this class records intent and verifies its visual consequence.
    """
    def __init__(self):
        self.state = CameraEstimate()
        self.direction_reversals = 0
        self._last_direction = 0

    def reset(self):
        self.state = CameraEstimate()
        self.direction_reversals = 0
        self._last_direction = 0

    def begin(self, parameters: dict, now: float):
        parameters = camera_gesture(parameters)
        action = parameters["camera_action"]
        dx = (number(parameters.get("x")) or .5)-.5
        direction = 1 if dx > 0 else -1 if dx < 0 else 0
        if direction and self._last_direction and direction != self._last_direction:
            self.direction_reversals += 1
        if direction:
            self._last_direction = direction
        self.state.last_action = {"action": action,
                                  "requested_dx": dx, "requested_dy":
                                  (number(parameters.get("y")) or .45)-.45,
                                  "started_at": now, "status": "PENDING"}

    def observe(self, camera_state: dict, now: float):
        motion = camera_state.get("camera_motion_px") or {}
        dx, dy = number(motion.get("dx")), number(motion.get("dy"))
        confidence = number(motion.get("confidence")) or 0.
        if dx is None or dy is None:
            return
        self.state.motion_confidence = confidence
        self.state.yaw_estimate += dx
        self.state.pitch_estimate += dy
        self.state.last_observation = {"at": now, "dx": dx, "dy": dy,
                                       "confidence": confidence,
                                       "source": "WORLD3D_GLOBAL_MOTION",
                                       "status": "ESTIMATED"}
        if self.state.last_action and abs(dx)+abs(dy) >= 1 and confidence >= .08:
            self.state.last_action["status"] = "VERIFIED"
            self.state.last_action["verified_at"] = now

    def snapshot(self):
        return {**asdict(self.state), "camera_direction_reversals": self.direction_reversals,
                "supported_actions": list(CAMERA_ACTIONS)}
