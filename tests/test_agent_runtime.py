import json
from pathlib import Path
import time
import pytest

from wowbot.agent.runtime import (
    AgentRuntime, replay, _manual_mouseover_learning_probe, _publishable_visual_matches,
    _VisualRecognitionStabilizer,
)
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Mode, Goal, Proposal, Observation
from wowbot.agent.world import WorldModel
from wowbot.agent.reasoner import OllamaReasoner
from wowbot.agent.memory import AgentMemory
from concurrent.futures import Future
from test_agent_core import state, binding_file


class Sensor:
    health = "offline_mock"
    frame = None
    def __init__(self): self.payload = None
    def poll(self, now):
        result, self.payload = self.payload, None
        return result


class ForegroundBackend:
    def __init__(self):
        self.foreground = True

    def is_selected_foreground(self):
        return self.foreground

    def emergency_pressed(self):
        return False


class SparseTelemetryVision:
    status = "ready"
    diagnostics = {"world": {"status": "ready"}}

    def __init__(self):
        self.calls = 0
        self.action_ready = True
        self.projection_revision = 0
        self.projection_at = 0.
        self.epoch = 1

    def update(self, frame, now, **kwargs):
        self.calls += 1
        self.projection_revision += 1
        self.projection_at = now
        return [{"source": "WORLD3D", "kind": "unknown_subject_candidate",
                 "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
                 "track_id": "WORLD3D:quest-start", "stable_frames": 4,
                 "confidence": .74, "x": .5, "y": .7, "inspectable": True,
                 "information_value": "HIGH",
                 "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED",
                                       "symbol_track_id": "WORLD3D:symbol"}]}]

    def close(self):
        pass

    def ready_for_action(self, now):
        return self.action_ready


def test_manual_mouseover_learning_requires_exact_fresh_visual_cursor_association():
    candidate = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                 "detector_kind": "unknown_subject_candidate", "x": .51, "y": .49,
                 "visual_signature": {"signature_id": "signed-crop"}}
    payload = {"mouseover": {"guid": "Creature-test"},
               "cursor_position": {"nx": .51, "ny": .49},
               "cursor_sample_time": 10., "mouseover_sample_time": 10.02}
    probe = _manual_mouseover_learning_probe(payload, [candidate])
    assert probe and probe["manual_mouseover_ground_truth"] is True
    assert probe["mouseover_association_distance"] == 0.
    assert _manual_mouseover_learning_probe({**payload, "mouseover_sample_time": 10.2}, [candidate]) is None
    assert _manual_mouseover_learning_probe(payload, [{**candidate, "x": .6}]) is None


def test_runtime_publishes_only_high_precision_visual_reidentification():
    matches = [
        {"identity_key": "npc:weak", "match_method": "APPROXIMATE_VISUAL_REIDENTIFICATION", "similarity": .89},
        {"identity_key": "npc:strong", "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION", "similarity": .90},
        {"identity_key": "npc:exact", "match_method": "EXACT_VISUAL_SIGNATURE", "similarity": 1.0},
        {"identity_key": "unknown:Player-1", "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION", "similarity": 1.0},
    ]
    assert [match["identity_key"] for match in _publishable_visual_matches(matches)] == [
        "npc:strong", "npc:exact",
    ]


def test_visual_recognition_requires_repeated_track_local_evidence():
    stabilizer = _VisualRecognitionStabilizer()
    spear = {"identity_key": "npc:150228", "similarity": .94,
             "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"}
    water = {"identity_key": "npc:150229", "similarity": .92,
             "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"}
    assert stabilizer.update("WORLD3D:8", [spear], 1.0) == []
    assert stabilizer.update("WORLD3D:8", [spear], 1.2) == []
    confirmed = stabilizer.update("WORLD3D:8", [spear], 1.4)
    assert confirmed[0]["identity_key"] == "npc:150228"
    assert confirmed[0]["temporal_support_frames"] == 3
    # A one-frame alternative from an adjacent creature never becomes an
    # evidence candidate, even after the first track has stabilised.
    assert stabilizer.update("WORLD3D:8", [water], 1.6) == []


def test_runtime_starts_manual_and_publishes_exact_cache(tmp_path):
    cache = binding_file(tmp_path)
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, cache, tmp_path / "output", sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Menj oda", 1, {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        sensor.payload = state()
        result = runtime.step(1)
        assert result["mode"] == "MANUAL" and not exe.commands
        assert result["bindings_cache"] == str(cache.resolve())
        runtime.mode("ASSIST")
        sensor.payload = state(2)
        result = runtime.step(2)
        assert result["decision"]["skill"] == "MOVE" and not exe.commands
        assert (tmp_path / "output" / "agent_status.json").exists()
    finally:
        runtime.close()


