from types import SimpleNamespace

from adapters.telemetry_packets import normalize
from wowbot.agent.models import Command, Observation, Outcome, Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def test_normalize_flattens_combat_hint_like_quest_ui():
    # PREPARED 2026-09-14, UNTESTED LIVE (needs the matching addon change --
    # combat_hint in AIPlayerControllerExport.lua -- installed/reloaded).
    # Mirrors quest_ui's own flattening, added the same way for the same
    # reason: skills.py's COMBAT/DEFEND verify() otherwise only sees a
    # landed spell cast via the slow/paged `events` list.
    value = {"quest_ui": {}, "combat_hint": {"spell_id": 123, "at": 45.6}}
    result = normalize(value)
    assert result["combat_last_spell_id"] == 123
    assert result["combat_last_cast_at"] == 45.6


def test_normalize_combat_hint_missing_defaults_to_none():
    value = {"quest_ui": {}}
    result = normalize(value)
    assert result["combat_last_spell_id"] is None
    assert result["combat_last_cast_at"] is None


def test_fast_lane_combat_fields_reach_world_state():
    # If these aren't in world.py's fast_keys, a FAST-lane packet's
    # combat_hint update never actually reaches world.state -- silently
    # defeating the whole point of this change. Mirrors
    # test_fast_state_updates_control_fields_without_refreshing_slow_facts's
    # pattern in test_agent_core.py.
    from wowbot.agent.models import Observation

    def state(t, **overrides):
        result = {"session_id": "test", "timestamp": t, "monotonic_time": t,
                  "map_id": 1609, "active_quests": [], "combat_last_spell_id": None,
                  "combat_last_cast_at": None}
        result.update(overrides)
        return result

    world = WorldModel()
    full = state(10, transport_kind="STATE", telemetry_lane="FULL_STATE")
    assert world.ingest(Observation.create(full, 10))
    fast = state(11, combat_last_spell_id=123, combat_last_cast_at=1.5,
                 transport_kind="FAST", telemetry_lane="FAST_STATE", fast_sequence=1)
    assert world.ingest(Observation.create(fast, 11))
    assert world.state["combat_last_spell_id"] == 123
    assert world.state["combat_last_cast_at"] == 1.5


def _make_attempt(baseline, started_at=0.):
    return SimpleNamespace(
        observation_id="baseline", deadline=8., started_at=started_at, baseline=baseline,
        proposal=Proposal.make("COMBAT", "test", {"guid": "boar", "quest_ids": []}),
        commands=(Command("BIND", "1", .05),))


def test_fast_cast_verified_confirms_combat_without_waiting_for_slow_events():
    registry = SkillRegistry()
    before = {"actionbar": [{"action": "1", "id": 123}], "target": {"guid": "boar", "health": 50},
              "active_quests": [], "combat_last_spell_id": None, "combat_last_cast_at": None,
              "event_sequence": 0, "events": [], "inventory": {}}
    world = WorldModel()
    world.ingest(Observation.create({**before, "combat_last_spell_id": 123,
                                     "combat_last_cast_at": 1.5}, 1.6))
    attempt = _make_attempt(before)
    outcome, reason = registry.verify(attempt, world, 1.6)
    assert outcome == Outcome.SUCCESS
    assert reason == "expected_observation_verified"


def test_fast_cast_verified_requires_a_newer_cast_time_than_baseline():
    # An unchanged combat_last_cast_at (a stale fast-lane sample, not a new
    # cast this attempt) must not be treated as fresh confirmation.
    registry = SkillRegistry()
    before = {"actionbar": [{"action": "1", "id": 123}], "target": {"guid": "boar", "health": 50},
              "active_quests": [], "combat_last_spell_id": 123, "combat_last_cast_at": 1.5,
              "event_sequence": 0, "events": [], "inventory": {}}
    world = WorldModel()
    world.ingest(Observation.create(dict(before), 8.1))
    attempt = _make_attempt(before)
    outcome, reason = registry.verify(attempt, world, 8.1)
    assert outcome == Outcome.FAILURE
