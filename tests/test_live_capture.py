import json
import threading
import time

from PIL import Image

from wowbot.agent.live_capture import LiveCaptureRecorder


def _frame(width=320, height=200):
    return (bytes([20, 40, 80, 255])*(width*height), width, height)


def test_capture_writes_client_frame_and_manifest_without_input(tmp_path):
    recorder = LiveCaptureRecorder(tmp_path, heartbeat=2, min_interval=.1, max_frames=3)
    status = {"pid": 10, "mode": "MANUAL", "sensor": "streaming",
              "decision": {"skill": "WAIT"}, "world": {"fresh": True,
              "player": {"map_id": 1409, "position": {"x": .2, "y": .3}}}}
    assert recorder.consider(_frame(), status, 1.) is True
    recorder.close()
    captures = list((tmp_path/"live-captures").rglob("*.jpg"))
    assert len(captures) == 1 and Image.open(captures[0]).size == (320, 200)
    manifest = next((tmp_path/"live-captures").rglob("manifest.jsonl"))
    event = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    assert event["summary"]["mode"] == "MANUAL"
    assert event["summary"]["map_id"] == 1409


def test_capture_is_rate_limited_and_bounded(tmp_path):
    recorder = LiveCaptureRecorder(tmp_path, heartbeat=2, min_interval=.5, max_frames=1)
    status = {"mode": "MANUAL", "world": {}}
    assert recorder.consider(_frame(), status, 1.) is True
    assert recorder.consider(_frame(), {**status, "mode": "FULL_AI"}, 1.1) is False
    recorder.close()
    assert recorder.consider(_frame(), status, 5.) is False
    assert recorder.diagnostics()["frames"] == 1


def test_rotate_starts_a_fresh_bounded_capture_segment(tmp_path):
    recorder = LiveCaptureRecorder(tmp_path, heartbeat=2, min_interval=.1, max_frames=1)
    status = {"mode": "FULL_AI", "world": {}}
    first = recorder.directory
    assert recorder.consider(_frame(), status, 1.) is True
    recorder.rotate()
    second = recorder.directory
    assert second != first
    assert recorder.diagnostics()["frames"] == 0
    assert recorder.diagnostics()["segment"] == 2
    assert recorder.consider(_frame(), status, 2.) is True
    recorder.close()
    assert len(list((tmp_path / "live-captures").rglob("*.jpg"))) == 2


def test_rotate_does_not_wait_for_an_inflight_encoder(tmp_path):
    recorder = LiveCaptureRecorder(tmp_path, heartbeat=2, min_interval=.1, max_frames=1)
    entered, release = threading.Event(), threading.Event()
    original_drain = recorder._drain

    def delayed_drain():
        entered.set()
        assert release.wait(2.)
        original_drain()

    recorder._drain = delayed_drain
    status = {"mode": "FULL_AI", "world": {}}
    assert recorder.consider(_frame(), status, 1.) is True
    assert entered.wait(1.)

    started = time.perf_counter()
    recorder.rotate()
    elapsed = time.perf_counter()-started

    assert elapsed < .1
    assert recorder.consider(_frame(), status, 2.) is True
    release.set()
    recorder.close()
    assert len(list((tmp_path / "live-captures").rglob("*.jpg"))) == 2


def test_only_the_newest_capture_runs_are_kept(tmp_path):
    # User 2026-10-04: live captures filled the disk.
    from wowbot.agent.live_capture import LiveCaptureRecorder
    root = tmp_path / "agent"
    names = ["20261001-100000-000-001", "20261002-100000-000-001", "20261003-100000-000-001",
             "20261004-100000-000-001"]
    for index, name in enumerate(names):
        folder = root / f"pid-{index}" / "live-captures" / name
        folder.mkdir(parents=True)
        (folder / "0001-x.jpg").write_bytes(b"jpg")
    empty = root / "pid-9" / "live-captures" / "20261004-120000-000-001"
    empty.mkdir(parents=True)
    other = root / "pid-0" / "agent_status.json"
    other.write_text("{}")
    recorder = LiveCaptureRecorder(root / "pid-5", keep_segments=3)
    recorder.prune_thread.join(5)
    left = sorted(path.name for path in root.glob("*/live-captures/*"))
    assert left == sorted(names[-2:] + [recorder.directory.name])
    assert other.exists()
