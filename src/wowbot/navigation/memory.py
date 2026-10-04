from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
import time


@dataclass(frozen=True, slots=True)
class RouteExperience:
    route_id: str
    attempts: int
    successes: int
    failures: int
    avg_time: float | None
    stuck_count: int
    replan_count: int

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def reliability_score(self) -> float:
        if not self.attempts:
            return 0.5
        penalty = min(0.5, self.stuck_count * 0.05 + self.replan_count * 0.03)
        return max(0.0, min(1.0, self.success_rate - penalty))


@dataclass(frozen=True, slots=True)
class SegmentExperience:
    segment_id: str
    attempts: int
    successes: int
    failures: int
    avg_time: float | None
    blocked_count: int

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0


class NavigationMemory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY, zone TEXT, start_key TEXT, destination_key TEXT,
                    node_ids_json TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL
                );
                CREATE TABLE IF NOT EXISTS route_experience (
                    route_id TEXT PRIMARY KEY REFERENCES routes(route_id), attempts INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                    total_time REAL NOT NULL DEFAULT 0, completed_time_samples INTEGER NOT NULL DEFAULT 0,
                    stuck_count INTEGER NOT NULL DEFAULT 0, replan_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS segment_experience (
                    segment_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                    total_time REAL NOT NULL DEFAULT 0, completed_time_samples INTEGER NOT NULL DEFAULT 0,
                    blocked_count INTEGER NOT NULL DEFAULT 0, last_used_at REAL
                );
            """)

    def record_route(self, route_id: str, *, zone: str | None, start_key: str, destination_key: str, node_ids: list[str] | None = None, node_ids_json: str | None = None) -> None:
        now = time.time()
        encoded = node_ids_json if node_ids_json is not None else json.dumps(node_ids or [])
        with self._connect() as conn:
            conn.execute("INSERT INTO routes(route_id, zone, start_key, destination_key, node_ids_json, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(route_id) DO UPDATE SET node_ids_json=excluded.node_ids_json, last_used_at=excluded.last_used_at", (route_id, zone, start_key, destination_key, encoded, now, now))
            conn.execute("INSERT OR IGNORE INTO route_experience(route_id) VALUES (?)", (route_id,))

    def record_outcome(self, route_id: str, *, success: bool, elapsed_seconds: float | None = None, stuck_count: int = 0, replan_count: int = 0) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO route_experience(route_id) VALUES (?)", (route_id,))
            conn.execute("UPDATE route_experience SET attempts=attempts+1, successes=successes+?, failures=failures+?, total_time=total_time+?, completed_time_samples=completed_time_samples+?, stuck_count=stuck_count+?, replan_count=replan_count+? WHERE route_id=?", (int(success), int(not success), elapsed_seconds or 0.0, int(elapsed_seconds is not None), stuck_count, replan_count, route_id))

    def record_segment_outcome(self, segment_id: str, *, success: bool, elapsed_seconds: float | None = None, blocked: bool = False) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO segment_experience(segment_id) VALUES (?)", (segment_id,))
            conn.execute("UPDATE segment_experience SET attempts=attempts+1, successes=successes+?, failures=failures+?, total_time=total_time+?, completed_time_samples=completed_time_samples+?, blocked_count=blocked_count+?, last_used_at=? WHERE segment_id=?", (int(success), int(not success), elapsed_seconds or 0.0, int(elapsed_seconds is not None), int(blocked), time.time(), segment_id))

    def get_experience(self, route_id: str) -> RouteExperience | None:
        with self._connect() as conn:
            row = conn.execute("SELECT route_id, attempts, successes, failures, total_time, completed_time_samples, stuck_count, replan_count FROM route_experience WHERE route_id=?", (route_id,)).fetchone()
        if row is None:
            return None
        route_id, attempts, successes, failures, total_time, samples, stuck_count, replan_count = row
        return RouteExperience(route_id, attempts, successes, failures, (total_time / samples) if samples else None, stuck_count, replan_count)

    def get_segment_experience(self, segment_id: str) -> SegmentExperience | None:
        with self._connect() as conn:
            row = conn.execute("SELECT segment_id, attempts, successes, failures, total_time, completed_time_samples, blocked_count FROM segment_experience WHERE segment_id=?", (segment_id,)).fetchone()
        if row is None:
            return None
        segment_id, attempts, successes, failures, total_time, samples, blocked_count = row
        return SegmentExperience(segment_id, attempts, successes, failures, (total_time / samples) if samples else None, blocked_count)
