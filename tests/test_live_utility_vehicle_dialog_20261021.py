"""Regressions from the user-operated 16:37-16:40 utility vehicle run.

Portable synthetic fixtures; no client input or user's database is opened.
The separate audit replays the actual recorded states through pure policies.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Attempt, Goal, Mode, Observation, Outcome, Prediction, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.agent.vehicle_abilities import stationary_objective_actions, stationary_vehicle_controls
from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
from wowbot.agent.recovery_planning import RecoveryPlanner
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.fast_movement_lane import advance_fast_movement
from wowbot.skills.interact import InteractSkill
from wowbot.runtime import SkillStatus

from test_agent_core import agent, state
from test_m0_combat_loot_skills import active
from test_talk_ride_credits_20261021 import DISC, SENDRAX, unit, state as npc_state, dialog


def console(t=100.):
    return state(t, in_vehicle=True, vehicle_controls=True, state_age=.1, is_mounted=False,
        player_world_position={"x": 10., "y": 20., "z": 30., "instance_id": 2175,
                               "coordinate_space": "WORLD_YARDS"},
        active_quests=[{"quest_id": 42, "is_complete": False, "objectives": [
            {"description": "1/1 Ride the console", "is_complete": True, "current": 1, "required": 1},
            *[{"description": "0/1 Search for "+name, "current": 0, "required": 1, "is_complete": False}
              for name in ("Power", "Allies", "Danger")]]}],
        actionbar=[{"action": f"ACTIONBUTTON{i}", "id": 100+i, "name": "Search for "+name,
                    "source": "VEHICLE_BAR", "kind": "spell", "is_usable": True,
                    "cooldown_remaining": 0., "max_range": 0., "is_harmful": False}
                   for i, name in enumerate(("Power", "Allies", "Danger"), 1)])


def world_for(payload, at=None):
    if payload.get("vehicle_controls"):
        # Raw addon snapshots carry vehicle_bar; actionbar is its canonical
        # WorldModel projection. Supply both sides in portable fixtures.
        payload = deepcopy(payload)
        payload["vehicle_bar"] = {"kind": "OVERRIDE", "actions": payload.get("actionbar") or []}
    world = WorldModel()
    at = at if at is not None else payload["monotonic_time"]
    world.ingest(Observation.create(payload, at))
    return world


def test_vehicle_objectives_use_their_exact_live_buttons_without_ground_route():
    live = console()
    seen = set()
    for _ in range(3):
        world = world_for(live)
        proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, live["monotonic_time"])
        assert proposals and all(p.skill == "VEHICLE_ABILITY" for p in proposals)
        chosen = proposals[0]
        index = int(chosen.parameters["binding"].removeprefix("ACTIONBUTTON"))
        assert index not in seen
        seen.add(index)
        assert chosen.parameters["objective_id"] == f"42:{index}"
        assert chosen.parameters["require_objective_progress"]
        assert not chosen.parameters["target_required"]
        assert SkillRegistry().available(chosen, world)
        assert SkillRegistry().commands(chosen, world)[0].binding == f"ACTIONBUTTON{index}"
        live["active_quests"][0]["objectives"][index].update(current=1, is_complete=True)
        live["monotonic_time"] += 1.
    assert seen == {1, 2, 3}


@pytest.mark.parametrize("change", ["no_bar", "unrelated", "duplicate_name", "cooldown", "unusable", "no_id"])
def test_utility_vehicle_waits_rather_than_guessing_a_button_or_moving(change):
    live = console()
    if change == "no_bar":
        live["actionbar"] = []
    elif change == "unrelated":
        for action in live["actionbar"]: action["name"] = "Unrelated button"
    elif change == "duplicate_name":
        live["actionbar"] *= 2
    else:
        for action in live["actionbar"]:
            if change == "cooldown": action["cooldown_remaining"] = 3.
            elif change == "unusable": action["is_usable"] = False
            elif change == "no_id": action.pop("id")
    world = world_for(live)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 100.)
    assert [p.skill for p in proposals] == ["WAIT"]


@pytest.mark.parametrize("change", ["stale", "spell_replaced", "binding_missing", "cooldown"])
def test_vehicle_dispatch_rechecks_current_bar_and_configured_binding(change):
    live = console()
    proposal = stationary_objective_actions(live)[0]
    bindings = SimpleNamespace(contains=lambda binding: change != "binding_missing")
    world = world_for(live)
    if change == "stale": world.state["state_age"] = 10.
    elif change == "spell_replaced": world.state["actionbar"][0]["id"] = 9999
    elif change == "cooldown": world.state["actionbar"][0]["cooldown_remaining"] = 2.
    assert not SkillRegistry(bindings).available(proposal, world)


def test_vehicle_cast_alone_never_verifies_the_named_objective():
    before = console()
    proposal = stationary_objective_actions(before)[0]
    attempt = Attempt("v", proposal, deepcopy(before), "old", 100., 106., (),
                      Prediction("p", "v", "credit", 100., 106., "old"))
    after = console(102.)
    after["events"] = [{"event_type": "SPELLCAST_SUCCEEDED", "sequence": 1, "payload": {"spell_id": 101}}]
    world = world_for(after)
    registry = SkillRegistry()
    assert registry.verify(attempt, world, 102.) == (Outcome.PENDING, "awaiting_vehicle_objective_credit")
    # Credit for a different button of the same quest is not this objective.
    world.state["active_quests"][0]["objectives"][2].update(current=1, is_complete=True)
    assert registry.verify(attempt, world, 103.)[0] is Outcome.PENDING
    world.state["active_quests"][0]["objectives"][1].update(current=1, is_complete=True)
    assert registry.verify(attempt, world, 104.)[0] is Outcome.SUCCESS


def test_old_stuck_recovery_cannot_override_stationary_vehicle_action():
    live = console()
    proposal = stationary_objective_actions(live)[0]
    world = world_for(live)
    decision = RecoveryPlanner().apply(proposal, world=world, goal=Goal.parse("Questelj", 1.),
        last_result={"skill": "MOVE", "outcome": "FAILURE", "reason": "supported_stuck"},
        navigation=SimpleNamespace(), registry=None, autonomy=None, failures={}, now=100.)
    assert decision.proposal is proposal
    assert not SkillRegistry().available(Proposal.make("RECOVER", "old recovery", {}), world)
    move = Proposal.make("MOVE", "old vendor trip", {"x": 500., "y": 0.})
    assert not SkillRegistry().available(move, world)
    assert movement_visual_interrupt(SimpleNamespace(proposal=move), live)["kind"] == "VEHICLE_QUEST_CONTROLS"


def test_fast_boarding_edge_yields_before_the_vehicle_bar_arrives():
    live = console()
    previous = {**live, "in_vehicle": False, "vehicle_controls": False, "actionbar": []}
    stops = []
    bot = SimpleNamespace(mode=Mode.FULL_AI, pending=SimpleNamespace(proposal=Proposal.make("MOVE", "old", {})),
        world=SimpleNamespace(state=previous, session_id=previous["session_id"]),
        command_dispatcher=SimpleNamespace(stop_movement=lambda: stops.append(True)))
    result = advance_fast_movement(bot, {"session_id": previous["session_id"], "in_vehicle": True}, 101., {"MOVE"})
    assert result["force_medium"] and not result["consumed"] and stops == [True]
    assert result["reason"] == "fast_vehicle_transition"


def test_a_known_dash_vehicle_keeps_its_existing_drivable_path():
    live = console()
    live["actionbar"] = [{"action": "ACTIONBUTTON1", "id": 900, "name": "Trample",
                          "source": "VEHICLE_BAR", "description": "Charge forward", "max_range": 0.}]
    assert not stationary_vehicle_controls(live)


def test_unselected_server_interact_proposals_do_not_consume_press_budget():
    from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
    live = npc_state(unit(DISC, 2., 0., 0),
        soft_targets=[{"source_unit": "softinteract", "guid": DISC}], soft_targets_sample_time=100.)
    policy = ServerNpcInteractionPolicy()
    first, = policy.propose(live)
    assert first.parameters["interaction_kind"] == "RIDE"
    again, = policy.propose(live)
    assert again == first and policy.pressed_at == {}
    planner = Planner(SkillRegistry())
    planner.quest.server_npcs = policy
    ExecutionBookkeeper().record(first, 100., planner=planner, approach_counts={})
    assert policy.pressed_at == {DISC: 100.}
    assert policy.propose(live) == []


def test_ride_interaction_waits_for_delayed_boarding_without_another_press():
    before = npc_state(unit(DISC, 2., 0., 0),
        soft_targets=[{"source_unit": "softinteract", "guid": DISC}], soft_targets_sample_time=100.)
    params = {"activation_source": "SOFT_INTERACT", "soft_guid": DISC, "interaction_kind": "RIDE"}
    from test_quest_dialog_fresh_evidence import _active
    running = _active(Proposal.make("INTERACT", "ride", params), before, now=100.)
    skill = InteractSkill()
    assert skill.begin(running, before).commands
    later = deepcopy(before)
    later["monotonic_time"] = 102.
    waiting = skill.verify(running, later, 102.)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    later["in_vehicle"] = True
    assert skill.verify(running, later, 104.).status is SkillStatus.SUCCESS


def test_gossip_progress_has_a_bounded_script_wait_not_the_generic_ten_seconds():
    bot, _ = agent()
    bot.world.ingest(Observation.create(state(100.), 100.))
    params = {"action": "GOSSIP_OPTION_SELECT", "gossip_transition": "QUEST_PROGRESS"}
    proposal = Proposal.make("QUEST_DIALOG", "spoken quest", params)
    attempt = bot.skill_executor.create_attempt(proposal, (), world=bot.world, goal=bot.goal,
        current_plan=SimpleNamespace(plan_id="plan"), timeouts=bot.timeouts, memory=None, now=100.)
    assert attempt.deadline == 145.


@pytest.mark.parametrize("skill,params,seconds", [
    ("DISMOUNT", {}, 5.), ("INTERACT", {"interaction_kind": "RIDE"}, 6.),
    ("VEHICLE_ABILITY", {"require_objective_progress": True}, 6.)])
def test_learned_short_timings_cannot_remove_the_response_assembly_window(skill, params, seconds):
    bot, _ = agent()
    bot.world.ingest(Observation.create(state(100.), 100.))
    memory = SimpleNamespace(learning_context=lambda *a: {}, verification_window=lambda *a: {
        "earliest": .01, "likely_start": .02, "likely_end": .1, "deadline": .2})
    attempt = bot.skill_executor.create_attempt(Proposal.make(skill, "test", params), (),
        world=bot.world, goal=bot.goal, current_plan=SimpleNamespace(plan_id="p"),
        timeouts=bot.timeouts, memory=memory, now=100.)
    assert attempt.deadline == 100.+seconds


def test_spoken_quest_waits_without_input_across_npc_replacement_until_actual_credit():
    from wowbot.runtime import ActiveSkillRuntime, Intent
    from wowbot.skills.quest_dialog import QuestDialogSkill
    from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
    before = dialog()
    before["active_quests"][0]["objectives"][0]["current"] = 0
    proposal = QuestDialogPlanningPolicy._talk_gossip(before, True)
    bot, _ = agent()
    bot.world.ingest(Observation.create(before, 100.))
    attempt = bot.skill_executor.create_attempt(proposal, (), world=bot.world, goal=bot.goal,
        current_plan=SimpleNamespace(plan_id="p"), timeouts=bot.timeouts, memory=None, now=100.)
    running = ActiveSkillRuntime().start(intent=Intent("QUEST_DIALOG", proposal.parameters),
        attempt=attempt, now=100., before_snapshot=before)
    skill = QuestDialogSkill()
    assert skill.begin(running, before).commands
    during = deepcopy(before)
    during.update(monotonic_time=112., target=None, quest_ui={"open": False})
    waiting = skill.verify(running, during, 112.)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    credited = deepcopy(during)
    credited["active_quests"][0]["objectives"][0].update(current=1, is_complete=True)
    assert skill.verify(running, credited, 126.).status is SkillStatus.SUCCESS
    assert skill.verify(running, during, 146.).status is SkillStatus.FAILURE


def empty_window(t):
    return state(t, quest_ui={"open": True, "action": "CONTINUE", "quest_id": 0, "x": 0, "y": 0},
        quest_ui_open=True, state_sample_time=t, state_age=.1,
        soft_targets=[{"source_unit": "softinteract", "guid": SENDRAX}], soft_targets_sample_time=t)


def test_empty_window_timer_resets_and_soft_recipient_is_remembered_without_a_target():
    world = world_for(empty_window(10.))
    planner = Planner(SkillRegistry())
    assert planner._close_empty_dialog(world, empty_window(10.)) is None
    assert planner._close_empty_dialog(world, empty_window(17.)).skill == "CLOSE_DIALOG"
    assert world.__dict__["empty_dialog_closes"][SENDRAX] == [17.]
    assert planner._close_empty_dialog(world, empty_window(18.)) is None
    assert planner._close_empty_dialog(world, empty_window(19.)) is None
    assert planner._close_empty_dialog(world, empty_window(25.)).skill == "CLOSE_DIALOG"


def test_multiple_gossip_rows_are_not_an_empty_window():
    live = dialog()
    live["state_sample_time"] = 100.
    planner = Planner(SkillRegistry())
    planner._empty_dialog_since = 1.
    assert planner._close_empty_dialog(world_for(live), live) is None


def test_empty_dialog_suppression_applies_to_server_turnin_and_objective_routes():
    world = world_for(empty_window(100.))
    world.__dict__["empty_dialog_closes"] = {SENDRAX: [90., 95.]}
    bad = [Proposal.make("INTERACT", "ender", {"soft_guid": SENDRAX}),
           Proposal.make("MOVE", "objective", {"server_entity_guid": SENDRAX})]
    other = Proposal.make("MOVE", "other NPC", {"server_entity_guid": DISC})
    assert Planner._without_empty_dialog_reopens([*bad, other], world, 100.) == [other]
    assert Planner._without_empty_dialog_reopens(bad, world, 220.) == bad


def test_known_server_turnin_has_no_parallel_static_poi_move():
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    from test_exiles_reach_live_fixes_20261020 import ENDER, ender_scene
    live = ender_scene(50.)
    live["quest_locations"] = [{"quest_id": 42, "x": .4, "y": .4, "source": "QUEST_API_WAYPOINT",
        "world_position": {"x": 500., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}]
    world = world_for(live)
    world.state.update(deepcopy(live))
    policy = QuestLocationPlanningPolicy()
    canonical = policy.propose_turnins(world.quest_model.records, world.state, {})
    fallback = policy.propose_known_locations(world)
    assert len(canonical) == 1 and canonical[0].parameters["server_entity_guid"] == ENDER
    assert not any(str(p.parameters.get("quest_id")) == "42" for p in fallback)


def test_a_window_whose_rows_the_agent_takes_nothing_from_is_closed_after_4_s():
    """User 2026-10-26: gossip rows / quest rows that are none of ours, not a
    vendor we need -> Goodbye (Escape) instead of waiting in front of it."""
    planner = Planner(SkillRegistry())
    live = dialog()
    live.update(monotonic_time=100., state_sample_time=100.)
    world = world_for(live)
    assert planner._close_unhelpful_dialog(world, live) is None              # starts the timer
    later = {**live, "monotonic_time": 103., "state_sample_time": 103.}
    assert planner._close_unhelpful_dialog(world, later) is None              # 3 s: not yet
    late = {**live, "monotonic_time": 104.5, "state_sample_time": 104.5}
    assert planner._close_unhelpful_dialog(world, late).skill == "CLOSE_DIALOG"
    vendor = {**late, "vendor_ui": {"open": True}}
    assert Planner(SkillRegistry())._close_unhelpful_dialog(world, vendor) is None
