"""Issue #69: WORLD3D evidence must expire from the WorldModel query and
from failing/stalled perception workers instead of living on."""
from types import SimpleNamespace

from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.agent.perception_background import PerceptionBackgroundMixin

TRACK = {"source": "WORLD3D", "track_id": "WORLD3D:5", "x": .5, "y": .5, "confidence": .8}


def _addon(at):
    return Observation.create({"session_id": "s", "frame_id": f"a:{at}", "timestamp": at,
                               "monotonic_time": at, "map_id": 1, "position": {"x": .5, "y": .5}},
                              at)


def test_world3d_track_expires_after_the_projection_ttl():
    world = WorldModel()
    world.ingest(_addon(1.))
    world.ingest(Observation.create({"session_id": "s", "frame_id": "v:2", "surface": "WORLD3D",
                                     "visual_candidates": [TRACK]}, 2., "WORLD3D"))
    world.ingest(_addon(3.))
    assert world.query.visual_tracks(source="WORLD3D")          # still fresh
    world.ingest(_addon(100.))                                   # FAST-only for 98 s
    assert world.query.visual_tracks(source="WORLD3D") == []


class _Pump(PerceptionBackgroundMixin):
    RESULT_TTL_SECONDS = 3.

    def __init__(self):
        import threading
        self._background_lock = threading.Lock()
        self._background_wake = threading.Event()
        self._background_request = None
        self._background_result = [TRACK]
        self._background_result_at = None
        self._background_error = None


def test_background_pump_returns_nothing_when_stale_or_never_produced(monkeypatch):
    import wowbot.agent.perception_background as background
    pump = _Pump()
    monkeypatch.setattr(background.time, "monotonic", lambda: 10.)
    assert pump.submit_latest() == []                            # no completed result
    pump._background_result_at = 9.
    assert pump.submit_latest() == [TRACK]
    pump._background_result_at = 5.
    assert pump.submit_latest() == []                            # older than the TTL


def test_exited_perception_process_stops_returning_items():
    from wowbot.agent.perception_process import ProcessPerceptionWorker
    worker = ProcessPerceptionWorker.__new__(ProcessPerceptionWorker)
    worker.items = [TRACK]
    worker.projection_at = 0.
    worker._drain = lambda: None
    worker._requests = SimpleNamespace()
    worker._process = SimpleNamespace(is_alive=lambda: False)
    import wowbot.agent.perception_process as process
    original = process._put_latest
    process._put_latest = lambda queue, value: None
    try:
        assert worker.submit_latest() == []
    finally:
        process._put_latest = original
