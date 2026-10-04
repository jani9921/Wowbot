from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from test_agent_core import agent, state


def test_kill_objective_builds_generic_verified_horizon_but_executes_only_first_step():
    bot, executor = agent()
    quest = {"quest_id": 42, "objectives": [{"objective_id": "42:kill", "type": "KILL",
        "required": 3, "current": 0,
        "target_location": {"map_id": 1609, "x": .55, "y": .45}}]}
    result = bot.tick(state(active_quests=[quest]), 1)
    plan = result["plan"]
    assert plan["steps"][0]["capability"] == "MOVE"
    assert plan["steps"][0]["status"] == "READY"
    assert [step["capability"] for step in plan["steps"]][1:] == [
        "ACQUIRE_TARGET", "APPROACH_TARGET", "COMBAT", "LOOT", "VERIFY_OBJECTIVE"]
    assert all(step["status"] == "BLOCKED_BY_PRIOR_STEP" for step in plan["steps"][1:])
    assert len(executor.commands) == 1
    assert executor.commands[0].binding in {"MOVEFORWARD", "TURNLEFT", "TURNRIGHT"}


def test_plan_records_constraints_replan_triggers_and_candidate_utility():
    bot, _ = agent()
    quest = {"quest_id": 7, "objectives": [{"objective_id": "7:talk", "type": "TALK_TO",
        "target_npc_id": 9, "required": 1, "current": 0}]}
    target = {"npc_id": 9, "guid": "Creature-9", "attackable": False}
    result = bot.tick(state(active_quests=[quest], target=target), 1)
    plan = result["plan"]
    assert {"SESSION_UNCHANGED", "TELEMETRY_FRESH", "OBJECTIVE_STILL_ACTIVE",
            "TARGET_IDENTITY_MATCH"} <= set(plan["constraints"])
    assert {"PREDICTION_ERROR", "QUEST_STATE_CHANGED", "SENSOR_DEGRADED"} <= set(plan["replan_triggers"])
    chosen = next(item for item in plan["candidate_utilities"]
                  if item["proposal_id"] == plan["selected_proposal_id"])
    assert set(chosen) >= {"priority", "reliability_bonus", "cost_penalty", "distance_penalty", "total"}


def test_horizon_never_makes_dependency_blocked_objective_ready():
    world = WorldModel()
    quest = {"quest_id": 3, "objectives": [
        {"objective_id": "3:first", "type": "TALK_TO", "current": 0},
        {"objective_id": "3:second", "type": "KILL", "current": 0,
         "dependencies": ["3:first"], "target_location": {"map_id": 1609, "x": .7, "y": .7}},
    ]}
    world.ingest(Observation.create(state(active_quests=[quest]), 1))
    planner = Planner(SkillRegistry())
    proposal = Proposal.make("WAIT", "needs evidence")
    horizon = planner.plan_horizon(proposal, world)
    assert all(step.get("objective_id") != "3:second" for step in horizon)
