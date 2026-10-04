import os

import pytest

from wowbot.agent.runtime import AgentRuntime
from wowbot.agent.sensor import ClientCapture
from wowbot.agent.dxgi_capture import DxgiClientCapture


def binding_file(tmp_path):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\n', encoding="utf-8")
    return path


class FakeExecutor:
    """Only needs a .backend attribute -- ClientCapture/DxgiClientCapture
    just store it at construction time without calling anything on it.
    stop()/stop_movement() are needed too: AgentRuntime.close() drives the
    agent to Mode.STOPPED, which calls executor.stop()."""
    def __init__(self):
        self.backend = object()
    def stop(self):
        pass
    def stop_movement(self):
        pass


def test_default_capture_backend_is_unchanged_gdi_client_capture(tmp_path, monkeypatch):
    # Live bug caught 2026-09-14: the sensor-selection branch in runtime.py
    # (added alongside the opt-in DXGI backend) referenced os.environ without
    # importing os -- every existing test passes sensor=... explicitly and
    # never exercises this branch, so it would have first failed in
    # production, on every single AgentRuntime construction that relies on
    # the default sensor. This test exercises exactly that branch.
    monkeypatch.delenv("AIPC_CAPTURE_BACKEND", raising=False)
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           executor=FakeExecutor(), vision=False)
    try:
        assert type(runtime.sensor.source.capture) is ClientCapture
        assert runtime.sensor.interval == .025
    finally:
        runtime.close()


def test_dxgi_capture_backend_is_opt_in_via_environment_variable(tmp_path, monkeypatch):
    dxcam = pytest.importorskip("dxcam")
    monkeypatch.setenv("AIPC_CAPTURE_BACKEND", "dxgi")
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           executor=FakeExecutor(), vision=False)
    try:
        from wowbot.agent.dxgi_capture import DxgiClientCapture
        assert type(runtime.sensor.source.capture) is DxgiClientCapture
        assert runtime.sensor.interval == pytest.approx(1 / 120)
    finally:
        runtime.close()


def test_process_capture_is_opt_in_via_environment_variable(tmp_path, monkeypatch):
    # Same defensive shape as the DXGI test above (see 2026-09-14 comment):
    # exercise the actual default-construction branch runtime.py takes, not
    # just the capture_worker module in isolation.
    from wowbot.agent.capture_worker import ProcessCaptureClient
    monkeypatch.setenv("AIPC_CAPTURE_PROCESS", "1")
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           executor=FakeExecutor(), vision=False)
    try:
        assert type(runtime.sensor.source.capture) is ProcessCaptureClient
        assert runtime._capture_process_handle is not None
        assert runtime._capture_process_handle.process.is_alive()
    finally:
        runtime.close()
    assert not runtime._capture_process_handle.process.is_alive()


def test_process_capture_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AIPC_CAPTURE_PROCESS", raising=False)
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           executor=FakeExecutor(), vision=False)
    try:
        assert runtime._capture_process_handle is None
        assert type(runtime.sensor.source.capture) is ClientCapture
    finally:
        runtime.close()


def test_dxgi_region_is_clipped_and_keeps_client_coordinate_offsets():
    assert DxgiClientCapture._clip_client_to_output(
        -20, 10, 200, 100, (0, 0, 1600, 900)) == (
            (0, 10, 180, 110), 20, 0, 180, 100, True)
    assert DxgiClientCapture._clip_client_to_output(
        100, 50, 200, 100, (0, 0, 1600, 900)) == (
            (100, 50, 300, 150), 0, 0, 200, 100, False)
    assert DxgiClientCapture._clip_client_to_output(
        1700, 50, 200, 100, (0, 0, 1600, 900)) is None
