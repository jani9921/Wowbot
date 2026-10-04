import multiprocessing as mp
import threading
import time
import uuid

from wowbot.agent.perception_process import ProcessPerceptionWorker
from wowbot.agent.shared_frame_buffer import SharedFrameRingBuffer
from wowbot.vision.world3d.capture_yolo_feed import FeedResult
from wowbot.vision.world3d.models import PixelRect, WorldCandidate


class _FeedOwner:
    """Owns feed endpoint queues like CaptureDrivenYoloFeed (test pushes results)."""

    def __init__(self):
        context = mp.get_context("spawn")
        self.results = context.Queue(maxsize=1)
        self.status = context.Queue(maxsize=4)
        self.generation = context.Value("i", 0)
        self.status.put(("ready", "cpu", None))
        self.closed = False

    def endpoint(self):
        return {"results": self.results, "status_messages": self.status,
                "generation": self.generation, "config": {"pipeline": {"enabled": True}},
                "model_path": "fake.engine"}

    def push(self, result):
        try:
            self.results.put_nowait(result)
        except Exception:
            try:
                self.results.get_nowait()
            except Exception:
                pass

    def close(self):
        self.closed = True


def test_world3d_runs_in_its_own_process_behind_the_same_interface():
    width, height = 320, 240
    prefix = f"pp_{uuid.uuid4().hex[:8]}"
    ring = SharedFrameRingBuffer.create(name_prefix=prefix, max_width=width, max_height=height)
    writer = SharedFrameRingBuffer.attach(name_prefix=prefix)
    feed = _FeedOwner()
    stop = threading.Event()

    def produce():
        index = 0
        while not stop.is_set():
            index += 1
            writer.write_frame(bytes([index % 250]) * (width * height * 4), width, height,
                               "captured", time.monotonic())
            box = WorldCandidate("unknown_subject_candidate", PixelRect(100, 60, 140, 160), .5,
                                 track_id=1, candidate_labels=("learned_subject_like",))
            feed.push(FeedResult(writer._frame_id, time.monotonic(), width, height, (box,),
                                 {"version": "world3d_v2"}, 5., time.monotonic(), index,
                                 feed.generation.value,
                                 True, {"backend": "botsort"}))
            time.sleep(1 / 40)

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()
    worker = ProcessPerceptionWorker(capture_ring=prefix, feed=feed, proposal_mode="YOLO_ONLY")
    try:
        geometry = {"client_id": "pid:1", "session_id": "s"}
        deadline = time.monotonic() + 30.
        items = []
        while time.monotonic() < deadline:
            items = worker.submit_latest(allow=True, geometry=geometry,
                                         context=("s", "g", 1, 0), world_map_open=False)
            if worker.ready_for_action(time.monotonic()) and any(
                    item.get("source") == "WORLD3D" for item in items):
                break
            time.sleep(.05)
        assert worker.ready_for_action(time.monotonic())
        assert any(item.get("source") == "WORLD3D" for item in items)
        assert worker.projection_revision > 0
        assert worker.rates(time.monotonic())["world_perception_hz"] >= 0
    finally:
        stop.set()
        producer.join(timeout=2)
        worker.close()
        writer.close()
        ring.close()
        ring.unlink()
    assert feed.closed
