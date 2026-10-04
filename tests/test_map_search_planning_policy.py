from __future__ import annotations

from wowbot.agent.map_search_planning import WorldMapFallbackPolicy
from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation, Outcome, Proposal
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def _world(**extra) -> WorldModel:
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "test:player", "timestamp": 1., "frame_id": "f1",
        "map_id": 1409, "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, "is_in_combat": False,
        "is_casting": False, "target": {}, "active_quests": [], **extra,
    }, 1.))
    return world


def test_tdb_reference_is_only_proposed_after_world_map_exhaustion() -> None:
    policy = WorldMapFallbackPolicy()
    goal = Goal.parse("Questelj", 1.)
    world = _world(quest_role_reference_candidates=[{
        "source": "TDB_REFERENCE", "role_hypothesis": "QUEST_STARTER",
        "spawn_ids": [9], "npc_ids": [156626], "quest_ids": [54951],
        "world_map_id": 2175, "x": 10., "y": 20., "z": 2.,
        "distance_yards": 12., "coordinate_space": "WORLD_YARDS",
        "identity_confirmed": False,
    }])
    proposals: list[Proposal] = []

    policy.add_quest_fallbacks(proposals, goal, world, 1., blocked_until={})
    assert [proposal.skill for proposal in proposals] == ["OPEN_MAP"]

    policy.state.exhausted = True
    proposals.clear()
    policy.add_quest_fallbacks(proposals, goal, world, 2., blocked_until={})
    assert [proposal.skill for proposal in proposals] == ["REACH_LOCATION"]
    assert proposals[0].parameters["source"] == "TDB_REFERENCE"
    assert proposals[0].parameters["purpose"] == "INSPECT_REFERENCE_LOCATION"
    assert proposals[0].parameters["identity_confirmed"] is False


def test_current_session_map_evidence_prevents_false_exhaustion() -> None:
    policy = WorldMapFallbackPolicy()
    policy.state.last_scan_started = 5.
    world = _world(world_map_open=True, remembered_locations=[{
        "map_id": 1409, "x": .6, "y": .7, "semantic_type": "QUEST_GIVER",
        "provenance": {"session_id": "test:player", "marker_associated": True,
                       "observed_monotonic": 6.},
    }])
    quest = QuestDomain()
    policy.state.context = (world.session_id, 1409, None)
    policy.state.scan_started = 1.

    result = policy.pre_domain_proposals(
        Goal.parse("Questelj", 1.), world, 20., registry=SkillRegistry(), quest=quest,
        inspections=lambda *_args: [])

    assert result and result[0].skill == "CLOSE_MAP"
    assert policy.state.exhausted is False
    assert quest.allow_db_fallback is False


def test_screen_edge_tooltip_does_not_keep_map_search_alive() -> None:
    policy = WorldMapFallbackPolicy()
    policy.state.last_scan_started = 5.
    world = _world(world_map_open=True, active_quests=[{"quest_id": 56775}],
                   remembered_locations=[{
        "map_id": 1409, "x": 1.0, "y": .153, "semantic_type": "QUEST_RELATED",
        "location_kind": "MAP_INSPECTION_AREA", "entity_position_confirmed": False,
        "provenance": {"session_id": "test:player", "marker_associated": True,
                       "observed_monotonic": 6., "semantic_source": "TOOLTIP"},
    }])
    quest = QuestDomain()
    policy.state.context = (world.session_id, 1409, None)
    policy.state.scan_started = 1.

    result = policy.pre_domain_proposals(
        Goal.parse("Questelj", 1.), world, 20., registry=SkillRegistry(), quest=quest,
        inspections=lambda *_args: [])

    assert result and result[0].skill == "CLOSE_MAP"
    assert policy.state.exhausted is True
    assert quest.allow_db_fallback is True


def test_selected_living_attackable_target_blocks_reopening_world_map() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(target={"guid": "dummy", "name": "Combat Dummy",
                           "attackable": True, "dead": False},
                   active_quests=[{"quest_id": 56775}])
    proposals: list[Proposal] = []

    policy.add_quest_fallbacks(
        proposals, Goal.parse("Questelj", 1.), world, 10., blocked_until={})

    assert proposals == []


