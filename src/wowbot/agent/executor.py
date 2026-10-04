from __future__ import annotations

import threading
import time
from .bindings import BindingsCache
from .models import Command
from wowbot.execution import InputScheduler
from wowbot.runtime.performance import measure_input_dispatch


class ExecutionError(RuntimeError):
    pass


class RecordingExecutor:
    """Offline action sink. Records proposals without any operating-system input."""

    def __init__(self):
        self.commands: list[Command] = []
        self.stops = 0

    def execute(self, commands: tuple[Command, ...]):
        self.commands.extend(commands)

    def execute_movement(self, commands: tuple[Command, ...]):
        self.commands.extend(commands)

    def stop(self):
        self.stops += 1

    def stop_movement(self):
        self.stops += 1

    def diagnostics(self):
        return {"kind": "RECORDING", "held_keys": [], "stops": self.stops,
                "commands": len(self.commands), "armed": False}


class InputExecutor:
    def __init__(self, pid: int, bindings: BindingsCache, backend=None):
        if pid <= 0:
            raise ValueError("A konkrét WoW PID kiválasztása szükséges")
        if backend is None:
            from .windows_input import WindowsInput
            backend = WindowsInput(pid)
        self.pid, self.bindings, self.backend = pid, bindings, backend
        self.cancelled = threading.Event()
        self._lock = threading.RLock()
        self._held: set[str] = set()
        # MOVEFORWARD is a persistent reach lease.  Steering remains a short
        # correction, while this watchdog guarantees release if the control
        # loop, sensor, focus guard, or process stops refreshing it.
        # A movement lease is refreshed by the fast closed-loop controller.
        # It must expire quickly when fresh visual/telemetry feedback stops;
        # several seconds of unattended W was enough to run through an NPC in
        # live tests.  This is deliberately longer than a healthy 20-40 Hz
        # control interval, but short enough to be a practical fail-safe.
        self.scheduler = InputScheduler(backend, self.cancelled, watchdog_seconds=.45)
        self.performance_monitor = None

    @property
    def movement_watchdog_seconds(self) -> float:
        return self.scheduler.movement_watchdog_seconds

    @movement_watchdog_seconds.setter
    def movement_watchdog_seconds(self, value: float) -> None:
        self.scheduler.movement_watchdog_seconds = float(value)

    def arm(self):
        self.cancelled.clear()

    def stop(self):
        self.cancelled.set()
        self.scheduler.stop_movement()
        with self._lock:
            self._release()

    def stop_movement(self):
        """Release a movement lease without disarming the selected executor."""
        try:
            self.scheduler.stop_movement()
        except Exception as error:
            raise ExecutionError("Input felengedési hiba: " + str(error)) from error

    def _release(self):
        errors = []
        for key in list(self._held):
            try:
                self.backend.key(key, False)
            except Exception as error:
                errors.append(str(error))
            else:
                self._held.discard(key)
        if errors:
            raise ExecutionError("Input felengedési hiba: " + "; ".join(errors))

    def diagnostics(self):
        with self._lock:
            short_held = sorted(self._held)
        return {"kind": "LIVE", "pid": self.pid,
                "armed": not self.cancelled.is_set(),
                "short_step_held_keys": short_held,
                **self.scheduler.diagnostics()}

    def _check(self):
        if self.scheduler.background_error:
            raise ExecutionError("Movement watchdog hiba: " + self.scheduler.background_error)
        if self.cancelled.is_set():
            raise ExecutionError("STOP/MANUAL megszakította a végrehajtást")
        if not self.backend.is_selected_foreground():
            raise ExecutionError("A kiválasztott PID ablaka nincs előtérben")
        if self.backend.emergency_pressed():
            self.stop()
            raise ExecutionError("F12 vészleállítás")

    @measure_input_dispatch
    def execute(self, commands: tuple[Command, ...]):
        if not self.bindings.unchanged():
            self.stop()
            raise ExecutionError("A kiválasztott bindings-cache megváltozott; töltsd be újra")
        # Resolve the complete short step before emitting any input.
        resolved = []
        for command in commands:
            if not 0 <= command.duration <= .35:
                raise ExecutionError("Az input lépés maximum 350 ms lehet")
            keys = [self.bindings.resolve(a) for a in ((command.binding,) if command.binding else ()) + command.simultaneous]
            if command.kind not in {"BIND", "CLICK", "CLICK_CURRENT_CURSOR", "HOVER", "POINTER", "MAP_ZOOM_IN", "MAP_STEP_OUT", "CAMERA_PAN"}:
                raise ExecutionError("Ismeretlen input parancs")
            if command.kind in {"CLICK", "HOVER", "POINTER", "MAP_ZOOM_IN", "MAP_STEP_OUT", "CAMERA_PAN"} and not (command.x is not None and command.y is not None and 0 <= command.x <= 1 and 0 <= command.y <= 1):
                raise ExecutionError("Érvénytelen klienskoordináta")
            resolved.append((command, keys))
        # POINTER is a pure pointer move that presses nothing, so it runs while
        # a movement lease holds W (user 2026-10-01: keep the pointer on the
        # approached NPC without stopping).  HOVER and everything else still
        # release movement first (their samples are taken stationary).
        pointer_only = all(command.kind == "POINTER" and not keys for command, keys in resolved)
        try:
            if not pointer_only:
                with self._lock:
                    self.stop_movement()
                    self._release()
            for command, keys in resolved:
                self._check()
                with self._lock:
                    self._check()
                    if command.kind == "CAMERA_PAN":
                        self.backend.move(.5, .45)
                    elif command.kind in {"CLICK", "HOVER", "POINTER", "MAP_ZOOM_IN", "MAP_STEP_OUT"}:
                        self.backend.move(command.x, command.y)
                    if command.kind == "MAP_ZOOM_IN":
                        self._check()
                        self.backend.wheel_up()
                    if command.kind == "MAP_STEP_OUT":
                        keys.append("BUTTON2")
                    if command.kind in {"CLICK", "CLICK_CURRENT_CURSOR"}:
                        keys.append("BUTTON1" if command.button == "LEFT" else "BUTTON2")
                    if command.kind == "CAMERA_PAN":
                        keys.append("BUTTON1" if command.button == "LEFT" else "BUTTON2")
                    for key in keys:
                        self._held.add(key)
                        self.backend.key(key, True)
                    if command.kind == "CAMERA_PAN":
                        self.backend.move(command.x, command.y)
                deadline = time.monotonic() + command.duration
                while time.monotonic() < deadline:
                    self._check()
                    self.cancelled.wait(min(.01, max(0, deadline - time.monotonic())))
                with self._lock:
                    self._release()
        finally:
            with self._lock:
                self._release()

    @measure_input_dispatch
    def execute_movement(self, commands: tuple[Command, ...]):
        """Validate then hand one movement lease to the sole InputScheduler."""
        if len(commands) != 1:
            raise ExecutionError("A movement lease pontosan egy parancsot fogad")
        command = commands[0]
        movement_actions = {"MOVEFORWARD", "MOVEBACKWARD", "TURNLEFT", "TURNRIGHT",
                            "STRAFELEFT", "STRAFERIGHT"}
        # User 2026-10-02: jump while running into a small obstacle.  JUMP
        # may ride along a forward lease only, as a transient key released
        # with the steering deadline (a held Space would keep re-jumping).
        jump_ok = command.binding == "MOVEFORWARD"
        if (command.kind != "BIND" or command.binding not in movement_actions
                or any(action not in movement_actions and not (action == "JUMP" and jump_ok)
                       for action in command.simultaneous)
                or not .04 <= command.duration <= .35):
            raise ExecutionError("Érvénytelen movement lease")
        if not self.bindings.unchanged():
            self.stop()
            raise ExecutionError("A kiválasztott bindings-cache megváltozott; töltsd be újra")
        actions = (command.binding,) + command.simultaneous
        resolved = {action: self.bindings.resolve(action) for action in actions}
        # A strafe is a primary translation lease, not transient steering.
        # The watchdog therefore owns its bounded release exactly as it owns
        # MOVEFORWARD; it is never dispatched on the ordinary action lane.
        forward = {key for action, key in resolved.items()
                   if action in {"MOVEFORWARD", "MOVEBACKWARD", "STRAFELEFT", "STRAFERIGHT"}}
        steering = {key for action, key in resolved.items()
                    if action in {"TURNLEFT", "TURNRIGHT", "JUMP"}}
        keys = tuple(resolved[action] for action in actions)
        try:
            self.scheduler.execute_movement(
                keys=keys, forward=forward, steering=steering,
                steering_duration=command.duration, check=self._check)
        except ExecutionError:
            raise
        except Exception as error:
            raise ExecutionError("Movement input scheduler hiba: " + str(error)) from error

    def close(self):
        self.stop()
        self.scheduler.close()
