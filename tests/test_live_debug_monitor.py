import json

import pytest

from tools.live_debug_monitor import (RotatingJsonlWriter, discover_status,
                                      format_change, summarize, telemetry_row)


def test_monitor_extracts_control_perception_and_safety_state():
    status = {"pid": 12, "mode": "FULL_AI", "sensor": "streaming",
        "decision": {"skill": "MOVE", "reason": "committed"},
        "result": {"outcome": "SUCCESS", "skill": "TARGET"},
        "autonomous_loop": {"phase": "APPROACHING", "last_replan_trigger": "TARGET_SELECTED",
                            "commitment": {"commitment_id": "c1", "target_guid": "g1"}},
        "movement_controller": {"phase": "FORWARD", "stuck_belief": "UNKNOWN"},
        "binding_preflight": {"ready": True, "missing": []},
        "world": {"fresh": True, "sensor_age": .1, "session_id": "s",
                  "player": {"map_id": 1409, "position": {"x": .2, "y": .3},
                             "active_quests": [{"quest_id": 1}],
                             "target": {"guid": "g1", "name": "Unknown until addon"}}},
        "vision_diagnostics": {"world": {"status": "ready", "duration_ms": 90, "candidates": 4},
                               "minimap": {"status": "ready", "duration_ms": 20, "candidates": 2},
                               "world3d_v2": {"generic_candidates": 3, "output_candidates": 4,
                                              "camera_motion_px": {"dx": 2, "dy": 0}},
                               "tracks": [{"source": "WORLD3D", "state": "STABLE"}]}}
    value = summarize(status)
    assert value["phase"] == "APPROACHING"
    assert value["commitment"]["target_guid"] == "g1"
    assert value["vision"]["stable_world_tracks"] == 1
    assert value["vision"]["generic_candidates"] == 3
    assert value["binding_ready"] is True
    assert format_change(value, None)


def test_monitor_emits_only_meaningful_changes():
    value = summarize({"mode": "MANUAL", "world": {}, "vision_diagnostics": {}})
    assert format_change(value, value) == []


def test_monitor_reads_unified_v3_v4_diagnostics():
    value = summarize({"vision_diagnostics": {
        "world3d_v3_v4": {"version": "world3d_v3_unified", "mode": "WORLD3D",
            "detector": {"refreshed": False, "last_refresh_ms": 143,
                         "generic_candidates": 7},
            "tracker": {"mode": "CPU_PATCH_PROPAGATION", "tracks": 12},
            "ocr": {"backend": "unavailable", "status": "backend_unavailable", "texts": 0}},
        "hard_examples": {"saved": 3}}})
    assert value["vision"]["pipeline_version"] == "world3d_v3_unified"
    assert value["vision"]["tracker_tracks"] == 12
    assert value["vision"]["ocr_status"] == "backend_unavailable"
    assert value["vision"]["hard_examples"] == 3


def test_monitor_surfaces_combat_hint_and_capture_backend():
    # PREPARED 2026-09-14, UNTESTED LIVE alongside combat_hint (addon 0.9.18/
    # telemetry_packets.py/world.py) and the DXGI capture backend
    # (dxgi_capture.py). This is the field to watch live: both values stay
    # None until a landed cast is actually fast-lane-confirmed, and the
    # backend name confirms at a glance which capture path is active.
    status = {"world": {"player": {"combat_last_spell_id": 123, "combat_last_cast_at": 45.6}},
              "sensor_diagnostics": {"capture_geometry": {"backend": "dxgi"}}}
    value = summarize(status)
    assert value["combat_hint"] == {"spell_id": 123, "cast_at": 45.6}
    assert value["sensor_diagnostics"]["capture_geometry"]["backend"] == "dxgi"
    previous = {**value, "combat_hint": {"spell_id": None, "cast_at": None}}
    assert any(line.startswith("combat_hint=") for line in format_change(value, previous))


def test_telemetry_row_extracts_the_raw_ingestable_player_state():
    # world.player is exactly self.state from WorldModel.snapshot() -- the
    # same shape AutonomousAgent.tick()'s payload argument expects -- so this
    # needs no addon/pixel decoding, unlike screenshot_session_replay.py's
    # (verified, live-tested) dead end with sparse live-capture screenshots.
    status = {"world": {"player": {"map_id": 1409, "target": {"guid": "g1"}}}}
    assert telemetry_row(status, 12.5) == {"at": 12.5, "state": {"map_id": 1409, "target": {"guid": "g1"}}}


def test_telemetry_row_skips_ticks_with_no_addon_state_yet():
    assert telemetry_row({"world": {"player": {}}}, 1.0) is None
    assert telemetry_row({"world": {}}, 1.0) is None
    assert telemetry_row({}, 1.0) is None


def test_jsonl_writer_rotates_and_keeps_a_bounded_number_of_segments(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    writer = RotatingJsonlWriter(path, max_bytes=80, backups=2)
    for index in range(12):
        writer.write({"index": index, "payload": "x" * 25})

    segments = sorted(tmp_path.glob("telemetry*.jsonl"))
    assert [item.name for item in segments] == [
        "telemetry.1.jsonl", "telemetry.2.jsonl", "telemetry.jsonl"]
    assert all(item.stat().st_size <= 80 for item in segments)
    rows = [json.loads(line) for item in segments
            for line in item.read_text(encoding="utf-8").splitlines()]
    assert rows
    assert max(row["index"] for row in rows) == 11


def test_telemetry_rows_replay_through_the_real_offline_harness(tmp_path):
    # End-to-end proof that a live_debug_monitor telemetry-*.jsonl file (not
    # just its shape in isolation) is directly consumable by the same
    # replay() the project already uses for tests/fixtures/agent_quest_replay.jsonl.
    from wowbot.agent.runtime import replay

    rows = [
        telemetry_row({"world": {"player": {"map_id": 1409, "monotonic_time": 0.0}}}, 0.0),
        telemetry_row({"world": {"player": {"map_id": 1409, "monotonic_time": 0.5,
                                             "target": {"guid": "g1"}}}}, 0.5),
    ]
    telemetry_path = tmp_path / "telemetry.jsonl"
    telemetry_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = replay(telemetry_path, tmp_path, goal="Questelj")

    assert result["frames"] == 2
    assert result["offline"] is True


def test_monitor_surfaces_tagged_obstacle_count_and_bearing():
    # PREPARED 2026-09-14, UNTESTED LIVE, alongside obstacle_perception.py.
    status = {"world": {"player": {"visual_candidates": [
        {"detector_kind": "obstacle_candidate", "x": .2},
        {"detector_kind": "obstacle_candidate", "x": .4},
        {"kind": "unknown_subject_candidate", "x": .9},
    ]}}}
    value = summarize(status)
    assert value["obstacle"]["count"] == 2
    assert value["obstacle"]["bearing"] == pytest.approx(0.3)
    previous = {**value, "obstacle": {"count": 0, "bearing": None}}
    assert any(line.startswith("obstacle=") for line in format_change(value, previous))


def test_monitor_reports_no_obstacle_when_nothing_is_tagged():
    value = summarize({"world": {"player": {"visual_candidates": []}}})
    assert value["obstacle"] == {"count": 0, "bearing": None}


def test_discovery_switches_to_newest_pid_status(tmp_path):
    old = tmp_path / "pid-10" / "agent_status.json"
    new = tmp_path / "pid-20" / "agent_status.json"
    old.parent.mkdir(); new.parent.mkdir()
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    old.touch(); new.touch()
    import os
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_700_000_100, 1_700_000_100))
    assert discover_status(tmp_path) == new
    assert discover_status(tmp_path, 10) == old
