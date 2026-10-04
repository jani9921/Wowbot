from wowbot.runtime import HealthMonitor


def test_health_monitor_reports_staleness_without_owning_control():
    monitor = HealthMonitor(stale_after_seconds=2.)
    healthy = monitor.observe(now=2., last_received=1., event_bus={"queue_depth": 3}, active_skill="MOVE")
    assert healthy.status == "HEALTHY"
    stale = monitor.observe(now=5., last_received=1., event_bus={"queue_depth": 0}, active_skill=None)
    assert stale.status == "DEGRADED"
    assert stale.reasons == ("observation_stale",)


def test_health_monitor_distinguishes_real_bus_supervisor_and_input_stalls():
    monitor = HealthMonitor(stale_after_seconds=2.)
    report = monitor.observe(
        now=10., last_received=9., active_skill="MOVE",
        event_bus={"queue_depth": 2, "last_consumed_at": 5.},
        last_supervisor_tick=5.,
        input_safety={"movement_watchdog_alive": False},
    )
    assert report.status == "DEGRADED"
    assert set(report.reasons) == {"event_bus_stalled", "supervisor_stalled", "input_watchdog_unhealthy"}


def test_empty_quiet_event_bus_is_not_reported_as_a_stall():
    report = HealthMonitor(stale_after_seconds=2.).observe(
        now=10., last_received=9., active_skill=None,
        event_bus={"queue_depth": 0, "last_consumed_at": 1.},
    )
    assert report.status == "HEALTHY"


def test_health_monitor_surfaces_isolated_event_subscriber_errors():
    report = HealthMonitor().observe(
        now=2., last_received=2., active_skill=None,
        event_bus={"queue_depth": 0, "subscriber_errors": [{"error": "boom"}]},
    )
    assert report.status == "DEGRADED"
    assert report.reasons == ("subscriber_failure",)