def test_recent_confirmed_anchor_for_committed_friendly_blocks_map_fallback() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(
        monotonic_time=20.,
        target={"guid": "npc", "attackable": False, "dead": False})
    # confirmed_mouseover_anchors is a WorldModel-derived projection, not a
    # client-owned input field, so install the already-validated projection
    # directly for this policy-level unit test.
    world.state["confirmed_mouseover_anchors"] = {"npc": {
        "guid": "npc", "x": .55, "y": .6, "sample_time": 10.,
        "source": "CONFIRMED_MOUSEOVER_ANCHOR",
    }}
    world.set_runtime_context(commitment={
        "kind": "TARGET", "target_guid": "npc"})
    quest = QuestDomain()
    quest.interaction_range_blocks["npc"] = {"started_at": 9.}
    proposals: list[Proposal] = []

    policy.add_quest_fallbacks(
        proposals, Goal.parse("Questelj", 1.), world, 20., blocked_until={})

    assert proposals == []


def test_recent_committed_anchor_blocks_map_even_if_retail_selection_temporarily_drops() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(monotonic_time=20., target={})
    world.state["confirmed_mouseover_anchors"] = {"npc": {
        "guid": "npc", "x": .55, "y": .6, "sample_time": 10.,
        "source": "CONFIRMED_MOUSEOVER_ANCHOR",
    }}
    world.set_runtime_context(commitment={
        "kind": "TARGET", "target_guid": "npc"})
    proposals: list[Proposal] = []

    policy.add_quest_fallbacks(
        proposals, Goal.parse("Questelj", 1.), world, 20., blocked_until={})

    assert proposals == []


def test_map_reopen_cooldown_is_skill_level_not_proposal_key_level() -> None:
    policy = WorldMapFallbackPolicy()
    policy.state.reopen_blocked_until = 40.
    world = _world()
    goal = Goal.parse("Questelj", 1.)

    blocked: list[Proposal] = []
    policy.add_quest_fallbacks(blocked, goal, world, 20., blocked_until={})
    assert blocked == []

    allowed: list[Proposal] = []
    policy.add_quest_fallbacks(allowed, goal, world, 41., blocked_until={})
    assert [proposal.skill for proposal in allowed] == ["OPEN_MAP"]


def test_closing_map_for_committed_visual_target_starts_reopen_cooldown() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(
        world_map_open=True,
        target={"guid": "npc", "attackable": False, "dead": False})
    world.set_runtime_context(commitment={
        "kind": "TARGET", "target_guid": "npc"})
    quest = QuestDomain()
    quest.interaction_range_blocks["npc"] = {"started_at": 1.}

    result = policy.pre_domain_proposals(
        Goal.parse("Questelj", 1.), world, 10., registry=SkillRegistry(),
        quest=quest, inspections=lambda *_args: [])

    assert result and result[0].skill == "CLOSE_MAP"
    assert policy.state.reopen_blocked_until == 40.


def test_blocked_live_location_does_not_suppress_map_fallback() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world()
    goal = Goal.parse("Questelj", 1.)
    blocked = Proposal.make("MOVE", "blocked location", {"x": .6, "y": .7})
    proposals = [blocked]

    policy.add_quest_fallbacks(
        proposals, goal, world, 10., blocked_until={blocked.key: 20.})

    assert proposals[-1].skill == "OPEN_MAP"


def test_verified_terminal_updates_map_zoom_and_reference_lifecycle_only() -> None:
    policy = WorldMapFallbackPolicy()
    quest = QuestDomain()
    inspect = SimpleNamespace(proposal=Proposal.make(
        "INSPECT", "map marker", {"source": "WORLD_MAP_CV"}))

    policy.on_terminal(
        inspect, Outcome.FAILURE, "expected_observation_missing", quest)

    assert policy.state.zoom_requested is True
    fallback_key = ("test:player", (9, 7))
    reach = SimpleNamespace(proposal=Proposal.make(
        "REACH_LOCATION", "reference", {
            "source": "TDB_REFERENCE", "fallback_key": fallback_key}))
    policy.on_terminal(reach, Outcome.FAILURE, "supported_stuck", quest)
    assert ("test:player", (7, 9)) in policy.state.used_location_fallbacks

    quest.interaction_range_blocks["npc"] = {"belief": "SUPPORTED"}
    interact = SimpleNamespace(proposal=Proposal.make(
        "REACH_OBJECT", "reference target", {
            "source": "TDB_REFERENCE", "fallback_key": (9, 7), "guid": "npc"}))
    policy.on_terminal(interact, Outcome.SUCCESS, "arrived", quest)
    assert (9, 7) in quest.used_spawn_fallbacks
    assert "npc" not in quest.interaction_range_blocks
    assert "npc" in quest.reference_arrivals


