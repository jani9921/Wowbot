"""Live 2026-10-27 15:45-15:56 (Obsidian Citadel assault): after the scene
every server unit came on map 2534 "Black Dragon Citadel - Narrative Version"
(client Map CosmeticParentMapID 2444) while the addon kept instance 2444.  All
were dropped as another map's spawns; the agent saw no Qalashi and no Siege
Arbalest.  A cosmetic child shares its parent's coordinates."""
from types import SimpleNamespace

from wowbot.agent import world_packet_reducer as reducer
from wowbot.packetio.context import guid_map_id

CONTEXT = {"selected_pid": 1, "session_id": "s", "character_guid": "c", "instance_id": 2444, "game_build": 70575}
# A real Qalashi Necksnapper create from the 15:51 capture (map 2534).
NECKSNAPPER = {"entity_guid": "2016D53CC0B6830002415F000060B358", "entry_id": 186892, "object_kind": "UNIT",
               "world_map_id": 2534, "dynamic_flags": 0, "npc_flags": 0, "x": 2288.45, "y": 2322.71, "z": 156.07,
               "facing": 2.34, "coordinate_space": "WORLD_YARDS", "position_source": "MOVEMENT"}


def with_map(raw_guid, map_id):
    high = int(raw_guid[:16], 16) & ~(0x1FFF << 29) | (map_id << 29)
    return f"{high:016X}{raw_guid[16:]}"


def test_cosmetic_child_maps_share_the_world():
    assert guid_map_id(NECKSNAPPER["entity_guid"]) == 2534
    assert reducer.same_world_map(2534, 2444) and reducer.same_world_map(2444, 2534)
    assert reducer.same_world_map(2444, 2444)
    assert not reducer.same_world_map(2552, 2444) and not reducer.same_world_map(0, 2444)


def test_the_citadel_units_enter_the_entity_table():
    model = SimpleNamespace()
    reducer._remember_entity(model, "ENTITY_CREATED", NECKSNAPPER, 10., CONTEXT)
    other = dict(NECKSNAPPER, entity_guid=with_map(NECKSNAPPER["entity_guid"], 2552))
    reducer._remember_entity(model, "ENTITY_CREATED", other, 10., CONTEXT)
    table = model.__dict__["_packet_entities"]
    assert len(table) == 1
    (entity,) = table.values()
    assert entity["entry_id"] == 186892 and entity["map_id"] == 2444      # the player's frame
    assert entity["position"]["x"] == NECKSNAPPER["x"]


def test_the_server_map_comes_from_new_world_or_the_creates_around_us():
    model = SimpleNamespace(addon_state={**CONTEXT, "map_id": 2022,
                                          "player_world_position": {"instance_id": 2444}})
    for index in range(10):
        body = dict(NECKSNAPPER, entity_guid=NECKSNAPPER["entity_guid"][:-2] + f"{index:02X}")
        reducer._remember_entity(model, "ENTITY_CREATED", body, 10.+index, CONTEXT)
    state = {"player_world_position": {"instance_id": 2444}}
    reducer._project_server_map(model, state)
    assert state["packet_server_map"]["map_id"] == 2534 and state["packet_server_map"]["source"] == "ENTITY_GUIDS"
    model.__dict__["_packet_server_map"] = {"map_id": 2444, "sampled_at": 30.,
        "scope": reducer._entity_scope(CONTEXT), "source": "SMSG_NEW_WORLD"}
    model.__dict__.pop("_packet_entities_context", None)
    state = {"player_world_position": {"instance_id": 2444}}
    reducer._project_server_map(model, state)
    assert "packet_server_map" not in state                       # back on the parent map


def test_geometry_answers_from_the_server_map_where_it_has_tiles():
    from wowbot.world_geometry.service import WorldGeometryService

    class Source:
        def exists(self, name):
            return name in {"2534_27_27.mmtile"}

    navmesh = SimpleNamespace(source=Source(), supports=lambda map_id: map_id in {2444, 2534})
    geometry = WorldGeometryService(navmesh=navmesh)
    wall, far = {"x": 2250.1, "y": 2509.6}, {"x": 900., "y": 900.}
    assert geometry.map_for(2444, wall) == 2444
    geometry.set_server_map(2444, 2534)
    assert geometry.map_for(2444, wall) == 2534 and geometry.map_for(2444, wall, far) == 2444
    geometry.set_server_map(2444, None)
    assert geometry.map_for(2444, wall) == 2444
