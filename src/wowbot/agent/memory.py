from __future__ import annotations

from collections import deque
from contextlib import closing, contextmanager
from pathlib import Path
import hashlib
import json
import logging
import sqlite3
import threading
import time
from .models import Observation, canonical

_logger = logging.getLogger(__name__)


class AgentMemory:
    """Append-only episodes/evidence plus context-scoped strategy statistics."""

    def __init__(self, path: Path, *, commit_interval_seconds: float = 0.0,
                 background_checkpoint_seconds: float = 0.0,
                 relation_flush_interval_seconds: float = 0.0,
                 async_writes: bool = False, cache_size_kib: int = 0):
        self.path = path
        # 0 keeps the historical commit-per-outermost-scope behavior.  The live
        # runtime passes ~1 s: live 2026-09-30 the per-step commit held 45 % of
        # all agent-thread samples, capping the control loop near 10-14 Hz.
        self.commit_interval_seconds = max(0.0, float(commit_interval_seconds))
        # Relation rows are keyed and coalesced in _relation_buffer, so a
        # bounded flush cadence writes each changing relation once per interval
        # instead of on every agent step (offline replay: ~21 ms per flush).
        self.relation_flush_interval_seconds = max(0.0, float(relation_flush_interval_seconds))
        self._last_commit_at = time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            except sqlite3.DatabaseError:
                pass
            db.executescript('''
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY, session TEXT, at REAL, kind TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, session TEXT, at REAL, source TEXT, correlation TEXT, payload TEXT,
                    recorded_order INTEGER);
                CREATE TABLE IF NOT EXISTS strategies (
                    context TEXT, skill TEXT, successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0,
                    PRIMARY KEY(context, skill));
                CREATE TABLE IF NOT EXISTS goals (id TEXT PRIMARY KEY, payload TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, session TEXT, at REAL, event_type TEXT, source TEXT,
                    observation_id TEXT, entity_ids TEXT, quest_ids TEXT, marker_ids TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS procedural_strategies (
                    context TEXT, domain TEXT, category TEXT, skill TEXT, version TEXT,
                    successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, total_cost REAL DEFAULT 0,
                    first_seen REAL, last_seen REAL, provenance TEXT,
                    PRIMARY KEY(context,skill,version));
                CREATE TABLE IF NOT EXISTS procedure_trials (
                    id INTEGER PRIMARY KEY, context TEXT, domain TEXT, skill TEXT, version TEXT,
                    at REAL, success INTEGER, cost REAL, reason TEXT, provenance TEXT);
                CREATE TABLE IF NOT EXISTS sensor_trials (
                    id INTEGER PRIMARY KEY, source TEXT, detector TEXT, context TEXT,
                    at REAL, correct INTEGER, latency REAL, error TEXT, provenance TEXT,
                    predicted_label TEXT, actual_label TEXT);
                CREATE TABLE IF NOT EXISTS action_timings (
                    id INTEGER PRIMARY KEY, skill TEXT, at REAL, outcome TEXT,
                    latency REAL, context TEXT, provenance TEXT);
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY, goal_id TEXT, session TEXT, domain TEXT,
                    started_at REAL, ended_at REAL, status TEXT,
                    initial_state TEXT, final_state TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS episode_steps (
                    episode_id TEXT, sequence INTEGER, at REAL, kind TEXT, payload TEXT,
                    PRIMARY KEY(episode_id,sequence));
                CREATE TABLE IF NOT EXISTS task_patterns (
                    id TEXT PRIMARY KEY, domain TEXT, version TEXT, signature TEXT,
                    preconditions TEXT, steps TEXT, expected TEXT, success TEXT, failure TEXT,
                    mean_cost REAL, successes INTEGER, failures INTEGER, confidence REAL,
                    stage TEXT, provenance TEXT, first_seen REAL, last_seen REAL);
                CREATE TABLE IF NOT EXISTS resource_sites (
                    site_key TEXT PRIMARY KEY, map_id TEXT, resource_type TEXT, version TEXT,
                    x REAL, y REAL, successes INTEGER, failures INTEGER,
                    first_seen REAL, last_seen REAL, provenance TEXT);
                CREATE TABLE IF NOT EXISTS goal_tasks (
                    id TEXT PRIMARY KEY, goal_id TEXT, status TEXT, score REAL,
                    updated_at REAL, payload TEXT);
                CREATE TABLE IF NOT EXISTS world_relations (
                    session TEXT, id TEXT, subject TEXT, predicate TEXT, object TEXT,
                    at REAL, payload TEXT, PRIMARY KEY(session,id));
                CREATE TABLE IF NOT EXISTS semantic_facts (
                    fact_key TEXT PRIMARY KEY, subject TEXT, predicate TEXT, value TEXT,
                    context TEXT, source TEXT, successes INTEGER, failures INTEGER,
                    first_seen REAL, last_seen REAL, provenance TEXT);
                CREATE TABLE IF NOT EXISTS rejection_memory (
                    signature TEXT, map_id TEXT, failures INTEGER DEFAULT 0,
                    contradictions INTEGER DEFAULT 0, first_seen REAL, last_seen REAL,
                    expires_at REAL, reason TEXT, provenance TEXT,
                    PRIMARY KEY(signature,map_id));
                CREATE TABLE IF NOT EXISTS rejection_trials (
                    signature TEXT, map_id TEXT, evidence_group TEXT,
                    at REAL, outcome TEXT, hover_quality REAL, reason TEXT,
                    provenance TEXT,
                    PRIMARY KEY(signature,map_id,evidence_group));
                CREATE TABLE IF NOT EXISTS consolidation_runs (
                    id INTEGER PRIMARY KEY, at REAL, before_count INTEGER,
                    removed_count INTEGER, after_count INTEGER, policy TEXT);
                CREATE INDEX IF NOT EXISTS idx_procedure_trials ON procedure_trials(context,skill,version,at);
                CREATE INDEX IF NOT EXISTS idx_sensor_trials ON sensor_trials(source,detector,context,at);
                CREATE INDEX IF NOT EXISTS idx_action_timings ON action_timings(skill,context,at);
                CREATE INDEX IF NOT EXISTS idx_episode_steps ON episode_steps(episode_id,sequence);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_pattern ON task_patterns(domain,version,signature);
                CREATE INDEX IF NOT EXISTS idx_resource_sites ON resource_sites(map_id,resource_type,version);
                CREATE INDEX IF NOT EXISTS idx_goal_tasks ON goal_tasks(goal_id,status,score);
                CREATE INDEX IF NOT EXISTS idx_world_relations ON world_relations(session,subject,predicate,object);
                CREATE INDEX IF NOT EXISTS idx_semantic_facts ON semantic_facts(subject,predicate,context,last_seen);
                CREATE INDEX IF NOT EXISTS idx_rejection_memory ON rejection_memory(map_id,last_seen);
                CREATE INDEX IF NOT EXISTS idx_rejection_trials ON rejection_trials(map_id,signature,at);
                CREATE INDEX IF NOT EXISTS idx_observations_recorded_order ON observations(recorded_order);
                CREATE INDEX IF NOT EXISTS idx_observations_at ON observations(at);
                CREATE INDEX IF NOT EXISTS idx_observations_source_order ON observations(source,recorded_order,id);
                CREATE INDEX IF NOT EXISTS idx_events_session_at ON events(session,at);
                -- consolidate()'s trim queries ORDER BY at,id / at,rowid to find
                -- the oldest rows to delete; idx_events_session_at and
                -- idx_world_relations above lead with session/subject and cannot
                -- serve that sort, forcing a full-table scan + sort once either
                -- table crossed its trim threshold (live-confirmed 2026-09-22:
                -- a several-hundred-ms control-loop stall every consolidate()
                -- pass once the DB had grown).
                CREATE INDEX IF NOT EXISTS idx_events_at_id ON events(at,id);
                CREATE INDEX IF NOT EXISTS idx_world_relations_at ON world_relations(at);
            ''')
            observation_columns = {row[1] for row in db.execute("PRAGMA table_info(observations)")}
            if "recorded_order" not in observation_columns:
                db.execute("ALTER TABLE observations ADD COLUMN recorded_order INTEGER")
            sensor_columns = {row[1] for row in db.execute("PRAGMA table_info(sensor_trials)")}
            if "predicted_label" not in sensor_columns:
                db.execute("ALTER TABLE sensor_trials ADD COLUMN predicted_label TEXT")
            if "actual_label" not in sensor_columns:
                db.execute("ALTER TABLE sensor_trials ADD COLUMN actual_label TEXT")
        self._sensor_profile_cache = {}
        self._procedure_profile_cache = {}
        self._rejection_cache = {}
        self._timing_cache = {}
        self._observe_attempted = 0
        self._observe_inserted = 0
        self._relation_buffer: dict[tuple[str, str], tuple[str, dict]] = {}
        self._metric_baseline = None  # (monotonic, db bytes) taken on first metrics()
        self._last_relation_flush_at = time.monotonic()
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # A checkpointed WAL is truncated back to 64 MB instead of keeping its
        # peak size (live 2026-10-03: 2.2 GB WAL next to a 500 MB database).
        self._conn.execute("PRAGMA journal_size_limit=67108864")
        # WAL auto-checkpoint runs inside whichever commit crosses ~4 MB and
        # waits for the disk; offline replay on the 384 MB live DB showed it as
        # the 0.25-1.2 s control-loop spikes.  The live runtime moves it to a
        # daemon thread with its own connection (PASSIVE never blocks writers).
        self._checkpoint_stop = threading.Event()
        self._checkpoint_thread = None
        if cache_size_kib > 0:
            # Keep a deferred transaction's dirty pages in memory instead of
            # spilling them to the WAL mid-transaction on the agent thread.
            self._conn.execute(f"PRAGMA cache_size=-{int(cache_size_kib)}")
        # Write-behind for high-volume appends (observations, relations): the
        # agent thread only enqueues; a daemon thread writes in small chunks,
        # releasing the lock between chunks.  Readers of those tables drain
        # the queue first, so they never observe a partial history.
        self._write_queue: deque = deque()
        self._write_wakeup = threading.Event()
        self._writer_idle = threading.Event()
        self._writer_idle.set()
        self._writer_stop = threading.Event()
        self._writer_thread = None
        if async_writes:
            self._writer_thread = threading.Thread(
                target=self._writer_loop, name="aipc-memory-writer", daemon=True)
            self._writer_thread.start()
        if background_checkpoint_seconds > 0:
            self._conn.execute("PRAGMA wal_autocheckpoint=0")
            self._checkpoint_thread = threading.Thread(
                target=self._checkpoint_loop, args=(float(background_checkpoint_seconds),),
                name="aipc-memory-checkpoint", daemon=True)
            self._checkpoint_thread.start()
        from .episode_memory import EpisodeMemory
        from .learning_memory import LearningMemory
        from .rejection_memory import RejectionMemory
        self.episode_memory = EpisodeMemory(self._tx, promote=self._promote_episode_pattern)
        self.learning_memory = LearningMemory(self._tx, self._ro)
        self.rejection_memory = RejectionMemory(self._tx, self._ro)

    @contextmanager
    def _tx(self):
        """Serialized transaction on the long-lived SQLite connection.

        Reentrant (same thread only, via the RLock): a `_tx()` opened while
        another `_tx()`/`batch()` is already active on this thread joins that
        outer transaction instead of committing separately. Without this,
        one busy tick emitting many small AgentMemory writes (one `_record()`
        call per queued event) paid a separate disk commit for each one --
        live-confirmed 2026-09-22 as a real contributor to control-loop
        stalls once the DB/WAL had grown. Only the outermost scope commits
        or rolls back.
        """
        with self._lock:
            self._tx_depth += 1
            deferred = self._tx_depth == 1 and self.commit_interval_seconds > 0
            if deferred:
                # Keep one long transaction open across scopes; a savepoint per
                # outermost scope lets a failure undo only its own writes.
                if not self._conn.in_transaction:
                    self._conn.execute("BEGIN")
                self._conn.execute("SAVEPOINT agent_memory_scope")
            try:
                yield self._conn
                if deferred:
                    self._conn.execute("RELEASE SAVEPOINT agent_memory_scope")
                    if time.monotonic()-self._last_commit_at >= self.commit_interval_seconds:
                        self._commit_now()
                elif self._tx_depth == 1:
                    self._conn.commit()
                    self._last_commit_at = time.monotonic()
            except BaseException:
                if deferred:
                    self._conn.execute("ROLLBACK TO SAVEPOINT agent_memory_scope")
                    self._conn.execute("RELEASE SAVEPOINT agent_memory_scope")
                elif self._tx_depth == 1:
                    self._conn.rollback()
                raise
            finally:
                self._tx_depth -= 1

    def _writer_loop(self) -> None:
        while True:
            self._write_wakeup.wait(.25)
            self._write_wakeup.clear()
            while self._write_queue:
                try:
                    kind, rows = self._write_queue.popleft()
                except IndexError:
                    break
                try:
                    with self._tx() as db:
                        if kind == "observations":
                            self._insert_observations(db, rows)
                        else:
                            self._insert_relations(db, rows)
                except Exception:
                    _logger.warning("background memory write failed (%s)", kind, exc_info=True)
            if not self._write_queue:
                self._writer_idle.set()
            if self._writer_stop.is_set() and not self._write_queue:
                return

    def _enqueue_write(self, kind: str, rows) -> None:
        self._writer_idle.clear()
        self._write_queue.append((kind, rows))
        self._write_wakeup.set()

    def drain_writes(self, timeout: float = 10.) -> bool:
        """Wait until every enqueued background write reached the connection."""
        if self._writer_thread is None:
            return True
        deadline = time.monotonic()+timeout
        while self._write_queue or not self._writer_idle.is_set():
            self._write_wakeup.set()
            if time.monotonic() > deadline:
                return False
            self._writer_idle.wait(.05)
        return True

    def _checkpoint_loop(self, interval: float) -> None:
        try:
            connection = sqlite3.connect(self.path, check_same_thread=False)
            connection.execute("PRAGMA busy_timeout=2000")
        except sqlite3.Error:
            _logger.warning("background WAL checkpoint connection failed", exc_info=True)
            return
        try:
            while not self._checkpoint_stop.wait(interval):
                try:
                    connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
                except sqlite3.Error:
                    _logger.debug("background WAL checkpoint skipped", exc_info=True)
        finally:
            connection.close()

    def _commit_now(self) -> None:
        if self._conn.in_transaction:
            self._conn.commit()
        self._last_commit_at = time.monotonic()

    def commit_pending(self) -> None:
        """Make deferred writes durable now (shutdown, cross-connection reads)."""
        self.drain_writes()
        with self._lock:
            if self._tx_depth == 0:
                self._commit_now()

    @contextmanager
    def batch(self):
        """Group a sequence of AgentMemory writes into one commit.

        Public counterpart to `_tx()` for external callers (e.g. one whole
        agent tick) that make several separate AgentMemory calls and want
        them to land as a single disk commit rather than one per call.
        """
        with self._tx():
            yield

    @contextmanager
    def _ro(self):
        with self._lock:
            yield self._conn

    def close(self):
        self.flush_world_relations()
        self.drain_writes()
        self._writer_stop.set()
        self._write_wakeup.set()
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=10)
        self._checkpoint_stop.set()
        if self._checkpoint_thread is not None:
            self._checkpoint_thread.join(timeout=5)
        with self._lock:
            try:
                self._commit_now()
            except Exception:
                _logger.warning("sqlite commit failed in AgentMemory.close()", exc_info=True)
            try:
                self._conn.close()
            except Exception:
                # V4-077: cleanup-time failure must not raise (would mask
                # the caller's own shutdown), but must not be silent either.
                _logger.warning("sqlite connection.close() failed in AgentMemory.close()", exc_info=True)

    def observe_many(self, observations) -> None:
        """Persist one sensor boundary in one ordered SQLite transaction.

        A complete AIPC frame expands into several source-specific Observation
        objects.  Opening/committing SQLite and scanning MAX(recorded_order) for
        every projection made the medium loop take seconds once the live DB had
        grown.  The WorldModel still ingests every immutable Observation; this
        method only batches their durable append operation.
        """
        observations = tuple(observations)
        if not observations:
            return
        self._observe_attempted += len(observations)
        if self._writer_thread is not None:
            self._enqueue_write("observations", observations)
            return
        with self._tx() as db:
            self._insert_observations(db, observations)

    def _insert_observations(self, db, observations) -> None:
        from .models import EventRecord
        if True:
            order = int(db.execute(
                "SELECT COALESCE(MAX(recorded_order),0)+1 FROM observations").fetchone()[0])
            for offset, observation in enumerate(observations):
                inserted = db.execute(
                    "INSERT OR IGNORE INTO observations(id,session,at,source,correlation,payload,recorded_order) "
                    "VALUES (?,?,?,?,?,?,?)", (
                        observation.observation_id, observation.session_id, observation.received_at,
                        observation.source, observation.correlation_id, observation.payload_json,
                        order+offset)).rowcount
                if not inserted:
                    continue
                self._observe_inserted += 1
                for raw in observation.payload.get("events", []):
                    event = EventRecord.create(raw, observation)
                    db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", (
                        event.event_id, event.session_id, event.received_at, event.event_type, event.source,
                        event.observation_id, canonical(event.entity_ids), canonical(event.quest_ids),
                        canonical(event.marker_ids), event.payload_json))

    def observe(self, observation: Observation):
        self.observe_many((observation,))

    def events(self, session: str) -> list[dict]:
        import json
        self.drain_writes()
        with self._ro() as db:
            rows = db.execute("SELECT id,at,event_type,source,observation_id,entity_ids,quest_ids,marker_ids,payload "
                              "FROM events WHERE session=? ORDER BY at,id", (session,)).fetchall()
        return [{"event_id": row[0], "at": row[1], "event_type": row[2], "source": row[3],
                 "observation_id": row[4], "entity_ids": json.loads(row[5]),
                 "quest_ids": json.loads(row[6]), "marker_ids": json.loads(row[7]),
                 "payload": json.loads(row[8])} for row in rows]

    def observations(self, session: str) -> list[Observation]:
        self.drain_writes()
        with self._ro() as db:
            rows = db.execute("SELECT id,session,at,source,correlation,payload FROM observations "
                              "WHERE session=? ORDER BY COALESCE(recorded_order,9223372036854775807),at,id",
                              (session,)).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row[5])
            # Some valid FAST observations deliberately carry a JSON null
            # wall-clock timestamp.  ``dict.get(key, fallback)`` does not use
            # the fallback when the key exists with a null value, which made
            # crash hydration fail on otherwise valid live sessions.  The
            # durable monotonic receive time is the canonical fallback.
            timestamp = payload.get("timestamp")
            if timestamp is None:
                timestamp = row[2]
            result.append(Observation(row[0], row[1], float(timestamp),
                                      row[2], row[3], row[5], row[4]))
        return result

    def hydrate_world(self, session: str):
        self.flush_world_relations()
        self.drain_writes()
        """Reconstruct WorldModel solely from the append-only Observation store."""
        from .world import WorldModel
        world = WorldModel()
        for observation in self.observations(session):
            world.ingest(observation)
        return world

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
        self.drain_writes()
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

    def record_rejection(self, marker: dict, *, map_id, reason: str, at: float,
                         ttl: float = 86400., evidence_group: str | None = None,
                         hover_quality: float = 1.) -> dict:
        return self.rejection_memory.record(marker, map_id=map_id, reason=reason, at=at,
                                            ttl=ttl, evidence_group=evidence_group,
                                            hover_quality=hover_quality)
        # Legacy implementation retained below temporarily for source-level
        # compatibility archaeology; production returns through the owner.
        from .rejection import rejection_signature
        signature = rejection_signature(marker)
        context = str(map_id if map_id is not None else "UNKNOWN")
        group = str(evidence_group or
                    f"{marker.get('source') or 'UNKNOWN'}:{int(at // 30)}")
        quality = max(0., min(1., float(hover_quality)))
        with self._tx() as db:
            recent = db.execute("""
                SELECT evidence_group,at FROM rejection_trials
                WHERE signature=? AND map_id=? AND outcome='ZERO_INFORMATION'
                ORDER BY at DESC LIMIT 1
            """, (signature, context)).fetchone()
            # Several retries from the same short scene episode are correlated
            # evidence, even when track IDs or frame IDs changed.
            if recent and 0 <= at-float(recent[1]) < 30.:
                group = str(recent[0])
            provenance = canonical({"source": marker.get("source"),
                                    "track_id": marker.get("track_id"),
                                    "detector_kind": marker.get("detector_kind") or marker.get("kind"),
                                    "evidence_group": group, "hover_quality": quality})
            inserted = db.execute("""
                INSERT OR IGNORE INTO rejection_trials
                    (signature,map_id,evidence_group,at,outcome,hover_quality,reason,provenance)
                VALUES (?,?,?,?,?,?,?,?)
            """, (signature, context, group, at, "ZERO_INFORMATION", quality,
                  reason, provenance)).rowcount
            if not inserted:
                return self.rejection_status(marker, map_id=map_id, at=at)
            db.execute("""
                INSERT INTO rejection_memory(signature,map_id,failures,contradictions,
                    first_seen,last_seen,expires_at,reason,provenance)
                VALUES (?,?,1,0,?,?,?,?,?)
                ON CONFLICT(signature,map_id) DO UPDATE SET
                    failures=rejection_memory.failures+1,last_seen=excluded.last_seen,
                    expires_at=excluded.expires_at,reason=excluded.reason,
                    provenance=excluded.provenance
            """, (signature, context, at, at, at+max(0., ttl), reason, provenance))
        self._rejection_cache.pop((signature, context), None)
        return self.rejection_status(marker, map_id=map_id, at=at)

    def record_rejection_contradiction(self, marker: dict, *, map_id, at: float) -> dict:
        return self.rejection_memory.record_contradiction(marker, map_id=map_id, at=at)
        from .rejection import rejection_signature
        signature = rejection_signature(marker)
        context = str(map_id if map_id is not None else "UNKNOWN")
        provenance = canonical({"source": marker.get("source"),
                                "track_id": marker.get("track_id"),
                                "counterevidence": "INSPECTION_PRODUCED_INFORMATION"})
        with self._tx() as db:
            db.execute("""
                INSERT OR IGNORE INTO rejection_trials
                    (signature,map_id,evidence_group,at,outcome,hover_quality,reason,provenance)
                VALUES (?,?,?,?,?,?,?,?)
            """, (signature, context, f"CONTRADICTION:{int(at * 1000)}", at,
                  "INFORMATION_OBSERVED", 1., "contradicting_information_observed",
                  provenance))
            db.execute("""
                INSERT INTO rejection_memory(signature,map_id,failures,contradictions,
                    first_seen,last_seen,expires_at,reason,provenance)
                VALUES (?,?,0,1,?,?,?,?,?)
                ON CONFLICT(signature,map_id) DO UPDATE SET
                    failures=0,contradictions=rejection_memory.contradictions+1,
                    last_seen=excluded.last_seen,expires_at=excluded.expires_at,
                    reason=excluded.reason,provenance=excluded.provenance
            """, (signature, context, at, at, at, "contradicting_information_observed", provenance))
        self._rejection_cache.pop((signature, context), None)
        return self.rejection_status(marker, map_id=map_id, at=at)

    def rejection_status(self, marker: dict, *, map_id, at: float,
                         threshold: int = 3) -> dict:
        return self.rejection_memory.status(marker, map_id=map_id, at=at, threshold=threshold)
        from .rejection import rejection_signature
        signature = rejection_signature(marker)
        context = str(map_id if map_id is not None else "UNKNOWN")
        cached = self._rejection_cache.get((signature, context))
        if cached and at-cached[0] < .5:
            return dict(cached[1])
        with self._ro() as db:
            row = db.execute("""
                SELECT failures,contradictions,first_seen,last_seen,expires_at,reason,provenance
                FROM rejection_memory WHERE signature=? AND map_id=?
            """, (signature, context)).fetchone()
        if not row or row[4] < at:
            result = {"signature": signature, "map_id": map_id, "belief": "UNKNOWN",
                      "confidence": 0., "failures": 0, "independent_trials": 0,
                      "contradictions": row[1] if row else 0}
            self._rejection_cache[(signature, context)] = at, result
            return dict(result)
        failures = int(row[0])
        rejected = failures >= max(1, int(threshold))
        suppressed = not rejected and failures > 0 and 0 <= at-float(row[3]) <= 15.
        result = {"signature": signature, "map_id": map_id,
                "belief": "REJECTED" if rejected else "SUPPRESSED" if suppressed else "CANDIDATE",
                "confidence": (1. if rejected or suppressed
                               else min(.85, failures/max(1, int(threshold)))),
                "failures": failures, "independent_trials": failures,
                "contradictions": int(row[1]),
                "first_seen": row[2], "last_seen": row[3], "expires_at": row[4],
                "suppressed_until": float(row[3])+15. if suppressed else None,
                "reason": row[5], "provenance": json.loads(row[6]) if row[6] else {}}
        self._rejection_cache[(signature, context)] = at, result
        return dict(result)

    def metrics(self) -> dict:
        """Bounded operational metrics; never scans payload blobs."""
        started = time.perf_counter()
        with self._ro() as db:
            # Row counts from the rowid range (index lookups), not COUNT(*):
            # live 2026-10-03 the COUNT(*) scans took 13 s on the agent thread
            # every 30 s and pulled the consumed FAST rate down to ~14 Hz.
            def approximate_count(table: str) -> int:
                low, high = db.execute(f"SELECT MIN(rowid),MAX(rowid) FROM {table}").fetchone()
                return 0 if low is None or high is None else int(high)-int(low)+1
            observations = approximate_count("observations")
            events = approximate_count("events")
            oldest = db.execute("SELECT at FROM observations ORDER BY at LIMIT 1").fetchone()
            newest = db.execute("SELECT at FROM observations ORDER BY at DESC LIMIT 1").fetchone()
            oldest, newest = (oldest or (None,))[0], (newest or (None,))[0]
        span = max(1., (newest or 0.)-(oldest or 0.))
        # PRAGMA sizes are instant; Path.stat() on the large, actively written
        # live DB took 176-282 ms per call on Windows (offline replay).
        with self._ro() as db:
            size = (int(db.execute("PRAGMA page_count").fetchone()[0])
                    * int(db.execute("PRAGMA page_size").fetchone()[0]))
        if self._metric_baseline is None:
            self._metric_baseline = (time.monotonic(), size)
        elapsed = max(.001, time.monotonic()-self._metric_baseline[0])
        growth = max(0, size-self._metric_baseline[1])/1048576/(elapsed/3600)
        with self._ro() as db:
            runs = db.execute("SELECT COALESCE(SUM(removed_count),0),COUNT(*) FROM consolidation_runs").fetchone()
        attempted = max(1, self._observe_attempted)
        return {"db_size_mb": round(size/1048576, 3),
                "growth_mb_per_hour": round(growth, 3),
                "observations": observations, "events": events,
                "observations_per_min": round(observations/span*60, 2),
                "events_per_min": round(events/span*60, 2),
                "duplicate_ratio": round(1-self._observe_inserted/attempted, 4),
                "consolidated_observations": int(runs[0]), "consolidation_runs": int(runs[1]),
                "consolidation_ratio": round(int(runs[0])/max(1, observations+int(runs[0])), 4),
                "query_latency_ms": round((time.perf_counter()-started)*1000, 3),
                "retention": "bounded perception raw; ground truth/events/episodes retained"}

    def consolidate(self, at: float, *, maximum_raw_observations: int = 15_000,
                    target_raw_observations: int = 8_000,
                    current_session: str | None = None,
                    maximum_addon_telemetry: int = 120_000,
                    target_addon_telemetry: int = 80_000,
                    maximum_rows_per_pass: int | None = None) -> dict:
        """Bound raw frame projections while retaining authoritative history.

        Derived CV/AI projections are always eligible for trimming. Addon
        ground truth (ADDON_TELEMETRY) additionally gets its own, much larger
        bound -- live-confirmed 2026-09-12: with no bound at all it reached
        ~1GB/session, growing forever, while nothing in this codebase ever
        reads back ADDON_TELEMETRY from a *previous* session (only the
        active one, for hydrate_world() crash recovery -- see observations()
        above) or uses it as a learning signal at all (this agent's behavior
        comes from the hand-tuned rules/priorities in planner.py/autonomy_
        loop.py, not from replaying history). `current_session`, when
        given, is fully exempted from this bound so an in-progress session's
        own hydration capability is never at risk -- only OLDER, already-
        closed sessions' addon telemetry gets trimmed. Normalized events,
        agent traces, completed episodes and learned memory (EntityMemory,
        WorldPointMemory -- separate database files, untouched here) are
        never removed by this policy.
        """
        self.drain_writes()
        maximum_raw_observations = max(4_000, int(maximum_raw_observations))
        target_raw_observations = max(2_000, min(int(target_raw_observations),
                                                 maximum_raw_observations))
        maximum_addon_telemetry = max(20_000, int(maximum_addon_telemetry))
        target_addon_telemetry = max(10_000, min(int(target_addon_telemetry),
                                                  maximum_addon_telemetry))
        remaining_budget = (None if maximum_rows_per_pass is None else
                            max(1, int(maximum_rows_per_pass)))

        def allowance(requested: int) -> int:
            """Return an available limit without charging rows not found."""
            requested = max(0, int(requested))
            return requested if remaining_budget is None else min(requested, remaining_budget)

        def consume(actual: int) -> None:
            nonlocal remaining_budget
            if remaining_budget is not None:
                remaining_budget = max(0, remaining_budget-max(0, int(actual)))
        # table -> (rows to keep, ORDER BY for "oldest first", key column).
        # journal and world_relations were added 2026-09-21 after a 12.6 h
        # live session left a 4.1 GB memory DB: world_relations 3.6 M rows /
        # 1.4 GB (one observed_by edge per track per frame -- also fixed at
        # the source in WorldModel.link) and journal 316 MB, neither of
        # which any code path reads back, while consolidate() only ever
        # looked at observations/events.
        trims = {"events": (15_000, "at,id", "id"),
                 "sensor_trials": (20_000, "id", "id"),
                 "procedure_trials": (20_000, "id", "id"),
                 "action_timings": (20_000, "id", "id"),
                 "journal": (20_000, "id", "id"),
                 "world_relations": (50_000, "at,rowid", "rowid")}
        with self._tx() as db:
            before = int(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
            derived_before = int(db.execute(
                "SELECT COUNT(*) FROM observations WHERE source IN "
                "('WORLD3D','WORLD3D_LOCAL_VIEW','MINIMAP_CV','WORLD_MAP_CV',"
                "'UI_CV','AI','ENTITY_MEMORY')").fetchone()[0])
            removed = 0
            if derived_before > maximum_raw_observations:
                requested = allowance(derived_before-target_raw_observations)
                removable = tuple(row[0] for row in db.execute(
                    "SELECT id FROM observations WHERE source IN "
                    "('WORLD3D','WORLD3D_LOCAL_VIEW','MINIMAP_CV','WORLD_MAP_CV',"
                    "'UI_CV','AI','ENTITY_MEMORY') "
                    "ORDER BY recorded_order,id LIMIT ?", (requested,)).fetchall())
                if removable:
                    db.executemany("DELETE FROM observations WHERE id=?", ((key,) for key in removable))
                    removed = len(removable)
                    consume(removed)
            addon_removed = 0
            addon_before = 0
            if current_session is not None:
                addon_before = int(db.execute(
                    "SELECT COUNT(*) FROM observations WHERE source='ADDON_TELEMETRY' AND session!=?",
                    (current_session,)).fetchone()[0])
                if addon_before > maximum_addon_telemetry:
                    requested = allowance(addon_before-target_addon_telemetry)
                    addon_removable = tuple(row[0] for row in db.execute(
                        "SELECT id FROM observations WHERE source='ADDON_TELEMETRY' AND session!=? "
                        "ORDER BY recorded_order,id LIMIT ?", (current_session, requested)).fetchall())
                    if addon_removable:
                        db.executemany("DELETE FROM observations WHERE id=?",
                                       ((key,) for key in addon_removable))
                        addon_removed = len(addon_removable)
                        consume(addon_removed)
            log_trims = {}
            log_backlog = {}
            for table, (keep, order, key) in trims.items():
                count = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if count > keep:
                    delete_count = allowance(count-keep)
                    if delete_count <= 0:
                        log_backlog[table] = count-keep
                        continue
                    db.execute(
                        f"DELETE FROM {table} WHERE {key} IN "
                        f"(SELECT {key} FROM {table} ORDER BY {order} LIMIT ?)",
                        (delete_count,))
                    log_trims[table] = delete_count
                    consume(delete_count)
                    if count-delete_count > keep:
                        log_backlog[table] = count-delete_count-keep
            after = before-removed-addon_removed
            policy = canonical({"maximum_raw_observations": maximum_raw_observations,
                                "target_raw_observations": target_raw_observations,
                                "maximum_addon_telemetry": maximum_addon_telemetry,
                                "target_addon_telemetry": target_addon_telemetry,
                                "log_trims": {table: values[0] for table, values in trims.items()},
                                "eligible": ["WORLD3D", "WORLD3D_LOCAL_VIEW", "MINIMAP_CV",
                                             "WORLD_MAP_CV", "UI_CV", "AI", "ENTITY_MEMORY"],
                                "addon_telemetry_eligible_outside_current_session": current_session is not None})
            db.execute("INSERT INTO consolidation_runs(at,before_count,removed_count,after_count,policy) "
                       "VALUES (?,?,?,?,?)", (at, before, removed+addon_removed, after, policy))
        observation_backlog = (max(0, derived_before-removed-target_raw_observations)
                               if derived_before > maximum_raw_observations else 0)
        addon_backlog = (max(0, addon_before-addon_removed-target_addon_telemetry)
                         if current_session is not None and addon_before > maximum_addon_telemetry else 0)
        backlog_rows = observation_backlog + addon_backlog + sum(log_backlog.values())
        return {"before": before, "removed": removed+addon_removed, "after": after,
                "cv_projections_removed": removed, "addon_telemetry_removed": addon_removed,
                "log_trims": log_trims, "backlog_rows": backlog_rows,
                "more_maintenance_due": backlog_rows > 0,
                "authoritative_observations_preserved": current_session is None, "policy": json.loads(policy)}

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
