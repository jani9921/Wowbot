"""A quest ender who follows the player (live 2026-10-22 23:11-23:13).

User: "a quest leadó NPC most followerként van jelen ... és annál kellene
leadni".  The Ruby Egg Guardian (190171) walked with the player, 3 yd away,
with a yellow "?" from the server and as the client's soft-interact unit;
it was known from monster moves only (no create block, no NPC flags), so it
was never pressed, and the TDB has no ender for the finished quests.
"""
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy

GUARDIAN = "Creature-0-3769-2444-47-190171-00005A7BEF"


def state(**extra):
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 2022,
        "player_world_position": {"x": 4074.6, "y": 216.5, "z": 38.2, "instance_id": 2444},
        "active_quests": [{"quest_id": 65998, "is_complete": True, "objectives": []}],
        "packet_entities": {GUARDIAN: {
            "guid": GUARDIAN, "kind": "CREATURE", "entry_id": 190171, "map_id": 2444,
            "quest_giver": {"reward_ready": True, "quest_available": False, "age": 26.},
            "position": {"x": 4071.6, "y": 216.4, "z": 39.2, "source": "PACKET_MONSTER_MOVE_ORIGIN",
                         "age": 12.7}}},
        "soft_targets": [], **extra}


def test_a_following_ender_with_a_quest_marker_is_pressed_when_it_is_the_f7_recipient():
    soft = [{"source_unit": "softinteract", "guid": GUARDIAN}]
    (press,) = ServerNpcInteractionPolicy().propose(state(soft_targets=soft, soft_targets_sample_time=100.))
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == GUARDIAN
    # Not the F7 recipient yet: walk up to its server point (no NPC flags needed).
    (move,) = ServerNpcInteractionPolicy().propose(state(player_world_position={
        "x": 4060., "y": 216.5, "z": 38.2, "instance_id": 2444}))
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == GUARDIAN
    # No quest marker and no NPC flags: nothing to talk to.
    plain = state(soft_targets=soft, soft_targets_sample_time=100.)
    plain["packet_entities"][GUARDIAN]["quest_giver"] = {}
    assert ServerNpcInteractionPolicy().propose(plain) == []
