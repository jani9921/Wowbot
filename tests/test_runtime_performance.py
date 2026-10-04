import pytest

from wowbot.runtime.performance import PerformanceMonitor, measure_input_dispatch


def test_performance_monitor_reports_bounded_percentiles_and_capture_rate():
    monitor = PerformanceMonitor(window=8)
    for index, duration in enumerate((2., 4., 6., 8.)):
        monitor.observe_latency("perception", duration)
        monitor.observe_capture(float(index))
    monitor.observe_event_queue_depth(3)
    monitor.observe_rate("capture_fps", 59.5)
    snapshot = monitor.snapshot(4.)
    assert snapshot["capture_fps"] == 59.5
    assert snapshot["rates"]["capture_fps"]["latest"] == 59.5
    assert snapshot["event_queue_depth_latest"] == 3
    assert snapshot["latencies"]["perception"]["p50_ms"] == 5.
    assert snapshot["latencies"]["perception"]["p95_ms"] > 7.
    assert snapshot["latencies"]["perception"]["p99_ms"] > 7.
    assert snapshot["latencies"]["perception"]["max_ms"] == 8.


def test_performance_monitor_rejects_invalid_measurements():
    monitor = PerformanceMonitor()
    monitor.observe_latency("input_dispatch", -1.)
    monitor.observe_latency("input_dispatch", float("nan"))
    assert monitor.summary("input_dispatch").count == 0


def test_input_dispatch_measurement_preserves_failure_semantics():
    class FailingExecutor:
        def __init__(self):
            self.performance_monitor = PerformanceMonitor()

        @measure_input_dispatch
        def execute(self):
            raise RuntimeError("dispatch failed")

    executor = FailingExecutor()
    with pytest.raises(RuntimeError, match="dispatch failed"):
        executor.execute()
    assert executor.performance_monitor.summary("input_dispatch").count == 1
