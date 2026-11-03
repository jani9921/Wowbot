"""User 2026-10-31 (live 08:00): hand in what is on the current map first.

The Fargodeep Mine (62, Goldshire) and Hero's Call: Westfall! (26378) were
both ready; equal priority and capped distance penalty flipped the choice."""
from wowbot.agent.models import Proposal
from wowbot.agent.turnin_order import ZoneResolver, order_turnins

UIMAPS = {39: {"ParentUiMapID": 37, "Type": 5}, 37: {"ParentUiMapID": 13, "Type": 3},
          52: {"ParentUiMapID": 13, "Type": 3}, 13: {"ParentUiMapID": 947, "Type": 2}}


TURNIN_BLOBS = {62: 37, 26209: 52}


class Catalog:
    def record(self, table, key):
        return UIMAPS.get(key, {}) if table == "UiMap" else {}

    def quest(self, quest_id, details=False):
        if quest_id not in TURNIN_BLOBS:
            return {}
        return {"records": [{"table": "QuestPOIBlob", "data": {"ObjectiveIndex": -1, "UiMapID": TURNIN_BLOBS[quest_id],
                                                               "PlayerConditionID": 0}}]}


def move(quest, x, y, **location):
    return Proposal.make("MOVE", "leadás", {"quest_id": quest, "x": x, "y": y, "instance_id": 0,
                                            "purpose": "LOCATE_TURN_IN_REGION", **location}, priority=110)


def poi(ui_map, x, y):
    return {"blobs": [{"objective_index": -1, "objective_id": 0, "ui_map_id": ui_map, "points": [{"x": x, "y": y}]}]}


def state(ui_map=39, pois=None):
    return {"map_id": ui_map, "player_world_position": {"x": -9826., "y": 198., "instance_id": 0},
            "packet_quest_pois": pois or {}}


def chosen(proposals):
    return max(proposals, key=lambda p: p.priority).parameters["quest_id"]


def test_micro_maps_belong_to_their_zone():
    zones = ZoneResolver(Catalog())
    assert [zones.zone(m) for m in (39, 37, 52, None, 0)] == [37, 37, 52, None, None]


def test_the_same_zone_turn_in_wins_even_from_the_mine_and_even_if_farther():
    zones = ZoneResolver(Catalog())
    # Westfall's POI placed nearer than Goldshire on purpose: the zone decides first.
    westfall = move(26378, -9850., 300., knowledge_priority="SERVER_POI", ui_map_id=52)
    goldshire = move(62, -9466., 74., knowledge_priority="PRIMARY_STATIC", map_id=39)   # TDB: map is a copy
    pois = {"62": poi(37, -9466., 74.)}
    for order in ([westfall, goldshire], [goldshire, westfall]):
        result = order_turnins(order, state(pois=pois), zones)
        assert chosen(result) == 62 and sorted(p.priority for p in result) == [109., 110.]


def test_a_tdb_region_without_zone_evidence_is_never_called_same_zone():
    zones = ZoneResolver(Catalog())
    tdb_near = move(2, -9830., 200., knowledge_priority="PRIMARY_STATIC", map_id=39)       # zone unknown
    elwynn_poi = move(1, -9600., 0., knowledge_priority="SERVER_POI", ui_map_id=37)
    assert chosen(order_turnins([tdb_near, elwynn_poi], state(), zones)) == 1
    other = move(3, -9830., 199., knowledge_priority="SERVER_POI", ui_map_id=52)
    assert chosen(order_turnins([other, tdb_near], state(), zones)) == 2                 # unknown before other zone


def test_live_0823_an_api_border_waypoint_is_no_zone_evidence():
    """The breadcrumb's API pin sat on the Elwynn map at the Westfall border;
    no server POI yet (first tick).  The DB2 turn-in blob places 62 in Elwynn."""
    zones = ZoneResolver(Catalog())
    westfall_pin = move(26378, -9700., 600., knowledge_priority="QUEST_API_CURRENT", map_id=37)
    goldshire_tdb = move(62, -9466., 74., knowledge_priority="PRIMARY_STATIC", map_id=37)
    assert chosen(order_turnins([westfall_pin, goldshire_tdb], state(37), zones)) == 62
    assert chosen(order_turnins([goldshire_tdb, westfall_pin], state(39), zones)) == 62


def test_within_a_zone_the_nearer_wins_and_one_move_is_untouched():
    zones = ZoneResolver(Catalog())
    near = move(5, -9800., 190., knowledge_priority="SERVER_POI", ui_map_id=37)
    far = move(6, -9466., 74., knowledge_priority="SERVER_POI", ui_map_id=37)
    assert chosen(order_turnins([far, near], state(), zones)) == 5
    assert order_turnins([far], state(), zones) == [far]
