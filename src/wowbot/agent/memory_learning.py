"""AgentMemory learning statistics: strategy reliability, procedures, sensors, action timing.

Split out of memory.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import hashlib
import json
import time
from .models import canonical


class MemoryLearningMixin:
    """Methods of AgentMemory (memory.py); moved verbatim."""

    def learn(self, context: str, skill: str, success: bool):
        with self._tx() as db:
            db.execute('''INSERT INTO strategies VALUES (?,?,?,?) ON CONFLICT(context,skill) DO UPDATE SET
                successes=successes+excluded.successes, failures=failures+excluded.failures''',
                       (context, skill, int(success), int(not success)))

    def reliability(self, context: str, skill: str) -> tuple[float, str]:
        with self._ro() as db:
            row = db.execute("SELECT successes,failures FROM strategies WHERE context=? AND skill=?", (context, skill)).fetchone()
        successes, failures = row or (0, 0)
        value = (successes + 2) / (successes + failures + 4)
        stage = "LEARNED" if successes >= 5 and value >= .75 else "SUPPORTED" if successes >= 3 else "EPISODIC"
        return value, stage

    @staticmethod
    def learning_context(state: dict, domain: str) -> dict:
        dimensions = state.get("client_dimensions") or state.get("capture_dimensions") or {}
        return {"domain": domain, "map_id": state.get("map_id"), "game_build": state.get("game_build"),
                "addon_version": state.get("addon_version"), "ui_scale": state.get("ui_scale"),
                "width": dimensions.get("width"), "height": dimensions.get("height")}

    @staticmethod
    def _context_keys(context: dict) -> tuple[str, str]:
        encoded = canonical(context)
        version = canonical({key: context.get(key) for key in
                             ("game_build", "addon_version", "ui_scale", "width", "height")})
        return encoded, hashlib.sha256(version.encode()).hexdigest()[:16]

    def learn_procedure(self, context: dict, skill: str, success: bool, *, cost: float,
                        at: float, reason: str, provenance: dict):
        return self.learning_memory.record_procedure(
            context, skill, success, cost=cost, at=at, reason=reason, provenance=provenance)
        encoded, version = self._context_keys(context)
        category = {"MOVE": "movement", "RECOVER": "recovery", "COMBAT": "combat",
                    "DEFEND": "combat", "ESCAPE": "combat",
                    "INSPECT": "observation", "OPEN_MAP": "observation", "CLOSE_MAP": "observation",
                    "INTERACT": "interaction", "TALK": "interaction", "USE": "interaction", "OBJECT_USE": "interaction",
                    "QUEST_DIALOG": "quest", "LOOT": "interaction", "GATHER": "interaction",
                    "HERB": "interaction", "MINE": "interaction", "FISH": "interaction"}.get(skill, "general")
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
        self._procedure_profile_cache.clear()

    def procedure_profile(self, context: dict, skill: str) -> dict:
        return self.learning_memory.procedure_profile(context, skill)
        encoded, version = self._context_keys(context)
        cache_key = encoded, skill, version
        cached = self._procedure_profile_cache.get(cache_key)
        if cached and time.monotonic()-cached[0] < 2.0:
            return dict(cached[1])
        with self._ro() as db:
            row = db.execute("SELECT successes,failures,total_cost,first_seen,last_seen,category,provenance "
                             "FROM procedural_strategies WHERE context=? AND skill=? AND version=?",
                             (encoded, skill, version)).fetchone()
            recent = db.execute("SELECT success FROM procedure_trials WHERE context=? AND skill=? AND version=? "
                                "ORDER BY at DESC,id DESC LIMIT 20", (encoded, skill, version)).fetchall()
            aggregate = db.execute("SELECT COALESCE(SUM(successes),0),COALESCE(SUM(failures),0),COUNT(DISTINCT context) "
                                   "FROM procedural_strategies WHERE domain=? AND skill=? AND version=?",
                                   (context.get("domain"), skill, version)).fetchone()
        successes, failures, total_cost, first_seen, last_seen, category, provenance = row or (0, 0, 0., None, None, "general", "{}")
        historical = (successes + 2) / (successes + failures + 4)
        recent_successes = sum(value[0] for value in recent)
        recent_precision = (recent_successes + 2) / (len(recent) + 4)
        all_success, all_failure, contexts = aggregate
        aggregate_precision = (all_success + 2) / (all_success + all_failure + 4)
        trials = successes + failures
        if trials >= 20 and historical >= .9 and recent_precision >= .85 and contexts >= 3:
            stage = "HIGH_CONFIDENCE"
        elif all_success + all_failure >= 12 and contexts >= 3 and aggregate_precision >= .75:
            stage = "GENERALIZED"
        elif trials >= 5 and historical >= .65:
            stage = "SUPPORTED"
        elif trials >= 3:
            stage = "REPEATED"
        else:
            stage = "EPISODIC"
        result = {"skill": skill, "category": category, "stage": stage, "successes": successes,
                "failures": failures, "historical_reliability": historical,
                "recent_reliability": recent_precision, "aggregate_reliability": aggregate_precision,
                "contexts": contexts, "mean_cost": total_cost/max(1, trials), "first_seen": first_seen,
                "last_seen": last_seen, "version": version, "provenance": json.loads(provenance)}
        self._procedure_profile_cache[cache_key] = time.monotonic(), result
        return dict(result)

    def record_sensor_outcome(self, source: str, detector: str, context: dict, *, correct: bool,
                              at: float, latency: float | None, error: str, provenance: dict,
                              predicted_label: str | None = None,
                              actual_label: str | None = None):
        return self.learning_memory.record_sensor(
            source, detector, context, correct=correct, at=at, latency=latency, error=error,
            provenance=provenance, predicted_label=predicted_label, actual_label=actual_label)
        encoded, _ = self._context_keys(context)
        predicted = str(predicted_label).upper() if predicted_label else None
        actual = str(actual_label).upper() if actual_label else None
        with self._tx() as db:
            db.execute("INSERT INTO sensor_trials(source,detector,context,at,correct,latency,error,provenance,predicted_label,actual_label) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (source, detector, encoded, at, int(correct), latency, error,
                        canonical(provenance), predicted, actual))
        self._sensor_profile_cache.clear()

    def sensor_profile(self, source: str, detector: str, context: dict) -> dict:
        return self.learning_memory.sensor_profile(source, detector, context)
        encoded, version = self._context_keys(context)
        cache_key = source, detector, encoded
        cached = self._sensor_profile_cache.get(cache_key)
        if cached and time.monotonic()-cached[0] < 2.0:
            return dict(cached[1])
        with self._ro() as db:
            historical = db.execute("SELECT correct,latency,error,predicted_label,actual_label,at FROM sensor_trials WHERE source=? AND detector=? AND context=? ORDER BY at",
                                    (source, detector, encoded)).fetchall()
            recent = historical[-20:]
        total = len(historical); correct = sum(row[0] for row in historical)
        recent_correct = sum(row[0] for row in recent)
        accuracy = (correct + 2) / (total + 4)
        recent_accuracy = (recent_correct + 2) / (len(recent) + 4)
        expected_label = str(detector).upper()

        def classification_metrics(rows):
            labelled = [row for row in rows if row[3] and row[4]]
            confusion = {}
            for row in labelled:
                predicted, actual = str(row[3]).upper(), str(row[4]).upper()
                confusion.setdefault(actual, {})[predicted] = confusion.setdefault(actual, {}).get(predicted, 0) + 1
            if not labelled or detector == "*":
                return None, None, confusion, len(labelled)
            tp = sum(1 for row in labelled if str(row[3]).upper() == expected_label
                     and str(row[4]).upper() == expected_label)
            fp = sum(1 for row in labelled if str(row[3]).upper() == expected_label
                     and str(row[4]).upper() != expected_label)
            fn = sum(1 for row in labelled if str(row[3]).upper() != expected_label
                     and str(row[4]).upper() == expected_label)
            precision = (tp + 1) / (tp + fp + 2)
            recall = (tp + 1) / (tp + fn + 2)
            return precision, recall, confusion, len(labelled)

        precision, recall, confusion, labelled = classification_metrics(historical)
        recent_precision, recent_recall, recent_confusion, recent_labelled = classification_metrics(recent)
        hp = precision if precision is not None else accuracy
        rp = recent_precision if recent_precision is not None else recent_accuracy
        hr = recall if recall is not None else hp
        rr = recent_recall if recent_recall is not None else rp
        latencies = [row[1] for row in recent if row[1] is not None]
        errors = sum(bool(row[2]) for row in recent)
        drift = total >= 8 and ((hp-rp >= .10) or (hr-rr >= .10))
        weight = max(.15, min(1., .25*hp + .25*hr + .25*rp + .25*rr))
        health = "DEGRADED" if drift or (len(recent) >= 5 and min(rp, rr) < .45) else "LEARNING" if total < 5 else "HEALTHY"
        result = {"source": source, "detector": detector, "context_version": version,
                "samples": total, "labelled_samples": labelled,
                "historical_accuracy": accuracy, "recent_accuracy": recent_accuracy,
                "historical_precision": hp, "recent_precision": rp,
                "historical_recall": hr, "recent_recall": rr,
                "confusion_matrix": confusion, "recent_confusion_matrix": recent_confusion,
                "weight": weight, "drift": drift, "health": health,
                "latency": sum(latencies)/len(latencies) if latencies else None,
                "error_rate": errors/max(1, len(recent)), "availability": total > 0,
                "last_sample_at": historical[-1][5] if historical else None}
        self._sensor_profile_cache[cache_key] = time.monotonic(), result
        return dict(result)

    def sensor_weight(self, source: str, state: dict) -> float | None:
        return self.learning_memory.reliability(source, "*", self.learning_context(state, "SENSOR"))

    def sensor_health(self, state: dict) -> list[dict]:
        return self.learning_memory.sensor_health(state, self.learning_context)
        context = self.learning_context(state, "SENSOR")
        encoded, _ = self._context_keys(context)
        with self._ro() as db:
            pairs = db.execute("SELECT DISTINCT source,detector FROM sensor_trials WHERE context=?",
                               (encoded,)).fetchall()
        return [self.sensor_profile(source, detector, context) for source, detector in pairs]

    def record_action_timing(self, skill: str, at: float, outcome: str, latency: float,
                             context: dict, provenance: dict) -> None:
        encoded, _ = self._context_keys(context)
        with self._tx() as db:
            db.execute("INSERT INTO action_timings(skill,at,outcome,latency,context,provenance) "
                       "VALUES (?,?,?,?,?,?)", (skill, at, outcome, max(0., latency),
                                                encoded, canonical(provenance)))
        self._timing_cache.pop((skill, encoded), None)

    def verification_window(self, skill: str, context: dict, fallback_timeout: float) -> dict:
        encoded, _ = self._context_keys(context)
        key = skill, encoded
        cached = self._timing_cache.get(key)
        if cached and time.monotonic()-cached[0] < 5.:
            return dict(cached[1])
        with self._ro() as db:
            rows = db.execute("SELECT latency FROM action_timings WHERE skill=? AND context=? "
                              "AND outcome='SUCCESS' ORDER BY at DESC LIMIT 100",
                              (skill, encoded)).fetchall()
        samples = sorted(float(row[0]) for row in rows if row[0] is not None)
        if len(samples) >= 5:
            q = lambda p: samples[min(len(samples)-1, int((len(samples)-1)*p))]
            earliest, likely_start, likely_end = q(.05), q(.20), q(.90)
            deadline = max(likely_end*1.75, q(.95)+.25)
            source = "LIVE_CALIBRATED"
        else:
            earliest, likely_start = .05, .10
            likely_end = max(.25, min(fallback_timeout*.70, fallback_timeout-.05))
            deadline, source = fallback_timeout, "CONTRACT_PRIOR"
        result = {"earliest": earliest, "likely_start": likely_start,
                  "likely_end": likely_end, "deadline": min(max(deadline, likely_end),
                  max(fallback_timeout*2., fallback_timeout)), "samples": len(samples), "source": source}
        self._timing_cache[key] = time.monotonic(), result
        return dict(result)
