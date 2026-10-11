from __future__ import annotations

from collections import deque
from contextlib import closing, contextmanager
from pathlib import Path
import json
import logging
import sqlite3
import threading
import time
from .models import Observation, canonical
from .memory_records import MemoryRecordsMixin
from .memory_learning import MemoryLearningMixin
from .memory_rejection import MemoryRejectionMixin
from .memory_maintenance import MemoryMaintenanceMixin
from .memory_patterns import MemoryPatternsMixin

_logger = logging.getLogger(__name__)


class AgentMemory(MemoryPatternsMixin, MemoryMaintenanceMixin, MemoryRejectionMixin,
                  MemoryLearningMixin, MemoryRecordsMixin):
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
        # Issues #71/#73: a failed batch is retried a bounded number of times
        # and then counted as lost (sticky); the queue is bounded with a short
        # backpressure wait, and drain_writes never reports completeness
        # after a loss.
        self.write_failures = 0
        self.lost_write_batches = 0
        self.writer_error: str | None = None
        self.write_queue_peak = 0
        self._write_queue_space = threading.Condition()
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

    WRITE_QUEUE_LIMIT = 512          # batches (one per sensor boundary)
    WRITE_RETRY_LIMIT = 3
    WRITE_RETRY_BACKOFF_SECONDS = .2
    WRITE_BACKPRESSURE_SECONDS = 1.

    def _lose_batch(self, kind: str, reason: str) -> None:
        self.lost_write_batches += 1
        self.writer_error = f"{kind}: {reason}"
        _logger.error("background memory batch lost (%s; %d lost so far)",
                      self.writer_error, self.lost_write_batches)

    def _writer_loop(self) -> None:
        while True:
            self._write_wakeup.wait(.25)
            self._write_wakeup.clear()
            while self._write_queue:
                try:
                    kind, rows = self._write_queue[0]
                except IndexError:
                    break
                attempts = 0
                while True:
                    try:
                        with self._tx() as db:
                            if kind == "observations":
                                self._insert_observations(db, rows)
                            else:
                                self._insert_relations(db, rows)
                        break
                    except Exception as error:
                        attempts += 1
                        self.write_failures += 1
                        _logger.warning("background memory write failed (%s, attempt %d)",
                                        kind, attempts, exc_info=True)
                        if attempts >= self.WRITE_RETRY_LIMIT:
                            self._lose_batch(kind, f"{type(error).__name__}: {error}")
                            break
                        self._writer_stop.wait(self.WRITE_RETRY_BACKOFF_SECONDS*attempts)
                self._write_queue.popleft()
                with self._write_queue_space:
                    self._write_queue_space.notify_all()
            if not self._write_queue:
                self._writer_idle.set()
            if self._writer_stop.is_set() and not self._write_queue:
                return

    def _enqueue_write(self, kind: str, rows) -> None:
        if len(self._write_queue) >= self.WRITE_QUEUE_LIMIT:
            # Backpressure: wait briefly for the writer.  A writer that cannot
            # keep up for that long is failing; drop explicitly (fail closed)
            # rather than grow memory without bound or stall the loop.
            self._write_wakeup.set()
            with self._write_queue_space:
                self._write_queue_space.wait_for(
                    lambda: len(self._write_queue) < self.WRITE_QUEUE_LIMIT,
                    timeout=self.WRITE_BACKPRESSURE_SECONDS)
            if len(self._write_queue) >= self.WRITE_QUEUE_LIMIT:
                self._lose_batch(kind, "write_queue_full")
                return
        self._writer_idle.clear()
        self._write_queue.append((kind, rows))
        self.write_queue_peak = max(self.write_queue_peak, len(self._write_queue))
        self._write_wakeup.set()

    def drain_writes(self, timeout: float = 10.) -> bool:
        """True only when every enqueued background write reached the
        connection and no batch was ever lost (issue #71)."""
        if self._writer_thread is None:
            return self.lost_write_batches == 0
        deadline = time.monotonic()+timeout
        while self._write_queue or not self._writer_idle.is_set():
            self._write_wakeup.set()
            if time.monotonic() > deadline:
                return False
            self._writer_idle.wait(.05)
        return self.lost_write_batches == 0

    def _drain_for_read(self, reader: str) -> bool:
        """Drain before reading; say so when the history may be partial."""
        complete = self.drain_writes()
        if not complete:
            _logger.warning("AgentMemory.%s reads possibly incomplete history "
                            "(pending=%d, lost=%d, error=%s)", reader,
                            len(self._write_queue), self.lost_write_batches, self.writer_error)
        return complete

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
        self._drain_for_read("commit_pending")
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
        self._drain_for_read("close")
        self._writer_stop.set()
        self._write_wakeup.set()
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=10)
        self._checkpoint_stop.set()
        if self._checkpoint_thread is not None:
            self._checkpoint_thread.join(timeout=5)
        if self._writer_thread is not None and self._writer_thread.is_alive():
            # Issue #73: never close the connection under a live writer.
            _logger.error("AgentMemory.close(): writer still running with %d queued "
                          "batches; connection left open", len(self._write_queue))
            return
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
        self._drain_for_read("events")
        with self._ro() as db:
            rows = db.execute("SELECT id,at,event_type,source,observation_id,entity_ids,quest_ids,marker_ids,payload "
                              "FROM events WHERE session=? ORDER BY at,id", (session,)).fetchall()
        return [{"event_id": row[0], "at": row[1], "event_type": row[2], "source": row[3],
                 "observation_id": row[4], "entity_ids": json.loads(row[5]),
                 "quest_ids": json.loads(row[6]), "marker_ids": json.loads(row[7]),
                 "payload": json.loads(row[8])} for row in rows]

    def observations(self, session: str) -> list[Observation]:
        self._drain_for_read("observations")
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
        complete = self._drain_for_read("hydrate_world")
        """Reconstruct WorldModel solely from the append-only Observation store."""
        from .world import WorldModel
        world = WorldModel()
        # A hydration after a lost/pending write is explicitly partial.
        world.__dict__["memory_history_complete"] = complete
        for observation in self.observations(session):
            world.ingest(observation)
        return world

