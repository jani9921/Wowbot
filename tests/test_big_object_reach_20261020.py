"""Big quest objects: learn the reachable edge (live 2026-10-20 10:16-10:18).

Catapult Destruction (55989, objective GO 326651): the walk aimed at the
catapult's centre ran into its model (supported_stuck 10:16:26, 10:17:25) and
Interact waited for 3.5 yd from that centre; F7 came only when the user
helped the character up onto the catapult.
"""
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow

CATAPULT = "GameObject-0-1465-2175-71046-326651-00005712AA"
SECOND = "GameObject-0-1465-2175-71046-326651-00005712BB"
CRATE = "GameObject-0-1465-2175-71046-180744-00005712CC"


def go(guid, x, y, go_type=10, flags=0xC204):
    return {"guid": guid, "kind": "GAMEOBJECT", "entry_id": int(guid.split("-")[5]), "map_id": 2175,
            "info": {"object_kind": "GAMEOBJECT", "go_type": go_type, "quest_objective_id": 389991},
            "dynamic_flags": {"value": flags},
            "position": {"x": x, "y": y, "z": 10., "source": "PACKET_CREATE_STATIONARY", "age": 5.}}


def state(x, now, *, facing=0., extra=()):
    objects = [go(CATAPULT, 10., 0.), go(SECOND, 40., 0.), *extra]
    return {"monotonic_time": now, "map_id": 1409, "is_in_combat": False, "orientation": facing,
            "soft_targets": [], "soft_targets_sample_time": now-.1,
            "player_world_position": {"x": x, "y": 0., "z": 10., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 55989, "is_complete": False, "objectives": [
                {"objective_id": "55989:0", "type": "INTERACT", "raw_type": "object",
                 "current": 0, "required": 4, "is_complete": False}]}],
            "reference_knowledge": {"quests": {"55989": {"objectives": [
                {"objective_id": 389991, "credit_kind": "GAMEOBJECT", "credit_object_id": 326651,
                 "object_template": {"object_id": 326651, "name": "Catapult"}, "order": 0}]}}},
            "packet_entities": {item["guid"]: item for item in objects}}


WALK = {"purpose": "APPROACH_QUEST_OBJECT_SPAWN", "quest_id": 55989, "server_entity_guid": CATAPULT}


def test_a_walk_blocked_at_the_edge_hands_off_and_f7_fires_from_there():
    flow = ObjectInteractionFlow()
    for at, x in ((1., 2.), (1.5, 4.), (2., 5.5)):                 # still closing in
        assert flow.object_move_handoff(state(x, at), WALK, 10.) is None
    assert flow.object_move_handoff(state(5.5, 2.6), WALK, 10.) is None   # pressing against it
    edge = flow.object_move_handoff(state(5.55, 3.3), WALK, 10.)
    assert edge["kind"] == "SERVER_QUEST_OBJECT_EDGE" and edge["guid"] == CATAPULT
    spot, _ = flow.packet_use_spot(state(5.55, 3.4), 55989, 10.)
    assert spot["guid"] == CATAPULT and flow.packet_use_range(spot) == 5.2
    assert flow.packet_interact_ready(state(5.55, 3.4), spot, 10.) == "READY"
    # The next catapult (same entry) is approached only to its edge.
    far, _ = flow.packet_use_spot(state(30., 4.), 55989, 10.)
    assert far["guid"] == SECOND and flow.packet_stop_distance(far) == 4.2


def test_turning_in_place_is_no_edge_and_a_failed_use_forgets_the_reach():
    flow = ObjectInteractionFlow()
    flow.object_move_handoff(state(5., 1.), WALK, 10.)
    assert flow.object_move_handoff(state(5., 1.8, facing=1.), WALK, 10.) is None   # turning
    assert flow.object_move_handoff(state(5., 2.4, facing=1.6), WALK, 10.) is None
    flow._learn_packet_reach(CATAPULT, 326651, 4.45)
    spot, _ = flow.packet_use_spot(state(5.55, 3.), 55989, 10.)
    assert flow.packet_use_range(spot) == 5.2
    flow.note_result({"action_id": "u1", "skill": "OBJECT_USE", "outcome": "FAILURE",
                      "reason": "quest_credit_not_received", "object_guid": CATAPULT}, state(5.55, 3.))
    assert flow.packet_use_range(spot) == flow.PACKET_USE_RANGE_YARDS


def test_decorations_beside_the_object_do_not_block_the_key():
    flow = ObjectInteractionFlow()
    flow._learn_packet_reach(CATAPULT, 326651, 4.45)
    live = state(5.55, 3., extra=(go(CRATE, 6.5, 1., go_type=5, flags=0x8000),))
    spot, _ = flow.packet_use_spot(live, 55989, 10.)
    assert flow.packet_interact_ready(live, spot, 10.) == "READY"
