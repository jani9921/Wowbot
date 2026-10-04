import pytest

from wowbot.agent.sensor_hub import SensorHub


class Source:
    health = "streaming"
    frame = (b"pixels", 1, 1)
    diagnostics = {"update_hz": 30.0}

    def __init__(self):
        self.interval = .025
        self.values = []
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def close(self):
        self.closed = True

    def poll(self, now):
        return self.values.pop(0) if self.values else None


def test_hub_owns_lifecycle_rate_and_compatibility_projection():
    source = Source()
    hub = SensorHub.for_primary(source, clock=lambda: 10.0)
    hub.start()
    assert source.started
    assert hub.frame == source.frame
    assert hub.source is None
    assert hub.interval == .025
    hub.set_rate("telemetry", 50)
    assert source.interval == pytest.approx(.02)
    assert hub.health == "streaming"
    assert hub.diagnostics["sensors"]["telemetry"]["rate_hz"] == 30.0
    hub.close()
    assert source.closed


def test_latest_value_dominates_and_stale_value_is_dropped():
    clock = [1.0]
    source = Source()
    hub = SensorHub.for_primary(source, freshness_seconds=.5, clock=lambda: clock[0])
    hub.publish_frame("telemetry", {"frame_id": "old"}, published_at=.0)
    hub.publish_frame("telemetry", {"frame_id": "new"}, published_at=1.0)
    assert hub.poll_latest() == {"frame_id": "new"}
    assert hub.poll_latest() is None

    hub.publish_frame("telemetry", {"frame_id": "stale"}, published_at=1.0)
    clock[0] = 1.6
    assert hub.poll_latest() is None


def test_poll_publishes_source_value_and_failure_invalidates_mailbox():
    clock = [2.0]
    source = Source()
    source.values.append({"frame_id": "one"})
    hub = SensorHub.for_primary(source, clock=lambda: clock[0])
    assert hub.poll(2.0) == {"frame_id": "one"}
    hub.publish_frame("telemetry", {"frame_id": "two"})
    hub.mark_sensor_failure("telemetry", "DEVICE_RESET")
    assert hub.poll_latest() is None
    health = hub.sensor_health()
    assert health.failure_reason == "DEVICE_RESET"
    assert not health.fresh


def test_hub_rejects_invalid_configuration():
    source = Source()
    with pytest.raises(ValueError, match="primary"):
        SensorHub({"telemetry": source}, primary="vision")
    hub = SensorHub.for_primary(source)
    with pytest.raises(ValueError, match="positive"):
        hub.set_rate("telemetry", 0)
    with pytest.raises(KeyError, match="unknown sensor"):
        hub.mark_sensor_failure("missing", "bad")
