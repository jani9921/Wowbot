from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def _objective(kind, description, *, entity=None):
    return SimpleNamespace(
        type=kind, objective_id="7:0", description=description,
        target_entity=entity, target_object=None,
        target_location={"map_id": 1409, "x": .4, "y": .6},
        location_candidates=(), confidence=.85, optional=False,
        raw={"type": kind, "description": description})


def _world(objective, *, target=None):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "entity-flow", "timestamp": 1., "monotonic_time": 1.,
        "frame_id": "one", "map_id": 1409, "position": {"x": .4, "y": .6},
        "target": target, "actionbar": [{"kind": "spell", "action": "1", "id": 100,
            "is_harmful": True, "is_usable": True, "in_range": True,
            "cooldown_remaining": 0.}],
        "active_quests": [{"quest_id": 7, "objectives": [{
            **objective.raw, "objective_id": "7:0", "target_entity": objective.target_entity,
            "target_location": objective.target_location, "current": 0, "required": 1,
        }]}],
    }, 1.))
    return world


def test_speak_arrival_enters_bounded_identity_search_then_hands_valid_target_to_talk():
    objective = _objective("TALK_TO", "Talk to Lady Jaina Proudmoore",
                           entity={"npc_id": 166824, "name": "Lady Jaina Proudmoore"})
    world, policy = _world(objective), QuestLocationPlanningPolicy()
    record = SimpleNamespace(quest_id=7, known_locations=[])
    policy.mark_reached({"quest_id": 7, **objective.target_location}, world.state)

    search = policy.propose_objective(world, objective, record, "7")
    assert search[0].skill == "SEEK_VISUAL_CUE"
    assert search[0].parameters["expected_npc_id"] == 166824
    assert search[0].parameters["search_capability"] == "SEARCH_LOCAL_ENTITY"

    matched_world = _world(objective, target={"guid": "Creature-1", "npc_id": 166824,
                                               "name": "Lady Jaina Proudmoore",
                                               "attackable": False})
    assert policy.propose_objective(matched_world, objective, record, "7") == []
    assert any(proposal.skill == "TALK" for proposal in
               Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), matched_world, 1.))


def test_kill_arrival_search_requires_hostile_identity_then_combat_policy_takes_over():
    objective = _objective("KILL", "0/3 Murlocs slain")
    world, policy = _world(objective), QuestLocationPlanningPolicy()
    record = SimpleNamespace(quest_id=7, known_locations=[])
    policy.mark_reached({"quest_id": 7, **objective.target_location}, world.state)

    search = policy.propose_objective(world, objective, record, "7")
    assert search[0].skill == "SEEK_VISUAL_CUE"
    assert search[0].parameters["require_attackable"] is True
    assert search[0].parameters["expected_name"] == "murlocs"

    matched_world = _world(objective, target={"guid": "Creature-2",
        "name": "Murloc Watershaper", "attackable": True, "dead": False})
    assert policy.propose_objective(matched_world, objective, record, "7") == []
    assert any(proposal.skill == "COMBAT" for proposal in
               Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), matched_world, 1.))
