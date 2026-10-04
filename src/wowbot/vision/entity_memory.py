from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import logging
import math
import sqlite3
import threading
import time
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EntityMemoryProfile:
    identity_key: str
    unit_type: str
    npc_id: int | None
    name: str | None
    first_seen: float
    last_seen: float
    seen_count: int
    last_map_id: int | None
    last_zone: str | None


class EntityMemory:
    """Persistent confirmed entity identity + spatial memory.

    Only addon-confirmed mouseover units are recorded as identities. Vision
    candidates can be associated later, but they cannot create confirmed
    identities by themselves.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_db()

    @contextmanager
    def _connect(self):
        """Serialized transaction on the long-lived SQLite connection.

        Was a fresh sqlite3.connect() per call (10 call sites, no WAL, a new
        Windows file handle for every visual candidate carrying a signature).
        Every call site already used `with self._connect() as conn:`, so
        making this a context manager itself -- instead of a plain method
        returning one -- needed no call-site changes; they now share one
        persistent, WAL-mode connection, guarded by the same lock pattern
        AgentMemory already uses (memory.py's _tx()/_ro()).
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
                _logger.warning("sqlite connection.close() failed in EntityMemory.close()", exc_info=True)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entity_profiles (
                    identity_key TEXT PRIMARY KEY,
                    unit_type TEXT NOT NULL,
                    npc_id INTEGER,
                    name TEXT,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 0,
                    last_map_id INTEGER,
                    last_zone TEXT
                );
                CREATE TABLE IF NOT EXISTS entity_guids (
                    identity_key TEXT NOT NULL,
                    guid TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(identity_key, guid)
                );
                CREATE TABLE IF NOT EXISTS entity_locations (
                    identity_key TEXT NOT NULL,
                    map_id INTEGER NOT NULL,
                    cell_x INTEGER NOT NULL,
                    cell_y INTEGER NOT NULL,
                    zone TEXT,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    avg_x REAL NOT NULL,
                    avg_y REAL NOT NULL,
                    PRIMARY KEY(identity_key, map_id, cell_x, cell_y)
                );
                CREATE TABLE IF NOT EXISTS entity_location_clusters_v2 (
                    identity_key TEXT NOT NULL,
                    map_id INTEGER NOT NULL,
                    phase_key TEXT NOT NULL,
                    instance_key TEXT NOT NULL,
                    context_key TEXT NOT NULL,
                    coordinate_space TEXT NOT NULL,
                    cell_x INTEGER NOT NULL,
                    cell_y INTEGER NOT NULL,
                    zone TEXT,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    avg_x REAL NOT NULL,
                    avg_y REAL NOT NULL,
                    PRIMARY KEY(identity_key,map_id,phase_key,instance_key,context_key,cell_x,cell_y)
                );
                CREATE TABLE IF NOT EXISTS entity_visuals (
                    identity_key TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(identity_key, signature)
                );
                CREATE TABLE IF NOT EXISTS entity_sightings (
                    identity_key TEXT NOT NULL, map_id INTEGER, x REAL, y REAL,
                    cell_x INTEGER, cell_y INTEGER, phase TEXT, instance_id TEXT,
                    quest_revision TEXT, observed_at REAL NOT NULL, observation_id TEXT,
                    UNIQUE(identity_key, observed_at, observation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_sightings
                    ON entity_sightings(identity_key,map_id,observed_at);
                CREATE INDEX IF NOT EXISTS idx_entity_visuals_signature
                    ON entity_visuals(signature);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(entity_visuals)")}
            if "failure_count" not in columns:
                conn.execute("ALTER TABLE entity_visuals ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0")
            conn.execute("""
                INSERT OR IGNORE INTO entity_location_clusters_v2
                    (identity_key,map_id,phase_key,instance_key,context_key,coordinate_space,
                     cell_x,cell_y,zone,first_seen,last_seen,seen_count,avg_x,avg_y)
                SELECT identity_key,map_id,'','','legacy','NORMALIZED_MAP',cell_x,cell_y,zone,
                       first_seen,last_seen,seen_count,avg_x,avg_y FROM entity_locations
            """)

    @staticmethod
    def identity_key(entity: dict[str, Any]) -> str | None:
        npc_id = entity.get("npc_id")
        unit_type = str(entity.get("unit_type") or "UNKNOWN")
        guid = entity.get("guid")
        if npc_id is not None:
            return f"npc:{int(npc_id)}"
        if guid:
            return f"{unit_type.lower()}:{guid}"
        return None

    def record_mouseover(self, entity: dict[str, Any], *, map_id: int | None,
                         map_x: float | None, map_y: float | None,
                         zone: str | None, observed_at: float | None = None,
                         phase: str | None = None, instance_id: str | None = None,
                         quest_revision: str | None = None, observation_id: str | None = None) -> str | None:
        key = self.identity_key(entity)
        if key is None:
            return None
        now = float(observed_at if observed_at is not None else time.time())
        unit_type = str(entity.get("unit_type") or "UNKNOWN")
        npc_id = int(entity["npc_id"]) if entity.get("npc_id") is not None else None
        name = entity.get("name")
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO entity_profiles(identity_key, unit_type, npc_id, name, first_seen, last_seen, seen_count, last_map_id, last_zone)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(identity_key) DO UPDATE SET
                    unit_type=excluded.unit_type,
                    npc_id=COALESCE(excluded.npc_id, entity_profiles.npc_id),
                    name=COALESCE(excluded.name, entity_profiles.name),
                    last_seen=excluded.last_seen,
                    seen_count=entity_profiles.seen_count + 1,
                    last_map_id=excluded.last_map_id,
                    last_zone=excluded.last_zone
            """, (key, unit_type, npc_id, name, now, now, map_id, zone))

            guid = entity.get("guid")
            if guid:
                conn.execute("""
                    INSERT INTO entity_guids(identity_key, guid, first_seen, last_seen, seen_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(identity_key, guid) DO UPDATE SET
                        last_seen=excluded.last_seen,
                        seen_count=entity_guids.seen_count + 1
                """, (key, str(guid), now, now))

            if map_id is not None and map_x is not None and map_y is not None:
                # 0.02 map-space cells preserve an approximate spawn/encounter
                # area without pretending the observation is an exact spawn point.
                cell_x = math.floor(float(map_x) / 0.02)
                cell_y = math.floor(float(map_y) / 0.02)
                phase_key = str(phase or "")
                instance_key = str(instance_id or "")
                context_key = json.dumps({"phase": phase_key, "instance": instance_key,
                                          "quest_revision": str(quest_revision or "")},
                                         sort_keys=True, separators=(",", ":"))
                row = conn.execute("""
                    SELECT seen_count, avg_x, avg_y FROM entity_location_clusters_v2
                    WHERE identity_key=? AND map_id=? AND phase_key=? AND instance_key=?
                      AND context_key=? AND cell_x=? AND cell_y=?
                """, (key, int(map_id), phase_key, instance_key, context_key, cell_x, cell_y)).fetchone()
                if row:
                    count, avg_x, avg_y = row
                    new_count = int(count) + 1
                    avg_x = (float(avg_x) * int(count) + float(map_x)) / new_count
                    avg_y = (float(avg_y) * int(count) + float(map_y)) / new_count
                    conn.execute("""
                        UPDATE entity_location_clusters_v2
                        SET last_seen=?, seen_count=?, avg_x=?, avg_y=?, zone=?
                        WHERE identity_key=? AND map_id=? AND phase_key=? AND instance_key=?
                          AND context_key=? AND cell_x=? AND cell_y=?
                    """, (now, new_count, avg_x, avg_y, zone, key, int(map_id), phase_key,
                          instance_key, context_key, cell_x, cell_y))
                else:
                    conn.execute("""
                        INSERT INTO entity_location_clusters_v2
                            (identity_key,map_id,phase_key,instance_key,context_key,coordinate_space,
                             cell_x,cell_y,zone,first_seen,last_seen,seen_count,avg_x,avg_y)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)
                    """, (key, int(map_id), phase_key, instance_key, context_key,
                          "NORMALIZED_MAP", cell_x, cell_y, zone, now, now,
                          float(map_x), float(map_y)))
                conn.execute("INSERT OR IGNORE INTO entity_sightings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (key, int(map_id), float(map_x), float(map_y), cell_x, cell_y,
                              phase, instance_id, quest_revision, now, observation_id))
        return key

    def associate_visual(self, identity_key: str, signature: dict[str, Any] | str,
                         observed_at: float | None = None) -> None:
        now = float(observed_at if observed_at is not None else time.time())
        encoded = self._appearance_json(signature)
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO entity_visuals(identity_key, signature, first_seen, last_seen, seen_count, failure_count)
                VALUES (?, ?, ?, ?, 1, 0)
                ON CONFLICT(identity_key, signature) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    seen_count=entity_visuals.seen_count + 1
            """, (identity_key, encoded, now, now))

    def record_visual_outcome(self, identity_key: str, signature: dict[str, Any] | str,
                              correct: bool, observed_at: float | None = None) -> None:
        if correct:
            self.associate_visual(identity_key, signature, observed_at)
            return
        now = float(observed_at if observed_at is not None else time.time())
        encoded = self._appearance_json(signature)
        with self._connect() as conn:
            conn.execute("UPDATE entity_visuals SET failure_count=failure_count+1,last_seen=? "
                         "WHERE identity_key=? AND signature=?", (now, identity_key, encoded))

    @staticmethod
    def _appearance_json(signature: dict[str, Any] | str) -> str:
        if isinstance(signature, str):
            try:
                signature = json.loads(signature)
            except (TypeError, json.JSONDecodeError):
                return signature
        value = dict(signature)
        value.pop("detector_context", None)
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def recognize_visual(self, signature: dict[str, Any] | str, *, min_seen_count: int = 3,
                         as_of: float | None = None, max_age: float | None = None) -> list[dict[str, Any]]:
        """Return supported identity candidates; never a confirmed identity."""
        encoded = self._appearance_json(signature)
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT identity_key, seen_count, failure_count, first_seen, last_seen
                FROM entity_visuals WHERE signature=? AND seen_count>=?
                  AND (? IS NULL OR last_seen>=?-?)
                ORDER BY seen_count DESC, last_seen DESC
            """, (encoded, int(min_seen_count), max_age, as_of, max_age)).fetchall()
            if not rows:
                # A crop signature is deliberately fine-grained, so two
                # independently labelled views of one entity often do not
                # produce the *same* signature three times.  Keep the old
                # three-observation requirement for an individual visual
                # template, but allow a supported *identity memory* to offer
                # a candidate from a high-similarity member view.  This is
                # still recognition evidence, never an identity fact.
                supported_rows = conn.execute("""
                    SELECT identity_key, seen_count, failure_count, first_seen, last_seen, signature
                    FROM entity_visuals WHERE seen_count>=?
                      AND (? IS NULL OR last_seen>=?-?)
                    ORDER BY seen_count DESC, last_seen DESC LIMIT 256
                """, (int(min_seen_count), max_age, as_of, max_age)).fetchall()
                approximate = self._similar_visual_rows(signature, supported_rows)
                rows = conn.execute("""
                    SELECT identity_key, seen_count, failure_count, first_seen, last_seen, signature
                    FROM entity_visuals
                    WHERE (? IS NULL OR last_seen>=?-?)
                    ORDER BY seen_count DESC, last_seen DESC LIMIT 256
                """, (max_age, as_of, max_age)).fetchall()
                # Do not let an older high-count template suppress a newer
                # multi-view identity candidate.  They are independent
                # evidence sources and must compete by score downstream.
                all_approximate = self._similar_visual_rows(signature, rows)
                identity_support: dict[str, tuple[int, int]] = {}
                for row in rows:
                    identity = str(row[0])
                    examples, observations = identity_support.get(identity, (0, 0))
                    identity_support[identity] = (examples + 1, observations + int(row[1]))
                return self._merge_identity_candidates(
                    approximate + self._aggregate_identity_examples(all_approximate, identity_support))
        return [{"identity_key": row[0], "seen_count": row[1], "failure_count": row[2],
                 "reliability": (row[1]+2)/(row[1]+row[2]+4), "first_seen": row[3],
                 "last_seen": row[4], "status": "SUPPORTED", "source": "ENTITY_MEMORY",
                 "match_method": "EXACT_VISUAL_SIGNATURE", "similarity": 1.0}
                for row in rows if (row[1]+2)/(row[1]+row[2]+4) >= .6]

    @staticmethod
    def _similar_visual_rows(signature: dict[str, Any] | str, rows: list[tuple]) -> list[dict[str, Any]]:
        """Tolerant re-identification for complete v2 appearance signatures.

        This is intentionally candidate generation, not confirmation. Minimal
        or legacy signatures are excluded so an arbitrary signature_id cannot
        masquerade as a visually similar observation.
        """
        if isinstance(signature, str):
            try:
                signature = json.loads(signature)
            except (TypeError, json.JSONDecodeError):
                return []
        if not isinstance(signature, dict) or not isinstance(signature.get("shape"), dict) \
                or not isinstance(signature.get("appearance"), dict):
            return []
        result = []
        query_shape, query_app = signature["shape"], signature["appearance"]
        numeric_keys = ("brightness_bin", "saturation_bin", "red_bin", "green_bin", "blue_bin", "fill_bin")
        for row in rows:
            try:
                known = json.loads(row[5])
            except (TypeError, json.JSONDecodeError):
                continue
            if known.get("representation_space") != signature.get("representation_space"):
                continue
            shape, app = known.get("shape"), known.get("appearance")
            if not isinstance(shape, dict) or not isinstance(app, dict):
                continue
            diffs = [abs(float(query_app[key])-float(app[key]))/31.0 for key in numeric_keys
                     if isinstance(query_app.get(key), (int, float)) and isinstance(app.get(key), (int, float))]
            if len(diffs) < 5:
                continue
            appearance_distance = sum(diffs)/len(diffs)
            aspect_distance = abs(float(query_shape.get("aspect", 0))-float(shape.get("aspect", 0)))
            size_distance = (abs(float(query_shape.get("w_bin", 0))-float(shape.get("w_bin", 0))) +
                             abs(float(query_shape.get("h_bin", 0))-float(shape.get("h_bin", 0))))/62.0
            distance = .72*appearance_distance + .18*min(1., aspect_distance) + .10*size_distance
            if distance > .14:
                continue
            similarity = max(0., 1.-distance/.14)
            reliability = (row[1]+2)/(row[1]+row[2]+4)
            if reliability*similarity < .44:
                continue
            result.append({"identity_key": row[0], "seen_count": row[1], "failure_count": row[2],
                           "reliability": reliability, "first_seen": row[3], "last_seen": row[4],
                           "status": "CANDIDATE", "source": "ENTITY_MEMORY",
                           "match_method": "APPROXIMATE_VISUAL_REIDENTIFICATION",
                           "similarity": round(similarity, 4)})
        return sorted(result, key=lambda item: (item["similarity"]*item["reliability"], item["seen_count"]), reverse=True)[:8]

    @staticmethod
    def _aggregate_identity_examples(
            matches: list[dict[str, Any]],
            identity_support: dict[str, tuple[int, int]] | None = None) -> list[dict[str, Any]]:
        """Make a conservative candidate from multiple labelled appearances.

        ``associate_visual`` is only reached after an exact cursor, current
        World3D subject crop and addon GUID agree.  Two such independent
        labelled appearances provide enough support to *suggest* an identity
        when a new crop closely matches either view.  A single labelled crop
        remains insufficient, and this method never returns ``SUPPORTED`` or
        ``CONFIRMED``.
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        for match in matches:
            grouped.setdefault(str(match["identity_key"]), []).append(match)
        candidates = []
        for identity_key, examples in grouped.items():
            # Each stored row is a distinct labelled appearance.  The query
            # need only strongly match one of them: distant/near camera views
            # of the same Murloc can be legitimately dissimilar.  What makes
            # it usable is that the identity has at least two independently
            # cursor/GUID-confirmed stored views.
            matched_example_count = len(examples)
            example_count, total_observations = (identity_support or {}).get(
                identity_key, (matched_example_count,
                               sum(int(example.get("seen_count", 0)) for example in examples)))
            best = max(examples, key=lambda item: (float(item["similarity"]), float(item["reliability"])))
            # This path is an identity suggestion made without a current
            # mouseover label.  Prefer precision decisively: broad .70-ish
            # appearance resemblance in a WoW scene is common across players,
            # NPCs and creature silhouettes.  The live Murloc replay showed
            # that .90 separates the exact learned body cue from those false
            # alternatives.
            if example_count < 2 or float(best["similarity"]) < .90:
                continue
            candidate = dict(best)
            candidate.update({
                "status": "CANDIDATE",
                "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION",
                "independent_example_count": example_count,
                "matched_example_count": matched_example_count,
                "matched_observation_count": total_observations,
                "similarity": round(float(best["similarity"]), 4),
            })
            candidates.append(candidate)
        return sorted(candidates,
                      key=lambda item: (item["similarity"] * item["reliability"],
                                        item["independent_example_count"]),
                      reverse=True)[:8]

    @staticmethod
    def _merge_identity_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Retain the strongest independent visual cue per identity.

        This keeps a durable one-template match and a newer multi-view match
        in the same candidate set without duplicating an identity.  It does
        not turn either candidate into an authoritative identity result.
        """
        def score(item: dict[str, Any]) -> tuple[float, int, int]:
            return (
                float(item.get("similarity", 0.)) * float(item.get("reliability", 0.)),
                int(item.get("independent_example_count", 1)),
                int(item.get("seen_count", 0)),
            )
        merged: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            identity = str(candidate.get("identity_key") or "")
            if identity and (identity not in merged or score(candidate) > score(merged[identity])):
                merged[identity] = candidate
        return sorted(merged.values(), key=score, reverse=True)[:8]

    def find_by_name(self, name: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return addon-confirmed identity candidates for a textual name.

        Exact case-insensitive matches are preferred. Substring matching is a
        fallback only; these results remain hypotheses, never identity facts.
        """
        needle = str(name or "").strip()
        if not needle:
            return []
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT identity_key, unit_type, npc_id, name, seen_count, first_seen, last_seen
                FROM entity_profiles WHERE name IS NOT NULL AND LOWER(name)=LOWER(?)
                ORDER BY seen_count DESC, last_seen DESC LIMIT ?
            """, (needle, int(limit))).fetchall()
            if not rows:
                rows = conn.execute("""
                    SELECT identity_key, unit_type, npc_id, name, seen_count, first_seen, last_seen
                    FROM entity_profiles WHERE name IS NOT NULL AND LOWER(name) LIKE '%'||LOWER(?)||'%'
                    ORDER BY seen_count DESC, last_seen DESC LIMIT ?
                """, (needle, int(limit))).fetchall()
        return [{"identity_key": row[0], "unit_type": row[1], "npc_id": row[2], "name": row[3],
                 "seen_count": row[4], "first_seen": row[5], "last_seen": row[6]}
                for row in rows]

    def get_profile(self, identity_key: str) -> EntityMemoryProfile | None:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT identity_key, unit_type, npc_id, name, first_seen, last_seen, seen_count, last_map_id, last_zone
                FROM entity_profiles WHERE identity_key=?
            """, (identity_key,)).fetchone()
        return EntityMemoryProfile(*row) if row else None

    def locations(self, identity_key: str, limit: int = 20, *, as_of: float | None = None,
                  max_age: float | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT map_id, avg_x, avg_y, zone, seen_count, first_seen, last_seen,
                       phase_key, instance_key, context_key, coordinate_space, cell_x, cell_y
                FROM entity_location_clusters_v2 WHERE identity_key=? AND (? IS NULL OR last_seen>=?-?)
                ORDER BY seen_count DESC, last_seen DESC LIMIT ?
            """, (identity_key, max_age, as_of, max_age, int(limit))).fetchall()
        return [
            {"map_id": r[0], "x": r[1], "y": r[2], "zone": r[3], "seen_count": r[4],
             "first_seen": r[5], "last_seen": r[6], "phase": r[7] or None,
             "instance_id": r[8] or None, "context": r[9], "coordinate_space": r[10],
             "cell_x": r[11], "cell_y": r[12]}
            for r in rows
        ]

    def visual_observations(self, identity_key: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT signature, first_seen, last_seen, seen_count, failure_count
                FROM entity_visuals WHERE identity_key=?
                ORDER BY seen_count DESC, last_seen DESC LIMIT ?
            """, (identity_key, int(limit))).fetchall()
        return [
            {"signature": r[0], "first_seen": r[1], "last_seen": r[2], "seen_count": r[3],
             "failure_count": r[4], "reliability": (r[3]+2)/(r[3]+r[4]+4)}
            for r in rows
        ]

    def summary(self, identity_key: str) -> dict[str, Any] | None:
        profile = self.get_profile(identity_key)
        if profile is None:
            return None
        return {
            "identity_key": profile.identity_key,
            "unit_type": profile.unit_type,
            "npc_id": profile.npc_id,
            "name": profile.name,
            "first_seen": profile.first_seen,
            "last_seen": profile.last_seen,
            "seen_count": profile.seen_count,
            "last_map_id": profile.last_map_id,
            "last_zone": profile.last_zone,
            "known_locations": self.locations(identity_key),
            "visual_observations": self.visual_observations(identity_key),
            "behavior": self.behavior(identity_key),
        }

    def behavior(self, identity_key: str, *, as_of: float | None = None,
                 max_age: float | None = None) -> dict[str, Any]:
        query = "SELECT map_id,x,y,cell_x,cell_y,phase,instance_id,quest_revision,observed_at FROM entity_sightings WHERE identity_key=?"
        args: list[Any] = [identity_key]
        if max_age is not None:
            query += " AND observed_at>=?"
            args.append(float(as_of if as_of is not None else time.time())-float(max_age))
        query += " ORDER BY observed_at"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        cells = [(row[0], row[3], row[4]) for row in rows]
        unique = list(dict.fromkeys(cells))
        transitions = sum(a != b for a, b in zip(cells, cells[1:]))
        if len(rows) < 3:
            kind, status, confidence = "UNKNOWN", "EPISODIC", (len(rows)+1)/5
        elif len(unique) == 1:
            kind, status, confidence = "STATIONARY", "SUPPORTED", min(.95, .55+.05*len(rows))
        else:
            kind = "PATROL_HYPOTHESIS"
            status = "SUPPORTED" if len(rows) >= 5 and transitions >= 2 else "HYPOTHESIS"
            confidence = min(.9, .4+.05*len(rows)+.05*min(3, transitions))
        xs, ys = [row[1] for row in rows], [row[2] for row in rows]
        return {"identity_key": identity_key, "behavior": kind, "status": status,
                "confidence": confidence, "samples": len(rows), "transitions": transitions,
                "route_cells": unique, "spawn_region": ({"map_id": rows[-1][0],
                    "min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)} if rows else None),
                "phases": sorted({str(row[5]) for row in rows if row[5] is not None}),
                "instances": sorted({str(row[6]) for row in rows if row[6] is not None}),
                "quest_revisions": sorted({str(row[7]) for row in rows if row[7] is not None})}
