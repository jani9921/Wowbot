"""Best Plans and Intentions (66048): after Fao's gossip the battle plans table
(a GOOBER the server links to "Fao the Relentless consulted", 427169, usable)
is used with F7 instead of re-talking to Fao (live 2026-10-26 21:35)."""
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, linked_object_entries

TABLE = "GameObject-0-3769-2444-47-377106-00005824C5"
FAO = "Creature-0-3769-2444-47-186331-00005824C5"


def camp(x=1856.0, y=1269.5, facing=0.5, soft=FAO):
    return {
        "monotonic_time": 10., "orientation": facing, "is_in_combat": False, "quest_ui": {"open": False},
        "player_world_position": {"x": x, "y": y, "z": 189.7, "z_observed": True, "instance_id": 2444,
                                  "coordinate_space": "WORLD_YARDS"},
        "soft_targets": [{"source_unit": "softinteract", "guid": soft}] if soft else [],
        "soft_targets_sample_time": 10.,
        "active_quests": [{"quest_id": 66048, "is_complete": False, "objectives": [
            {"description": "0/1 Fao the Relentless consulted", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"66048": {"objectives": [
            {"objective_id": 427169, "description": "Fao the Relentless consulted",
             "credit_kind": "CREATURE_CREDIT", "credit_object_id": 186331}]}}},
        "packet_entities": {TABLE: {"guid": TABLE, "kind": "GAMEOBJECT", "entry_id": 377106, "map_id": 2444,
                                    "info": {"object_kind": "GAMEOBJECT", "go_type": 10, "quest_objective_id": 427169},
                                    "dynamic_flags": {"value": 49668},
                                    "position": {"x": 1858.42, "y": 1272.32, "z": 189.66, "sampled_at": 10.,
                                                 "source": "PACKET_CREATE_STATIONARY"}}}}


def test_the_linked_usable_table_is_a_candidate_of_its_quest():
    assert linked_object_entries(camp()) == {"377106": "66048"}
    spent = camp()
    spent["packet_entities"][TABLE]["dynamic_flags"]["value"] = 49664          # no Activate
    assert linked_object_entries(spent) == {}


def test_walk_into_the_tent_then_f7_on_the_table():
    (move,) = ServerNpcInteractionPolicy().propose(camp())
    assert move.skill == "MOVE" and move.parameters["object_id"] == 377106
    assert move.parameters["stop_distance"] == 1.2 and move.parameters["face_on_arrival"] is True
    (use,) = ServerNpcInteractionPolicy().propose(camp(x=1857.4, y=1272.3, facing=0., soft=None))
    assert use.skill == "OBJECT_USE" and use.parameters["activation_source"] == "INTERACT_KEY_PACKET"
    # Fao still the client's F7 recipient: no press (it would talk to him).
    assert ServerNpcInteractionPolicy().propose(camp(x=1857.4, y=1272.3, facing=0.)) == []
    # Already beside the table, another F7 recipient is not solved by
    # repeatedly walking into the table's collision model.


def test_the_linked_table_goes_before_a_nearer_quest_npc():
    """Live 21:46: Fao 1.9 yd, the table 8.2 yd; nearest-first re-talked to Fao."""
    state = camp(x=1851.0, y=1268.0)
    state["packet_entities"][FAO] = {
        "guid": FAO, "kind": "CREATURE", "entry_id": 186331, "map_id": 2444,
        "info": {"npc_flags": 3}, "quest_giver": {"quest_available": False, "reward_ready": False},
        "position": {"x": 1852.5, "y": 1268.5, "z": 189.7, "sampled_at": 10., "source": "PACKET_CREATE_STATIONARY"}}
    import wowbot.agent.server_npc_planning as planning
    original = planning.objective_npc_entries
    planning.objective_npc_entries = lambda state, **queries: {"186331": "66048"}
    try:
        (step,) = ServerNpcInteractionPolicy().propose(state)
    finally:
        planning.objective_npc_entries = original
    assert step.skill == "MOVE" and step.parameters.get("object_id") == 377106


def test_no_interact_keeps_the_table_closed_until_the_talk():
    """Live 22:46:42: re-accepted 66048, the plans went 0xc204 -> 0xc284
    (Activate kept, NO_INTERACT added) until Fao's gossip; F7 was pressed on
    them anyway and failed OUT_OF_RANGE."""
    closed = camp()
    closed["packet_entities"][TABLE]["dynamic_flags"]["value"] = 0xc284
    assert linked_object_entries(closed) == {}
    assert ServerNpcInteractionPolicy().propose(closed) == []
    from wowbot.agent.packet_entity_facts import server_object_interactable
    assert not server_object_interactable(closed, TABLE)
    assert server_object_interactable(camp(), TABLE)                 # 0xc204 after the talk
