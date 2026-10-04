"""Engine replay: combat interrupts safely, then one valid intent resumes."""
from wowbot.agent.models import Attempt, Observation, Prediction, Proposal
from wowbot.agent.models import Outcome
from test_agent_core import agent, state


def _attempt():
    proposal = Proposal.make("INTERACT", "test interaction", {"guid": "npc-1"})
    return Attempt("old-action", proposal, {}, "old-observation", 1., 8., (),
                   Prediction("old-prediction", "old-action", "dialog", 1., 8., "old-observation"))


def _quest_navigation_attempt():
    proposal = Proposal.make("MOVE", "quest objective region", {
        "x": .8, "y": .5, "map_id": 1609,
        "quest_id": 42, "objective_id": "42:reach",
    })
    return Attempt("quest-move", proposal, {}, "old-observation", 1., 91., (),
                   Prediction("quest-move-prediction", "quest-move", "reach_destination",
                              1., 91., "old-observation"))


def test_combat_interrupt_closes_old_skill_then_resumes_same_interaction_once_safe():
    value, executor = agent()
    value.pending = _attempt()

    # The safety interrupt terminates the active attempt and stores intent
    # data only. It cannot leave an input-owning active state behind.
    interrupt = state(1., target={"guid": "npc-1", "attackable": False}, is_in_combat=True)
    # Hold only the new planner dispatch for this exact interrupt observation;
    # it lets this replay inspect the cancellation boundary before a separate
    # survival-combat proposal can begin.
    value.executed_observation = Observation.create(interrupt, 1.).observation_id
    value.tick(interrupt, 1.)
    assert value.pending is None
    assert value.supervisor.snapshot()["suspended"]["skill"] == "INTERACT"

    # When the combat interrupt is over and the exact target remains valid,
    # the preserved intent wins over a newly generated observation.
    value.tick(state(2., target={"guid": "npc-1", "attackable": False}, is_in_combat=False), 2.)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert executor.commands[-1].binding == "INTERACTTARGET"
    assert value.supervisor.snapshot()["suspended"] is None


def test_manual_mode_discards_suspended_intent_before_it_can_resume():
    value, executor = agent()
    value.pending = _attempt()
    value.tick(state(1., target={"guid": "npc-1", "attackable": False}, is_in_combat=True), 1.)
    value.set_mode("MANUAL")
    assert value.supervisor.snapshot()["suspended"] is None


def test_combat_preemption_resumes_the_same_quest_navigation_subgoal():
    """M6.4: combat cannot erase a live quest-navigation intent."""
    value, executor = agent()
    value.pending = _quest_navigation_attempt()

    interrupt = state(1., target={"guid": "attacker-1", "attackable": True},
                      is_in_combat=True)
    value.executed_observation = Observation.create(interrupt, 1.).observation_id
    value.tick(interrupt, 1.)
    assert executor.stops >= 1
    movement = value.navigation.snapshot(1.)["movement"]
    assert movement["phase"] == "IDLE" and movement["destination"] is None
    suspended = value.supervisor.snapshot()["suspended"]
    assert value.pending is None
    assert suspended and suspended["skill"] == "MOVE"

    resumed = value.tick(state(2., is_in_combat=False), 2.)
    assert value.pending and value.pending.proposal.skill == "MOVE"
    assert value.pending.proposal.parameters["quest_id"] == 42
    assert value.pending.proposal.parameters["objective_id"] == "42:reach"
    assert resumed["supervisor"]["suspended"] is None


def test_long_combat_preserves_the_same_quest_navigation_subgoal_until_clear():
    value, _ = agent()
    value.pending = _quest_navigation_attempt()
    interrupt = state(1., target={"guid": "attacker-1", "attackable": True},
                      is_in_combat=True)
    value.executed_observation = Observation.create(interrupt, 1.).observation_id
    value.tick(interrupt, 1.)

    # A normal fight may outlive the old 20-second generic resume window.
    assert value.supervisor.resume_candidate(
        state(45., is_in_combat=True), 45.) is None
    assert value.supervisor.snapshot()["suspended"]["skill"] == "MOVE"

    resumed = value.tick(state(46., is_in_combat=False), 46.)
    assert value.pending and value.pending.proposal.skill == "MOVE"
    assert value.pending.proposal.parameters["quest_id"] == 42
    assert resumed["supervisor"]["suspended"] is None


def test_death_safely_pauses_without_erasing_the_high_level_goal():
    """M6.5: no blind revive input; the user can later re-arm/revalidate."""
    value, executor = agent()
    goal_id = value.goal.goal_id
    value.pending = _quest_navigation_attempt()

    stopped = value.tick(state(1., is_dead=True, is_ghost=True), 1.)

    assert value.mode.value == "MANUAL"
    assert value.goal and value.goal.goal_id == goal_id
    assert value.pending is None
    assert executor.stops >= 1
    recovery = stopped["supervisor"]["recovery"]
    assert recovery["reason"] == "PLAYER_DEAD"
    assert recovery["required_condition"] == "PLAYER_ALIVE_AND_LOADING_STABLE"
    assert stopped["decision"]["recovery_required"] == "PLAYER_ALIVE_AND_LOADING_STABLE"

    # Only a new, alive observation after the user explicitly re-arms FULL_AI
    # clears the checkpoint; the normal planner then revalidates the goal.
    value.set_mode("FULL_AI")
    recovered = value.tick(state(2., is_dead=False, is_ghost=False), 2.)
    assert recovered["supervisor"]["recovery"] is None
    assert recovered["supervisor"]["last_resume_reason"] == "recovery_stabilized_replan_required"


def test_repeated_same_action_failure_is_engine_blocked_by_loop_guard():
    """M6.13 oscillation: repeated failure cannot retry forever."""
    value, _ = agent()
    proposal = Proposal.make("INTERACT", "same NPC", {"guid": "npc-1"})
    for index in range(5):
        attempt = Attempt(f"repeat-{index}", proposal, {}, f"obs-{index}", float(index),
                          float(index + 8), (),
                          Prediction(f"prediction-{index}", f"repeat-{index}", "dialog",
                                     float(index), float(index + 8), f"obs-{index}"))
        value.pending = attempt
        value._finish(Outcome.FAILURE, "target_lost", float(index + 1))
    assert value.last_result["loop_guard"]["level"] == "CONFIRMED"
    assert value.planner.blocked_until[proposal.key] > 5.


def test_combat_success_without_quest_credit_is_not_quest_success():
    """M6.13: a kill result and an objective credit are separate facts."""
    value, _ = agent()
    proposal = Proposal.make("COMBAT", "uncredited target", {
        "guid": "mob-1", "quest_id": 42, "objective_id": "42:kill",
    })
    attempt = Attempt("combat-uncredited", proposal,
                      {"active_quests": [{"quest_id": 42, "objectives": [{"current": 0, "required": 1}]}]},
                      "obs-before", 1., 9., (),
                      Prediction("prediction-combat", "combat-uncredited", "target_dead", 1., 9., "obs-before"))
    value.pending = attempt
    value.world.state = {"active_quests": [{"quest_id": 42, "objectives": [{"current": 0, "required": 1}]}]}
    value._finish(Outcome.SUCCESS, "target_dead", 2.)
    assert value.last_result["quest_credit"]["confirmed"] is False
    assert value.goal.completed_steps == 1  # action only, never quest completion
    assert value.goal.status != "COMPLETED"
