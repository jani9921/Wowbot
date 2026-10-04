"""Multi-timescale scheduling primitives for the single autonomous agent.

The fast control loop is never gated here. Only expensive high-level planning
is rate limited; meaningful world transitions open the gate immediately.
"""
from __future__ import annotations

from collections import deque
import hashlib
import heapq
import json
import threading


class RuntimeCadenceScheduler:
    """Thread-safe named cadence gates for sensor/perception work."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._rates: dict[str, RateMeter] = {}
        self._skips: dict[str, int] = {}
        self._lock = threading.Lock()

    def _due(self, name: str, now: float, interval: float,
             *, enabled: bool = True) -> bool:
        if not enabled:
            return False
        with self._lock:
            if now-self._last.get(name, -1e9) + 1e-9 < max(0., interval):
                self._skips[name] = self._skips.get(name, 0)+1
                return False
            self._last[name] = now
            self._rates.setdefault(name, RateMeter(10.)).mark(now)
            return True

    def should_capture(self, now: float, *, interval: float = 1/40) -> bool:
        return self._due("capture", now, interval)

    def should_run_world3d(self, now: float, *, interval: float = 1/15,
                           enabled: bool = True) -> bool:
        return self._due("world3d", now, interval, enabled=enabled)

    def should_run_minimap(self, now: float, *, interval: float = .1,
                           enabled: bool = True) -> bool:
        return self._due("minimap", now, interval, enabled=enabled)

    def should_run_map(self, now: float, *, interval: float = .2,
                       enabled: bool = True) -> bool:
        return self._due("world_map", now, interval, enabled=enabled)

    def should_run_ocr(self, now: float, *, interval: float = .6,
                       enabled: bool = True) -> bool:
        return self._due("ocr", now, interval, enabled=enabled)

    def rates(self, now: float) -> dict:
        with self._lock:
            return {
                **{f"{name}_hz": meter.hz(now)
                   for name, meter in self._rates.items()},
                **{f"{name}_skips": count
                   for name, count in self._skips.items()},
            }

    def reset(self) -> None:
        with self._lock:
            self._last.clear()
            self._rates.clear()
            self._skips.clear()


class RateMeter:
    def __init__(self, window_seconds: float = 10.) -> None:
        self.window_seconds = window_seconds
        self.samples: deque[float] = deque()

    def mark(self, at: float) -> None:
        self.samples.append(at)
        self._trim(at)

    def _trim(self, now: float) -> None:
        while self.samples and now-self.samples[0] > self.window_seconds:
            self.samples.popleft()

    def hz(self, now: float) -> float:
        self._trim(now)
        if len(self.samples) < 2:
            return 0.
        return round((len(self.samples)-1)/max(.001, self.samples[-1]-self.samples[0]), 2)


class BrainScheduler:
    """Event gate for the 0.2–2 Hz slow brain."""
    def __init__(self, minimum_interval: float = .5, heartbeat: float = 5.) -> None:
        self.minimum_interval = minimum_interval
        self.heartbeat = heartbeat
        self.last_at = -1e9
        self.last_signature = ""
        self.last_trigger = "INITIAL"
        self.ticks = 0
        self.skips = 0
        self.rate = RateMeter(30.)
        self.cadence = RuntimeCadenceScheduler()

    def should_capture(self, now: float, *, interval: float = 1/40) -> bool:
        return self.cadence.should_capture(now, interval=interval)

    def should_run_world3d(self, now: float, *, interval: float = 1/15,
                           enabled: bool = True) -> bool:
        return self.cadence.should_run_world3d(now, interval=interval, enabled=enabled)

    def should_run_minimap(self, now: float, *, interval: float = .1,
                           enabled: bool = True) -> bool:
        return self.cadence.should_run_minimap(now, interval=interval, enabled=enabled)

    def should_run_map(self, now: float, *, interval: float = .2,
                       enabled: bool = True) -> bool:
        return self.cadence.should_run_map(now, interval=interval, enabled=enabled)

    def should_run_ocr(self, now: float, *, interval: float = .6,
                       enabled: bool = True) -> bool:
        return self.cadence.should_run_ocr(now, interval=interval, enabled=enabled)

    def rates(self, now: float) -> dict:
        return {**self.cadence.rates(now), "brain_hz": self.rate.hz(now)}

    @staticmethod
    def signature(state: dict, goal=None) -> str:
        target, mouseover = state.get("target") or {}, state.get("mouseover") or {}
        quest_ui = state.get("quest_ui") or {}
        # nsmallest(64, ...) yields the identical deterministic result as
        # sorted(...)[:64] (needed so equivalent world states hash the same
        # way) without paying O(m log m) to sort every live candidate when
        # only a bounded 64-entry prefix is ever kept.
        # track_id is deliberately excluded (live-confirmed 2026-09-22 with a
        # controlled before/after signature comparison): while a vision
        # track never stabilizes (a stuck search/INSPECT loop), its id keeps
        # getting reassigned every tick even though the aggregate picture
        # (state/belief/inspectable) does not change, which forced a full
        # replan on effectively every tick instead of the intended ~2 Hz
        # cadence (brain_skips stayed 0 for 80 consecutive live ticks). A
        # genuinely new/upgraded track (e.g. the first INSPECTABLE one) still
        # changes this multiset and is still caught immediately; only a pure
        # identity swap between otherwise-identical tracks is now ignored.
        tracks = heapq.nsmallest(64, (
            (str(item.get("track_state")),
             str(item.get("belief")), bool(item.get("inspectable")))
            for item in state.get("visual_candidates", []) if item.get("track_id")))
        value = {"goal": getattr(goal, "goal_id", None),
            "goal_status": getattr(goal, "status", None), "session": state.get("session_id"),
            "map": state.get("map_id"), "quest_revision": state.get("quest_state_revision"),
            "target": (target.get("guid"), target.get("dead", target.get("is_dead")),
                       target.get("attackable", target.get("is_attackable"))),
            "mouseover": (mouseover.get("guid"), mouseover.get("npc_id"), mouseover.get("quest_role")),
            # ``quest_ui_open`` alone is insufficient: the fast lane may
            # first report an open frame, then resolve its exact action and
            # normalized button point a packet later.  That second transition
            # is a real planning event, not cursor noise, because it turns an
            # otherwise passive dialog into a safe, addressable transaction.
            "ui": (state.get("world_map_open"), state.get("quest_ui_open"),
                   quest_ui.get("open"),
                   quest_ui.get("action") or state.get("quest_ui_action"),
                   quest_ui.get("quest_id") if quest_ui.get("quest_id") is not None else state.get("quest_ui_quest_id"),
                   quest_ui.get("x") if quest_ui.get("x") not in (None, 0) else state.get("quest_ui_x"),
                   quest_ui.get("y") if quest_ui.get("y") not in (None, 0) else state.get("quest_ui_y"),
                   state.get("gossip_open"), state.get("loading"), state.get("input_blocked")),
            "combat": (state.get("is_in_combat"), state.get("is_dead"), state.get("is_ghost")),
            "tracks": tracks}
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()[:20]

    def should_plan(self, state: dict, goal, now: float) -> tuple[bool, str]:
        signature = self.signature(state, goal)
        changed, elapsed = signature != self.last_signature, now-self.last_at
        if changed or elapsed >= self.heartbeat:
            reason = "WORLD_EVENT" if self.last_signature else "INITIAL"
        elif elapsed >= self.minimum_interval:
            reason = "BRAIN_CADENCE"
        else:
            self.skips += 1
            return False, "FAST_LOOP_CONTINUES"
        self.last_signature, self.last_at, self.last_trigger = signature, now, reason
        self.ticks += 1
        self.rate.mark(now)
        return True, reason

    def reset(self) -> None:
        self.__init__(self.minimum_interval, self.heartbeat)

    def snapshot(self, now: float) -> dict:
        return {"brain_hz": self.rate.hz(now), "brain_ticks": self.ticks,
                "brain_skips": self.skips, "last_trigger": self.last_trigger,
                "minimum_interval_ms": round(self.minimum_interval*1000),
                "heartbeat_seconds": self.heartbeat,
                "sensor_rates": self.cadence.rates(now)}
