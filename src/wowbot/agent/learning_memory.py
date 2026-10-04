"""Durable procedure and sensor reliability learning on the shared store."""
from __future__ import annotations

import hashlib
import json
import time

from .models import canonical


class LearningMemory:
    """Own empirical trials; never represents current world truth."""

    def __init__(self, transaction, reader) -> None:
        self._tx, self._ro = transaction, reader
        self._sensor_cache: dict = {}
        self._procedure_cache: dict = {}

    @staticmethod
    def context_keys(context: dict) -> tuple[str, str]:
        encoded = canonical(context)
        version = canonical({key: context.get(key) for key in
                             ("game_build", "addon_version", "ui_scale", "width", "height")})
        return encoded, hashlib.sha256(version.encode()).hexdigest()[:16]

    def record_procedure(self, context: dict, skill: str, success: bool, *, cost: float,
                         at: float, reason: str, provenance: dict) -> None:
        encoded, version = self.context_keys(context)
        category = {"MOVE": "movement", "RECOVER": "recovery", "COMBAT": "combat",
                    "DEFEND": "combat", "ESCAPE": "combat", "INSPECT": "observation",
                    "OPEN_MAP": "observation", "CLOSE_MAP": "observation",
                    "INTERACT": "interaction", "TALK": "interaction", "USE": "interaction",
                    "OBJECT_USE": "interaction", "QUEST_DIALOG": "quest", "LOOT": "interaction",
                    "GATHER": "interaction", "HERB": "interaction", "MINE": "interaction",
                    "FISH": "interaction"}.get(skill, "general")
        prov = canonical(provenance)
        with self._tx() as db:
            db.execute("""INSERT INTO procedural_strategies
                (context,domain,category,skill,version,successes,failures,total_cost,first_seen,last_seen,provenance)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(context,skill,version) DO UPDATE SET
                successes=successes+excluded.successes, failures=failures+excluded.failures,
                total_cost=total_cost+excluded.total_cost, last_seen=excluded.last_seen,
                provenance=excluded.provenance""",
                (encoded, context.get("domain"), category, skill, version, int(success), int(not success),
                 float(cost), at, at, prov))
            db.execute("INSERT INTO procedure_trials(context,domain,skill,version,at,success,cost,reason,provenance) VALUES (?,?,?,?,?,?,?,?,?)",
                       (encoded, context.get("domain"), skill, version, at, int(success), float(cost), reason, prov))
        self._procedure_cache.clear()

    def procedure_profile(self, context: dict, skill: str) -> dict:
        encoded, version = self.context_keys(context)
        cache_key = encoded, skill, version
        cached = self._procedure_cache.get(cache_key)
        if cached and time.monotonic()-cached[0] < 2.:
            return dict(cached[1])
        with self._ro() as db:
            row = db.execute("SELECT successes,failures,total_cost,first_seen,last_seen,category,provenance FROM procedural_strategies WHERE context=? AND skill=? AND version=?",
                             (encoded, skill, version)).fetchone()
            recent = db.execute("SELECT success FROM procedure_trials WHERE context=? AND skill=? AND version=? ORDER BY at DESC,id DESC LIMIT 20",
                                (encoded, skill, version)).fetchall()
            aggregate = db.execute("SELECT COALESCE(SUM(successes),0),COALESCE(SUM(failures),0),COUNT(DISTINCT context) FROM procedural_strategies WHERE domain=? AND skill=? AND version=?",
                                   (context.get("domain"), skill, version)).fetchone()
        successes, failures, total_cost, first_seen, last_seen, category, provenance = row or (0, 0, 0., None, None, "general", "{}")
        historical = (successes+2)/(successes+failures+4)
        recent_precision = (sum(value[0] for value in recent)+2)/(len(recent)+4)
        all_success, all_failure, contexts = aggregate
        aggregate_precision = (all_success+2)/(all_success+all_failure+4)
        trials = successes+failures
        stage = ("HIGH_CONFIDENCE" if trials >= 20 and historical >= .9 and recent_precision >= .85 and contexts >= 3
                 else "GENERALIZED" if all_success+all_failure >= 12 and contexts >= 3 and aggregate_precision >= .75
                 else "SUPPORTED" if trials >= 5 and historical >= .65
                 else "REPEATED" if trials >= 3 else "EPISODIC")
        result = {"skill": skill, "category": category, "stage": stage, "successes": successes,
                  "failures": failures, "historical_reliability": historical,
                  "recent_reliability": recent_precision, "aggregate_reliability": aggregate_precision,
                  "contexts": contexts, "mean_cost": total_cost/max(1, trials), "first_seen": first_seen,
                  "last_seen": last_seen, "version": version, "provenance": json.loads(provenance)}
        self._procedure_cache[cache_key] = time.monotonic(), result
        return dict(result)

    def record_sensor(self, source: str, detector: str, context: dict, *, correct: bool,
                      at: float, latency: float | None, error: str, provenance: dict,
                      predicted_label: str | None = None, actual_label: str | None = None) -> None:
        encoded, _ = self.context_keys(context)
        predicted = str(predicted_label).upper() if predicted_label else None
        actual = str(actual_label).upper() if actual_label else None
        with self._tx() as db:
            db.execute("INSERT INTO sensor_trials(source,detector,context,at,correct,latency,error,provenance,predicted_label,actual_label) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (source, detector, encoded, at, int(correct), latency, error,
                        canonical(provenance), predicted, actual))
        self._sensor_cache.clear()

    @staticmethod
    def _classification(rows, detector: str):
        labelled = [row for row in rows if row[3] and row[4]]; confusion = {}
        for row in labelled:
            predicted, actual = str(row[3]).upper(), str(row[4]).upper()
            confusion.setdefault(actual, {})[predicted] = confusion.setdefault(actual, {}).get(predicted, 0)+1
        if not labelled or detector == "*":
            return None, None, confusion, len(labelled)
        expected = str(detector).upper()
        tp = sum(1 for row in labelled if str(row[3]).upper() == expected and str(row[4]).upper() == expected)
        fp = sum(1 for row in labelled if str(row[3]).upper() == expected and str(row[4]).upper() != expected)
        fn = sum(1 for row in labelled if str(row[3]).upper() != expected and str(row[4]).upper() == expected)
        return (tp+1)/(tp+fp+2), (tp+1)/(tp+fn+2), confusion, len(labelled)

    def sensor_profile(self, source: str, detector: str, context: dict) -> dict:
        encoded, version = self.context_keys(context); cache_key = source, detector, encoded
        cached = self._sensor_cache.get(cache_key)
        if cached and time.monotonic()-cached[0] < 2.:
            return dict(cached[1])
        with self._ro() as db:
            historical = db.execute("SELECT correct,latency,error,predicted_label,actual_label,at FROM sensor_trials WHERE source=? AND detector=? AND context=? ORDER BY at",
                                    (source, detector, encoded)).fetchall()
        recent = historical[-20:]; total = len(historical)
        accuracy = (sum(row[0] for row in historical)+2)/(total+4)
        recent_accuracy = (sum(row[0] for row in recent)+2)/(len(recent)+4)
        precision, recall, confusion, labelled = self._classification(historical, detector)
        recent_precision, recent_recall, recent_confusion, _ = self._classification(recent, detector)
        hp, rp = precision if precision is not None else accuracy, recent_precision if recent_precision is not None else recent_accuracy
        hr, rr = recall if recall is not None else hp, recent_recall if recent_recall is not None else rp
        latencies = [row[1] for row in recent if row[1] is not None]
        drift = total >= 8 and (hp-rp >= .10 or hr-rr >= .10)
        weight = max(.15, min(1., .25*(hp+hr+rp+rr)))
        health = "DEGRADED" if drift or len(recent) >= 5 and min(rp, rr) < .45 else "LEARNING" if total < 5 else "HEALTHY"
        result = {"source": source, "detector": detector, "context_version": version,
                  "samples": total, "labelled_samples": labelled, "historical_accuracy": accuracy,
                  "recent_accuracy": recent_accuracy, "historical_precision": hp,
                  "recent_precision": rp, "historical_recall": hr, "recent_recall": rr,
                  "confusion_matrix": confusion, "recent_confusion_matrix": recent_confusion,
                  "weight": weight, "drift": drift, "health": health,
                  "latency": sum(latencies)/len(latencies) if latencies else None,
                  "error_rate": sum(bool(row[2]) for row in recent)/max(1, len(recent)),
                  "availability": total > 0, "last_sample_at": historical[-1][5] if historical else None}
        self._sensor_cache[cache_key] = time.monotonic(), result
        return dict(result)

    def sensor_health(self, state: dict, context_factory) -> list[dict]:
        context = context_factory(state, "SENSOR"); encoded, _ = self.context_keys(context)
        with self._ro() as db:
            pairs = db.execute("SELECT DISTINCT source,detector FROM sensor_trials WHERE context=?", (encoded,)).fetchall()
        return [self.sensor_profile(source, detector, context) for source, detector in pairs]

    def expire(self, now: float, *, max_trials: int = 20_000) -> int:
        removed = 0
        with self._tx() as db:
            for table in ("procedure_trials", "sensor_trials"):
                count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                excess = max(0, count-max_trials)
                if excess:
                    removed += db.execute(f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} ORDER BY id LIMIT ?)", (excess,)).rowcount
        self._sensor_cache.clear(); self._procedure_cache.clear()
        return int(removed)

    def consolidate(self, now: float) -> int:
        return self.expire(now)

    def reliability(self, source: str, detector: str, context: dict) -> float | None:
        profile = self.sensor_profile(source, detector, context)
        return float(profile["weight"]) if profile["samples"] else None
