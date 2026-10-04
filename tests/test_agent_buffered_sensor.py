import threading
import time
from wowbot.agent.sensor import BufferedPixelSensor, PixelSensor


def test_mailbox_does_not_make_old_observations_fresh():
    sensor = BufferedPixelSensor(None)
    sensor.pending = ({"state_age": 1., "frame_id": "one"}, 5.)
    assert sensor.poll(5.2)["state_age"] == 1.2000000000000002
    assert sensor.poll(5.3) is None
    sensor.pending = ({"state_age": 0.}, 5.)
    assert sensor.poll(6.) is None


def test_mailbox_preserves_short_lived_mouseover_transition():
    sensor = BufferedPixelSensor(None)
    base = {"frame_id": "one", "state_age": 0., "mouseover": False}
    hover = {"frame_id": "two", "state_age": 0.,
             "mouseover": {"guid": "Creature-1", "name": "Jaina"}}
    after = {"frame_id": "three", "state_age": 0., "mouseover": False}
    sensor._last_transition_key = sensor._transition_key(base)
    sensor.transitions.append((hover, 5.0))
    sensor.pending = (after, 5.05)
    assert sensor.poll(5.1)["mouseover"]["guid"] == "Creature-1"
    assert sensor.poll(5.11)["frame_id"] == "three"


def test_transition_key_ignores_cursor_motion_but_tracks_identity_and_ui():
    first = {"cursor_position": {"nx": .1}, "mouseover": {"guid": "A"},
             "quest_ui": {"open": False}}
    moved = {**first, "cursor_position": {"nx": .9}}
    changed = {**moved, "mouseover": {"guid": "B"}}
    assert BufferedPixelSensor._transition_key(first) == BufferedPixelSensor._transition_key(moved)
    assert BufferedPixelSensor._transition_key(first) != BufferedPixelSensor._transition_key(changed)


def test_sensor_continues_while_consumer_is_busy_and_closes():
    class Source:
        health = "streaming"
        frame = None
        def __init__(self):
            self.count = 0
            self.produced = threading.Event()
        def poll(self, now):
            self.count += 1
            if self.count >= 4:
                self.produced.set()
            return {"frame_id": str(self.count), "state_age": 0.}
    source = Source()
    sensor = BufferedPixelSensor(source, interval=.005)
    try:
        sensor.start()
        assert source.produced.wait(2)
        # No consumer poll was needed to keep assembling data.
        assert sensor.diagnostics["updates"] >= 3
        assert sensor.diagnostics["coalesced"] >= 2
    finally:
        sensor.close()
    assert not sensor.thread.is_alive()
    assert sensor.pending is None


def test_sensor_diagnostics_expose_worker_and_source_rates():
    class Source:
        health = "streaming"
        frame = None
        diagnostics = {"source_fast_hz": 45.0}

    sensor = BufferedPixelSensor(Source(), interval=1/120)
    sensor.polls = 12
    sensor.updates = 8
    now = time.monotonic()
    for index in range(12):
        sensor.poll_rate.mark(now-(11-index)*.01)
    for index in range(8):
        sensor.update_rate.mark(now-(7-index)*.01)
    diagnostics = sensor.diagnostics
    assert diagnostics["interval_ms"] == 8.333
    assert diagnostics["poll_hz"] > 10
    assert diagnostics["update_hz"] > 7
    assert diagnostics["source"]["source_fast_hz"] == 45.0


def test_dxgi_no_new_frame_does_not_masquerade_as_focus_loss():
    class Capture:
        last_capture_status = "no_new_frame"
        def capture(self):
            return None

    sensor = PixelSensor(Capture())
    prior_frame = (b"pixels", 1, 1)
    sensor.frame = prior_frame
    sensor.health = "streaming"
    assert sensor.poll(time.monotonic()) is None
    assert sensor.health == "streaming"
    assert sensor.frame is prior_frame
