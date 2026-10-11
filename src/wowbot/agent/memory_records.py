"""AgentMemory event, goal, world-relation and semantic-fact records.

Split out of memory.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import hashlib
import json
import time
from .models import canonical


class MemoryRecordsMixin:
    """Methods of AgentMemory (memory.py); moved verbatim."""

    def save_event_record(self, event) -> None:
        """Persist addon and derived WorldModel events through one schema."""
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", (
                event.event_id, event.session_id, event.received_at, event.event_type, event.source,
                event.observation_id, canonical(event.entity_ids), canonical(event.quest_ids),
                canonical(event.marker_ids), event.payload_json))

    def record(self, session: str, at: float, kind: str, payload: dict):
        with self._tx() as db:
            db.execute("INSERT INTO journal(session,at,kind,payload) VALUES (?,?,?,?)", (session, at, kind, canonical(payload)))

    def save_goal(self, goal):
        from dataclasses import asdict
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO goals VALUES (?,?)", (goal.goal_id, canonical(asdict(goal))))

    def latest_active_goal(self):
        from .models import Goal
        with self._ro() as db:
            rows = db.execute("SELECT payload FROM goals").fetchall()
        values = [json.loads(row[0]) for row in rows]
        active = [value for value in values if value.get("status") in {"ACTIVE", "RECOVERING"}]
        return Goal(**max(active, key=lambda value: value.get("created_at", 0))) if active else None

    def save_goal_task(self, task: dict):
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO goal_tasks VALUES (?,?,?,?,?,?)",
                       (task["task_id"], task["goal_id"], task["status"], task["score"],
                        task["updated_at"], canonical(task)))

    def goal_tasks(self, goal_id: str) -> list[dict]:
        with self._ro() as db:
            rows = db.execute("SELECT payload FROM goal_tasks WHERE goal_id=? ORDER BY score DESC,id",
                              (goal_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_world_relation(self, session: str, relation: dict):
        self._relation_buffer[(session, relation["relation_id"])] = (session, dict(relation))

    def flush_world_relations(self, *, force: bool = True) -> int:
        if not self._relation_buffer:
            return 0
        if (not force and self.relation_flush_interval_seconds > 0
                and time.monotonic()-self._last_relation_flush_at < self.relation_flush_interval_seconds):
            return 0
        self._last_relation_flush_at = time.monotonic()
        rows = list(self._relation_buffer.values())
        self._relation_buffer.clear()
        if self._writer_thread is not None:
            self._enqueue_write("relations", rows)
            return len(rows)
        with self._tx() as db:
            self._insert_relations(db, rows)
        return len(rows)

    @staticmethod
    def _insert_relations(db, rows) -> None:
        db.executemany(
            "INSERT OR REPLACE INTO world_relations VALUES (?,?,?,?,?,?,?)",
            [(session, relation["relation_id"], relation["subject"],
              relation["predicate"], relation["object"], relation["at"],
              canonical(relation)) for session, relation in rows])

    def world_relations(self, session: str) -> list[dict]:
        self.flush_world_relations()
        self._drain_for_read("world_relations")
        with self._ro() as db:
            rows = db.execute("SELECT payload FROM world_relations WHERE session=? ORDER BY at,id",
                              (session,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_semantic_fact(self, subject: str, predicate: str, value, context: dict,
                             source: str, at: float, provenance: dict):
        encoded_context, encoded_value = canonical(context), canonical(value)
        fact_key = hashlib.sha256(f"{subject}:{predicate}:{encoded_value}:{encoded_context}".encode()).hexdigest()[:24]
        with self._tx() as db:
            # A different explicit value in the exact same context is a
            # counterexample, not silent replacement.
            db.execute("UPDATE semantic_facts SET failures=failures+1,last_seen=? "
                       "WHERE subject=? AND predicate=? AND context=? AND value<>?",
                       (at, subject, predicate, encoded_context, encoded_value))
            db.execute("""INSERT INTO semantic_facts VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fact_key) DO UPDATE SET successes=successes+1,last_seen=excluded.last_seen,
                source=excluded.source,provenance=excluded.provenance""",
                (fact_key, subject, predicate, encoded_value, encoded_context, source,
                 1, 0, at, at, canonical(provenance)))

    def semantic_facts(self, *, subject: str | None = None, predicate: str | None = None,
                       context: dict | None = None, supported_only=False) -> list[dict]:
        clauses, args = [], []
        for column, value in (("subject", subject), ("predicate", predicate),
                              ("context", canonical(context) if context is not None else None)):
            if value is not None:
                clauses.append(f"{column}=?"); args.append(value)
        query = "SELECT fact_key,subject,predicate,value,context,source,successes,failures,first_seen,last_seen,provenance FROM semantic_facts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY last_seen DESC,fact_key"
        with self._ro() as db:
            rows = db.execute(query, args).fetchall()
        result = []
        for row in rows:
            reliability = (row[6]+2)/(row[6]+row[7]+4)
            stage = "SUPPORTED" if row[6] >= 3 and reliability >= .65 else "REPEATED" if row[6]+row[7] >= 2 else "EPISODIC"
            if supported_only and stage != "SUPPORTED":
                continue
            result.append({"fact_key": row[0], "subject": row[1], "predicate": row[2],
                           "value": json.loads(row[3]), "context": json.loads(row[4]),
                           "source": row[5], "successes": row[6], "failures": row[7],
                           "reliability": reliability, "stage": stage, "first_seen": row[8],
                           "last_seen": row[9], "provenance": json.loads(row[10])})
        return result
