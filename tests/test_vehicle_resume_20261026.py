"""Completed boarding credit survives logout, actual vehicle possession does not."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.autonomy_loop import AutonomousLoop, CommittedSubgoal
from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.fast_movement_lane import advance_fast_movement
from wowbot.agent.models import Goal, Mode, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_creature_memory import QuestCreatureMemory
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.vehicle_prerequisites import learned_requirements, resume_proposals
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.interact import InteractSkill
from wowbot.verification.interaction import InteractionVerifier


BOARDER = "Creature-0-3769-2444-47-193979-00001234"
OTHER = "Vehicle-0-3769-2444-47-186771-00005678"


def scene():
    objectives = [
        dict(description="1/1 Ruby Whelpling chosen", current=1, required=1, is_complete=True),
        dict(description="12/12 Agitated Weedling slain", current=12, required=12, is_complete=True),
        dict(description="2/6 Intrusive Pupstinger slain", current=2, required=6, is_complete=False),
        dict(description="0/1 Relentless Gust slain", current=0, required=1, is_complete=False),
    ]
    for obj in objectives:
        obj.update(type="KILL", raw_type="monster")
    return dict(
        session_id="relogin", monotonic_time=100., player_present=True, in_vehicle=False,
        on_taxi=False, is_in_combat=False, map_id=2022, orientation=0.,
        server_mode=dict(selected=True, active=True),
        player_world_position=dict(x=1550., y=-219., z=312., instance_id=2444,
                                   coordinate_space="WORLD_YARDS", z_known=True, z_observed=True),
        active_quests=[dict(quest_id=70061, title="Training Wings", is_complete=False, objectives=objectives)],
        packet_entities={}, soft_targets=[], target=None,
        reference_knowledge=dict(quests={"70061": dict(
            objectives=[dict(objective_id=429779, order=0, description="Ruby Whelpling chosen",
                             credit_action="SPELLCLICK", credit_name="Ruby Whelpling",
                             spellclick_creatures=[dict(entry=193979)],
                             named_creatures=[dict(entry=186771), dict(entry=190912)])],
            pois=[dict(poi_id="70061:0:1", objective_id=429779, objective_index=0,
                       world_map_id=2444, ui_map_id=2022, verified_build=66384,
                       points=[dict(x=1571., y=-219., z=312.)])],
            spawn_candidates=[dict(entry=186771, entity_kind="CREATURE", objective_id=429779,
                                   location_kind="OBSERVER_POSITION", x=1550., y=-219., z=312.,
                                   world_map_id=2444)],
        )}))


def remember(memory, state, indices=(0, 1, 2, 3), riding=True):
    for index in indices:
        obj = state["active_quests"][0]["objectives"][index]
        memory.record_progress(70061, index, description=obj["description"], in_vehicle=riding,
                               skill="INTERACT" if index == 0 else "VEHICLE_ABILITY", at=10.)


@pytest.fixture
def prepared():
    state = scene()
    memory = QuestCreatureMemory()
    remember(memory, state)
    state["vehicle_requirements"] = learned_requirements(state, memory)
    yield state, memory
    memory.close()


def world_for(state, memory):
    world = WorldModel()
    world.quest_creature_memory = memory
    world.ingest(Observation.create(state, state["monotonic_time"]))
    world.state.update(deepcopy(state))
    return world


def unit(guid=BOARDER, entry=193979, x=1571., z=312.):
    return dict(guid=guid, kind="CREATURE", entry_id=entry, name="Ruby Whelpling", map_id=2444,
                info=dict(npc_flags=0, health=100),
                position=dict(x=x, y=-219., z=z, instance_id=2444))


def test_resume_survives_memory_reopen_without_reopening_completed_quest_credit(tmp_path):
    state = scene()
    path = tmp_path / "creature.sqlite3"
    memory = QuestCreatureMemory(path)
    remember(memory, state)
    memory.close()
    restored = QuestCreatureMemory(path)
    try:
        # A genuinely new model, not an old in-memory remount flag.
        world = WorldModel()
        world.quest_creature_memory = restored
        world.ingest(Observation.create(state, 100.))
        requirements = world.state["vehicle_requirements"]
        assert requirements[0]["npc_ids"] == ["193979"]
        assert requirements[0]["remaining_objectives"] == ["70061:2", "70061:3"]
        assert world.state["active_quests"][0]["objectives"][0]["is_complete"]
        assert world.quest_model.records[70061].objectives[0].completion_state == "COMPLETE"
    finally:
        restored.close()


def test_full_planner_returns_to_boarding_point_and_releases_old_kill_commitment(prepared):
    state, memory = prepared
    world = world_for(state, memory)
    goal, planner = Goal.parse("Questelj", 100.), Planner(SkillRegistry())
    proposals = planner.candidates(goal, world, 100.)
    move = proposals[0]
    assert (move.skill, move.parameters.get("purpose")) == ("MOVE", "RETURN_TO_QUEST_VEHICLE")
    assert (move.parameters["x"], move.parameters["y"], move.parameters["z"]) == (1571., -219., 312.)
    assert move.parameters["require_navmesh"] and move.parameters["z_known"]
    loop = AutonomousLoop()
    loop.commitment = CommittedSubgoal("old", goal.goal_id, world.session_id, "TARGET", OTHER,
        None, ("70061:2",), world.quest_signature(world.state), 99., 99.)
    assert loop.choose(proposals, move, goal, world, 100.) == move
    assert loop.commitment is None


def test_live_exact_boarding_actor_overrides_tdb_and_other_same_named_vehicle(prepared):
    state, memory = prepared
    state["packet_entities"] = {OTHER: unit(OTHER, 186771, x=1551.), BOARDER: unit(x=1562.)}
    policy = ServerNpcInteractionPolicy()
    move, = resume_proposals(state, policy)
    assert move.skill == "MOVE"
    assert move.parameters["x"] == 1562.
    assert move.parameters["server_entity_guid"] == BOARDER
    assert move.parameters["npc_id"] == 193979


def test_fresh_exact_recipient_boards_once_and_requires_actual_vehicle_entry(prepared):
    state, memory = prepared
    state["packet_entities"] = {BOARDER: unit(x=1552.)}
    state.update(soft_targets=[dict(guid=BOARDER, npc_id=193979, source_unit="softinteract")],
                 soft_targets_sample_time=100.)
    policy = ServerNpcInteractionPolicy()
    interact, = resume_proposals(state, policy)
    assert interact.skill == "INTERACT" and interact.parameters["interaction_kind"] == "RIDE"
    assert interact.parameters["expected_result"] == "VEHICLE_ENTERED"
    assert resume_proposals(state, policy)[0] == interact  # planning cannot consume press budget
    planner = Planner(SkillRegistry())
    planner.quest.server_npcs = policy
    ExecutionBookkeeper().record(interact, 100., planner=planner, approach_counts={})
    assert resume_proposals(state, policy)[0].skill == "WAIT"

    from test_quest_dialog_fresh_evidence import _active
    running = _active(interact, state, now=100.)
    skill = InteractSkill()
    assert skill.begin(running, state).commands
    later = deepcopy(state)
    later["monotonic_time"] = 102.
    assert skill.verify(running, later, 102.).status is SkillStatus.RUNNING
    later.update(in_vehicle=True, vehicle_controls=True)
    assert skill.verify(running, later, 104.).status is SkillStatus.SUCCESS
    assert resume_proposals(later, policy) is None
    assert later["active_quests"] == state["active_quests"]


@pytest.mark.parametrize("soft", [
    dict(guid=OTHER, source_unit="softinteract"),
    dict(guid=BOARDER, source_unit="softinteract", is_attackable=True),
    dict(guid=BOARDER, source_unit="softinteract", is_dead=True),
])
def test_wrong_or_unsafe_soft_recipient_never_presses(prepared, soft):
    state, _ = prepared
    state["packet_entities"] = {BOARDER: unit(x=1552.)}
    state.update(soft_targets=[soft], soft_targets_sample_time=100.)
    assert resume_proposals(state, ServerNpcInteractionPolicy())[0].skill == "WAIT"


def test_stale_recipient_never_presses(prepared):
    state, _ = prepared
    state["packet_entities"] = {BOARDER: unit(x=1552.)}
    state.update(soft_targets=[dict(guid=BOARDER, source_unit="softinteract")],
                 soft_targets_sample_time=90.)
    assert resume_proposals(state, ServerNpcInteractionPolicy())[0].skill == "WAIT"


@pytest.mark.parametrize("kind", ["quest", "vendor", "credit"])
def test_window_or_other_progress_does_not_prove_remount(prepared, kind):
    state, _ = prepared
    after = deepcopy(state)
    if kind == "quest":
        after["quest_ui"] = dict(open=True)
    elif kind == "vendor":
        after["vendor_ui"] = dict(open=True)
    else:
        after["active_quests"][0]["objectives"][2]["current"] = 3
    assert not InteractionVerifier().evaluate(
        state, after, expected_guid=BOARDER, expected_result="VEHICLE_ENTERED").success


def test_completed_stage_does_not_reboard_for_later_on_foot_boss(prepared):
    state, memory = prepared
    objectives = state["active_quests"][0]["objectives"]
    for obj in objectives:
        obj["is_complete"] = True
    objectives.append(dict(description="0/1 Torgok slain", is_complete=False, type="KILL"))
    assert learned_requirements(state, memory) == []


def test_spellclick_heal_or_unproven_boarding_is_not_a_vehicle_requirement(prepared):
    state, _ = prepared
    memory = QuestCreatureMemory()
    try:
        remember(memory, state, riding=False)
        assert learned_requirements(state, memory) == []
    finally:
        memory.close()


def test_live_on_foot_success_disproves_requirement(prepared):
    state, memory = prepared
    remember(memory, state, indices=(2, 3), riding=False)
    assert learned_requirements(state, memory) == []


def test_completed_quest_and_abandoned_quest_do_not_reboard(prepared):
    state, memory = prepared
    state["active_quests"][0]["is_complete"] = True
    assert learned_requirements(state, memory) == []
    state["active_quests"] = []
    assert learned_requirements(state, memory) == []


@pytest.mark.parametrize("change", [dict(in_vehicle=True), dict(in_vehicle=None),
                                    dict(on_taxi=True), dict(is_in_combat=True)])
def test_runtime_state_gates_reboarding(prepared, change):
    state, _ = prepared
    state.update(change)
    assert resume_proposals(state, ServerNpcInteractionPolicy()) is None


def test_wrong_map_or_missing_boarding_location_waits_without_kill_area_fallback(prepared):
    state, _ = prepared
    state["reference_knowledge"]["quests"]["70061"]["pois"][0]["world_map_id"] = 2175
    proposal, = resume_proposals(state, ServerNpcInteractionPolicy())
    assert proposal.skill == "WAIT" and proposal.parameters["purpose"] == "QUEST_VEHICLE_REQUIRED"


def test_completing_one_vehicle_objective_does_not_trigger_timed_exit(prepared):
    state, memory = prepared
    state.update(in_vehicle=True, vehicle_controls=True)
    world = world_for(state, memory)
    world.quest_stage_completed_at = {"70061": 20.}
    world.quest_stage_completed_in_vehicle = {"70061": True}
    world.last_received = 100.
    assert Planner(SkillRegistry())._vehicle_stage_exit_reason(world, 100.) is None


def test_boarding_prerequisite_interrupts_old_route_then_live_actor_takes_over(prepared):
    state, _ = prepared
    old = SimpleNamespace(proposal=Proposal.make("MOVE", "old objective trip",
        {"quest_id": "70061", "purpose": "LOCATE_QUEST_OBJECTIVE_REGION"}))
    assert movement_visual_interrupt(old, state, identity_only=True)["reason"] == "quest_vehicle_missing"
    route, = resume_proposals(state, ServerNpcInteractionPolicy())
    running = SimpleNamespace(proposal=route)
    assert movement_visual_interrupt(running, state, identity_only=True) is None
    state["packet_entities"] = {OTHER: unit(OTHER, 186771, x=1551.)}
    assert movement_visual_interrupt(running, state, identity_only=True) is None
    state["packet_entities"][BOARDER] = unit(x=1557.)
    assert movement_visual_interrupt(running, state, identity_only=True)["reason"] == "quest_vehicle_actor_available"
    approach, = resume_proposals(state, ServerNpcInteractionPolicy())
    running.proposal = approach
    assert movement_visual_interrupt(running, state, identity_only=True) is None
    state["player_world_position"]["x"] = 1555.
    state.update(soft_targets=[dict(guid=BOARDER, source_unit="softinteract")],
                 soft_targets_sample_time=100.)
    assert movement_visual_interrupt(running, state, identity_only=True)["reason"] == "quest_vehicle_interaction_ready"


def test_fast_vehicle_loss_releases_old_flight_route_before_navigation_runs(prepared):
    state, memory = prepared
    state["in_vehicle"] = True
    world = world_for(state, memory)
    stops = []
    bot = SimpleNamespace(mode=Mode.FULL_AI, world=world,
        pending=SimpleNamespace(proposal=Proposal.make("MOVE", "old vehicle aim", {"purpose": "VEHICLE_AIM"})),
        command_dispatcher=SimpleNamespace(stop_movement=lambda: stops.append(True)))
    outcome = advance_fast_movement(bot, {"session_id": world.session_id, "in_vehicle": False}, 101., {"MOVE"})
    assert outcome["force_medium"] and not outcome["consumed"] and stops == [True]
    assert outcome["reason"] == "fast_vehicle_transition"
