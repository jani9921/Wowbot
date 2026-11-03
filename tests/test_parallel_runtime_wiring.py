"""Production sensor facade and runtime lifecycle, with no client input."""
import json
import sys
import time
from types import SimpleNamespace

import pytest

from test_agent_core import binding_file, state
from test_parallel_control import control_sample, setup
from wowbot.agent.capture_selection import build_default_sensor
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Mode
from wowbot.agent.parallel_runtime import ParallelRuntimePump
from wowbot.agent.runtime import AgentRuntime
from wowbot.agent.sensor import BufferedPixelSensor
from wowbot.agent.sensor_hub import SensorHub


@pytest.mark.parametrize("wrapped", [False, True])
def test_unsupported_sensor_reports_why_fast_control_did_not_start(wrapped):
    agent, executor = setup("INSPECT")
    sensor = SimpleNamespace(poll=lambda now: None)
    if wrapped:
        sensor = SensorHub.for_primary(sensor)
    pump = ParallelRuntimePump(SimpleNamespace(sensor=sensor, agent=agent))
    try:
        assert pump.start() is False
        assert not agent.parallel_control.enabled
        assert not pump.active and pump.thread is None
        assert pump.snapshot()["status"] == "sensor_without_peek_latest"
        assert not executor.commands
    finally:
        pump.close()


def test_pump_has_single_lifecycle_and_manual_start_does_not_send_input():
    agent, executor = setup("INSPECT")
    agent.set_mode(Mode.MANUAL)
    sensor = SimpleNamespace(peek_latest=lambda now: pytest.fail("read in MANUAL"))
    runtime = SimpleNamespace(sensor=sensor, agent=agent)
    pump = ParallelRuntimePump(runtime)
    try:
        assert pump.snapshot()["status"] == "not_started"
        assert pump.start()
        assert pump.snapshot()["status"] == "running" and pump.active
        with pytest.raises(RuntimeError, match="once"):
            pump.start()
        assert not executor.commands
    finally:
        pump.close()
    assert pump.snapshot()["status"] == "stopped"
    assert not pump.active and not pump.thread.is_alive()
    with pytest.raises(RuntimeError, match="once"):
        pump.start()


def test_thread_start_failure_does_not_leave_fast_control_enabled(monkeypatch):
    agent, _ = setup("INSPECT")
    pump = ParallelRuntimePump(SimpleNamespace(
        sensor=SimpleNamespace(peek_latest=lambda now: None), agent=agent))
    def fail_start(thread):
        raise RuntimeError("thread creation failed")
    monkeypatch.setattr("wowbot.agent.parallel_runtime.threading.Thread.start", fail_start)
    try:
        with pytest.raises(RuntimeError, match="creation failed"):
            pump.start()
        assert not agent.parallel_control.enabled and not pump.active
        assert "creation failed" in pump.snapshot()["error"]
    finally:
        pump.close()


@pytest.mark.parametrize("backend", ["gdi", "dxgi"])
@pytest.mark.parametrize("process", [False, True])
def test_default_capture_factory_preserves_fast_snapshot_capability(monkeypatch, backend, process):
    capture = SimpleNamespace()
    handle = SimpleNamespace(client=capture)
    calls = []
    def make_capture(pid, executor_backend):
        calls.append(pid)
        return capture
    def make_process(**kwargs):
        calls.append(kwargs["pid"])
        assert kwargs["backend_name"] == backend
        return handle
    monkeypatch.setenv("AIPC_CAPTURE_BACKEND", backend)
    monkeypatch.setenv("AIPC_CAPTURE_PROCESS", "1" if process else "0")
    monkeypatch.setattr("wowbot.agent.capture_selection.ClientCapture", make_capture)
    monkeypatch.setattr("wowbot.agent.dxgi_capture.DxgiClientCapture", make_capture)
    monkeypatch.setattr("wowbot.agent.capture_worker.start_capture_process", make_process)
    hub, capture_handle = build_default_sensor(42, None)
    try:
        assert isinstance(hub, SensorHub) and hub.supports_peek_latest
        assert calls == [42]
        assert capture_handle is (handle if process else None)
        assert hub.source.capture is capture
        hub._sensors[hub.primary].latest_payload = ({"frame_id": "test"}, 10.)
        assert hub.peek_latest(10.1)[1] == 10.
    finally:
        hub.close()


