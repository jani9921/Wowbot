"""ProcessCaptureClient / capture_worker (phase 2, real multiprocessing.Process
via the deterministic "fake" backend -- no WoW window or GPU required)."""
import time
import uuid

import pytest

from wowbot.agent.capture_worker import ProcessCaptureClient, start_capture_process
from wowbot.agent.shared_frame_buffer import SharedFrameRingBuffer


@pytest.fixture
def handle():
    handle = start_capture_process(
        pid=0, backend_name="fake", name_prefix=f"aipc_cw_test_{uuid.uuid4().hex[:12]}",
        max_width=8, max_height=8, interval=0.01)
    yield handle
    handle.stop()


def _wait_for_real_frame(client, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.capture()
        if result is not None:
            return result
        time.sleep(0.02)
    return None


def test_process_capture_client_receives_real_frames_from_a_child_process(handle):
    result = _wait_for_real_frame(handle.client)
    assert result is not None
    raw, width, height = result
    assert (width, height) == (4, 4)
    assert len(raw) == 4 * 4 * 4
    assert handle.client.last_capture_status == "captured"


def test_process_capture_client_sees_fresh_frames_over_time(handle):
    _wait_for_real_frame(handle.client)
    fills = set()
    for _ in range(10):
        result = handle.client.capture()
        if result is not None:
            fills.add(result[0][0])
        time.sleep(0.02)
    # The fake backend increments its fill byte every capture; sampling
    # across real elapsed time should not keep returning the same frame.
    assert len(fills) > 1


def test_process_capture_client_does_not_republish_one_snapshot_as_fresh():
    class AliveProcess:
        @staticmethod
        def is_alive():
            return True

    prefix = f"aipc_cw_test_{uuid.uuid4().hex[:12]}"
    owner = SharedFrameRingBuffer.create(name_prefix=prefix, max_width=4, max_height=4)
    reader = SharedFrameRingBuffer.attach(name_prefix=prefix)
    try:
        client = ProcessCaptureClient(AliveProcess(), reader)
        owner.write_frame(bytes([7]) * 64, 4, 4, "captured", 1.0)
        assert client.capture() is not None
        assert client.capture() is None
        owner.write_frame(bytes([8]) * 64, 4, 4, "captured", 2.0)
        assert client.capture()[0][0] == 8
    finally:
        reader.close()
        owner.close()
        owner.unlink()


def test_process_capture_client_reports_dead_process_after_stop():
    h = start_capture_process(pid=0, backend_name="fake",
                              name_prefix=f"aipc_cw_test_{uuid.uuid4().hex[:12]}",
                              max_width=4, max_height=4, interval=0.01)
    _wait_for_real_frame(h.client)
    h.stop()
    assert h.client.capture() is None
    assert h.client.last_capture_status == "capture_process_died"


def test_unknown_backend_name_is_rejected():
    from wowbot.agent.capture_worker import _build_capture
    with pytest.raises(ValueError):
        _build_capture(0, "not_a_real_backend")


def test_vertical_fast_cache_is_not_suppressed_by_primary_discovery_throttle(monkeypatch):
    import adapters.pixel_bridge as bridge
    from wowbot.agent.capture_worker import _StripDecoder
    from wowbot.agent.shared_frame_buffer import PAYLOAD_DECODED
    monkeypatch.setattr(bridge, "_GRID_CACHE", {})
    monkeypatch.setattr(bridge, "_VERTICAL_FAST_CACHE", {(1345, 697): (1145, 300, 3.)})
    monkeypatch.setattr(bridge, "decode_payload_from_bgra", lambda *a: "AIPC5|s|2|0|1|FAST|{}")
    decoder = _StripDecoder()
    decoder.next_discovery = 100.
    payload, status = decoder.decode(b"", 1345, 697, 99.)
    assert status == PAYLOAD_DECODED and "|FAST|" in payload
