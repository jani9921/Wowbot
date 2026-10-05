"""AgentMemory task episodes, verified task patterns and resource sites.

Split out of memory.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import hashlib
import json
from .models import canonical


class MemoryPatternsMixin:
    """Methods of AgentMemory (memory.py); moved verbatim."""

    def start_episode(self, goal, session: str, state: dict, at: float) -> str:
        return self.episode_memory.start(goal, session, state, at)

    def record_episode_step(self, episode_id: str | None, at: float, kind: str, payload: dict):
        self.episode_memory.record_step(episode_id, at, kind, payload)

    def finish_episode(self, episode_id: str | None, state: dict, at: float, status: str, result: dict):
        self.episode_memory.finish(episode_id, state, at, status, result)

    def episode(self, episode_id: str) -> dict | None:
        return self.episode_memory.get(episode_id)

    def _promote_episode_pattern(self, episode_id: str):
        episode = self.episode(episode_id)
        if not episode or episode["status"] != "SUCCESS":
            return
        verified = [step["payload"] for step in episode["steps"]
                    if step["kind"] == "VERIFICATION" and step["payload"].get("outcome") == "SUCCESS"]
        skills = [str(step.get("skill") or "UNKNOWN") for step in verified]
        if not skills:
            return
        context = self.learning_context(episode["initial_state"], episode["domain"])
        _, version = self._context_keys(context)
        signature = hashlib.sha256(canonical(skills).encode()).hexdigest()[:24]
        pattern_id = hashlib.sha256(f"{episode['domain']}:{version}:{signature}".encode()).hexdigest()[:24]
        cost = max(0., (episode["ended_at"] or episode["started_at"])-episode["started_at"])
        context_key = canonical(context)
        provenance = {"episode_ids": [episode_id], "context_keys": [context_key]}
        with self._tx() as db:
            existing = db.execute("SELECT successes,failures,mean_cost,provenance,first_seen FROM task_patterns "
                                  "WHERE domain=? AND version=? AND signature=?",
                                  (episode["domain"], version, signature)).fetchone()
            successes, failures = ((existing[0], existing[1]) if existing else (0, 0))
            successes += 1
            mean_cost = ((existing[2]*max(0, successes-1)+cost)/successes) if existing else cost
            if existing:
                previous = json.loads(existing[3]); provenance["episode_ids"] = (previous.get("episode_ids", [])+[episode_id])[-20:]
                provenance["context_keys"] = list(dict.fromkeys(previous.get("context_keys", [])+[context_key]))[-20:]
            confidence = (successes+2)/(successes+failures+4)
            stage = "GENERALIZED" if successes >= 5 and len(provenance["context_keys"]) >= 3 else "SUPPORTED" if successes >= 3 else "REPEATED" if successes >= 2 else "EPISODIC"
            values = (pattern_id, episode["domain"], version, signature,
                      canonical({key: context.get(key) for key in ("map_id", "game_build", "addon_version", "ui_scale", "width", "height")}),
                      canonical(skills), canonical([step.get("expected") for step in verified]),
                      canonical({"episode_status": "SUCCESS"}), canonical({"episode_status": "FAILURE"}),
                      mean_cost, successes, failures, confidence, stage, canonical(provenance),
                      existing[4] if existing else episode["started_at"], episode["ended_at"])
            db.execute("INSERT OR REPLACE INTO task_patterns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)

    def task_patterns(self, domain: str | None = None) -> list[dict]:
        query = "SELECT id,domain,version,signature,preconditions,steps,expected,success,failure,mean_cost,successes,failures,confidence,stage,provenance,first_seen,last_seen FROM task_patterns"
        args = ()
        if domain:
            query += " WHERE domain=?"; args = (domain,)
        query += " ORDER BY confidence DESC,successes DESC"
        with self._ro() as db:
            rows = db.execute(query, args).fetchall()
        keys = ("id", "domain", "version", "signature", "preconditions", "steps", "expected",
                "success", "failure", "mean_cost", "successes", "failures", "confidence", "stage",
                "provenance", "first_seen", "last_seen")
        json_fields = {"preconditions", "steps", "expected", "success", "failure", "provenance"}
        return [{key: json.loads(value) if key in json_fields else value for key, value in zip(keys, row)}
                for row in rows]

    def find_similar_task_patterns(self, domain: str, candidate_skills: list[str], state: dict,
                                   limit: int = 5) -> dict:
        patterns = [item for item in self.task_patterns(domain)
                    if item["stage"] in {"SUPPORTED", "GENERALIZED"}]
        wanted = [str(item) for item in candidate_skills]
        wanted_set = set(wanted)
        scored = []
        for pattern in patterns:
            known = [str(item) for item in pattern["steps"]]
            known_set = set(known)
            union = wanted_set | known_set
            jaccard = len(wanted_set & known_set)/len(union) if union else 1.
            positions = [known.index(item) for item in wanted if item in known]
            ordered = (1. if len(positions) == 1 else
                       sum(a <= b for a, b in zip(positions, positions[1:]))/(len(positions)-1)) if positions else 0.
            preconditions = pattern["preconditions"]
            map_match = preconditions.get("map_id") == state.get("map_id")
            similarity = min(1., .65*jaccard + .25*ordered + (.1 if map_match else 0.))
            scored.append({**pattern, "similarity": round(similarity, 5), "map_match": map_match})
        scored.sort(key=lambda item: (-item["similarity"], -item["confidence"], item["id"]))
        best = scored[0]["similarity"] if scored else None
        return {"mode": "NO_REFERENCE" if best is None else "EXPLORATION" if best < .3 else "REUSE_CANDIDATE",
                "novelty": None if best is None else round(1-best, 5), "matches": scored[:limit]}

    def record_resource_site(self, state: dict, resource_type: str, location: dict, success: bool,
                             at: float, provenance: dict):
        map_id = location.get("map_id", state.get("map_id"))
        try:
            x, y = float(location["x"]), float(location["y"])
        except (KeyError, TypeError, ValueError):
            return
        if map_id is None or not 0 <= x <= 1 or not 0 <= y <= 1:
            return
        _, version = self._context_keys(self.learning_context(state, "RESOURCE"))
        kind = str(resource_type or "UNKNOWN").upper()
        site_key = hashlib.sha256(f"{map_id}:{kind}:{version}:{x:.4f}:{y:.4f}".encode()).hexdigest()[:24]
        with self._tx() as db:
            db.execute("""INSERT INTO resource_sites VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(site_key) DO UPDATE SET successes=successes+excluded.successes,
                failures=failures+excluded.failures,last_seen=excluded.last_seen,
                provenance=excluded.provenance""",
                (site_key, str(map_id), kind, version, x, y, int(success), int(not success),
                 at, at, canonical(provenance)))

    def resource_sites(self, state: dict, resource_type: str, supported_only=True) -> list[dict]:
        map_id = state.get("map_id")
        _, version = self._context_keys(self.learning_context(state, "RESOURCE"))
        kind = str(resource_type or "UNKNOWN").upper()
        with self._ro() as db:
            rows = db.execute("SELECT site_key,x,y,successes,failures,first_seen,last_seen,provenance "
                              "FROM resource_sites WHERE map_id=? AND resource_type=? AND version=?",
                              (str(map_id), kind, version)).fetchall()
        result = []
        for row in rows:
            reliability = (row[3]+2)/(row[3]+row[4]+4)
            stage = "SUPPORTED" if row[3] >= 3 and reliability >= .65 else "REPEATED" if row[3]+row[4] >= 2 else "EPISODIC"
            if supported_only and stage != "SUPPORTED":
                continue
            result.append({"site_key": row[0], "map_id": map_id, "x": row[1], "y": row[2],
                           "resource_type": kind, "successes": row[3], "failures": row[4],
                           "reliability": reliability, "stage": stage, "first_seen": row[5],
                           "last_seen": row[6], "provenance": json.loads(row[7])})
        return sorted(result, key=lambda item: (-item["reliability"], -item["last_seen"]))
