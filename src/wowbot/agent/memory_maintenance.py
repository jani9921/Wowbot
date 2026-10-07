"""AgentMemory metrics and bounded consolidation of derived observations.

Split out of memory.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import json
import time
from .models import canonical


class MemoryMaintenanceMixin:
    """Methods of AgentMemory (memory.py); moved verbatim."""

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
                "write_queue_batches": len(self._write_queue),
                "write_queue_peak": self.write_queue_peak,
                "write_failures": self.write_failures,
                "lost_write_batches": self.lost_write_batches,
                "writer_error": self.writer_error,
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
        self._drain_for_read("consolidate")
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
