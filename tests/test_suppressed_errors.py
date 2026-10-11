"""Issue #31: deliberately non-blocking error paths are counted and
reported (rate-limited) instead of being swallowed silently."""
from wowbot.agent.suppressed_errors import SuppressedErrors


def test_first_occurrence_and_rate_limited_summary_are_written(tmp_path):
    clock = iter([0., 1., 2., 70.]).__next__
    log = tmp_path / "runtime_errors.log"
    errors = SuppressedErrors(log, interval_seconds=60., clock=clock)
    for _ in range(3):
        errors.report("entrance_observer", ValueError("bad row"))
    assert errors.snapshot() == {"entrance_observer:ValueError": 3}
    assert log.read_text(encoding="utf-8").count("suppressed error") == 1
    errors.report("entrance_observer", ValueError("again"))
    text = log.read_text(encoding="utf-8")
    assert text.count("suppressed error") == 2 and "x4" in text and "first: ValueError: bad row" in text


def test_failing_frame_listener_is_counted_and_others_still_run():
    import time
    from wowbot.agent.sensor import BufferedPixelSensor

    class Source:
        health = "ok"
        frame = None
        def poll(self, now):
            self.frame = (bytes(4), 1, 1)
            return {"session_id": "s", "monotonic_time": now}

    sensor = BufferedPixelSensor(Source(), interval=.005)
    ran = []
    def broken():
        raise RuntimeError("listener bug")
    sensor.frame_listeners.extend([broken, lambda: ran.append(1)])
    sensor.start()
    try:
        deadline = time.monotonic() + 2.
        while not ran and time.monotonic() < deadline:
            time.sleep(.01)
    finally:
        sensor.close()
    assert ran
    assert any(key.startswith("frame_listener:broken:RuntimeError")
               for key in sensor.diagnostics["listener_errors"])
