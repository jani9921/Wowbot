import threading
import time

from wowbot.agent.sensor import BufferedPixelSensor
from wowbot.agent.sensor_hub import SensorHub


class _ChangingFrameSource:
    health = "streaming"

    def __init__(self):
        self.frame = None
        self.count = 0

    def poll(self, now):
        self.count += 1
        self.frame = (bytes([self.count % 256]) * 16, 2, 2)
        return None


def test_new_capture_frame_wakes_registered_listeners():
    sensor = BufferedPixelSensor(_ChangingFrameSource(), interval=.005)
    woke = threading.Event()
    hub = SensorHub.for_primary(sensor)
    assert hub.add_frame_listener(woke.set) is True
    sensor.start()
    try:
        assert woke.wait(2.0)
    finally:
        sensor.stop_event.set()
        sensor.thread.join(timeout=2.0)


def test_listener_errors_do_not_stop_the_sensor():
    source = _ChangingFrameSource()
    sensor = BufferedPixelSensor(source, interval=.005)

    def broken():
        raise RuntimeError("listener failure")

    sensor.frame_listeners.append(broken)
    sensor.start()
    try:
        deadline = time.monotonic() + 2.0
        while source.count < 5 and time.monotonic() < deadline:
            time.sleep(.01)
        assert source.count >= 5
        assert not str(sensor.health).startswith("sensor_error")
    finally:
        sensor.stop_event.set()
        sensor.thread.join(timeout=2.0)
