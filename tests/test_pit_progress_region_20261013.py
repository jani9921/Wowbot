"""Live 2026-10-13 06:10 (Who Lurks in the Pit): the first cocoon credit
(0/5 -> 1/5) made the "zone reached" mark stale; 31 yd from the rim POI the
agent climbed out of the pit back to it."""
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy


def _state(current, complete=False):
    return {"active_quests": [{"quest_id": 55639, "is_complete": False, "objectives": [
        {"current": current, "required": 5, "is_complete": complete}]}]}


def test_a_rising_count_keeps_the_reached_region():
    sign = QuestLocationPlanningPolicy.region_signature
    assert sign(_state(0)) == sign(_state(1))
    assert sign(_state(4)) != sign(_state(5, complete=True))


def test_a_cocoon_credit_does_not_send_the_agent_back_to_the_rim_poi():
    policy = QuestLocationPlanningPolicy()
    poi = {"quest_id": 55639, "map_id": 1409, "x": .5096, "y": .5999, "source": "QUEST_POI",
           "world_position": {"x": 81., "y": -2242., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
    policy.mark_reached(poi, _state(0))
    key = policy.location_key(poi)
    assert policy.reached_quest_locations[key] == policy.region_signature(_state(1))
