"""REV4 P3 consumer parity, shadow only: native views vs. the addon snapshot.

No consumer changes authority; the verdict is journaled so a live run can
prove parity before the addon transport is retired."""
from dataclasses import replace
from types import SimpleNamespace

from wowbot.agent.models import Observation
from wowbot.agent.native_parity import NativeParityMonitor, inventory_parity, quest_parity
from test_own_create_quest_log_20261030 import create_payload
from test_own_health_packets_20261030 import own_event
from test_packet_agent_bridge import addon, bridge, deliver  # noqa: F401  (pytest fixture)


def query(quests=(), membership="COMPLETE", items=()):
    slots = [{"fields": {"quest_id": {"value": quest}}} for quest in quests]
    return SimpleNamespace(
        quest_log_slots=lambda now: {"membership": membership, "slots": slots},
        native_inventory=lambda now: {"items": [{"item_id": i, "stack_count": c} for i, c in items]})


def state(quests=(), coverage="COMPLETE", items=(), complete=True):
    return {"monotonic_time": 10., "collection_coverage": {"active_quests": coverage, "inventory": "COMPLETE"},
            "active_quests": [{"quest_id": quest} for quest in quests],
            "inventory": {"items": [{"item_id": i, "count": c} for i, c in items], "complete": complete,
                          "sample_time": 10.}}


def test_questlog_parity_needs_two_complete_sides():
    assert quest_parity(query((1, 2)), state((2, 1)), 10.)["verdict"] == "AGREE"
    differ = quest_parity(query((1, 2, 5)), state((1, 2, 7)), 10.)
    assert differ["verdict"] == "DIFFER" and differ["only_native"] == [5] and differ["only_addon"] == [7]
    assert quest_parity(query((1,), membership="PARTIAL"), state((1,)), 10.)["verdict"] == "UNKNOWN"
    assert quest_parity(query((1,)), state((1,), coverage="PARTIAL"), 10.)["verdict"] == "UNKNOWN"


def test_native_counts_are_lower_bounds_and_native_only_items_are_not_judged():
    result = inventory_parity(query(items=((6948, 1), (117, 3), (2589, 4))),
                              state(items=((117, 5), (2589, 2), (159, 1))), 10.)
    assert result["verdict"] == "DIFFER" and result["native_exceeds_addon"] == [[2589, 4, 2]]
    assert result["only_native"] == [6948] and result["only_addon"] == [159]   # e.g. the hearthstone, equipped
    ok = inventory_parity(query(items=((117, 3),)), state(items=((117, 5),)), 10.)
    assert ok["verdict"] == "CONSISTENT" and ok["shared_items"] == 1
    assert inventory_parity(query(), state(items=((117, 5),)), 10.)["verdict"] == "UNKNOWN"
    assert inventory_parity(query(items=((117, 3),)), state(items=((117, 5),), complete=False),
                            10.)["verdict"] == "UNKNOWN"


def test_the_monitor_journals_only_verdict_changes_and_never_breaks():
    monitor, records = NativeParityMonitor(), []
    record = lambda now, kind, payload: records.append((now, kind, payload))
    monitor.observe(query((1,)), state((1,)), 10., record)
    monitor.observe(query((1,)), state((1,)), 11., record)                 # unchanged: nothing
    monitor.observe(query((1, 2)), state((1,)), 11.5, record)              # changed but within 2 s
    monitor.observe(query((1, 2)), state((1,)), 12.5, record)
    assert [kind for _, kind, _ in records] == ["NATIVE_PARITY", "NATIVE_PARITY"]
    assert records[0][2]["questlog"]["verdict"] == "AGREE"
    assert records[1][2]["questlog"]["only_native"] == [2]
    assert records[1][2]["counts"]["questlog:AGREE"] == 2 and records[1][2]["counts"]["questlog:DIFFER"] == 2
    broken = SimpleNamespace()                                              # no native views at all
    assert monitor.assess(broken, state(), 20.)["questlog"]["verdict"] == "UNKNOWN"


def test_the_engine_carries_one_shadow_monitor():
    import inspect
    from wowbot.agent import engine
    source = inspect.getsource(engine)
    assert "NativeParityMonitor()" in source and "self.native_parity.observe(" in source


def test_a_real_native_create_baseline_meets_the_addon_questlog(bridge):
    """Through the packet bridge: the cold CREATE baseline (quest 55639) vs. the addon list."""
    bridge.world.ingest(Observation.create(addon(game_build='70575'), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = own_event()
    event = next(e for e in decoder.decode_all(replace(record, payload=create_payload()))
                 if e.event_type == 'OWN_QUEST_LOG_UPDATE')
    deliver(bridge, event)
    world_state = {**bridge.world.state, "collection_coverage": {"active_quests": "COMPLETE"}}
    result = quest_parity(bridge.world.query, world_state, 10.)
    assert result["verdict"] == "AGREE" and result["quests"] == 1        # the addon lists quest 55639 only