@pytest.mark.parametrize("boundary", ["stale", "future", "failure", "closed", "foreground",
                                      "emergency", "deadline"])
def test_wrapped_sensor_pump_preserves_safety_boundaries(boundary):
    agent, executor = setup()
    payload, vision = control_sample(agent, 10., 1)
    buffered = BufferedPixelSensor(SimpleNamespace())
    buffered.latest_payload = (payload, 10.)
    hub = SensorHub.for_primary(buffered)
    executor.backend = SimpleNamespace(emergency_pressed=lambda: boundary == "emergency",
                                      is_selected_foreground=lambda: boundary != "foreground")
    runtime = SimpleNamespace(agent=agent, executor=executor, sensor=hub,
                              perception=SimpleNamespace(peek_control=lambda now: vision),
                              test_deadline=10. if boundary == "deadline" else None,
                              test_dialog_grace_deadline=None)
    pump = ParallelRuntimePump(runtime)
    before = list(executor.commands)
    try:
        if boundary == "failure":
            hub.mark_sensor_failure(hub.primary, "DEVICE_RESET")
        elif boundary == "closed":
            hub.close()
        pump.step(10.6 if boundary == "stale" else 9.9 if boundary == "future" else 10.1)
        assert executor.commands == before
        assert executor.stops > 0 and pump.wake_medium.is_set()
        if boundary == "emergency":
            assert agent.mode == Mode.MANUAL
    finally:
        pump.close()
        hub.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_real_runtime_lifecycle_with_hub_publishes_actual_pump_state(tmp_path, monkeypatch, enabled):
    for key in ("AIPC_THREAD_PROFILE", "AIPC_ASYNC_VISUAL_MEMORY", "AIPC_PACKET_TELEMETRY",
                "AIPC_MAP_DATASET"):
        monkeypatch.setenv(key, "0")
    monkeypatch.setenv("AIPC_PARALLEL_CONTROL", "1" if enabled else "0")
    class PixelSource:
        health = "streaming"
        frame = None
        def poll(self, now):
            return state(now)
    buffered = BufferedPixelSensor(PixelSource(), interval=.01)
    hub = SensorHub.for_primary(buffered)
    executor = RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=hub, executor=executor, vision=False)
    switch_interval = sys.getswitchinterval()
    try:
        runtime.start()
        deadline = time.monotonic()+3.
        while "parallel_control" not in runtime.status and time.monotonic() < deadline:
            time.sleep(.01)
        assert runtime.agent.mode == Mode.MANUAL
        parallel = runtime.status["parallel_control"]
        assert parallel["enabled"] is enabled
        assert parallel["pump"]["active"] is enabled
        assert parallel["pump"]["status"] == ("running" if enabled else "not_started")
        if enabled:
            assert parallel["pump"]["sensor"] == "SensorHub"
            assert runtime.parallel_pump.thread.name == "aipc-fast-control"
        else:
            assert runtime.parallel_pump is None
        assert not executor.commands
    finally:
        runtime.close()
        sys.setswitchinterval(switch_interval)
    assert not buffered.thread.is_alive()
    assert not runtime.thread.is_alive()
    saved = json.loads((tmp_path / "output" / "agent_status.json").read_text(encoding="utf-8"))
    assert saved["mode"] == "STOPPED"
    assert saved["parallel_control"]["enabled"] is False
    assert saved["parallel_control"]["pump"]["active"] is False
    assert saved["parallel_control"]["pump"]["status"] == ("stopped" if enabled else "not_started")
    assert saved["input_safety"]["held_keys"] == []
