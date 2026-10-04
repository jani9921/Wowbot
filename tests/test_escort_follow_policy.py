from types import SimpleNamespace

from wowbot.agent.escort_follow import EscortFollowPolicy
from wowbot.agent.movement_controller import ReachMovementController
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.world import WorldModel


def _objective():
    return SimpleNamespace(
        objective_id="7:escort", type="ESCORT", optional=False,
        confidence=.95, target_entity={"npc_id": 123, "name": "Kelsey"},
        target_location=None, location_candidates=(), raw={},
        completion_state="INCOMPLETE")


def _record():
    return SimpleNamespace(quest_id="7", known_locations=())


def _state(now=1., *, entity=True):
    escort = {"guid": "Creature-escort", "npc_id": 123, "name": "Kelsey",
              "position": {"map_id": 1409, "x": .55, "y": .5,
                           "sample_time": now}}
    return {"map_id": 1409, "position": {"x": .5, "y": .5},
            "orientation": 0., "monotonic_time": now,
            "movement": {"moving": False, "speed": 0.},
            "target": {}, "entities": [escort] if entity else [],
            "active_quests": [{"quest_id": 7, "objectives": [{
                "objective_id": "escort", "current": 0, "required": 1,
                "is_complete": False}]}]}


def test_quest_escort_proposes_follow_for_exact_live_entity_not_group_leader():
    world = WorldModel()
    world.state = _state()
    proposal = QuestLocationPlanningPolicy().propose_objective(
        world, _objective(), _record(), "7")[0]
    assert proposal.skill == "FOLLOW"
    assert proposal.parameters["follow_quest_entity"] is True
    assert proposal.parameters["follow_entity_guid"] == "Creature-escort"


def test_escort_follow_tolerates_short_occlusion_then_requests_reacquisition():
    policy = EscortFollowPolicy()
    proposal = policy.follow(_objective(), _record(), _state())
    controller = ReachMovementController()
    controller.start(proposal.parameters, _state(), "one", 1.)
    short = controller.observe(_state(1.5, entity=False), "two", 1.5)
    assert not short.terminal
    lost = controller.observe(_state(3.6, entity=False), "three", 3.6)
    assert lost.terminal
    assert lost.reason == "reach_object_identity_or_position_lost"


def test_missing_escort_emits_bounded_reacquire_and_credit_verifier_is_authoritative():
    policy, objective, record = EscortFollowPolicy(), _objective(), _record()
    proposal = policy.propose(objective, record, _state(entity=False))[0]
    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["search_capability"] == "SEARCH_LOCAL_ENTITY"
    after = _state()
    after["active_quests"][0]["objectives"][0].update(
        current=1, is_complete=True)
    verified = policy.verify_progress(_state(), after, objective, record)
    assert verified.success
