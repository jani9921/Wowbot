from wowbot.agent.goal_manager import GoalManager, classify_failure, classify_prediction_error
from wowbot.agent.memory import AgentMemory
from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation, Plan, Prediction, Proposal, VerificationRecord
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import FailureEscalationStage, FailureManager, FailureReason


def state(**overrides):
    value = {"session_id": "s", "frame_id": "f", "timestamp": 1,
             "map_id": 1609, "position": {"x": .1, "y": .1}, "orientation": 0,
             "player_present": True, "is_in_combat": False, "is_casting": False,
             "target": None, "actionbar": [], "active_quests": []}
    value.update(overrides)
    return value


def world(**overrides):
    value = WorldModel()
    value.ingest(Observation.create(state(**overrides), 1))
    return value


def test_goal_manager_persists_priority_and_bounds_repeated_failure(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    manager = GoalManager(memory)
    goal = Goal.parse("Questelj egész nap", 1)
    manager.set_goal(goal, 1)
    proposal = Proposal.make("MOVE", "objective", {"objective_id": "q:1", "map_id": 1609,
                                                     "x": .4, "y": .5}, confidence=.7, priority=60)
    contracts = SkillRegistry().contracts
    assert manager.filter([proposal], contracts, 1)
    for at in (2, 3, 4):
        manager.outcome(proposal, False, "expected_observation_missing", at)
    assert manager.filter([proposal], contracts, 5) == []
    snapshot = manager.snapshot(5)
    assert snapshot["persistent"] and snapshot["unresolved"] == 1
    saved = memory.goal_tasks(goal.goal_id)
    assert saved[0]["status"] == "UNRESOLVED" and saved[0]["failures"] == 3
    restored = memory.latest_active_goal()
    assert restored.goal_id == goal.goal_id and restored.status == "RECOVERING"


def test_failure_classification_is_explicit():
    assert classify_failure("MOVE", "expected_observation_missing") == "PATH_BLOCKED"
    assert classify_failure("INSPECT", "expected_observation_missing") == "VISION_UNCERTAIN"
    assert classify_failure("COMBAT", "expected_observation_missing") == "COMBAT_FAILURE"


def test_dungeon_and_pvp_domains_require_explicit_normalized_location():
    registry = SkillRegistry()
    dungeon = Goal.parse("Complete this dungeon", 1)
    assert Planner(registry).candidates(dungeon, world(), 1)[0].skill == "WAIT"
    dungeon_world = world(instance_state={"inside": True, "encounter_id": 7,
        "objective_location": {"map_id": 1609, "x": .4, "y": .5}, "confidence": .85})
    proposal = Planner(registry).candidates(dungeon, dungeon_world, 1)[0]
    assert proposal.skill == "MOVE" and proposal.parameters["encounter_id"] == 7

    pvp = Goal.parse("Go do battlegrounds", 1)
    pvp_world = world(pvp_state={"match_active": True, "objective_id": "flag",
        "objective_location": {"map_id": 1609, "x": .6, "y": .7}, "confidence": .8})
    proposal = Planner(registry).candidates(pvp, pvp_world, 1)[0]
    assert proposal.skill == "MOVE" and proposal.parameters["pvp_objective_id"] == "flag"


def test_plan_exposes_its_own_confidence_and_uncertainty():
    goal = Goal.parse("Questelj", 1)
    proposal = Proposal.make("MOVE", "hypothesis", {"map_id": 1609, "x": .4, "y": .5}, confidence=.42)
    contract = SkillRegistry().contracts["MOVE"]
    plan = Plan.create(goal, proposal, [proposal], contract, 1, "obs")
    assert plan.confidence == .42 and plan.uncertainty == .58


def test_high_level_goal_and_tasks_restore_passively(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    goal = Goal.parse("Questelj egész nap", 1)
    memory.save_goal(goal)
    manager = GoalManager(memory)
    manager.set_goal(goal, 1)
    proposal = Proposal.make("MOVE", "objective", {"objective_id": "q:1", "map_id": 1609,
                                                     "x": .4, "y": .5}, priority=60)
    manager.filter([proposal], SkillRegistry().contracts, 1)
    restored = memory.latest_active_goal()
    other = GoalManager(memory)
    other.set_goal(restored, 2, resume=True)
    assert restored.goal_id == goal.goal_id
    assert other.snapshot(2)["high_level_goal_id"] == goal.goal_id
    assert len(other.snapshot(2)["tasks"]) == 1


def test_goal_lifecycle_tracks_recovery_completion_progress_and_priority():
    goal = Goal.parse("Menj oda", 1, {"priority": .9, "finite": True,
                                      "complete_when_tasks_complete": True})
    manager = GoalManager()
    manager.set_goal(goal, 1)
    proposal = Proposal.make("INSPECT", "unknown subject", {"objective_id": "inspect:1"},
                             confidence=.7, priority=80)
    manager.filter([proposal], SkillRegistry().contracts, 1)
    for at in (2, 3, 4):
        manager.outcome(proposal, False, "expected_observation_missing", at)
    assert goal.status == "RECOVERING" and goal.recovery_count == 1
    assert manager.filter([proposal], SkillRegistry().contracts, 125)
    assert goal.status == "ACTIVE"
    manager.outcome(proposal, True, "mouseover_confirmed", 126)
    manager.sync_world(SimpleNamespace(records={}), 126)
    manager.mark_task_completed("inspect:1", 127)
    assert goal.status == "COMPLETED" and goal.progress == 1 and goal.completed_at == 127
    snapshot = manager.snapshot(127)
    assert snapshot["goal_priority"] == .9
    assert [item["status"] for item in snapshot["lifecycle"]] == [
        "ACTIVE", "RECOVERING", "ACTIVE", "COMPLETED"]


def test_finite_goal_consumes_failure_escalation_without_infinite_retry():
    goal = Goal.parse("Questelj", 1, {
        "finite": True, "max_goal_recoveries": 99})
    manager = GoalManager()
    manager.set_goal(goal, 1)
    proposal = Proposal.make(
        "COMBAT", "objective", {"objective_id": "q:kill"}, priority=80)
    manager.filter([proposal], SkillRegistry().contracts, 1)
    failures = FailureManager()
    decisions = []
    for at in range(2, 8):
        decision = failures.record_failure(
            correlation_id=proposal.key, skill="COMBAT",
            reason=FailureReason.OUT_OF_RANGE, at=float(at))
        decisions.append(decision)
        manager.outcome(
            proposal, False, "out_of_range", float(at),
            failure_decision=decision)
    assert decisions[2].escalation_stage is FailureEscalationStage.DOMAIN_RECOVERY
    assert decisions[3].escalation_stage is FailureEscalationStage.PLANNER_REPLAN
    assert decisions[4].escalation_stage is FailureEscalationStage.GOAL_ALTERNATIVE
    assert decisions[5].escalation_stage is FailureEscalationStage.GOAL_FAILED
    assert goal.status == "FAILED"
    assert goal.failure_reason == "failure_budget_exhausted:REAPPROACH_TARGET"


def test_goal_completion_duration_requires_reaching_explicit_deadline():
    manager = GoalManager()
    manager.set_goal(Goal.parse("Explore", 10, {"duration": 30}), 10)

    assert not manager.completion_condition_verified(world(), 39.999)
    assert manager.completion_condition_verified(world(), 40)


def test_goal_completion_until_bags_full_requires_zero_free_slots():
    manager = GoalManager()
    manager.set_goal(Goal.parse("Farm until bags are full", 1,
                                {"until_bags_full": True}), 1)

    assert not manager.completion_condition_verified(
        world(inventory={"free_slots": 1}), 2)
    assert manager.completion_condition_verified(
        world(inventory={"free_slots": 0}), 2)


def test_move_goal_completion_uses_verified_same_map_distance():
    manager = GoalManager()
    manager.set_goal(Goal.parse("Menj oda", 1, {
        "destination": {"map_id": 1609, "x": .102, "y": .101},
    }), 1)

    assert manager.completion_condition_verified(world(), 2)
    manager.goal.parameters["destination"] = {
        "map_id": 1609, "x": .2, "y": .2,
    }
    assert not manager.completion_condition_verified(world(), 2)
    manager.goal.parameters["destination"] = {
        "map_id": 2175, "x": .1, "y": .1,
    }
    assert not manager.completion_condition_verified(world(), 2)


def test_quest_attempts_and_progress_do_not_imply_goal_completion():
    manager = GoalManager()
    goal = Goal.parse("Questelj", 1)
    goal.completed_steps = 999
    goal.progress = 1.0
    manager.set_goal(goal, 1)

    assert not manager.completion_condition_verified(world(), 999)


def test_goal_plan_action_observation_verification_are_distinct_linked_objects():
    current = world()
    goal = Goal.parse("Questelj", 1)
    proposal = Proposal.make("WAIT", "collect evidence")
    plan = Plan.create(goal, proposal, [proposal], SkillRegistry().contracts["WAIT"],
                       2, current.latest.observation_id)
    current.record_plan_graph(goal, plan, current.latest)
    prediction = Prediction("prediction-1", "action-1", "new observation", 2, 3,
                            current.latest.observation_id)
    attempt = SimpleNamespace(action_id="action-1", plan_id=plan.plan_id,
                              observation_id=current.latest.observation_id,
                              prediction=prediction)
    current.record_action_graph(attempt, current.latest)
    verification = VerificationRecord("verification-1", "action-1", "WAIT", plan.plan_id,
        "prediction-1", "new observation", "SUCCESS", "observed", 3,
        current.latest.observation_id, current.latest.observation_id,
        (current.latest.observation_id,))
    current.record_verification_graph(verification, current.latest)
    assert current.query.relation(subject=f"goal:{goal.goal_id}", predicate="has_subgoal")
    assert current.query.relation(subject=f"subgoal:{plan.subgoal_id}", predicate="planned_by",
                                  object=f"plan:{plan.plan_id}")
    assert current.query.relation(subject=f"plan:{plan.plan_id}", predicate="selected_action",
                                  object="action:action-1")
    assert current.query.relation(subject="action:action-1", predicate="verified_by",
                                  object="verification:verification-1")
    assert current.query.relation(subject="prediction:prediction-1", predicate="resolved_by",
                                  object="verification:verification-1")


def test_prediction_error_classification_distinguishes_observation_and_effect():
    assert classify_prediction_error("expected_observation_missing") == "UNOBSERVED"
    assert classify_prediction_error("target_identity_changed") == "WRONG_EFFECT"
    assert classify_prediction_error("You need to be closer") == "PARTIAL_EFFECT"
    assert classify_prediction_error("movement_safety_deadline") == "NO_EFFECT"


def test_reaching_a_unit_reopens_its_blocked_interaction_task(tmp_path):
    """Live 2026-09-30: far-away silent INTERACTs blocked Jaina's INTERACT for
    120 s; after VISUAL_APPROACH reached her every proposal was filtered."""
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    manager = GoalManager(memory)
    goal = Goal.parse("Questelj egész nap", 1)
    manager.set_goal(goal, 1)
    contracts = SkillRegistry().contracts
    interact = Proposal.make("INTERACT", "talk", {"guid": "Creature-jaina"}, priority=70)
    approach = Proposal.make("VISUAL_APPROACH", "approach",
                             {"guid": "Creature-jaina", "purpose": "INTERACT"}, priority=102)
    assert manager.filter([interact, approach], contracts, 1)
    for at in (2, 3, 4):
        manager.outcome(interact, False, "no_response", at)
    assert manager.filter([interact], contracts, 5) == []
    manager.outcome(approach, True, "skill_postcondition_verified", 6)
    assert manager.filter([interact], contracts, 7) == [interact]
