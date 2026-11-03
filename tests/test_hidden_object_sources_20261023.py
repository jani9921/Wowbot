"""Books saved by looting chests the TDB lists only as hidden item rows.

Live 2026-10-23 00:21 (Library of Alexstrasza 66000): the only live objective
was "0/4 Books saved" (credit "Library of Alexstrasza Quest KC [DNT]").  The
TDB's description-less item rows come from book chests 376941-376946; the
server named each chest's objective (quest_objective_id 427692 ...) with our
Activate flag.  The agent fought off attackers, then waited 122 yd away.
"""
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.packet_entity_facts import hidden_object_sources, objective_objects

BOOK = "GameObject-0-3769-2444-47-376945-00005824C8"


def item_row(objective_id, item, entry):
    return {"amount": 1, "credit_kind": "ITEM", "credit_object_id": item, "description": "",
            "objective_id": objective_id, "raw_type": 1,
            "item_sources": [{"entry": entry, "item_id": item, "kind": "GAMEOBJECT",
                              "relation": "QUEST_ITEM_ASSOCIATION", "confirmed": False}]}


def state(*, activate=True, complete=False):
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 2022,
        "player_world_position": {"x": 4214.8, "y": 156.4, "z": 52.8, "instance_id": 2444, "z_observed": True},
        "active_quests": [{"quest_id": 66000, "is_complete": complete, "objectives": [
            {"description": "0/4 Books saved", "raw_type": "monster", "type": "KILL", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"66000": {"objectives": [
            {"amount": 4, "credit_kind": "CREATURE_CREDIT", "credit_object_id": 189921,
             "credit_name": "Library of Alexstrasza Quest KC [DNT]", "description": "Books saved",
             "objective_id": 427448, "raw_type": 0},
            item_row(427692, 192745, 376941), item_row(427712, 192755, 376945)]}}},
        "packet_entities": {BOOK: {
            "guid": BOOK, "kind": "GAMEOBJECT", "entry_id": 376945, "map_id": 2444,
            "info": {"go_type": 3, "quest_objective_id": 427712},
            "dynamic_flags": {"value": 49700 if activate else 49696},
            "position": {"x": 4105.0, "y": 55.4, "z": 47.8, "instance_id": 2444}}},
    }


def test_the_server_named_book_chest_is_a_use_spot():
    assert hidden_object_sources(state(), 66000) == [("427692", "376941"), ("427712", "376945")]
    (book,) = objective_objects(state(), 66000)
    assert book["guid"] == BOOK and book["usable"] is True
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    spot, known = flow.packet_use_spot(state(), 66000, 52.8)
    assert known and spot["guid"] == BOOK and spot["object_id"] == 376945
    assert flow.packet_interact_ready(state(), spot, 52.8) == "OUT_OF_RANGE"


def test_looted_or_finished_books_are_left_alone():
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    # Activate cleared after our loot: known but nothing to use.
    assert flow.packet_use_spot(state(activate=False), 66000, 52.8) == (None, True)
    # Ready for turn-in: the chests are no longer work.
    assert flow.packet_use_spot(state(complete=True), 66000, 52.8) == (None, False)


def remembered_state(*, now=100., player=(4105.6, 55.9)):
    value = state()
    value["monotonic_time"] = now
    value["player_world_position"].update(x=player[0], y=player[1])
    value["packet_entities"] = {}          # the server forgot the far chests
    value["reference_knowledge"]["quests"]["66000"]["objectives"].append(item_row(427711, 192754, 376944))
    value["reference_knowledge"]["quests"]["66000"]["spawn_candidates"] = [
        {"entity_kind": "GAMEOBJECT", "entry": entry, "x": x, "y": y, "z": z, "world_map_id": 2444,
         "source": "LEARNED_SPAWN", "spawn_id": f"learned:{entry}"}
        for entry, x, y, z in ((376945, 4105.0, 55.4, 47.8), (376941, 4105.7, 101.5, 42.0),
                               (376944, 4275.7, 298.5, 72.0))]
    return value


def test_far_unopened_chests_are_walked_to_from_their_learned_place():
    """Live 00:40:58: 3/4, the server had dropped the chests 296-351 yd away."""
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    current = remembered_state()
    current["active_quests"][0]["objectives"][0]["current"] = 3
    for guid in ("GameObject-0-3769-2444-47-376945-00005824C8",
                 "GameObject-0-3769-2444-47-376941-00005824C8"):
        flow._note_used_object_guid(current, guid)          # credited earlier this acceptance
    assert flow.packet_use_spot(current, 66000, 52.8) == (None, False)
    spot = flow.remembered_object_spot(current, 66000)
    assert spot["object_id"] == "376944" and round(spot["distance"]) == 296
    # Taken again (progress dropped from 3 to 0): every chest counts anew.
    flow._note_used_object_entry(current, 66000, "376944")
    again = remembered_state(player=(4214.8, 156.4))
    again["active_quests"][0]["objectives"][0]["current"] = 0
    assert flow.remembered_object_spot(again, 66000)["object_id"] == "376941"
    current["player_world_position"].update(x=4214.8, y=156.4)
    assert flow.remembered_object_spot(current, 66000) is None


def test_a_chest_missing_at_its_place_is_crossed_off():
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    for now in (100., 102.):
        assert flow.remembered_object_spot(remembered_state(now=now), 66000)["object_id"] == "376941"
    # 4 s at 376945's place without the server showing it usable: gone.
    assert flow.remembered_object_spot(remembered_state(now=104.5), 66000)["object_id"] == "376941"
    assert "376945" in flow._used_object_entries(remembered_state(now=104.5), 66000)


def test_an_unreachable_learned_place_is_skipped_for_the_next_one():
    """Live 00:47:45: the walk to 376944 failed (route) and was asked again."""
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    current = remembered_state(player=(4214.8, 156.4))
    first = flow.remembered_object_spot(current, 66000)["object_id"]
    flow.note_result({"action_id": "a1", "skill": "MOVE", "outcome": "FAILURE",
                      "purpose": "LOCATE_REMEMBERED_QUEST_OBJECT",
                      "reason": "required_navmesh_route_unavailable"}, current)
    second = flow.remembered_object_spot(current, 66000)["object_id"]
    assert second != first


def test_poi_zone_sweep_when_no_chest_is_known():
    """User 2026-10-23: walk the quest POI zone; the server sends what is near."""
    flow = ObjectInteractionFlow.__new__(ObjectInteractionFlow)
    current = remembered_state(player=(4130., 60.))
    current["reference_knowledge"]["quests"]["66000"]["spawn_candidates"] = []
    current["reference_knowledge"]["quests"]["66000"]["pois"] = [{
        "objective_index": 0, "objective_id": 427448, "world_map_id": 2444, "ui_map_id": 2022,
        "conditions": {}, "points": [{"x": x, "y": y, "z": 0} for x, y in
                                     ((4117, 41), (4296, 225), (4307, 302), (4283, 352),
                                      (4256, 388), (4202, 421), (4120, 300))]}]
    assert flow.remembered_object_spot(current, 66000) is None
    cell = flow.server_sweep_cell(current, 66000)
    assert cell is not None and cell["distance"] > ObjectInteractionFlow.SWEEP_SIGHT_YARDS
    # Walking there marks it seen; the next cell is another one.
    current["player_world_position"].update(x=cell["x"], y=cell["y"])
    following = flow.server_sweep_cell(current, 66000)
    assert following is None or (round(following["x"]), round(following["y"])) != (round(cell["x"]), round(cell["y"]))
