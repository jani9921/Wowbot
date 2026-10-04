import time

from wowbot.agent.bindings import BindingsCache
from wowbot.agent.executor import InputExecutor
from wowbot.agent.models import Command
from wowbot.execution import InputScheduler


class Backend:
    def __init__(self):
        self.calls = []
        self.down = {}

    def key(self, key, down):
        self.calls.append((key, down))
        self.down[key] = down

    def is_key_down(self, key):
        return self.down.get(key, False)

    def is_selected_foreground(self):
        return True

    def emergency_pressed(self):
        return False

    def move(self, x, y):
        self.calls.append((x, y))


def test_scheduler_owns_one_persistent_forward_lease_and_short_steering():
    import threading
    backend = Backend()
    scheduler = InputScheduler(backend, threading.Event(), watchdog_seconds=.15)
    try:
        scheduler.execute_movement(keys=("W", "A"), forward={"W"}, steering={"A"},
                                   steering_duration=.02, check=lambda: None)
        assert backend.calls == [("W", True), ("A", True)]
        time.sleep(.06)
        # Steering is short-lived, but forward remains scheduler-owned until
        # a new command, explicit stop, or missed-refresh watchdog expiry.
        assert ("A", False) in backend.calls
        assert backend.down["W"] is True
        scheduler.stop_movement()
        assert backend.down["W"] is False
        assert scheduler.diagnostics()["movement_stops"] == 1
    finally:
        scheduler.close()


def test_normal_input_releases_the_scheduler_lease_before_hover(tmp_path):
    cache_path = tmp_path / "bindings-cache.wtf"
    cache_path.write_text('bind "W" "MOVEFORWARD"\n', encoding="utf-8")
    backend = Backend()
    executor = InputExecutor(42, BindingsCache(cache_path), backend)
    try:
        executor.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
        executor.execute((Command("HOVER", duration=0., x=.5, y=.5),))
        hover_index = backend.calls.index((.5, .5))
        assert ("W", False) in backend.calls[:hover_index]
        assert backend.down["W"] is False
    finally:
        executor.close()


def test_selected_pid_movement_lane_accepts_bounded_los_strafe_lease(tmp_path):
    cache_path = tmp_path / "bindings-cache.wtf"
    cache_path.write_text('bind "Q" "STRAFELEFT"\n', encoding="utf-8")
    backend = Backend()
    executor = InputExecutor(42, BindingsCache(cache_path), backend)
    try:
        executor.execute_movement((Command("BIND", "STRAFELEFT", .35),))
        assert backend.down["Q"] is True
        assert executor.scheduler.diagnostics()["held_keys"] == ["Q"]
        executor.stop_movement()
        assert backend.down["Q"] is False
    finally:
        executor.close()


def test_pointer_only_move_keeps_the_forward_lease(tmp_path):
    """User 2026-10-01: keep the pointer on the approached NPC while walking.
    POINTER presses nothing, so W stays held; HOVER keeps releasing it."""
    cache_path = tmp_path / "bindings-cache.wtf"
    cache_path.write_text('bind "W" "MOVEFORWARD"\n', encoding="utf-8")
    backend = Backend()
    executor = InputExecutor(42, BindingsCache(cache_path), backend)
    try:
        executor.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
        executor.execute((Command("POINTER", duration=0., x=.4, y=.6),))
        assert (.4, .6) in backend.calls
        assert ("W", False) not in backend.calls
        assert backend.down["W"] is True
    finally:
        executor.close()
