"""A quest giver that is an object (live 2026-10-23 00:11:13-00:11:21).

Library of Alexstrasza (66000) starts at a book on the ground, GameObject
377499 "On the Origin of Draconic Species" (type 2, quest giver).  The server
showed it with a "!", 4.3 yd away, and the client's soft-interact recipient
was exactly that book; only creatures were considered, so the agent waited
until the user pressed F7.
"""
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.runtime.entity_identity import check_entity_identity
from wowbot.runtime.skill_identity import expected_identity, soft_interact

BOOK = "GameObject-0-3769-2444-47-377499-00005824C8"


def state(*, soft=True, marker=True, x=4055.3):
    value = {"guid": BOOK, "kind": "GAMEOBJECT", "entry_id": 377499, "map_id": 2444,
             "info": {"go_type": 2},
             "quest_giver": {"quest_available": marker, "reward_ready": False, "age": 22.},
             "position": {"x": 4058.9, "y": 246.8, "z": 54.9, "instance_id": 2444}}
    return {
        "monotonic_time": 100., "orientation": .34, "map_id": 2022,
        "player_world_position": {"x": x, "y": 244.4, "z": 54.7, "instance_id": 2444, "z_observed": True},
        "active_quests": [],
        "packet_entities": {BOOK: value},
        "soft_targets": ([{"source_unit": "softinteract", "guid": BOOK,
                           "name": "On the Origin of Draconic Species"}] if soft else []),
        "soft_targets_sample_time": 100.,
    }


def test_a_quest_marked_book_that_is_the_f7_recipient_is_pressed():
    (press,) = ServerNpcInteractionPolicy().propose(state())
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == BOOK
    assert press.parameters["object_id"] == 377499 and "npc_id" not in press.parameters
    assert press.parameters["interaction_kind"] == "QUEST_OBJECT"
    # The availability gate compares the object ID taken from the GUID.
    assert check_entity_identity(expected_identity(press.parameters), soft_interact(state()))


def test_walks_up_first_and_ignores_unmarked_objects():
    (move,) = ServerNpcInteractionPolicy().propose(state(soft=False, x=4040.))
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == BOOK
    assert move.parameters["object_id"] == 377499
    # No server quest marker: a chair, a door or a crate is never a quest giver.
    assert ServerNpcInteractionPolicy().propose(state(marker=False)) == []
