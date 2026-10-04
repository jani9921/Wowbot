"""Campaign quests first (user 2026-10-03, option B + C).

A campaign "!" is always the next pickup; side quests are taken only when on
the way (<= 60 yd) or when no campaign quest is available or in progress.
While a campaign quest is open, far side-quest trips wait.
"""
from types import SimpleNamespace

from wowbot.agent.map_poi_planning import MapPoiPlanningPolicy
from wowbot.agent.models import Proposal
from wowbot.agent.quest_planning import QuestDomain


def _giver(quest_id, x, y, campaign):
    return {"quest_id": quest_id, "quest_name": f"q{quest_id}", "x": .5, "y": .5,
            "source": "QUESTLINE_API", "is_campaign": campaign,
            "world_position": {"x": x, "y": y, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}


def _world(givers, active=()):
    return SimpleNamespace(state={
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175},
        "monotonic_time": 1., "active_quests": list(active),
        "map_pois": {"available_quests": list(givers)}})


def _targets(world):
    return [p.parameters["quest_id"] for p in MapPoiPlanningPolicy().quest_giver_moves(world)]


def test_campaign_giver_is_preferred_over_a_nearer_side_quest():
    givers = [_giver(1, 80., 0., False), _giver(2, 300., 0., True)]
    assert _targets(_world(givers)) == [2]


def test_side_quests_on_the_way_are_picked_up_too():
    givers = [_giver(1, 40., 0., False), _giver(2, 300., 0., True), _giver(3, 200., 0., False)]
    assert _targets(_world(givers)) == [2, 1]


def test_side_quests_carry_on_when_no_campaign_is_available():
    givers = [_giver(1, 80., 0., False), _giver(3, 200., 0., False)]
    assert _targets(_world(givers)) == [1, 3]


def test_no_new_campaign_pickup_while_one_is_in_progress():
    givers = [_giver(2, 300., 0., True), _giver(1, 40., 0., False)]
    active = [{"quest_id": 9, "is_campaign": True, "is_complete": False}]
    assert _targets(_world(givers, active)) == [1]


def _move(quest_id, x, purpose="LOCATE_QUEST_OBJECTIVE_REGION", priority=40.):
    return Proposal.make("MOVE", "m", {"quest_id": quest_id, "x": x, "y": 0.,
                                       "coordinate_space": "WORLD_YARDS", "purpose": purpose},
                         priority=priority)


def test_campaign_work_first_and_far_side_trips_wait():
    state = {"player_world_position": {"x": 0., "y": 0.},
             "active_quests": [{"quest_id": 9, "is_campaign": True, "is_complete": False},
                               {"quest_id": 5, "is_campaign": False, "is_complete": False}]}
    proposals = [_move(9, 300.), _move(5, 50.), _move(5, 400.),
                 Proposal.make("COMBAT", "c", {"quest_ids": [9]}, priority=90.)]
    result = QuestDomain.prefer_campaign(proposals, state)
    assert [(p.skill, p.parameters.get("quest_id"), p.priority) for p in result] == [
        ("MOVE", 9, 44.), ("MOVE", 5, 40.), ("COMBAT", None, 94.)]
    # Campaign done (only turn-in left) or no campaign at all: side trips are free.
    state["active_quests"][0]["is_complete"] = True
    assert len(QuestDomain.prefer_campaign(proposals, state)) == 4
