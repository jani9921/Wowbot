"""SharedFrameRingBuffer: lock-free single-writer/single-reader frame
transport (docs/PROCESS_BASED_CAPTURE_DESIGN_2026-09-22.txt, phase 1)."""
import multiprocessing
import threading
import time
import uuid

import pytest

from wowbot.agent.shared_frame_buffer import SLOT_COUNT, SharedFrameRingBuffer


@pytest.fixture
def prefix():
    return f"aipc_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def buffers(prefix):
    owner = SharedFrameRingBuffer.create(name_prefix=prefix, max_width=64, max_height=64)
    reader = SharedFrameRingBuffer.attach(name_prefix=prefix)
    yield owner, reader
    reader.close()
    owner.close()
    owner.unlink()


def _frame(fill: int, width=4, height=4) -> bytes:
    return bytes([fill]) * (width * height * 4)


def test_read_before_any_write_reports_not_started_with_no_frame(buffers):
    _owner, reader = buffers
    result = reader.read()
    assert result is not None
    assert result.raw is None
    assert result.status == "not_started"


def test_write_frame_then_read_round_trips_exactly(buffers):
    owner, reader = buffers
    payload = _frame(7)
    owner.write_frame(payload, width=4, height=4, status="captured", captured_at=1.5)
    result = reader.read()
    assert result.raw == payload
    assert (result.width, result.height) == (4, 4)
    assert result.status == "captured"
    assert result.captured_at == 1.5


def test_write_status_without_a_frame_keeps_the_last_frame_available(buffers):
    owner, reader = buffers
    payload = _frame(3)
    owner.write_frame(payload, width=4, height=4, status="captured", captured_at=1.0)
    owner.write_status("selected_PID_not_foreground", captured_at=2.0)
    result = reader.read()
    assert result.raw == payload  # last good frame preserved
    assert result.status == "selected_PID_not_foreground"
    assert result.captured_at == 2.0


def test_writes_beyond_slot_count_wrap_around_and_stay_readable(buffers):
    owner, reader = buffers
    for i in range(SLOT_COUNT * 3):
        owner.write_frame(_frame(i % 256), width=4, height=4, status="captured", captured_at=float(i))
    result = reader.read()
    assert result.raw == _frame((SLOT_COUNT * 3 - 1) % 256)


def test_frame_larger_than_slot_size_is_rejected(buffers):
    owner, _reader = buffers
    with pytest.raises(ValueError):
        owner.write_frame(b"x" * 999_999, width=999, height=999, status="captured", captured_at=1.0)


def test_payload_must_match_declared_bgra_dimensions(buffers):
    owner, _reader = buffers
    with pytest.raises(ValueError, match="dimensions"):
        owner.write_frame(b"x" * 12, width=4, height=4,
                          status="captured", captured_at=1.0)


def test_only_the_owner_may_unlink(prefix):
    owner = SharedFrameRingBuffer.create(name_prefix=prefix, max_width=8, max_height=8)
    reader = SharedFrameRingBuffer.attach(name_prefix=prefix)
    try:
        with pytest.raises(RuntimeError):
            reader.unlink()
    finally:
        reader.close()
        owner.close()
        owner.unlink()


def test_concurrent_writer_and_reader_never_observe_a_torn_frame(buffers):
    owner, reader = buffers
    stop = threading.Event()
    observed_bad = []

    def write_loop():
        i = 0
        while not stop.is_set():
            owner.write_frame(_frame(i % 256), width=4, height=4, status="captured", captured_at=float(i))
            i += 1

    def read_loop():
        for _ in range(2000):
            result = reader.read()
            if result is not None and result.raw is not None:
                fill = result.raw[0]
                if result.raw != bytes([fill]) * len(result.raw):
                    observed_bad.append(result.raw)

    writer_thread = threading.Thread(target=write_loop)
    writer_thread.start()
    try:
        read_loop()
    finally:
        stop.set()
        writer_thread.join(timeout=5)
    assert observed_bad == []


def _child_write_frames(name_prefix: str, count: int) -> None:
    ring = SharedFrameRingBuffer.attach(name_prefix=name_prefix)
    try:
        for i in range(count):
            ring.write_frame(bytes([i % 256]) * (4 * 4 * 4), width=4, height=4,
                             status="captured", captured_at=float(i))
            time.sleep(0.005)
    finally:
        ring.close()


def test_a_real_separate_process_can_write_frames_the_parent_reads(prefix):
    owner = SharedFrameRingBuffer.create(name_prefix=prefix, max_width=4, max_height=4)
    try:
        process = multiprocessing.Process(target=_child_write_frames, args=(prefix, 10))
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        result = owner.read()
        assert result is not None and result.raw is not None
        assert result.status == "captured"
    finally:
        owner.close()
        owner.unlink()
