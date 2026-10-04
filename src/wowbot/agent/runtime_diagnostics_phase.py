"""Diagnostics, maintenance and status publication for one medium runtime tick."""
from __future__ import annotations

import time

from .models import Mode
from .runtime_control import next_medium_interval


def finalize_runtime_diagnostics(runtime, result: dict, *, current: float,
                                 started_at: float, sensor_ms: float,
                                 perception_ms: float, observations_ms: float,
                                 tick_ms: float, backend) -> dict:
    """Project diagnostics after Agent.tick; never plan or dispatch input."""
    performance = runtime.agent.performance_monitor
    sensor_diagnostics = getattr(runtime.sensor, "diagnostics", {})
    performance.observe_latency("capture_poll", sensor_diagnostics.get("poll_ms"))
    performance.observe_rate("capture_fps", sensor_diagnostics.get("poll_hz"))
    performance.observe_latency("perception", perception_ms)
    performance.observe_latency("observation_build", observations_ms)
    performance.observe_latency("agent_tick", tick_ms)
    if runtime.perception:
        world_diagnostics = (runtime.perception.diagnostics or {}).get("world") or {}
        performance.observe_latency(
            "world_detector", world_diagnostics.get("detector_duration_ms"))
        performance.observe_latency(
            "world_tracker", world_diagnostics.get("propagate_duration_ms"))

    phase_started = time.perf_counter()
    if current >= runtime._next_maintenance:
        pruned_evidence = runtime.agent.world.prune_expired_evidence(current)
        if runtime.agent.mode == Mode.FULL_AI:
            # Retention is never control work.  Even an indexed SQLite DELETE
            # briefly owns the single writer lock and can starve FAST samples;
            # defer it while autonomous input authority is armed.
            runtime._maintenance_status = {
                "status": "deferred_full_ai",
                "pruned_evidence_keys": pruned_evidence,
            }
        else:
            consolidated = runtime.memory.consolidate(
                current, current_session=runtime.agent.world.session_id,
                # Never delete thousands of rows in one control tick.
                maximum_rows_per_pass=256)
            runtime._maintenance_status = {
                "status": "complete", "pruned_evidence_keys": pruned_evidence,
                **consolidated}
        # Backlog is diagnostic, not permission to monopolize the hot loop.
        # Re-running COUNT/DELETE every 500 ms live-collapsed a healthy 35 Hz
        # telemetry source to 2--3 Hz.  Producers are bounded at their source;
        # historical backlog is drained incrementally once per minute.
        runtime._next_maintenance = current + 60.
    maintenance_ms = (time.perf_counter()-phase_started)*1000
    performance.observe_latency("memory_maintenance", maintenance_ms)

    result["spawn_reference"] = runtime.spatial.spawn_reference(
        runtime.agent.world.state)
    if runtime.sensor.frame:
        runtime.vision_dataset.consider(
            runtime.sensor.frame[0], runtime.sensor.frame[1],
            runtime.sensor.frame[2], runtime.agent.world.state, current)
    result["vision_dataset"] = runtime.vision_dataset.diagnostics()
    map_dataset = getattr(runtime, "map_marker_dataset", None)
    if map_dataset is not None:
        if runtime.sensor.frame:
            map_dataset.consider(
                runtime.sensor.frame[0], runtime.sensor.frame[1],
                runtime.sensor.frame[2], runtime.agent.world.state, current)
        result["map_marker_dataset"] = map_dataset.diagnostics()
    if ((runtime.test_deadline is not None
         or runtime.test_dialog_grace_deadline is not None)
            and runtime.agent.mode != Mode.FULL_AI):
        runtime.test_deadline = None
        runtime.test_dialog_grace_deadline = None
    result["binding_preflight"] = runtime._binding_preflight()
    result["binding_inventory"] = runtime.binding_inventory.status
    result["input_coordinates"] = getattr(backend, "coordinate_diagnostics", {})
    result["input_safety"] = (
        runtime.executor.diagnostics()
        if hasattr(runtime.executor, "diagnostics") else {})

    step_ms = (time.perf_counter()-started_at)*1000
    runtime._step_latencies.append(step_ms)
    ordered_latency = sorted(runtime._step_latencies)
    p95 = (ordered_latency[min(len(ordered_latency)-1,
                               int(len(ordered_latency)*.95))]
           if ordered_latency else 0.)
    result.update(
        pid=runtime.pid, bindings_cache=str(runtime.bindings.path),
        bindings_sha256=runtime.bindings.digest,
        bindings=runtime.bindings.actions,
        sensor=("selected_PID_not_foreground" if runtime._foreground_suspended
                else runtime.sensor.health),
        arm_in=max(0., runtime.arm_at-current) if runtime.arm_at else None,
        arm_waiting_for_fresh_state=(runtime.arm_at is not None
                                     and current >= runtime.arm_at),
        arm_blockers=list(runtime._arm_blockers),
        foreground_suspended=runtime._foreground_suspended,
        foreground_grace_remaining=(
            max(0., 15.-(current-runtime._not_foreground_since))
            if runtime._not_foreground_since is not None else None),
        test_remaining=(max(0., runtime.test_deadline-current)
                        if runtime.test_deadline is not None else None),
        test_dialog_grace_remaining=(
            max(0., runtime.test_dialog_grace_deadline-current)
            if runtime.test_dialog_grace_deadline is not None else None),
        timings_ms={
            "sensor": round(sensor_ms, 2), "step": round(step_ms, 2),
            "step_p95": round(p95, 2), "perception": round(perception_ms, 2),
            "observations": round(observations_ms, 2), "tick": round(tick_ms, 2),
            "maintenance": round(maintenance_ms, 2),
            "status_write": round(runtime._status_write_ms, 2)},
        loop_rates={
            "fast_control_hz": runtime._runtime_rate.hz(current),
            "movement_fast_consumer_hz": runtime._fast_control_consumed_rate.hz(current),
            "control_target_hz": runtime.control_hz,
            "addon_payload_hz": runtime._payload_rate.hz(current),
            "addon_fast_state_hz": runtime._fast_payload_rate.hz(current),
            "consumed_fast_state_hz": runtime._fast_payload_rate.hz(current),
            "pixelstrip_source_fast_hz": (
                (sensor_diagnostics.get("source") or {}).get("source_fast_hz")),
            "addon_full_state_hz": runtime._full_payload_rate.hz(current),
            **(runtime.perception.rates(current)
               if runtime.perception and hasattr(runtime.perception, "rates") else {})},
        maintenance=runtime._maintenance_status,
        sensor_diagnostics=sensor_diagnostics,
        status_write_error=runtime._status_write_error,
        main_thread_poll={
            "none_streak": runtime._poll_none_streak,
            "last_payload_ago": (
                round(current-runtime._last_payload_at, 3)
                if runtime._last_payload_at is not None else None)},
        vision=runtime.perception.status if runtime.perception else "disabled",
        vision_diagnostics=(runtime.perception.diagnostics
                            if runtime.perception else {}))
    runtime.live_capture.consider(runtime.sensor.frame, result, current)
    result["live_capture"] = runtime.live_capture.diagnostics()
    runtime.status = result
    if current-runtime.last_write >= .5:
        runtime.last_write = current
        runtime._publish_status(result)
    notice = (f"{result['mode']} | {result['sensor']} | "
              f"{result.get('decision', {}).get('skill', '-')} | "
              f"{result.get('result', {}).get('reason', '')}")
    if notice != runtime._last_notice:
        print(notice, flush=True)
        runtime._last_notice = notice

    # Completion-relative scheduling leaves a real FAST-control window after
    # a CPU-heavy perception/planning tick.
    completed_at = time.monotonic() if runtime.started else current
    runtime._next_medium_at = completed_at + next_medium_interval(
        runtime.agent, runtime.medium_hz)
    return result