def test_missing_marker_steps_out_only_to_addon_reported_parent_map() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(
        world_map_open=True,
        active_quests=[{"quest_id": 54951, "objectives": []}],
        map_context={"player_map_id": 1409, "displayed_map_id": 1409,
                     "active_map_id": 1409, "parent_map_id": 13,
                     "parent_map_name": "Eastern Kingdoms", "world_map_open": True})
    policy.state.context = (world.session_id, 1409, None)
    policy.state.scan_started = 1.
    policy.state.last_scan_started = 1.
    registry = SkillRegistry()

    result = policy.pre_domain_proposals(
        Goal.parse("Questelj", 1.), world, 20., registry=registry,
        quest=QuestDomain(), inspections=lambda *_args: [])

    assert result and result[0].skill == "INSPECT"
    assert result[0].parameters["map_step_out"] is True
    assert result[0].parameters["expected_parent_map_id"] == 13
    assert result[0].parameters["absence_semantics"] == "UNKNOWN"
    assert registry.commands(result[0], world)[0].kind == "MAP_STEP_OUT"


def test_zero_parent_map_sentinel_closes_scan_instead_of_step_out_loop() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(
        world_map_open=True,
        active_quests=[{"quest_id": 55122, "objectives": []}],
        map_context={"active_map_id": 1409, "parent_map_id": 0,
                     "world_map_open": True})
    policy.state.context = (world.session_id, 1409, None)
    policy.state.scan_started = policy.state.last_scan_started = 1.
    quest = QuestDomain()

    result = policy.pre_domain_proposals(
        Goal.parse("Questelj", 1.), world, 20., registry=SkillRegistry(),
        quest=quest, inspections=lambda *_args: [])

    assert result and result[0].skill == "CLOSE_MAP"
    assert policy.state.parent_map_id is None
    assert policy.state.exhausted is True
    assert quest.allow_db_fallback is True


def test_external_map_close_terminates_scan_and_prevents_reopen_loop() -> None:
    policy = WorldMapFallbackPolicy()
    quest = QuestDomain()
    goal = Goal.parse("Questelj", 1.)
    open_world = _world(
        world_map_open=True, active_quests=[{"quest_id": 55122}],
        map_context={"active_map_id": 1409, "parent_map_id": 0,
                     "world_map_open": True})
    policy.state.context = (open_world.session_id, 1409, None)
    policy.state.scan_started = policy.state.last_scan_started = 5.

    closed_world = _world(
        world_map_open=False, active_quests=[{"quest_id": 55122}],
        map_context={"active_map_id": 1409, "parent_map_id": 0,
                     "world_map_open": False})
    assert policy.pre_domain_proposals(
        goal, closed_world, 6., registry=SkillRegistry(), quest=quest,
        inspections=lambda *_args: []) is None
    proposals: list[Proposal] = []
    policy.add_quest_fallbacks(
        proposals, goal, closed_world, 6., blocked_until={})

    assert policy.state.exhausted is True
    assert quest.allow_db_fallback is True
    assert not any(proposal.skill == "OPEN_MAP" for proposal in proposals)


def test_untracked_marker_absence_stays_unknown_and_does_not_step_parent() -> None:
    policy = WorldMapFallbackPolicy()
    world = _world(
        world_map_open=True,
        map_context={"active_map_id": 1409, "parent_map_id": 13,
                     "parent_map_name": "Eastern Kingdoms", "world_map_open": True})
    policy.state.context = (world.session_id, 1409, None)
    policy.state.scan_started = policy.state.last_scan_started = 1.

    result = policy.pre_domain_proposals(
        Goal.parse("Questelj", 1.), world, 20., registry=SkillRegistry(),
        quest=QuestDomain(), inspections=lambda *_args: [])

    assert result and result[0].skill == "CLOSE_MAP"
    assert policy.state.exhausted is True
