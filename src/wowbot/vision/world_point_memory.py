from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import json
import logging
import threading
import time
from typing import Any

from wowbot.vision.map_mouseover import MapMouseover

_logger = logging.getLogger(__name__)


class WorldPointMemory:
    """Persistent semantic map/minimap mouseover observations.

    Only map-space coordinates are persisted as world points. Minimap
    observations are still emitted in telemetry but are not promoted to
    global x/y without a proven map-space conversion.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS world_points (
                    point_key TEXT PRIMARY KEY,
                    map_id INTEGER NOT NULL,
                    semantic_type TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    name TEXT,
                    npc_id INTEGER,
                    tooltip TEXT,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(world_points)")}
            if "provenance" not in columns:
                conn.execute("ALTER TABLE world_points ADD COLUMN provenance TEXT")
            # points() filters by map_id and last_seen, ordered by seen_count
            # then last_seen -- a full-table scan without this, growing
            # slower every call as the session accumulates map markers. Ran
            # synchronously inside runtime.py's step() via SpatialMemory, so
            # a slow query here blocks the whole control loop -- live-
            # confirmed 2026-09-12 as the cause of 6+s receive_gap stalls
            # (sensor.poll() itself stayed healthy; step() just never got
            # back to it while stuck in this query on an unindexed table).
            conn.execute("CREATE INDEX IF NOT EXISTS idx_world_points_map_last_seen "
                         "ON world_points(map_id, last_seen)")

    @contextmanager
    def _connect(self):
        """Serialized transaction on the long-lived SQLite connection.

        Was a fresh sqlite3.connect() per call (record()/points(), no WAL,
        a new Windows file handle every time), mirroring the same pattern
        already fixed once in entity_memory.py this session.
        """
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                # V4-077: cleanup-time failure must not raise (would mask
                # the caller's own shutdown), but must not be silent either.
                _logger.warning("sqlite connection.close() failed in WorldPointMemory.close()", exc_info=True)

    @staticmethod
    def point_key(mouse: MapMouseover, *, name: str | None = None, npc_id: int | None = None) -> str | None:
        if mouse.surface != "WORLD_MAP" or mouse.map_id is None or mouse.x is None or mouse.y is None:
            return None
        identity = f"npc:{npc_id}" if npc_id is not None else f"name:{name or ''}"
        # 0.005 map-space cells avoid pretending a cursor is pixel-perfect.
        return f"{mouse.map_id}:{mouse.semantic_type}:{round(mouse.x / 0.005)}:{round(mouse.y / 0.005)}:{identity}"

    def record(self, mouse: MapMouseover, *, name: str | None = None,
               npc_id: int | None = None, observed_at: float | None = None,
               provenance: dict | None = None) -> str | None:
        key = self.point_key(mouse, name=name, npc_id=npc_id)
        if key is None:
            return None
        now = float(observed_at if observed_at is not None else time.time())
        with self._connect() as conn:
            row = conn.execute("SELECT seen_count FROM world_points WHERE point_key=?", (key,)).fetchone()
            if row:
                conn.execute("""
                    UPDATE world_points SET last_seen=?, seen_count=seen_count+1,
                        name=COALESCE(?, name), npc_id=COALESCE(?, npc_id), tooltip=COALESCE(?, tooltip)
                    WHERE point_key=?
                """, (now, name, npc_id, mouse.tooltip or None, key))
            else:
                conn.execute("""
                    INSERT INTO world_points(point_key,map_id,semantic_type,x,y,name,npc_id,tooltip,first_seen,last_seen,seen_count)
                    VALUES (?,?,?,?,?,?,?,?,?,?,1)
                """, (key, mouse.map_id, mouse.semantic_type, mouse.x, mouse.y, name, npc_id, mouse.tooltip, now, now))
            if provenance is not None:
                conn.execute("UPDATE world_points SET provenance=? WHERE point_key=?",
                             (json.dumps(provenance), key))
        return key

    def points(self, map_id: int | None = None, limit: int = 100, *, as_of: float | None = None,
               max_age: float | None = None) -> list[dict[str, Any]]:
        query = "SELECT map_id,semantic_type,x,y,name,npc_id,seen_count,first_seen,last_seen,tooltip,provenance FROM world_points"
        params: list[Any] = []
        if map_id is not None:
            query += " WHERE map_id=?"
            params.append(int(map_id))
        if max_age is not None:
            query += " AND" if map_id is not None else " WHERE"
            query += " last_seen>=?"
            params.append(float(as_of if as_of is not None else time.time())-float(max_age))
        query += " ORDER BY seen_count DESC, last_seen DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [{"map_id": r[0], "semantic_type": r[1], "x": r[2], "y": r[3], "name": r[4], "npc_id": r[5], "seen_count": r[6], "first_seen": r[7], "last_seen": r[8], "tooltip": r[9],
                 "coordinate_space": "NORMALIZED_MAP",
                 "location_kind": "MAP_INSPECTION_AREA", "entity_position_confirmed": False,
                 "provenance": json.loads(r[10]) if r[10] else {"coordinate_source": "LEGACY_UNSPECIFIED"}} for r in rows]
