"""Durable episode lifecycle owner backed by the shared memory transaction."""
from __future__ import annotations

import hashlib
import json

from .models import canonical


class EpisodeMemory:
    """Own episode/step CRUD; learning promotion remains an explicit callback."""

    def __init__(self, transaction, *, promote=None) -> None:
        self._transaction = transaction
        self._promote = promote

    def start(self, goal, session: str, state: dict, at: float) -> str:
        episode_id = hashlib.sha256(canonical({
            "goal": goal.goal_id, "session": session, "at": at}).encode()).hexdigest()[:24]
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO episodes VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (episode_id, goal.goal_id, session, goal.domain, at, None, "ACTIVE",
                        canonical(state), None, None))
        return episode_id

    def record_step(self, episode_id: str | None, at: float, kind: str, payload: dict) -> None:
        if not episode_id:
            return
        with self._transaction() as db:
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM episode_steps WHERE episode_id=?",
                (episode_id,)).fetchone()[0]
            db.execute("INSERT INTO episode_steps VALUES (?,?,?,?,?)",
                       (episode_id, sequence, at, kind, canonical(payload)))

    def finish(self, episode_id: str | None, state: dict, at: float,
               status: str, result: dict) -> None:
        if not episode_id:
            return
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE episodes SET ended_at=?,status=?,final_state=?,result=? WHERE id=? AND status='ACTIVE'",
                (at, status, canonical(state), canonical(result), episode_id))
        if cursor.rowcount and status == "SUCCESS" and self._promote is not None:
            self._promote(episode_id)

    def get(self, episode_id: str) -> dict | None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT goal_id,session,domain,started_at,ended_at,status,initial_state,final_state,result "
                "FROM episodes WHERE id=?", (episode_id,)).fetchone()
            steps = db.execute(
                "SELECT sequence,at,kind,payload FROM episode_steps WHERE episode_id=? ORDER BY sequence",
                (episode_id,)).fetchall()
        if not row:
            return None
        return {"episode_id": episode_id, "goal_id": row[0], "session": row[1],
                "domain": row[2], "started_at": row[3], "ended_at": row[4],
                "status": row[5], "initial_state": json.loads(row[6]),
                "final_state": json.loads(row[7]) if row[7] else None,
                "result": json.loads(row[8]) if row[8] else None,
                "steps": [{"sequence": step[0], "at": step[1], "kind": step[2],
                           "payload": json.loads(step[3])} for step in steps]}
