import pytest

from wowbot.agent.sensor_hub import SensorHub
from wowbot.agent.sensor import BufferedPixelSensor


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


def test_hub_exposes_buffered_latest_without_consuming_or_restamping_edges():
    sensor = BufferedPixelSensor(Source())
    edge = {"frame_id": "hover-edge", "mouseover": {"guid": "npc"}}
    latest = {"frame_id": "latest", "state_age": .02}
    sensor.transitions.append((edge, 10.))
    sensor.pending = sensor.latest_payload = (latest, 10.05)
    hub = SensorHub.for_primary(sensor)
    try:
        assert hub.supports_peek_latest
        for _ in range(3):
            payload, received_at = hub.peek_latest(10.1)
            assert payload["frame_id"] == "latest"
            assert payload["state_age"] == pytest.approx(.07)
            assert received_at == 10.05
        assert len(sensor.transitions) == 1
        assert hub.poll(10.1)["frame_id"] == "hover-edge"
        assert hub.poll(10.1)["frame_id"] == "latest"
        assert hub.poll(10.1) is None
        assert hub.peek_latest(10.1)[1] == 10.05
        assert latest["state_age"] == .02
    finally:
        hub.close()
    assert hub.peek_latest(10.1) is None


@pytest.mark.parametrize("now", [9.99, 10.21, float("nan")])
def test_hub_peek_uses_original_receipt_time_and_its_freshness_limit(now):
    sensor = BufferedPixelSensor(Source())
    sensor.latest_payload = ({"frame_id": "one"}, 10.)
    hub = SensorHub.for_primary(sensor, freshness_seconds=.2)
    try:
        assert hub.peek_latest(now) is None
        assert hub.peek_latest(10.1)[1] == 10.
    finally:
        hub.close()


def test_hub_peek_respects_failure_and_never_reads_another_sensor():
    from types import SimpleNamespace
    first = SimpleNamespace(peek_latest=lambda now: ({"frame_id": "primary"}, 10.))
    other = SimpleNamespace(peek_latest=lambda now: pytest.fail("read secondary sensor"))
    hub = SensorHub({"telemetry": first, "other": other})
    assert hub.peek_latest(10.1)[0]["frame_id"] == "primary"
    hub.mark_sensor_failure("telemetry", "DEVICE_RESET")
    assert hub.peek_latest(10.1) is None
    hub.close()
    assert hub.peek_latest(10.1) is None


def test_poll_only_hub_does_not_claim_fast_snapshot_capability():
    hub = SensorHub.for_primary(Source())
    assert not hub.supports_peek_latest
    assert hub.peek_latest(10.) is None