def test_runtime_wires_explicit_learned_model_into_canonical_world3d_pipeline(
        tmp_path, monkeypatch):
    cache = binding_file(tmp_path)
    sentinel_detector = object()
    seen = {}

    def build(model_path, *, capture_handle=None):
        seen["model_path"] = model_path
        seen["capture_handle"] = capture_handle
        return sentinel_detector

    monkeypatch.setattr(
        "wowbot.vision.world3d.learned_detector.build_runtime_learned_detector",
        build,
    )
    runtime = AgentRuntime(
        42, cache, tmp_path / "output", sensor=Sensor(),
        executor=RecordingExecutor(), world3d_model=tmp_path / "trained.pt")
    try:
        assert seen["model_path"] == tmp_path / "trained.pt"
        # An injected sensor has no capture process, so no capture-driven feed.
        assert seen["capture_handle"] is None
        assert runtime.perception.world3d.v2.learned_detector is sentinel_detector
    finally:
        runtime.close()


def test_fast_payload_compaction_drops_inherited_full_state_baggage():
    payload = state(
        transport_kind="FAST", fast_sequence=44,
        player_world_position={"x": 1., "y": 2., "instance_id": 2175},
        inventory={"items": [{"item_id": index} for index in range(1000)]},
        binding_catalog_page={"rows": ["large"] * 1000},
        active_quests=[{"quest_id": 1}],
    )

    compact = AgentRuntime._compact_fast_payload(payload)

    assert compact["fast_sequence"] == 44
    assert compact["player_world_position"]["x"] == 1.
    assert "inventory" not in compact
    assert "binding_catalog_page" not in compact
    assert "active_quests" not in compact


