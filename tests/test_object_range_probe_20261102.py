"""Live 2026-11-02 (26230 Feast or Famine, Fresh Dirt 203972): a walk to the
dirt stalled 7.8 yd away on the terrain, was learned as a big object's edge
(8.56 yd), F7 there failed OUT_OF_RANGE, and the alternative approach ring
was as wide as the failed spot -- the agent circled and left.  A range
failure now probes inside the Interact reach, straight in first, and an
entry whose learned edge failed on range is never learned as big again."""
import math

from wowbot.agent.object_approach_search import ObjectApproachSearch

DIRT = "GameObject-0-3111-0-54196-203972-000068A448"


def state(px, py=0., now=10.):
    return {"monotonic_time": now, "session_id": "s", "character_guid": "c",
            "player_world_position": {"x": px, "y": py, "z": 41., "instance_id": 0},
            "active_quests": [], "packet_entities": {DIRT: {
                "guid": DIRT, "kind": "GAMEOBJECT", "entry_id": 203972, "map_id": 0,
                "position": {"x": 0., "y": 0., "z": 41.}}}}


def spot():
    return {"guid": DIRT, "x": 0., "y": 0., "z": 41., "instance_id": 0}


def test_a_range_failure_probes_closer_and_straight_in_first():
    search = ObjectApproachSearch()
    search.reject(state(8.), DIRT, reason="out_of_range")
    goal = search.goal(state(8.), spot())
    assert math.hypot(goal["x"], goal["y"]) <= ObjectApproachSearch.CLOSER_YARDS + 1e-6
    assert goal["x"] > 0 and abs(goal["y"]) < 1e-6                  # same bearing: straight toward it


def test_a_blocked_approach_still_tries_other_sides_at_the_same_ring():
    search = ObjectApproachSearch()
    search.reject(state(8.), DIRT, reason="supported_stuck")
    goal = search.goal(state(8.), spot())
    assert math.hypot(goal["x"], goal["y"]) > 8.


def test_an_entry_whose_learned_edge_failed_on_range_is_not_learned_big_again():
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    flow._learn_packet_reach(DIRT, 203972, 7.8)
    assert flow.packet_use_range({"guid": DIRT, "object_id": 203972}) > ObjectInteractionFlow.PACKET_USE_RANGE_YARDS
    flow.__dict__.setdefault("_small_entries", set()).add("203972")
    flow._forget_packet_reach(DIRT, 203972)
    assert flow.packet_use_range({"guid": DIRT, "object_id": 203972}) == ObjectInteractionFlow.PACKET_USE_RANGE_YARDS
