import sqlite3

from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Observation


def test_consolidation_removes_only_old_derived_observations(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    rows = []
    for index in range(10_020):
        source = "WORLD3D" if index < 10_010 else "ADDON_TELEMETRY"
        rows.append(Observation.create({"session_id": "s", "frame_id": f"f{index}",
                                        "timestamp": index, "value": index}, index, source))
    memory.observe_many(rows)
    result = memory.consolidate(20_000, maximum_raw_observations=10_000,
                                target_raw_observations=5_000)
    # The bound applies to derived CV rows, not to the ten authoritative addon
    # rows that happen to share the same table.
    assert result["removed"] == 5_010
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM observations WHERE source='ADDON_TELEMETRY'").fetchone()[0] == 10
        assert db.execute("SELECT COUNT(*) FROM consolidation_runs").fetchone()[0] == 1


def test_consolidation_treats_large_world3d_local_view_as_derived_cv(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    rows = [Observation.create({
        "session_id": "s", "frame_id": f"local-{index}", "timestamp": index,
        "world3d_batch": {"tracks": [{"track_id": str(index), "blob": "x" * 2048}]},
    }, index, "WORLD3D_LOCAL_VIEW") for index in range(10_020)]
    rows.extend(Observation.create({
        "session_id": "s", "frame_id": f"addon-{index}", "timestamp": 20_000 + index,
    }, 20_000 + index, "ADDON_TELEMETRY") for index in range(10))
    memory.observe_many(rows)

    result = memory.consolidate(
        30_000, maximum_raw_observations=10_000,
        target_raw_observations=5_000)

    assert result["cv_projections_removed"] == 5_020
    with sqlite3.connect(memory.path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM observations WHERE source='ADDON_TELEMETRY'").fetchone()[0] == 10
        assert db.execute(
            "SELECT COUNT(*) FROM observations WHERE source='WORLD3D_LOCAL_VIEW'").fetchone()[0] == 5_000


def test_verification_window_learns_from_successful_live_timings(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    context = memory.learning_context({"map_id": 1}, "QUEST")
    for index, latency in enumerate((.2, .3, .4, .5, .6, .7)):
        memory.record_action_timing("INTERACT", index, "SUCCESS", latency, context, {})
    window = memory.verification_window("INTERACT", context, 3.)
    assert window["source"] == "LIVE_CALIBRATED"
    assert window["samples"] == 6
    assert window["earliest"] <= window["likely_start"] <= window["likely_end"] <= window["deadline"]


def test_consolidation_bounds_journal_and_world_relations(tmp_path):
    # Live 2026-09-21: 12.6 h session -> world_relations 3.6 M rows / 1.4 GB,
    # journal 316 MB; nothing reads either back, consolidate() ignored both.
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    for index in range(120):
        memory.record("s", index, "MOVEMENT_CONTROL_UPDATE", {"i": index})
        memory.save_world_relation("s", {"relation_id": f"r{index}", "subject": f"track:{index}",
                                         "predicate": "observed_by", "object": f"observation:{index}",
                                         "at": index, "confidence": 1., "evidence": [], "status": "HYPOTHESIS"})
    memory.flush_world_relations()
    result = memory.consolidate(1_000)
    assert result["log_trims"] == {}  # far below the live caps -> untouched
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 120
        assert db.execute("SELECT COUNT(*) FROM world_relations").fetchone()[0] == 120

    # Push journal over the real cap (20_000) and check the oldest rows go.
    with sqlite3.connect(memory.path) as db:
        for index in range(120, 20_100):
            db.execute("INSERT INTO journal(session,at,kind,payload) VALUES (?,?,?,?)", ("s", index, "X", "{}"))
        db.commit()
    result = memory.consolidate(2_000)
    assert result["log_trims"]["journal"] == 100
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 20_000
        assert db.execute("SELECT MIN(at) FROM journal").fetchone()[0] == 100  # oldest rows went first
    with sqlite3.connect(memory.path) as db:
        db.executemany("INSERT INTO world_relations VALUES (?,?,?,?,?,?,?)",
                       (("s", f"x{index}", "track:a", "observed_by", f"observation:{index}", index, "{}")
                        for index in range(120, 50_050)))
        db.commit()
    result = memory.consolidate(3_000)
    assert result["log_trims"]["world_relations"] == 50
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM world_relations").fetchone()[0] == 50_000
        assert db.execute("SELECT MIN(at) FROM world_relations").fetchone()[0] == 50


def test_events_and_world_relations_trim_queries_have_a_matching_index(tmp_path):
    # consolidate() sorts events by (at,id) and world_relations by (at,rowid)
    # to find the oldest rows; idx_events_session_at and the subject/predicate
    # index on world_relations cannot serve that sort (session/subject lead
    # them), which forced a full-table scan + sort on every consolidate()
    # pass once either table crossed its trim threshold.
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    with sqlite3.connect(memory.path) as db:
        events_plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM events ORDER BY at,id LIMIT 5").fetchall()
        relations_plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT rowid FROM world_relations ORDER BY at,rowid LIMIT 5").fetchall()
    # "USE TEMP B-TREE FOR ORDER BY" is SQLite's tell for an unindexed sort
    # (a real full scan followed by an in-memory sort of every row); using
    # an index to satisfy the ORDER BY directly never needs one.
    assert not any("TEMP B-TREE" in str(row) for row in events_plan), events_plan
    assert not any("TEMP B-TREE" in str(row) for row in relations_plan), relations_plan


def test_events_over_cap_trims_oldest_first(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    with sqlite3.connect(memory.path) as db:
        db.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            ((f"e{index}", "s", float(index), "X", "SRC", None, "[]", "[]", "[]", "{}")
             for index in range(15_100)))
        db.commit()
    result = memory.consolidate(20_000)
    assert result["log_trims"]["events"] == 100
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 15_000
        assert db.execute("SELECT MIN(at) FROM events").fetchone()[0] == 100  # oldest rows went first


def test_runtime_sized_consolidation_never_exceeds_global_delete_budget(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    with sqlite3.connect(memory.path) as db:
        db.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            ((f"e{index}", "s", float(index), "X", "SRC", None,
              "[]", "[]", "[]", "{}") for index in range(15_400)))
        db.executemany(
            "INSERT INTO journal(session,at,kind,payload) VALUES (?,?,?,?)",
            (("s", index, "X", "{}") for index in range(20_400)))
        db.commit()

    first = memory.consolidate(20_000, maximum_rows_per_pass=256)

    assert sum(first["log_trims"].values()) <= 256
    assert first["more_maintenance_due"] is True
    assert first["backlog_rows"] > 0
    with sqlite3.connect(memory.path) as db:
        remaining_overflow = (
            db.execute("SELECT COUNT(*) FROM events").fetchone()[0] - 15_000
            + db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] - 20_000)
    assert remaining_overflow == 800-sum(first["log_trims"].values())


def test_authoritative_observations_are_not_reported_as_cv_cleanup_backlog(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    with sqlite3.connect(memory.path) as db:
        db.executemany(
            "INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
            ((f"truth-{index}", "old", float(index), "PLAYER_STATE", "c", "{}", index)
             for index in range(20_000)))
        db.executemany(
            "INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
            ((f"cv-{index}", "old", 30_000. + index, "WORLD3D_LOCAL_VIEW", "c", "{}",
              30_000 + index) for index in range(2)))
        db.commit()

    result = memory.consolidate(
        40_000, maximum_raw_observations=10_000,
        target_raw_observations=5_000, maximum_rows_per_pass=256)

    assert result["cv_projections_removed"] == 0
    assert result["backlog_rows"] == 0
    assert result["more_maintenance_due"] is False


def test_memory_batch_commits_multiple_writes_as_one_unit(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    with memory.batch():
        memory.record("s", 1., "A", {})
        memory.record("s", 2., "B", {})
        memory.record("s", 3., "C", {})
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 3


def test_memory_batch_rolls_back_every_nested_write_on_a_later_failure(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    try:
        with memory.batch():
            memory.record("s", 1., "A", {})
            memory.record("s", 2., "B", {})
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    # Even though the first two writes each looked like a complete `_tx()`
    # call, neither should have committed on its own -- the whole batch is
    # one transaction and a later failure must undo all of it.
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 0


def test_nested_tx_depth_returns_to_zero_after_a_batch(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    with memory.batch():
        memory.record("s", 1., "A", {})
    assert memory._tx_depth == 0