def test_slow_medium_tick_leaves_a_real_fast_control_window_after_completion(tmp_path):
    """A medium overrun must not starve the movement consumer.

    Live 2026-09-23 had a ~29 Hz pixelstrip source but only ~4.7 Hz movement
    consumption: the next medium deadline was measured from the *start* of a
    ~300 ms medium tick, so it was already due again almost immediately.  This
    reproduces an overrun and proves fresh FAST packets are consumed before a
    second expensive tick is allowed.
    """
    sensor, executor = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=executor, vision=False)
    try:
        now = time.monotonic()
        runtime.agent.set_goal("Menj oda", now,
                               {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.agent.set_mode(Mode.FULL_AI)
        runtime.agent.tick(state(now), now)
        assert runtime.agent.pending and runtime.agent.pending.proposal.skill == "MOVE"

        ordinary_tick = runtime.agent.tick
        medium_calls = 0

        def deliberately_slow_tick(payload, at, supplemental=()):
            nonlocal medium_calls
            medium_calls += 1
            time.sleep(.36)  # longer than the configured 1/3 s medium period
            return ordinary_tick(payload, at, supplemental)

        runtime.agent.tick = deliberately_slow_tick
        runtime.started = True
        before = runtime.agent._fast_control_updates
        for sequence in range(10):
            sample_at = time.monotonic()
            sensor.payload = state(
                sample_at, transport_kind="FAST", telemetry_lane="FAST_STATE",
                fast_sequence=sequence + 1,
                position={"x": .5, "y": .499},
                movement={"speed": 7., "moving": True})
            runtime.step(sample_at)
            time.sleep(.01)

        assert medium_calls == 1
        assert runtime.agent._fast_control_updates - before >= 9
    finally:
        runtime.close()


def test_fast_movement_lane_keeps_pumping_passive_world3d_tracker(tmp_path):
    """FAST movement packets must not starve the independent visual tracker."""
    sensor, executor = Sensor(), RecordingExecutor()
    sensor.frame = (bytes(4 * 64 * 48), 64, 48)
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=executor, vision=False)
    runtime.perception = SparseTelemetryVision()
    try:
        now = time.monotonic()
        runtime.agent.set_goal("Menj oda", now,
                               {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.agent.set_mode(Mode.FULL_AI)
        runtime.agent.tick(state(now), now)
        assert runtime.agent.pending and runtime.agent.pending.proposal.skill == "MOVE"
        runtime._next_medium_at = now + 10.

        sensor.payload = state(
            now + .02, transport_kind="FAST", telemetry_lane="FAST_STATE",
            fast_sequence=1, position={"x": .5, "y": .499},
            movement={"speed": 7., "moving": True})
        runtime.step(now + .02)

        assert runtime.perception.calls == 1
        assert runtime.agent._fast_control_updates >= 1
    finally:
        runtime.close()


def test_runtime_close_persists_stopped_and_released_input_state(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    output = tmp_path / "output"
    runtime = AgentRuntime(42, binding_file(tmp_path), output,
                           sensor=sensor, executor=exe, vision=False)
    sensor.payload = state()
    runtime.step(1)
    runtime.close()

    final_status = json.loads((output / "agent_status.json").read_text(encoding="utf-8"))
    assert final_status["mode"] == "STOPPED"
    assert final_status["arm_in"] is None
    assert final_status["input_safety"]["held_keys"] == []
    assert final_status["input_safety"]["armed"] is False


def test_runtime_saves_an_auto_labeled_example_when_mouseover_matches_a_tracked_candidate(tmp_path):
    # End-to-end wiring check for AutoLabeledExampleCollector (vision_dataset.py):
    # the detailed labeling/cooldown/limit logic itself is covered directly in
    # test_vision_dataset.py -- this only proves AgentRuntime.step() actually
    # reaches it with real sensor.frame + world.state, and that the result
    # surfaces in agent_status.json for the live debugger to show.
    sensor, exe = Sensor(), RecordingExecutor()
    sensor.frame = (bytes(64*64*4), 64, 64)
    runtime = AgentRuntime(42, binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n'), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        sensor.payload = state(
            1, mouseover={"guid": "Creature-1", "name": "Murky", "npc_id": 555, "attackable": True},
            cursor_position={"nx": .5, "ny": .5},
            visual_candidates=[{"kind": "unknown_subject_candidate", "track_id": 7, "x": .5, "y": .5,
                                "bbox": {"left": 10, "top": 10, "right": 40, "bottom": 60}}])
        result = runtime.step(1)
        assert result["vision_dataset"]["saved"] == 1
        saved = list((tmp_path / "output" / "vision-dataset" / "meta").glob("*.json"))
        assert len(saved) == 1
    finally:
        runtime.close()


def test_runtime_fast_lane_does_not_republish_slow_quest_projection(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        sensor.payload = state(1, transport_kind="STATE", telemetry_lane="FULL_STATE",
                               active_quests=[{"quest_id": 1, "objectives": []}])
        runtime.step(1)
        quest_observations = sum(obs.source == "QUEST_STATE"
                                 for obs in runtime.agent.world.history)
        sensor.payload = state(2, transport_kind="FAST", telemetry_lane="FAST_STATE",
                               fast_sequence=2, movement={"speed": 7, "moving": True},
                               active_quests=[{"quest_id": 999, "objectives": []}])
        runtime.step(2)
        assert sum(obs.source == "QUEST_STATE" for obs in runtime.agent.world.history) == quest_observations
        assert runtime.agent.world.state["active_quests"][0]["quest_id"] == 1
        assert runtime.agent.world.state["movement"]["moving"] is True
    finally:
        runtime.close()


def test_reference_reach_gets_fast_world3d_interrupt_between_addon_samples(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    sensor.frame = (bytes(4 * 640 * 480), 640, 480)
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)

    runtime.perception = SparseTelemetryVision()
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.agent.planner.map_search_exhausted = True
        runtime.agent.planner.map_search_context = ("test:player-1", 1409, None)
        reference = {"source": "TDB_REFERENCE", "source_sha256": "digest",
            "world_map_id": 2175, "x": 20., "y": 0., "z": 0.,
            "distance_yards": 20., "coordinate_space": "WORLD_YARDS",
            "spawn_ids": [1], "npc_ids": [156626], "quest_ids": [54951],
            "role_hypothesis": "QUEST_STARTER", "identity_confirmed": False}
        initial = state(1, map_id=1409, world_map_open=False,
            player_world_position={"x": 0., "y": 0., "z": 0., "instance_id": 2175},
            quest_role_reference_candidates=[reference])
        runtime.agent.set_mode(Mode.FULL_AI)
        first = runtime.agent.tick(initial, 1.)
        assert first["pending"]["proposal"]["skill"] == "REACH_LOCATION"

        second = runtime.step(1.1)  # no addon payload; only fresh World3D
        assert exe.stops >= 1
        assert second["result"]["reason"] == "live_visual_inspection_candidate_observed"
        assert second["decision"]["skill"] == "INSPECT"
        assert second["world"]["observation_sources"]["WORLD3D"] == 1
    finally:
        runtime.close()


def test_vision_keeps_running_between_sparse_complete_telemetry_payloads(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    sensor.frame = (bytes(4 * 640 * 480), 640, 480)
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    runtime.perception = SparseTelemetryVision()
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.step(1.)  # no complete pixel-strip payload
        assert runtime.perception.calls == 1
        runtime.agent.set_mode(Mode.ASSIST)
        sensor.payload = state(2., world_map_open=False, active_quests=[])
        result = runtime.step(2.)
        assert runtime.perception.calls == 2
        assert result["decision"]["skill"] == "INSPECT"
        assert result["decision"]["parameters"]["track_id"] == "WORLD3D:quest-start"
        assert not exe.commands  # MANUAL remains read-only
    finally:
        runtime.close()


def test_committed_visual_servo_requests_40hz_tracker_with_cpu_backpressure():
    # Exercise the production scheduler contract without requiring a frame.
    from wowbot.agent.perception import PerceptionWorker
    worker = PerceptionWorker()
    try:
        worker.lanes["world"]["duration_ms"] = 5.
        # 45 Hz admission headroom absorbs periodic canonical/minimap work
        # while the public completed-tracker target remains at least 40 Hz.
        assert worker._dynamic_interval("world", {"fast_visual_servo": True}) == pytest.approx(1/45)
        worker.lanes["world"]["duration_ms"] = 60.
        assert worker._dynamic_interval("world", {"fast_visual_servo": True}) == pytest.approx(.066)
        # A slow full detector must not throttle the cheap tracker lane. V3
        # owns the independent heavy-refresh deadline.
        worker.lanes["world"]["duration_ms"] = 700.
        worker._propagate_duration_ms = 12.
        assert worker._dynamic_interval("world", {"fast_visual_servo": True}) == pytest.approx(1/45)
    finally:
        worker.close()


def test_slow_detector_refresh_does_not_throttle_balanced_tracker_lane():
    from wowbot.agent.perception import PerceptionWorker
    worker = PerceptionWorker()
    try:
        worker.lanes["world"]["duration_ms"] = 131.
        worker._detector_duration_ms = 131.
        worker._propagate_duration_ms = 4.1
        assert worker._dynamic_interval("world", {}) == pytest.approx(1/40)
    finally:
        worker.close()


def test_single_propagation_spike_does_not_permanently_throttle_tracker():
    from wowbot.agent.perception import PerceptionWorker
    worker = PerceptionWorker()
    try:
        worker._propagate_duration_ms = 244.
        worker._propagate_duration_window_ms.extend((244., 8., 9.))
        assert worker._dynamic_interval(
            "world", {"fast_visual_servo": True}) == pytest.approx(1/45)

        worker._propagate_duration_window_ms.clear()
        worker._propagate_duration_window_ms.extend((58., 60., 62.))
        assert worker._dynamic_interval(
            "world", {"fast_visual_servo": True}) == pytest.approx(.066)
    finally:
        worker.close()


def test_world_map_publication_does_not_count_as_world3d_tracker_or_detector():
    from wowbot.agent.perception import PerceptionWorker
    worker = PerceptionWorker()
    frame = (bytes(4 * 320 * 240), 320, 240)
    worker.pipeline._world_map = lambda *_: []
    try:
        worker.update(frame, 1., world_map_open=True)
        deadline = time.monotonic() + 1.
        while (worker.lanes["world"]["future"] is not None
               and not worker.lanes["world"]["future"].done()
               and time.monotonic() < deadline):
            time.sleep(.005)
        worker.update(frame, 1.1, world_map_open=True)
        assert len(worker.tracker_rate.samples) == 0
        assert len(worker.detector_rate.samples) == 0
        assert worker._detector_duration_ms is None
        assert worker._propagate_duration_ms is None
    finally:
        worker.close()


def test_world_lane_reports_split_detector_and_tracker_cost():
    from wowbot.agent.perception import PerceptionWorker
    worker = PerceptionWorker()
    try:
        worker._detector_duration_ms = 325.
        worker._propagate_duration_ms = 250.
        rates = worker.rates(1.)
        assert "world_detector_hz" in rates
        assert "world_tracker_hz" in rates
        worker.lanes["world"]["at"] = 1.
        worker.lanes["world"]["items"] = []
        worker.visual_tracks.snapshot = lambda: []
        worker.update(None, 1.)
        world = worker.diagnostics["world"]
        assert world["detector_duration_ms"] == 325.
        assert world["propagate_duration_ms"] == 250.
    finally:
        worker.close()


def test_runtime_arming_cannot_start_without_sensor(tmp_path):
    runtime = AgentRuntime(42, binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n'), tmp_path / "output", sensor=Sensor(), executor=RecordingExecutor(), vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.mode("FULL_AI")
        assert runtime.agent.mode == Mode.MANUAL
        runtime.arm_at = 2
        runtime.arm_deadline = 2
        result = runtime.step(2)
        assert result["mode"] == "MANUAL" and result["result"]["outcome"] == "CANCELLED"
    finally:
        runtime.close()


def test_arming_uses_new_observation_and_waits_with_no_input(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output", sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Menj oda", 1, {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 2, 12
        result = runtime.step(2)
        assert result["mode"] == "MANUAL" and result["arm_waiting_for_fresh_state"] and not exe.commands
        sensor.payload = state(3)
        result = runtime.step(3)
        assert result["mode"] == "FULL_AI" and exe.commands
    finally:
        runtime.close()


def test_arming_exposes_exact_blockers_instead_of_generic_strip_error(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Menj oda", 1,
                               {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 2., 20.
        result = runtime.step(2.)
        assert result["mode"] == "MANUAL"
        assert "waiting_for_fresh_addon_state" in result["arm_blockers"]
        assert not exe.commands
    finally:
        runtime.close()


def test_full_ai_suspends_through_temporary_telemetry_outage_and_recovers(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Explore", 1)
        runtime.agent.set_mode(Mode.FULL_AI)
        sensor.payload = state(1.)
        runtime.step(1.)

        suspended = runtime.step(8.)
        stops_after_suspend = exe.stops
        assert suspended["mode"] == "FULL_AI"
        assert suspended["decision"]["reason"] == \
            "telemetry_suspended_waiting_for_stable_recovery"

        sensor.payload = state(8.1)
        first = runtime.step(8.1)
        assert first["mode"] == "FULL_AI"
        assert first["decision"]["reason"] == \
            "telemetry_suspended_waiting_for_stable_recovery"
        assert exe.stops == stops_after_suspend

        sensor.payload = state(8.2)
        recovered = runtime.step(8.2)
        assert recovered["mode"] == "FULL_AI"
        assert recovered["decision"]["reason"] != \
            "telemetry_suspended_waiting_for_stable_recovery"
    finally:
        runtime.close()


def test_focus_loss_pauses_planner_once_before_backend_rejection_can_demote(tmp_path):
    sensor, exe, backend = Sensor(), RecordingExecutor(), ForegroundBackend()
    exe.backend = backend
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Explore", 1)
        sensor.payload = state(1.)
        runtime.step(1.)
        runtime.agent.set_mode(Mode.FULL_AI)
        stops_before = exe.stops
        backend.foreground = False

        paused = runtime.step(2.)
        assert paused["mode"] == "FULL_AI"
        assert paused["sensor"] == "selected_PID_not_foreground"
        assert paused["decision"]["reason"] == "selected_pid_foreground_suspended"
        assert exe.stops == stops_before + 1

        runtime.step(2.5)
        assert exe.stops == stops_before + 1
        demoted = runtime.step(17.1)
        assert demoted["mode"] == "MANUAL"
    finally:
        runtime.close()


def test_arming_rechecks_bindings_against_fresh_actionbar(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    cache = binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n')
    runtime = AgentRuntime(42, cache, tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1)
        # Click-time state has no actionbar entries, so only the fresh arming
        # observation can reveal the unbound harmful action.
        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = state(2, actionbar=[{
            "action": "ACTIONBUTTON2", "is_harmful": True, "is_usable": True}])
        result = runtime.step(2)

        assert result["mode"] == "MANUAL"
        assert result["result"]["outcome"] == "CANCELLED"
        assert result["result"]["missing_bindings"] == ["ACTIONBUTTON2"]
        assert result["binding_preflight"]["ready"] is False
        assert not exe.commands
    finally:
        runtime.close()


def test_arming_does_not_reject_stale_actionbar_before_fresh_sample(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    cache = binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n')
    runtime = AgentRuntime(42, cache, tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1)
        sensor.payload = state(1, actionbar=[{
            "action": "ACTIONBUTTON2", "is_harmful": True, "is_usable": True}])
        runtime.step(1)

        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = state(2, actionbar=[{
            "action": "ACTIONBUTTON1", "is_harmful": True, "is_usable": True}])
        result = runtime.step(2)

        assert result["mode"] == "FULL_AI"
        assert result["binding_preflight"]["ready"] is True
    finally:
        runtime.close()


def test_arming_rejects_exact_client_binding_mismatch(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n'), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = state(2,
            control_bindings={"MOVEFORWARD": {"primary": "W", "secondary": ""},
                              "TURNLEFT": {"primary": "Z", "secondary": ""},
                              "TURNRIGHT": {"primary": "D", "secondary": ""},
                              "JUMP": {"primary": "SPACE", "secondary": ""},
                              "INTERACTTARGET": {"primary": "F", "secondary": ""},
                              "TARGETNEARESTENEMY": {"primary": "TAB", "secondary": ""}},
            binding_catalog_page={"status": "ok", "revision": 1, "binding_set": 1,
                                  "page": 0, "pages": 1, "count": 0, "rows": {}})
        result = runtime.step(2)
        assert result["mode"] == "MANUAL"
        assert result["result"]["outcome"] == "CANCELLED"
        assert result["result"]["binding_mismatches"] == [
            {"action": "TURNLEFT", "client": ["Z"], "selected_cache": ["A"]}]
        assert not exe.commands
    finally:
        runtime.close()


def test_full_ai_stops_when_late_client_binding_mismatch_arrives(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Menj oda", 1,
                               {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.agent.set_mode(Mode.FULL_AI)
        sensor.payload = state(2,
            control_bindings={"MOVEFORWARD": {"primary": "W", "secondary": "UP"},
                              "TURNLEFT": {"primary": "Z", "secondary": ""},
                              "TURNRIGHT": {"primary": "RIGHT", "secondary": "D"}},
            binding_catalog_page={"status": "ok", "revision": 1, "binding_set": 1,
                                  "page": 0, "pages": 1, "count": 0, "rows": {}})
        result = runtime.step(2)
        assert result["mode"] == "MANUAL"
        assert result["result"]["reason"].startswith("Az élő kliens bindingje eltér")
        assert not exe.diagnostics()["held_keys"]
    finally:
        runtime.close()


def test_arming_waits_for_a_recent_completed_world3d_result(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    sensor.frame = (bytes(4 * 640 * 480), 640, 480)
    runtime = AgentRuntime(42, binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n'), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    vision = SparseTelemetryVision()
    vision.action_ready = False
    runtime.perception = vision
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.test_step(actions=1, seconds=5)
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = state(2., world_map_open=False, active_quests=[])
        result = runtime.step(2.)
        assert result["mode"] == "MANUAL"
        assert result["arm_waiting_for_fresh_state"]
        assert not exe.commands

        vision.action_ready = True
        sensor.payload = state(3., world_map_open=False, active_quests=[])
        result = runtime.step(3.)
        assert result["mode"] == "FULL_AI"
        assert result["decision"]["skill"] == "INSPECT"
        assert exe.commands
    finally:
        runtime.close()


def test_bounded_run_stops_even_if_no_action_is_available(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output", sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Explore", 1)
        runtime.test_step(actions=60, seconds=2)
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = state(2)
        runtime.step(2)
        sensor.payload = state(4)
        result = runtime.step(4)
        assert result["mode"] == "MANUAL"
        assert result["result"]["reason"] == "bounded_live_test_timeout"
        assert not exe.commands
    finally:
        runtime.close()


def test_bounded_run_grants_one_short_window_for_confirmed_quest_dialog(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.agent.set_mode(Mode.FULL_AI)
        runtime.test_deadline = 2.
        runtime._test_dialog_grace_enabled = True
        sensor.payload = state(2, quest_ui={
            "open": True, "action": "ACCEPT", "quest_id": 55122,
            "x": .35, "y": .45,
        })
        result = runtime.step(2.)
        assert result["mode"] == "FULL_AI"
        assert runtime.test_deadline is None
        assert runtime.test_dialog_grace_deadline == pytest.approx(7.)
        assert runtime._test_dialog_grace_used is True
        assert any(command.kind == "CLICK" for command in exe.commands)
    finally:
        runtime.close()


def test_bounded_run_does_not_extend_for_unaddressable_quest_dialog(tmp_path):
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.agent.set_mode(Mode.FULL_AI)
        runtime.test_deadline = 2.
        runtime._test_dialog_grace_enabled = True
        sensor.payload = state(2, quest_ui={"open": True, "action": "ACCEPT", "x": 0, "y": 0})
        result = runtime.step(2.)
        assert result["mode"] == "MANUAL"
        assert result["result"]["reason"] == "bounded_live_test_timeout"
        assert not exe.commands
    finally:
        runtime.close()


def test_complete_offline_quest_combat_loot_turnin_replay(tmp_path):
    path = Path(__file__).parent / "fixtures" / "agent_quest_replay.jsonl"
    result = replay(path, tmp_path)
    assert result["offline"] is True
    assert result["frames"] == 8
    # The fixture still contains a legacy normalized-map turn-in waypoint and
    # no mmap source.  That marker is search evidence, not a traversable world
    # route, so the agent must no longer emit the former direct-line MOVE.
    assert len(result["commands"]) == 6
    assert result["status"]["goal"]["completed_steps"] == 6
    assert result["status"]["goal"]["failures"] == 0
    assert result["status"]["result"]["skill"] == "QUEST_DIALOG"
    assert result["status"]["result"]["outcome"] == "SUCCESS"
    assert result["status"]["decision"]["skill"] == "WAIT"
    relations = result["status"]["world"]["relations"]
    assert any(edge["predicate"] == "observed_by" for edge in relations)
    predicates = {edge["predicate"] for edge in relations}
    assert {"has_subgoal", "planned_by", "selected_action", "verified_by", "resolved_by"} <= predicates
    assert any(event["event_type"] == "AGENT_VERIFICATION"
               for event in result["status"]["world"]["event_records"])
    session = result["status"]["world"]["session_id"]
    assert AgentMemory(tmp_path / "replay_memory.sqlite3").world_relations(session)
    assert result["hydration"]["verified"] is True
    assert all(result["hydration"]["checks"].values())
    package = json.loads((tmp_path / "replay_package.json").read_text(encoding="utf-8"))
    assert package["format"] == "AIPC_REPLAY_PACKAGE_V1"
    assert package["config_snapshot"]["input_backend"] == "RECORDING_EXECUTOR"
    assert len(package["world_state_deltas"]) == 8
    assert len(package["trace"]) == 8
    assert package["frame_references"] == []


def test_ollama_cannot_invent_actions_or_override_combat():
    reasoner = OllamaReasoner({"enabled": False})
    try:
        world = WorldModel()
        world.ingest(Observation.create(state(), 1))
        goal = Goal.parse("Questelj", 1)
        proposals = [Proposal.make("COMBAT", "defend", priority=100), Proposal.make("MOVE", "walk", priority=40)]
        assert reasoner.advise(goal, world, proposals, 1) == proposals[0]
        # Even an arbitrary model string is never interpreted as executable code.
        reasoner.answer = ("unknown", "__import__('os').system('something')", "ignore rules")
        assert reasoner.advise(goal, world, proposals, 2) == proposals[0]
    finally:
        reasoner.close()


def test_ai_reasoning_is_bounded_hypothesis_with_only_allowed_references():
    context = {"candidates": [{"id": "allowed"}], "allowed_evidence": ["obs-1"]}
    result = OllamaReasoner._normalize({"candidate_id": "invented", "confidence": 99,
        "hypothesis": "maybe", "supporting_evidence": ["obs-1", "fake"],
        "contradicting_evidence": ["fake"], "recommended_observation": "run shell"}, context)
    assert result["candidate_id"] is None and result["recommended_plan"] is None
    assert result["confidence"] == .6 and result["status"] == "HYPOTHESIS"
    assert result["supporting_evidence"] == ["obs-1"] and result["contradicting_evidence"] == []
    assert result["recommended_observation"] == "NONE"


def test_completed_ai_result_becomes_separate_observation():
    reasoner = OllamaReasoner({"enabled": False, "model": "test"})
    try:
        world = WorldModel()
        world.ingest(Observation.create(state(), 1))
        reasoner.last_reasoning = {"reasoning_id": "r1", "confidence": .3,
                                   "hypothesis": "UNKNOWN", "status": "HYPOTHESIS"}
        reasoner.unpublished = True
        obs = reasoner.take_observation(world, 1.1)
        assert obs.source == "AI" and obs.correlation_id == world.latest.correlation_id
        assert obs.payload["ai_reasoning"]["status"] == "HYPOTHESIS"
        assert reasoner.take_observation(world, 1.2) is None
    finally:
        reasoner.close()


def test_stale_ai_result_is_not_attached_to_new_world_context():
    reasoner = OllamaReasoner({"enabled": False})
    try:
        world = WorldModel()
        world.ingest(Observation.create(state(), 1))
        goal = Goal.parse("Questelj", 1)
        proposals = [Proposal.make("MOVE", "a", priority=50), Proposal.make("WAIT", "b", priority=49)]
        reasoner.key = "old-context"
        reasoner.future = Future()
        reasoner.future.set_result({"candidate_id": proposals[0].key, "reason": "old",
                                    "confidence": .3, "hypothesis": "old", "status": "HYPOTHESIS"})
        reasoner.advise(goal, world, proposals, 2)
        assert reasoner.take_observation(world, 2) is None
    finally:
        reasoner.close()


def test_spatial_memory_stores_identity_without_fake_exact_location(tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    memory = SpatialMemory(tmp_path)
    payload = state(mouseover={"guid": "creature-1", "npc_id": 42, "name": "NPC", "unit_type": "NPC"})
    memory.ingest(payload, 2)
    assert memory.entities.get_profile("npc:42").name == "NPC"
    assert memory.entities.locations("npc:42") == []


def test_spatial_memory_associates_visual_only_with_identity_at_probe(tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    memory = SpatialMemory(tmp_path)
    signature = {"version": 1, "signature_id": "sig-1", "appearance": {"red_bin": 4}}
    payload = state(mouseover={"guid": "creature-1", "npc_id": 42, "name": "NPC"},
                    cursor_position={"nx": .4, "ny": .6})
    probe = {"source": "WORLD3D", "x": .4, "y": .6, "visual_signature": signature}
    memory.ingest(payload, 2, probe=probe)
    visuals = memory.entities.visual_observations("npc:42")
    assert len(visuals) == 1 and "sig-1" in visuals[0]["signature"]
    memory.ingest({**payload, "mouseover": {}}, 5, probe=probe)
    assert len(memory.entities.visual_observations("npc:42")) == 1


def test_runtime_keeps_addon_and_memory_observations_separate(tmp_path):
    sensor = Sensor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=RecordingExecutor(), vision=False)
    try:
        payload = state(mouseover={"guid": "creature-1", "npc_id": 42, "name": "NPC"})
        sensor.payload = payload
        runtime.step(1)
        assert "remembered_locations" not in payload
        assert "map_marker_observations" not in runtime.agent.world.addon_state
        assert "remembered_locations" in runtime.agent.world.state
        sources = [item.source for item in runtime.agent.world.history]
        assert sources == ["ADDON_TELEMETRY", "PLAYER_STATE", "MOUSEOVER", "UI_STATE", "WORLD_MAP_STATE", "QUEST_STATE", "TOOLTIP",
                           "SPATIAL_MEMORY", "SEMANTIC_MEMORY"]
        assert len({item.observation_id for item in runtime.agent.world.history}) == 9
        assert len({item.correlation_id for item in runtime.agent.world.history}) == 1
        evidence = runtime.agent.world.evidence["mouseover"]
        assert len({item.independence_group for item in evidence}) == 1
    finally:
        runtime.close()


def test_arming_waits_for_learned_detector_warmup(tmp_path):
    # Issue #30: the detector blocker must gate arming, not only the GUI text.
    sensor, exe = Sensor(), RecordingExecutor()
    sensor.frame = (bytes(4 * 640 * 480), 640, 480)
    runtime = AgentRuntime(42, binding_file(tmp_path, 'bind "TAB" "TARGETNEARESTENEMY"\n'), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    vision = SparseTelemetryVision()
    vision.detector_warm = False
    vision.detector_ready = lambda now: vision.detector_warm
    runtime.perception = vision
    try:
        runtime.agent.set_goal("Questelj", 1)
        runtime.test_step(actions=1, seconds=5)
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = state(2., world_map_open=False, active_quests=[])
        result = runtime.step(2.)
        assert result["mode"] == "MANUAL"
        assert "waiting_for_world3d_detector" in result["arm_blockers"]
        assert not exe.commands

        vision.detector_warm = True
        sensor.payload = state(3., world_map_open=False, active_quests=[])
        result = runtime.step(3.)
        assert result["mode"] == "FULL_AI"
    finally:
        runtime.close()


def test_arming_rejects_a_running_addon_that_differs_from_the_project(tmp_path):
    # Issue #32: an updated project addon without /reload must not arm.
    sensor, exe = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=exe, vision=False)
    try:
        assert runtime.expected_addon_version          # read from the repo toc
        runtime.expected_addon_version = "0.9.59"
        runtime.agent.set_goal("Menj oda", 1, {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 2, 12
        sensor.payload = {**state(2), "addon_version": "0.9.56"}
        result = runtime.step(2)
        assert result["mode"] == "MANUAL" and not exe.commands
        assert result["result"]["addon_version_mismatch"] == {"running": "0.9.56",
                                                              "expected": "0.9.59"}
        runtime.mode("FULL_AI")
        runtime.arm_at, runtime.arm_deadline = 3, 13
        sensor.payload = {**state(3), "addon_version": "0.9.59"}
        assert runtime.step(3)["mode"] == "FULL_AI"
    finally:
        runtime.close()


def test_stabilizer_expires_every_tracks_evidence_and_stays_bounded():
    # Issue #76: only the current track's stale evidence was ever deleted.
    stabilizer = _VisualRecognitionStabilizer()
    match = {"identity_key": "npc:1", "similarity": .9,
             "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"}
    for index in range(2000):
        stabilizer.update(f"WORLD3D:{index}", [match], float(index) * .01)
    stabilizer.update("WORLD3D:new", [], 100.)
    assert stabilizer.retained == 0
    stabilizer.update("WORLD3D:a", [match], 200.)
    stabilizer.reset()
    assert stabilizer.retained == 0


def test_perception_reset_does_not_transfer_identity_to_a_reused_track_id():
    # Issue #75: after a reset WORLD3D:1 was a different subject but the 1 s
    # recognition cache and the stabilizer still carried the old one.
    from types import SimpleNamespace
    from wowbot.agent.runtime_observation_phase import _recognition_cache_for_epoch
    def match(key):
        return [{"identity_key": key, "similarity": .95,
                 "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"}]
    runtime = SimpleNamespace(perception=SimpleNamespace(epoch=1),
                              _visual_recognition_stabilizer=_VisualRecognitionStabilizer())
    cache = _recognition_cache_for_epoch(runtime)
    cache[("track", "WORLD3D:1")] = (0., match("npc:jaina"))
    for at in (0., .1, .2):
        runtime._visual_recognition_stabilizer.update("WORLD3D:1", match("npc:jaina"), at)
    assert _recognition_cache_for_epoch(runtime) is cache and cache   # same epoch: kept
    runtime.perception.epoch = 2                                        # reset
    assert not _recognition_cache_for_epoch(runtime)
    published = []
    for at in (.3, .4, .5):
        published += runtime._visual_recognition_stabilizer.update(
            "WORLD3D:1", match("npc:keela"), at)
    assert [item["identity_key"] for item in published] == ["npc:keela"]
