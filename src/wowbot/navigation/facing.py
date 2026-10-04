"""Single bounded screen-space facing primitive for local M0 recovery."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wowbot.agent.models import Command, number


class FaceStatus(StrEnum):
    ALIGNED = "ALIGNED"
    ADJUSTING = "ADJUSTING"
    TARGET_LOST = "TARGET_LOST"
    FAILED = "FAILED"


@dataclass(frozen=True)
class FaceResult:
    status: FaceStatus
    commands: tuple[Command, ...] = ()
    error: float | None = None
    reason: str | None = None


class FaceController:
    """Issue at most one bounded turn from a fresh target screen position."""

    # Enter alignment through the narrow band; once aligned, retain it until
    # error crosses the wider exit band. Reversing these creates chatter.
    ENTER_DEADZONE = .025
    EXIT_DEADZONE = .045
    CENTRAL_CONE_DEGREES = 15.0
    DEFAULT_TIMEOUT_SECONDS = 1.8

    def __init__(self, bindings=None):
        self.bindings = bindings
        self._aligned = False
        self._target_ref: str | None = None
        self._deadline: float | None = None

    def reset(self) -> None:
        self._aligned = False
        self._target_ref = None
        self._deadline = None

    def begin(self, target, now: float, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._aligned = False
        self._target_ref = str(
            (target or {}).get("guid") or (target or {}).get("track_id") or "") or None
        self._deadline = now + max(.1, float(timeout))

    @staticmethod
    def estimate_error(target) -> float | None:
        if isinstance(target, dict):
            screen = target.get("screen_position") or target
            value = number(screen.get("x"))
        else:
            value = number(target)
        if value is None or not .02 < value < .98:
            return None
        return value - .5

    def turn_command(self, error: float) -> Command | None:
        binding = "TURNRIGHT" if error > 0 else "TURNLEFT"
        if self.bindings is not None and not self.bindings.contains(binding):
            return None
        return Command("BIND", binding, min(.16, max(.06, abs(error) * .35)))

    def is_aligned(self) -> bool:
        return self._aligned

    def tick(self, target, now: float) -> FaceResult:
        if self._deadline is not None and now > self._deadline:
            self.cancel()
            return FaceResult(FaceStatus.FAILED, reason="facing_timeout")
        error = self.estimate_error(target)
        if error is None:
            self._aligned = False
            return FaceResult(
                FaceStatus.TARGET_LOST, reason="fresh_screen_anchor_missing")
        threshold = self.EXIT_DEADZONE if self._aligned else self.ENTER_DEADZONE
        if abs(error) <= threshold:
            self._aligned = True
            return FaceResult(FaceStatus.ALIGNED, error=error)
        command = self.turn_command(error)
        if command is None:
            self._aligned = False
            return FaceResult(
                FaceStatus.FAILED, error=error, reason="turn_binding_missing")
        self._aligned = False
        return FaceResult(FaceStatus.ADJUSTING, (command,), error=error)

    def cancel(self) -> None:
        self.reset()

    def face_screen_x(self, x: object) -> FaceResult:
        error = self.estimate_error(x)
        if error is None:
            self._aligned = False
            return FaceResult(
                FaceStatus.TARGET_LOST, reason="fresh_screen_anchor_missing")
        threshold = self.EXIT_DEADZONE if self._aligned else self.ENTER_DEADZONE
        if abs(error) <= threshold:
            self._aligned = True
            return FaceResult(FaceStatus.ALIGNED, error=error)
        command = self.turn_command(error)
        if command is None:
            self._aligned = False
            return FaceResult(
                FaceStatus.FAILED, error=error, reason="turn_binding_missing")
        self._aligned = False
        return FaceResult(FaceStatus.ADJUSTING, (command,), error=error)
