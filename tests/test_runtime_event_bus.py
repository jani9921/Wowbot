from wowbot.runtime import ActiveSkillRuntime, EventBus, Intent, RuntimeEvent
from concurrent.futures import ThreadPoolExecutor


def test_event_bus_deduplicates_explicit_id_and_preserves_idless_events():
    bus = EventBus()
    event = RuntimeEvent("COMBAT_STARTED", 1., event_id="same", source="test")
    assert bus.publish(event) is True
    assert bus.publish(event) is False
    assert bus.publish(RuntimeEvent("WORLD_OBSERVATION_UPDATED", 1.)) is True
    assert len(bus.consume()) == 2


def test_event_bus_orders_safety_before_observation_and_dispatch_stably():
    bus = EventBus()
    bus.publish(RuntimeEvent("SKILL_STARTED", 1.))
    bus.publish(RuntimeEvent("WORLD_OBSERVATION_UPDATED", 1.))
    bus.publish(RuntimeEvent("PLAYER_DIED", 1.))
    assert [event.event_type for event in bus.consume()] == [
        "PLAYER_DIED", "WORLD_OBSERVATION_UPDATED", "SKILL_STARTED"]


def test_active_skill_lifecycle_events_are_correlated_and_idempotent_ready():
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("INTERACT"), attempt=object(), now=1.)
    events = runtime.drain_events()
    assert events[0].event_id and events[0].source == "ACTIVE_SKILL_RUNTIME"
    assert events[0].correlation_id == runtime.state.runtime_id


def test_event_bus_coalesces_low_value_updates_and_keeps_latest_event():
    bus = EventBus()
    bus.publish(RuntimeEvent("ENTITY_UPDATED", 1., {"track_id": "t-1", "version": 1}))
    bus.publish(RuntimeEvent("ENTITY_UPDATED", 2., {"track_id": "t-1", "version": 2}))

    events = bus.consume()
    assert len(events) == 1 and events[0].metadata["version"] == 2
    assert bus.diagnostics()["coalesced"] == 1


def test_event_bus_never_silently_drops_critical_event_when_queue_is_full():
    bus = EventBus(max_events=8)
    for index in range(8):
        assert bus.publish(RuntimeEvent("WORLD_OBSERVATION_UPDATED", float(index)))
    assert bus.publish_critical(RuntimeEvent("PLAYER_DIED", 9.))

    events = bus.consume()
    assert any(event.event_type == "PLAYER_DIED" for event in events)
    assert bus.diagnostics()["dropped"] >= 1


def test_all_critical_queue_overflow_is_preserved_and_observable():
    bus = EventBus(max_events=8)
    for index in range(8):
        assert bus.publish(RuntimeEvent(
            "PLAYER_DIED", float(index), event_id=f"death:{index}"))
    assert bus.publish(RuntimeEvent(
        "LOOP_CONFIRMED", 9., event_id="loop:confirmed"))

    diagnostics = bus.diagnostics()
    assert diagnostics["queue_depth"] == 9
    assert diagnostics["critical_overflow"] == 1
    assert diagnostics["dropped"] == 0
    assert len(bus.consume()) == 9


def test_loop_confirmation_remains_a_named_critical_event():
    bus = EventBus(max_events=8)
    bus.publish_critical(RuntimeEvent("LOOP_CONFIRMED", 1., {"count": 5}, event_id="loop:1"))
    assert bus.consume()[0].event_type == "LOOP_CONFIRMED"


def test_event_bus_subscriber_is_filtered_and_exception_isolated():
    bus = EventBus()
    received = []
    token = bus.subscribe("QUEST_COMPLETE", lambda event: received.append(event.event_type))
    bus.subscribe(None, lambda event: (_ for _ in ()).throw(RuntimeError("observer failure")))
    bus.publish(RuntimeEvent("QUEST_COMPLETE", 1.))

    assert received == ["QUEST_COMPLETE"]
    assert bus.unsubscribe(token)
    assert bus.diagnostics()["subscriber_errors"]
    assert bus.get_recent_events("QUEST_COMPLETE")[-1].event_type == "QUEST_COMPLETE"


def test_event_bus_is_thread_safe_for_parallel_producers_and_deduplication():
    bus = EventBus(max_events=2048, history_size=2048)

    def publish(producer):
        for sequence in range(100):
            event_id = f"{producer}:{sequence}"
            assert bus.publish(RuntimeEvent(
                "WORLD_OBSERVATION_UPDATED", float(sequence),
                {"producer": producer, "sequence": sequence},
                event_id=event_id, source=str(producer)))
            assert bus.publish(RuntimeEvent(
                "WORLD_OBSERVATION_UPDATED", float(sequence),
                event_id=event_id, source=str(producer))) is False

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(publish, range(8)))

    events = bus.consume()
    assert len(events) == 800
    for producer in range(8):
        ordered = [event.metadata["sequence"] for event in events
                   if event.metadata.get("producer") == producer]
        assert ordered == list(range(100))
    assert bus.diagnostics()["queue_depth"] == 0
