"""Offline regressions from the user-operated 09:00 Murloc Mania run.

No game input or live completion claim. Check the actual reducer, movement
handoff, visual identity gate and planner, not a quest-ID-specific script.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.vision_seek import SeekVisualCueController
from wowbot.agent.world import WorldModel


GUID = "Creature-0-4247-2175-41656-150229-000051CB55"
OBJECTIVE = {"objective_id": "55122:0", "type": "COLLECT", "raw_type": "item",
             "description": "0/6 First Aid Kits recovered from defeated Murlocs",
             "current": 0, "required": 6, "is_complete": False}
AREA = {"map_id": 1409, "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS",
        "instance_id": 2175, "x": 100., "y": 100., "source": "TDB_SPAWN",
        "knowledge_priority": "PRIMARY_STATIC", "z_known": False}
MOUSE = {"guid": GUID, "npc_id": 150229, "name": "Murloc Watershaper",
         "unit_type": "NPC", "is_attackable": True, "is_dead": False,
         "quest_related": True, "identity_source": "WOW_API_MOUSEOVER",
         "tooltip": "Murloc Watershaper ~ Murloc Mania ~ " + OBJECTIVE["description"]}


def snapshot(at=10., *, mouse=None, player_x=70., **extra):
    return {"session_id": "murloc-regression:player", "frame_id": f"full:{at}",
            "transport_kind": "STATE_Z", "timestamp": at, "monotonic_time": at,
            "state_sample_time": at, "map_id": 1409, "player_present": True,
            "character_guid": "Player-self", "is_in_combat": False,
            "player_world_position": {"coordinate_space": "WORLD_YARDS",
                "instance_id": 2175, "x": player_x, "y": 100.},
            "target": None, "mouseover": deepcopy(mouse),
            "cursor_position": {"nx": .3, "ny": .45},
            "active_quests": [{"quest_id": 55122, "title": "Murloc Mania",
                "is_complete": False, "objectives": [{**OBJECTIVE, "search_area": AREA}]}],
            "actionbar": [{"kind": "spell", "action": "1", "id": 100,
                "is_harmful": True, "is_usable": True, "in_range": True,
                "cooldown_remaining": 0.}], **extra}


def ingest(payload, received=None):
    world = WorldModel()
    assert world.ingest(Observation.create(payload, received or payload["monotonic_time"]))
    return world


def move(purpose="SEARCH_LOCAL_OBJECTIVE_AREA"):
    return SimpleNamespace(proposal=Proposal.make("MOVE", "quest route", {
        **AREA, "quest_id": 55122, "objective_id": "55122:0",
        "objective_type": "COLLECT", "purpose": purpose, "stop_distance": 8.}))


@pytest.mark.parametrize("purpose", ["SEARCH_LOCAL_OBJECTIVE_AREA",
                                    "LOCATE_QUEST_OBJECTIVE_REGION"])
def test_fresh_named_murloc_interrupts_route_even_away_from_endpoint(purpose):
    world = ingest(snapshot(mouse=MOUSE))
    handoff = movement_visual_interrupt(move(purpose), world.state)
    assert handoff and handoff["kind"] == "OBJECTIVE_UNIT_HOVERED"
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 10.), world, 10.)
    assert proposals[0].skill == "TARGET"
    assert proposals[0].parameters["guid"] == GUID


@pytest.mark.parametrize("unit", [
    {**MOUSE, "guid": "Player-other", "is_player": False},
    {**MOUSE, "unit_type": "PLAYER"},
    {**MOUSE, "dead": None, "is_dead": True},
    {**MOUSE, "health": 0},
    {**MOUSE, "name": "Rabbit", "quest_related": False, "tooltip": "Rabbit"},
])
def test_player_dead_or_irrelevant_unit_does_not_interrupt(unit):
    assert movement_visual_interrupt(move(), ingest(snapshot(mouse=unit)).state) is None


@pytest.mark.parametrize("extra", [
    {"mouseover_sample_time": 9.},
    {"mouseover_sample_time": 10.1},
    {"mouseover_sample_time": 10., "cursor_sample_time": 9.8},
    {"map_mouseover": {"surface": "WORLD_MAP"}},
    {"map_mouseover": {"surface": "MINIMAP"}},
])
def test_incoherent_or_nonworld_hover_does_not_interrupt(extra):
    assert movement_visual_interrupt(move(), ingest(snapshot(mouse=MOUSE, **extra)).state) is None


def test_completed_collect_objective_cannot_interrupt_again():
    payload = snapshot(mouse=MOUSE)
    payload["active_quests"][0]["objectives"][0].update(current=6, is_complete=True)
    assert movement_visual_interrupt(move(), ingest(payload).state) is None


def waiting_seek(state, at=10.):
    seek = SeekVisualCueController()
    seek.begin({"purpose": "IDENTIFY"}, state, at - .2)
    seek.identity_hover_requested_at = at - .1
    seek.identity_hover_mouse_sample_before = at - .3
    return seek


def test_full_sample_gives_seek_and_target_the_same_original_time_then_combat():
    world = ingest(snapshot(mouse=MOUSE))
    assert world.state["mouseover_sample_time"] == 10.
    assert world.state["cursor_sample_time"] == 10.
    assessment = waiting_seek(world.state).observe(world.state, "full-hover", 10.)
    assert assessment.terminal and assessment.success
    assert assessment.reason == "identity_available_during_visual_seek"
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 10.)
    target = planner.candidates(goal, world, 10.)[0]
    assert target.skill == "TARGET" and target.parameters["guid"] == GUID
    assert SkillRegistry().available(target, world)
    assert world.ingest(Observation.create(snapshot(10.1, mouse=MOUSE, target=MOUSE), 10.1))
    assert any(p.skill == "COMBAT" for p in planner.candidates(goal, world, 10.1))
    assert world.quest_model.records[55122].objectives[0].raw["current"] == 0


@pytest.mark.parametrize("explicit", [False, True])
def test_delayed_full_or_explicit_old_sample_does_not_confirm_new_hover(explicit):
    extra = ({"mouseover_sample_time": 8., "cursor_sample_time": 8.} if explicit
             else {"state_sample_time": 8.})
    world = ingest(snapshot(mouse=MOUSE, **extra), received=10.)
    assert world.state["mouseover_sample_time"] == 8.
    result = waiting_seek(world.state).observe(world.state, "old-full", 10.)
    assert not result.terminal
    assert not any(p.skill == "TARGET" for p in
                   Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 10.), world, 10.))


@pytest.mark.parametrize("unit", [{**MOUSE, "guid": "Player-other"},
                                 {**MOUSE, "is_dead": True}])
def test_seek_does_not_accept_player_or_corpse_as_new_npc_identity(unit):
    world = ingest(snapshot(mouse=unit))
    seek = waiting_seek(world.state)
    seek.intent["require_attackable"] = True
    assert not seek.observe(world.state, "wrong-unit", 10.).terminal


def located(world, policy):
    record = world.quest_model.records[55122]
    return policy.propose_objective(world, record.objectives[0], record, "55122")


def test_collect_arrival_is_remembered_while_searching_and_counting_items():
    policy = QuestLocationPlanningPolicy()
    world = ingest(snapshot())
    route = located(world, policy)[0]
    assert route.skill == "MOVE" and route.parameters["stop_distance"] == 8.
    policy.mark_reached(route.parameters, world.state)
    # The search walks away from the original region/spawn point.
    for count in (0, 1, 5):
        payload = snapshot(11. + count, player_x=60.)
        payload["active_quests"][0]["objectives"][0]["current"] = count
        assert world.ingest(Observation.create(payload, 11. + count))
        proposals = located(world, policy)
        assert [p.skill for p in proposals] == ["SEEK_VISUAL_CUE"]
        assert proposals[0].parameters["purpose"] == "SEARCH_LOCAL_OBJECTIVE_AREA"
        assert world.quest_model.records[55122].objectives[0].raw["current"] == count


@pytest.mark.parametrize("mouse", [None, {"guid": "Player-other", "name": "Other Player"}])
def test_collect_uses_navigation_eight_yard_arrival_not_four_yards(mouse):
    world = ingest(snapshot(player_x=94., mouse=mouse))
    assert [p.skill for p in located(world, QuestLocationPlanningPolicy())] == ["SEEK_VISUAL_CUE"]


def test_changed_region_or_map_does_not_reuse_an_old_collect_arrival():
    policy = QuestLocationPlanningPolicy()
    world = ingest(snapshot())
    policy.mark_reached(located(world, policy)[0].parameters, world.state)
    changed = snapshot(11.)
    changed["active_quests"][0]["objectives"][0]["search_area"] = {**AREA, "x": 200.}
    assert [p.skill for p in located(ingest(changed), policy)] == ["MOVE"]
    other_instance = snapshot(12.)
    other_instance["player_world_position"]["instance_id"] = 1
    assert [p.skill for p in located(ingest(other_instance), policy)] == ["MOVE"]


def test_completed_collect_objective_emits_no_new_region_action():
    payload = snapshot()
    payload["active_quests"][0]["objectives"][0].update(current=6, is_complete=True)
    assert located(ingest(payload), QuestLocationPlanningPolicy()) == []


def test_generic_combat_subject_also_interrupts_without_a_tooltip():
    world = ingest(snapshot(mouse={**MOUSE, "tooltip": "", "quest_related": False}))
    assert movement_visual_interrupt(move(), world.state)["kind"] == "OBJECTIVE_UNIT_HOVERED"


def test_addon_quest_flag_can_identify_an_item_source_without_name_guessing():
    unit = {**MOUSE, "name": "Supplies Carrier", "tooltip": "", "quest_id": 55122}
    assert movement_visual_interrupt(move(), ingest(snapshot(mouse=unit)).state)["kind"] == "OBJECTIVE_UNIT_HOVERED"
    unit["quest_id"] = 99999
    assert movement_visual_interrupt(move(), ingest(snapshot(mouse=unit)).state) is None


def test_fast_sample_does_not_inherit_the_older_paged_sample_clock():
    world = ingest(snapshot(mouse=MOUSE, transport_kind="FAST", state_sample_time=3.))
    assert world.state["mouseover_sample_time"] == 10.
    assert world.state["cursor_sample_time"] == 10.


def test_unknown_full_sample_time_is_not_invented_from_receipt():
    world = ingest(snapshot(mouse=MOUSE, state_sample_time=None), received=11.)
    assert world.state.get("mouseover_sample_time") is None
    assert not waiting_seek(world.state).observe(world.state, "unknown-time", 10.).terminal
    assert movement_visual_interrupt(move(), world.state) is None
    assert not any(p.skill == "TARGET" for p in
                   Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 10.), world, 10.))


def test_semantic_hover_cancels_movement_without_claiming_region_arrival():
    from test_active_skill_supervision import context, supervisor
    from wowbot.agent.models import Outcome
    from wowbot.runtime import SkillResult, SkillStatus

    runner = supervisor(SkillResult(SkillStatus.RUNNING))
    attempt, active, world = context("MOVE")
    world.latest = SimpleNamespace(source="ADDON", payload={})
    step = runner.step(attempt, active, world, world_observation_id="full",
        visual_observation_id="vision", now=10., reference_reach_interrupt={
            "reason": "objective_unit_under_cursor", "kind": "OBJECTIVE_UNIT_HOVERED"})
    assert step.terminal_outcome is Outcome.CANCELLED
    assert step.stop_movement and not step.commands


def test_actual_agent_replans_running_move_to_target_on_the_same_hover_sample():
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.models import Attempt, Mode, Prediction

    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.set_goal("Questelj", 9.9)
    seed = snapshot(9.9)
    assert agent.world.ingest(Observation.create(seed, 9.9))
    route = move().proposal
    agent.pending = Attempt("murloc-move", route, seed, "seed", 9.9, 30., (),
        Prediction("p", "murloc-move", "location", 9.9, 30., "seed"))
    agent.set_mode(Mode.FULL_AI)
    try:
        agent.tick(snapshot(mouse=MOUSE), 10.)
        assert agent.pending and agent.pending.proposal.skill == "TARGET"
        assert agent.pending.proposal.parameters["guid"] == GUID
        assert agent.last_result["outcome"] == "CANCELLED"
        assert not agent.planner.quest.reached_quest_locations
        assert not any(c.binding == "TARGETNEARESTENEMY" for c in executor.commands)
    finally:
        agent.set_mode(Mode.STOPPED)


def test_fast_movement_yields_exact_hover_without_finalizing_or_clicking():
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.fast_movement_lane import advance_fast_movement
    from wowbot.agent.models import Attempt, Mode, Prediction

    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.set_goal("Questelj", 9.9)
    seed = snapshot(9.9)
    assert agent.world.ingest(Observation.create(seed, 9.9))
    agent.pending = Attempt("fast-murloc", move().proposal, seed, "seed", 9.9, 30., (),
        Prediction("p", "fast-murloc", "location", 9.9, 30., "seed"))
    agent.set_mode(Mode.FULL_AI)
    try:
        result = advance_fast_movement(agent, snapshot(mouse=MOUSE, transport_kind="FAST"),
                                       10., {"MOVE"})
        assert result["force_medium"] and result["reason"] == "objective_unit_under_cursor"
        assert agent.pending.action_id == "fast-murloc"
        assert not executor.commands
        assert agent.world.state.get("mouseover") is None
        agent.tick(snapshot(mouse=MOUSE, transport_kind="FAST"), 10.)
        assert agent.pending.proposal.skill == "TARGET"
        assert agent.pending.proposal.parameters["guid"] == GUID
    finally:
        agent.set_mode(Mode.STOPPED)


def test_parallel_view_uses_original_full_clock_and_does_not_refresh_omitted_hover():
    from wowbot.agent.parallel_view import control_view

    base = ingest(snapshot(mouse=MOUSE)).state
    delayed = snapshot(11., mouse=MOUSE, state_sample_time=8.)
    view = control_view(base, delayed, None, 11.)
    assert view["mouseover_sample_time"] == view["cursor_sample_time"] == 8.
    assert not waiting_seek(view, 11.).observe(view, "delayed-parallel", 11.).terminal
    omitted = {"transport_kind": "FAST", "monotonic_time": 11.}
    view = control_view(base, omitted, None, 11.)
    assert view["mouseover_sample_time"] == 10.
    assert view["cursor_sample_time"] == 10.
