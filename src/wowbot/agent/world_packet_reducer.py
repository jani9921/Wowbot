"""Typed packet evidence at the canonical WorldModel boundary, never input."""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import math

from .models import number, json_copy as copy
from wowbot.context_contracts import SessionContext, context_matches
from wowbot.packetio.context import addon_context, addon_entity_guid, guid_map_id, same_player
from wowbot.packetio.validation import ENTITY_EVENTS as ENTITY_KINDS, normalize_event, verified_semantics


def _context(model, state, pid):
    provider = getattr(model, "session_context_provider", None)
    return provider.expected(pid) if provider is not None else addon_context(state, pid)

# Server-side creature/vehicle/game-object facts (Ymir 70448, layouts from the
# pinned WPP source and checked byte-exact on a real capture). A creature's
# position is its create position or its latest spline start/destination;
# both stay valid until the unit moves again or is removed.
ENTITY_LIMIT = 512
PROJECTED_ENTITIES = 96
POSITION_MAX_AGE = 300.
# The server answers quest-giver status queries when a giver comes into view
# and after quest-state changes; between those the status stays current.
QUEST_GIVER_MAX_AGE = 900.
QUEST_CREDIT_MAX_AGE = 900.
QUEST_POI_MAX_AGE = 1800.
EVENT_FRESH_SECONDS = 2.


def freshness_limit(event_type) -> float:
    """How old a delivered event may be when it is read.

    Live 2026-10-31 09:58 (login, Westfall): the agent read the packet queue
    late during the login and discarded 130 events as older than 2 s, the
    quest POI answers among them; the client asks for POIs only at login and
    on accept, so the turn-in and the objective search had none.  A POI is
    static quest geometry with its own lifetime; motion, combat and entity
    facts keep the 2 s rule."""
    from wowbot.packetio.inbox import max_event_age
    return max_event_age(event_type, EVENT_FRESH_SECONDS)
PENDING_KINDS = ENTITY_KINDS | {'QUEST_POI_UPDATE'}
REMOVED_VISIBLE_FOR = 60.
_INFO_FIELDS = ("object_kind", "npc_flags", "go_flags", "go_state", "go_type", "quest_objective_id")
# Live 2026-10-21 10:57:06: the packet source opened its context from the
# newest addon payload while the merged addon state the reducer checks was
# not complete yet; the snapshot replay of every nearby object (the rib cage
# holding Professor Cogcatcher among them) arrived in that ~0.5 s and was
# dropped -- the cage was never known and the agent stood still beside it.
# Entity facts arriving then wait PENDING_SECONDS for a matching context.
PENDING_SECONDS = 15.
PENDING_LIMIT = 4096


def _poi_scope(context):
    """Quest POIs are scoped by player identity, not by world or phase.

    Live 2026-10-31 09:40 (login, Westfall): the server answered the POI
    queries 1.5 s before the login's NEW_WORLD; the world step changed the
    entity scope and the projection dropped every POI, so the turn-in and the
    objective search fell back to TDB.  Each blob carries its own world map,
    which every consumer checks against the player's world."""
    bound = SessionContext.from_mapping(context)
    if bound is None:
        return None
    identity = bound.identity
    return {"selected_pid": identity.selected_pid, "session_id": identity.session_id,
            "character_guid": identity.character_guid, "game_build": identity.game_build}


def _remember_quest_poi(model, event, sampled, expected):
    body = event['payload']
    age = event['timestamp']-body.get('capture_timestamp', event['timestamp'])
    if not 0 <= age <= QUEST_POI_MAX_AGE:
        return
    sampled -= age
    scope = _poi_scope(expected)
    if model.__dict__.get('_packet_poi_context') != scope:
        model.__dict__['_packet_quest_pois'] = {}
    model.__dict__['_packet_poi_context'] = scope
    records = model.__dict__.setdefault('_packet_quest_pois', {})
    key = str(body['quest_id'])
    if sampled < records.get(key, {}).get('sampled_at', -math.inf):
        return
    records[key] = {'quest_id': body['quest_id'], 'blobs': copy(body['blobs']),
                    'sampled_at': sampled, 'verified': True,
                    'source': 'SMSG_QUEST_POI_QUERY_RESPONSE'}
    while len(records) > 64:
        records.pop(next(iter(records)))


def _entity_scope(context):
    # The addon map_id is the UI map (1409 vs. a cave sub-map); a UI-map step
    # inside the same world map must not forget the server's entity facts.
    bound = SessionContext.from_mapping(context)
    return bound.entity_scope() if bound else None


@lru_cache(maxsize=256)
def _cosmetic_root(map_id):
    """The map whose coordinates a cosmetic (narrative/phase) map shares.

    Live 2026-10-27 15:45:33-15:56 (The Courage of One's Convictions, Taking
    the Walls): after the scene into the Obsidian Citadel every server unit
    and object came on map 2534 "Black Dragon Citadel - Narrative Version"
    (client Map CosmeticParentMapID 2444) while the addon kept instance 2444.
    All of them were dropped as another map's spawns; the agent never saw a
    Qalashi or the South Siege Arbalest and only fought what attacked it."""
    from wowbot.quests.client_catalog import ClientCatalog
    seen = []
    current = map_id
    while type(current) is int and current >= 0 and current not in seen and len(seen) < 8:
        seen.append(current)
        try:
            parent = (ClientCatalog().record("Map", current) or {}).get("CosmeticParentMapID")
        except Exception:                       # missing catalogue: exact maps only
            return current
        if type(parent) is not int or parent < 0:
            return current
        current = parent
    return current


def same_world_map(entity_map, instance) -> bool:
    """The entity's GUID map is the player's map or shares its cosmetic root."""
    return entity_map == instance or (type(entity_map) is int and type(instance) is int
                                      and _cosmetic_root(entity_map) == _cosmetic_root(instance))


SERVER_MAP_SAMPLES = 40          # recent entity creates that name the server map
SERVER_MAP_SHARE = .6


def _remember_entity(model, kind, body, sampled, context):
    scope = _entity_scope(context)
    if scope is None:
        return
    guid = addon_entity_guid(body.get("entity_guid"))
    raw_map = guid_map_id(body["entity_guid"]) if guid is not None else None
    if guid is None or not same_world_map(raw_map, context["instance_id"]):
        return  # another map's spawn (or a player/pet) never enters this world
    if model.__dict__.get("_packet_entities_context") != scope:
        model.__dict__["_packet_entities"] = {}
        model.__dict__["_packet_entities_context"] = scope
        model.__dict__.pop("_entity_raw_maps", None)
        known = model.__dict__.get("_packet_server_map")
        if known and known["scope"] != scope:
            model.__dict__.pop("_packet_server_map", None)
    if kind == "ENTITY_CREATED":
        # Without SMSG_NEW_WORLD (a run started inside the narrative map,
        # live 15:50) the creates around us still name the server's map.
        recent = model.__dict__.setdefault("_entity_raw_maps", deque(maxlen=SERVER_MAP_SAMPLES))
        recent.append((raw_map, sampled))
    table = model.__dict__.setdefault("_packet_entities", {})
    entity = table.pop(guid, None) or {"guid": guid, "kind": guid.split("-", 1)[0].upper(),
        "entry_id": int(guid.split("-")[5]), "map_id": context["instance_id"]}
    position = None
    if kind == "ENTITY_CREATED":
        entity.pop("removed", None)
        entity["info"] = {k: body[k] for k in _INFO_FIELDS if k in body} | {"sampled_at": sampled}
        entity["dynamic_flags"] = {"value": body["dynamic_flags"], "sampled_at": sampled}
        entity.pop("unit", None)
        _remember_unit(entity, body, sampled, context)
        if "x" in body:
            position = {"x": body["x"], "y": body["y"], "z": body["z"], "facing": body["facing"],
                        "source": "PACKET_CREATE_"+body["position_source"]}
    elif kind == "ENTITY_POSITION":
        position = {"x": body["x"], "y": body["y"], "z": body["z"], "source": "PACKET_MONSTER_MOVE_ORIGIN",
                    "move_time_ms": body.get("move_time_ms")}
        if "destination_x" in body:
            position["destination"] = {"x": body["destination_x"], "y": body["destination_y"],
                                       "z": body["destination_z"]}
    elif kind == "ENTITY_REMOVED":
        entity["removed"] = {"reason": body["removal"], "sampled_at": sampled}
    elif kind == "ENTITY_FLAGS":
        if sampled >= (entity.get("dynamic_flags") or {}).get("sampled_at", -math.inf):
            entity["dynamic_flags"] = {"value": body["dynamic_flags"], "sampled_at": sampled}
    elif kind == "ENTITY_UNIT_UPDATE":
        _remember_unit(entity, body, sampled, context)
    elif sampled >= (entity.get("quest_giver") or {}).get("sampled_at", -math.inf):
        entity["quest_giver"] = {k: body.get(k, False) for k in (
            "quest_available", "reward_ready", "quest_incomplete", "trivial_available", "future_quest")
        } | {"status_flags": body["status_flags"], "sampled_at": sampled}
    if position and sampled >= (entity.get("position") or {}).get("sampled_at", -math.inf):
        entity["position"] = position | {"sampled_at": sampled, "coordinate_space": "WORLD_YARDS"}
    entity["last_sampled_at"] = max(sampled, entity.get("last_sampled_at", -math.inf))
    table[guid] = entity  # re-insert: oldest-touched entries are evicted first
    while len(table) > ENTITY_LIMIT:
        table.pop(next(iter(table)))


_UNIT_VALUES = ("health", "max_health", "level", "faction_template", "unit_flags", "unit_flags2",
                "unit_flags3", "bounding_radius", "combat_reach")
UNIT_IN_COMBAT = 0x80000          # UNIT_FLAG_IN_COMBAT (live 16:38: 0x88840 while fighting)


def _remember_unit(entity, body, sampled, context) -> None:
    """Health, level, faction, unit flags, reach and relations of a creature.

    Other players' GUIDs never enter the world model: a target or creator is
    kept as "us" (the selected character) or as a creature/vehicle GUID."""
    values = {key: body[key] for key in _UNIT_VALUES if key in body}
    for key, mine, other in (("target_guid", "targets_me", "target_entity"),
                             ("summoned_by", "summoned_by_me", None), ("created_by", "created_by_me", None)):
        if key not in body:
            continue
        raw = body[key]
        values[mine] = raw is not None and same_player(raw, context["character_guid"])
        if other is not None:
            values[other] = addon_entity_guid(raw) if raw else None
    if not values:
        return
    unit = entity.get("unit") or {}
    if sampled < unit.get("sampled_at", -math.inf):
        return
    entity["unit"] = {**unit, **values, "sampled_at": sampled}


def _estimate(position, age):
    """Linear progress along a one-point spline; a finished move is at its destination."""
    destination, duration = position.get("destination"), position.get("move_time_ms")
    if not destination or not duration:
        return None
    progress = max(0., min(1., age*1000./duration))
    return {k: position[k]+(destination[k]-position[k])*progress for k in ("x", "y", "z")} | {
        "progress": round(progress, 3), "arrived": progress >= 1.}


def _project_entities(model, state, reference):
    table = model.__dict__.get("_packet_entities")
    stored = model.__dict__.get("_packet_entities_context")
    if not stored:
        return
    if _entity_scope(_context(model, model.addon_state, stored["selected_pid"])) != stored:
        model.__dict__.pop("_packet_entities", None)
        model.__dict__.pop("_packet_entities_context", None)
        model.__dict__.pop("_entity_raw_maps", None)
        return
    if not table:
        return
    def age(sample):
        return reference-sample["sampled_at"]
    me = state.get("player_world_position") or {}
    projected = []
    for entity in table.values():
        removed = entity.get("removed")
        if removed and age(removed) > REMOVED_VISIBLE_FOR:
            continue
        value = {k: entity[k] for k in ("guid", "kind", "entry_id", "map_id")}
        if removed:
            value["removed"] = {**removed, "age": round(max(0., age(removed)), 3)}
        for part in ("info", "dynamic_flags", "unit"):
            if entity.get(part):
                value[part] = copy(entity[part])
        giver = entity.get("quest_giver")
        if giver and -1. <= age(giver) <= QUEST_GIVER_MAX_AGE:
            value["quest_giver"] = {**copy(giver), "age": round(max(0., age(giver)), 3)}
        position = entity.get("position")
        if position:
            elapsed = age(position)
            # A create position or a spline with a known destination stays
            # true until the next move/removal (a standing giver sends no
            # more moves); only a destination-less spline start ages out.
            settled = (position["source"].startswith("PACKET_CREATE_")
                       or position.get("destination") is not None)
            if -1. <= elapsed and (settled or elapsed <= POSITION_MAX_AGE):
                value["position"] = {**copy(position), "age": round(max(0., elapsed), 3)}
                estimate = _estimate(position, max(0., elapsed))
                if estimate:
                    value["position"]["estimate"] = estimate
        if len(value) == 4:
            continue
        point = (value.get("position") or {}).get("estimate") or value.get("position")
        distance = (math.dist((point["x"], point["y"]), (me["x"], me["y"]))
                    if point and type(me.get("x")) in {int, float} and type(me.get("y")) in {int, float}
                    else math.inf)
        if point and distance < math.inf:
            value["distance"] = round(distance, 2)
        # Quest givers with a server "!"/"?" first, then nearest: a standing
        # giver must not be crowded out of the bounded projection by mobs.
        marker = value.get("quest_giver") or {}
        projected.append((not (marker.get("quest_available") or marker.get("reward_ready")),
                          bool(removed), distance, value))
    projected.sort(key=lambda item: item[:3])
    result = {item[3]["guid"]: item[3] for item in projected[:PROJECTED_ENTITIES]}
    if result:
        state["packet_entities"] = result


def _project_server_map(model, state) -> None:
    """``packet_server_map``: the server's map for the player when it is a
    cosmetic relative of the addon's instance (live 2026-10-27 15:45:40:
    SMSG_NEW_WORLD to 2534 "Black Dragon Citadel - Narrative Version" while
    the addon kept 2444).  World geometry routes on that map's own navmesh
    there: the narrative citadel's walls and gates differ from 2444's."""
    instance = (state.get("player_world_position") or {}).get("instance_id")
    known = model.__dict__.get("_packet_server_map")
    if known:
        scope = known.get("scope")
        # A NEW_WORLD can precede every entity create. Its scope must be
        # checked against the current context even when the entity table is
        # empty; otherwise the previous phase's cosmetic map survives.
        current = _entity_scope(_context(model, model.addon_state, scope["selected_pid"])) if scope else None
        if current is None or current != scope:
            model.__dict__.pop("_packet_server_map", None)
            known = None
    if type(instance) is not int:
        return
    if known and same_world_map(known["map_id"], instance):
        if known["map_id"] != instance:
            state["packet_server_map"] = {k: known[k] for k in ("map_id", "sampled_at", "source")}
        return
    recent = model.__dict__.get("_entity_raw_maps") or ()
    counts = {}
    for raw_map, _ in recent:
        counts[raw_map] = counts.get(raw_map, 0) + 1
    if not counts:
        return
    raw_map, count = max(counts.items(), key=lambda item: item[1])
    if raw_map != instance and count >= SERVER_MAP_SHARE*len(recent) and same_world_map(raw_map, instance):
        state["packet_server_map"] = {"map_id": raw_map, "sampled_at": recent[-1][1],
                                      "source": "ENTITY_GUIDS", "samples": len(recent)}


# Standing still sends no own movement packets.  0.75 yd dropped the held
# height on addon position jitter (live 2026-10-27 16:10: 11 of 52 samples on
# the citadel wall had no height).
HELD_HEIGHT_YARDS = 1.5
VEHICLE_POSE_HOLD_SECONDS = 60.


def _held_own_height(model, state) -> None:
    """The server-reported height of our own last movement, while we stand there.

    Retail exports no player height (z_known False) and own movement packets
    stop when the character stands still, so the newer addon sample always
    replaced the packet position and the Z resolver guessed layers ("ambiguous
    player layer after fall").  While the addon x/y is still where our last
    own movement packet put us, that packet's z is an observation.
    """
    last = model.__dict__.get("_packet_last_own")
    position = state.get("player_world_position") or {}
    if not last or not position or position.get("z_observed") is True:
        return
    if _entity_scope(_context(model, model.addon_state, last["context"]["selected_pid"])) !=             _entity_scope(last["context"]):
        model.__dict__.pop("_packet_last_own", None)
        return
    x, y = number(position.get("x")), number(position.get("y"))
    if (x is None or y is None or state.get("loading") or state.get("player_present") is False
            or str(position.get("instance_id")) != str(last["context"]["instance_id"])
            or math.hypot(x-last["x"], y-last["y"]) > HELD_HEIGHT_YARDS):
        return
    state["player_world_position"] = {**position, "z": last["z"], "z_known": True, "z_observed": True,
                                      "z_source": "PACKET_CLIENT_MOVEMENT_HELD"}


COURSE_KINDS = frozenset({"SCENE_STARTED", "SCENE_ENDED", "SCENE_EVENT", "MOVEMENT_ROOT", "GOSSIP_SELECTED"})
SCENE_ENDED_VISIBLE_FOR = 30.
STARTER_SECONDS = 30.            # a gossip row this long before a scene started it
FAILED_COURSE_VISIBLE_FOR = 900.


def _remember_scene(model, kind, direction, body, sampled, context) -> None:
    """The client scene that runs now and the own client's ring triggers.

    Skyriding courses and races (2026-10-25) are client scenes: the server
    names the scene package (SMSG_PLAY_SCENE); the own client's scene script
    reports each ring it flew through ("Checkpoint") and the finish
    ("RaceComplete").  A race start line roots the rider until the start.
    """
    scope = _entity_scope(context)
    if model.__dict__.get("_packet_scene_context") != scope:
        model.__dict__["_packet_scene"] = None
        model.__dict__["_packet_root"] = None
        model.__dict__["_packet_gossip"] = None
        model.__dict__["_packet_failed_course"] = None
        model.__dict__["_packet_scene_context"] = scope
    if kind == "MOVEMENT_ROOT":
        if same_player(body.get("mover_guid"), context["character_guid"]):
            model.__dict__["_packet_root"] = {"rooted": body["rooted"] is True, "sampled_at": sampled}
        return
    if kind == "GOSSIP_SELECTED":
        guid = addon_entity_guid(body.get("entity_guid"))
        if guid is not None:
            model.__dict__["_packet_gossip"] = {"guid": guid, "entry_id": body.get("entry_id"),
                                                "gossip_menu_id": body.get("gossip_menu_id"),
                                                "gossip_option_id": body.get("gossip_option_id"),
                                                "sampled_at": sampled}
        return
    scene = model.__dict__.get("_packet_scene")
    instance = body.get("scene_instance_id")
    if kind == "SCENE_STARTED" and direction == "SERVER_TO_CLIENT":
        own = model.__dict__.get("_packet_last_own") or {}
        position = model.addon_state.get("player_world_position") or {}
        start = ({k: own[k] for k in ("x", "y", "z")} if own and 0 <= sampled-own["sampled_at"] <= 30.
                 else {k: position.get(k) for k in ("x", "y")})
        gossip = model.__dict__.get("_packet_gossip") or {}
        starter = (copy(gossip) if gossip and 0 <= sampled-gossip["sampled_at"] <= STARTER_SECONDS else None)
        model.__dict__["_packet_scene"] = {
            "scene_instance_id": instance, "package_id": body["package_id"], "scene_id": body.get("scene_id"),
            "started_at": sampled, "start_position": start, "checkpoints": 0, "race_complete": 0,
            "ended_at": None, "starter": starter}
        model.__dict__["_packet_failed_course"] = None      # a new attempt runs
    elif scene is not None and scene["scene_instance_id"] == instance:
        if kind == "SCENE_EVENT" and direction == "CLIENT_TO_SERVER" and scene["ended_at"] is None:
            key = "checkpoints" if body.get("scene_event") == "CHECKPOINT" else "race_complete"
            scene[key] += 1
        elif kind == "SCENE_ENDED":
            scene["ended_at"] = sampled
            scene["canceled"] = body.get("canceled") is True
            if scene.get("starter") and not scene["race_complete"]:
                # Not finished (the race timed out): who started it, for a retry.
                model.__dict__["_packet_failed_course"] = {
                    k: copy(scene.get(k)) for k in ("scene_instance_id", "package_id", "scene_id",
                                                    "start_position", "starter", "checkpoints")} | {
                    "ended_at": sampled}


def _project_scene(model, state, reference) -> None:
    state.pop("packet_scene", None)
    state.pop("route_counters", None)
    state.pop("movement_rooted", None)
    state.pop("failed_scene_course", None)
    stored = model.__dict__.get("_packet_scene_context")
    if not stored or _entity_scope(_context(model, state, stored["selected_pid"])) != stored:
        return
    root = model.__dict__.get("_packet_root")
    if root is not None:
        state["movement_rooted"] = copy(root)
    failed = model.__dict__.get("_packet_failed_course")
    if failed and 0 <= reference-failed["ended_at"] <= FAILED_COURSE_VISIBLE_FOR:
        state["failed_scene_course"] = copy(failed)
    scene = model.__dict__.get("_packet_scene")
    if not scene or (scene["ended_at"] is not None and reference-scene["ended_at"] > SCENE_ENDED_VISIBLE_FOR):
        return
    state["packet_scene"] = {**copy(scene), "active": scene["ended_at"] is None}
    if scene["ended_at"] is None:
        # Declarative checkpoint evidence for a FlightPath (conditions root).
        state["route_counters"] = {"scene": {k: scene[k] for k in (
            "scene_instance_id", "package_id", "checkpoints", "race_complete")}}


def _vehicle_mover(guid) -> bool:
    return isinstance(guid, str) and len(guid) == 32 and int(guid[:16], 16) >> 58 == 9


def _own_flight(safe, sampled, expected, *, in_vehicle=False):
    """The selected player's own client movement sample, or None.

    In a vehicle the client moves the vehicle (CMSG_SET_ACTIVE_MOVER): live
    2026-10-26 11:05-11:06 the Ruby Whelpling's own packets carried the only
    height (z 284.3) and facing; a client sends movement only for the mover
    it controls, so in a vehicle a Vehicle-GUID mover is ours."""
    body = safe["payload"]
    mover = body.get("mover_guid")
    if not (safe["event_type"] == "MOVEMENT_UPDATE" and safe["direction"] == "CLIENT_TO_SERVER"
            and (same_player(mover, expected["character_guid"]) or (in_vehicle and _vehicle_mover(mover)))
            and body.get("is_selected_client_movement") is True
            and not body.get("on_transport") and not body.get("standing_on_game_object")
            and body.get("coordinate_space") == "WORLD_YARDS"
            and all(type(body.get(k)) in {int, float} and math.isfinite(body[k]) for k in ("x", "y", "z", "facing"))):
        return None
    return {
        "sample_time": sampled, "source_opcode": body.get("source_opcode"),
        "vehicle_mover": _vehicle_mover(mover),
        **{k: body.get(k) for k in ("pitch", "flying", "can_fly", "adv_flying", "falling", "fall_z_speed",
                                    "fall_xy_speed", "forward_velocity", "up_velocity")},
        "z": body["z"], "facing": body["facing"],
        "position": {**{k: body[k] for k in ("x", "y", "z")},
                     "coordinate_space": "WORLD_YARDS", "instance_id": expected["instance_id"],
                     "sample_time": sampled, "source": "PACKET_CLIENT_MOVEMENT"},
    }


def _remember_own(model, flight, sampled, expected) -> bool:
    last_own = model.__dict__.get("_packet_last_own") or {}
    if sampled <= last_own.get("sampled_at", -math.inf):
        return False
    model.__dict__["_packet_last_own"] = {"context": copy(expected), "sampled_at": sampled,
        **{k: flight["position"][k] for k in ("x", "y", "z")}, "flight": flight}
    return True


# Live 2026-10-31 02:09-02:12 (Fargodeep Mine entrance): the addon's UI map
# flipped Elwynn 37 / mine 39 every few seconds.  Each flip changed the
# logical context, so the transport took a new nonce and every in-flight event
# (own movement included) was dropped as another context; for 160 s no own
# height arrived and each position probe timed out.  The UI map is no world,
# session or phase identity (P1-B: a UI-map step keeps the entity facts).  The
# exact transport-context equality, PID, session, character, build, world and
# phase checks are unchanged.
def _same_scope(context, expected) -> bool:
    return context_matches(context, expected, include_ui_map=False)


def _authenticated(model, obs):
    """(normalized event, addon context, sample time) of an authentic, fresh,
    in-context packet observation, else None.  Raises on a malformed event."""
    event, context = obs.payload.get("packet_event"), obs.payload.get("packet_context")
    safe = normalize_event(event)
    expected = _context(model, model.addon_state, safe["selected_pid"])
    provenance = obs.payload.get("provenance") or {}
    sampled = number(event.get("sampled_at_monotonic"))
    if (expected is None or not isinstance(context, dict) or event.get("ipc_context") != context
            or not context.get("context_id") or provenance.get("producer") != "RuntimePacketSource"
            or provenance.get("selected_pid") != safe["selected_pid"]
            or sampled is None or not math.isfinite(sampled) or not 0 <= obs.received_at-sampled <= 2.
            or not _same_scope(context, expected)):
        return None
    from .packet_continuity import accepts_event, refresh
    if not accepts_event(model, safe):
        return None
    refresh(model, model.state)
    return safe, expected, sampled


class WorldPacketReducer:
    @staticmethod
    def peek_own_movement(model, obs) -> bool:
        """Flight feedback for the fast control lane (user 2026-10-25).

        Live 17:28 (Skyriding, "circles around a ring"): the packet inbox is
        drained only by the medium tick (live 1-3 Hz, seconds under SQLite
        load), so the ~20 Hz flight loop steered on a facing and pitch
        0.3-0.6 s old and turned ~1.3 rad past every heading.  The client's
        newest own movement sample, under the same authentication, context
        and semantic checks, updates only the bounded flight feedback here;
        the event stays queued and the medium tick applies it in full.
        """
        try:
            accepted = _authenticated(model, obs)
        except (ValueError, TypeError, OverflowError, KeyError):
            return False
        if accepted is None:
            return False
        safe, expected, sampled = accepted
        if not verified_semantics(safe) or safe["provenance"].get("game_build") != expected["game_build"]:
            return False
        flight = _own_flight(safe, sampled, expected, in_vehicle=model.addon_state.get("in_vehicle") is True)
        return flight is not None and _remember_own(model, flight, sampled, expected)

    @staticmethod
    def apply(model, obs, *, defer_rebuild=False):
        event, context = obs.payload.get("packet_event"), obs.payload.get("packet_context")
        try:
            safe = normalize_event(event)
            expected = _context(model, model.addon_state, safe["selected_pid"])
            provenance = obs.payload.get("provenance") or {}
            authentic = (isinstance(context, dict) and event.get("ipc_context") == context
                         and bool(context.get("context_id"))
                         and provenance.get("producer") == "RuntimePacketSource"
                         and provenance.get("selected_pid") == safe["selected_pid"])
            sampled = number(event.get("sampled_at_monotonic"))
            fresh = (sampled is not None and math.isfinite(sampled)
                     and 0 <= obs.received_at-sampled <= freshness_limit(safe["event_type"]))
            if (authentic and fresh and safe["event_type"] in PENDING_KINDS and expected is None):
                # The addon context is not known yet.
                WorldPacketReducer._hold(model, obs, safe, sampled, context)
                return False
            if (expected is None or not authentic or not fresh
                    or not _same_scope(context, expected)):
                return False
        except (ValueError, TypeError, OverflowError):
            return False
        from .packet_continuity import accepts_event
        if not accepts_event(model, safe):
            return False
        from .packet_continuity import refresh as refresh_continuity
        refresh_continuity(model, model.state)
        seen = model.__dict__.setdefault("_packet_event_ids", deque(maxlen=1024))
        if safe["event_id"] in seen:
            return False
        seen.append(safe["event_id"])
        WorldPacketReducer._flush_pending(model, expected, obs.received_at, seen)
        kind, body = safe["event_type"], safe["payload"]
        verified = verified_semantics(safe) and safe["provenance"].get("game_build") == expected["game_build"]
        model.history.append(obs)
        model.add_evidence("packet_event:"+kind, {"event_id": safe["event_id"],
            "payload": body, "semantic_status": safe["semantic_status"],
            "verified": verified}, obs, confidence=1. if verified else 0., ttl=2.)
        model.__dict__["_packet_status"] = {"last_event": kind, "last_sampled_at": sampled,
            "last_received_at": obs.received_at, "semantic_verified": verified, "source": "PACKET_TELEMETRY"}
        if verified:
            from wowbot.packetio.own_inventory_codec import EVENTS as INVENTORY_EVENTS
            if (kind in INVENTORY_EVENTS and same_player(body.get('mover_guid'),expected['character_guid'])
                    and same_world_map(body['world_map_id'],expected['instance_id'])):
                from .packet_inventory import remember as remember_inventory
                remember_inventory(model,kind,body,obs,sampled,expected)
                from .runtime_packet_progress import note_collection
                note_collection(model,safe,obs)
            from wowbot.packetio.quest_definition import EVENTS as DEFINITION_EVENTS
            if kind in DEFINITION_EVENTS:
                from .server_quest_definitions import remember as remember_definition, scope as definition_scope
                provider = model.session_context_provider
                generation = provider.process.generation if provider is not None else None
                remember_definition(model.quest_model, kind, body, definition_scope(expected, generation),
                                    obs, sampled, safe['provenance'])
            if (kind in {'OWN_QUEST_LOG_UPDATE','OWN_QUEST_LOG_INVALIDATED'}
                    and same_player(body.get('mover_guid'), expected['character_guid'])
                    and same_world_map(body['world_map_id'], expected['instance_id'])):
                from .packet_quest_log import remember as remember_quest_log, invalidate as invalidate_quest_log
                if kind == 'OWN_QUEST_LOG_INVALIDATED':
                    invalidate_quest_log(model,obs,sampled,expected)
                else:
                    remember_quest_log(model,body,obs,sampled,expected)
                from .runtime_packet_progress import note_collection
                note_collection(model,safe,obs)
            if (kind == 'OWN_PROFILE_UPDATE' and same_player(body.get('mover_guid'), expected['character_guid'])
                    and same_world_map(body['world_map_id'], expected['instance_id'])):
                from .packet_own_profile import remember as remember_profile
                remember_profile(model, body, obs, sampled, expected)
            if kind == 'OWN_POWER_UPDATE' and same_player(body.get('mover_guid'), expected['character_guid']):
                from .packet_own_power import remember as remember_power
                remember_power(model, body, obs, sampled, expected)
            if kind == 'MAP_CHANGED' and model.session_context_provider is not None:
                model.session_context_provider.advance_world(event)
                expected = model.session_context_provider.expected(safe['selected_pid'])
            if (kind == 'OWN_UNIT_UPDATE' and same_player(body.get('mover_guid'), expected['character_guid'])
                    and same_world_map(body['world_map_id'], expected['instance_id'])):
                from .packet_own_health import remember as remember_health
                remember_health(model, body, obs, sampled, expected)
            from wowbot.packetio.spell_cast import CAST_EVENTS
            if kind in CAST_EVENTS or kind in {'ENTITY_REMOVED', 'MAP_CHANGED'}:
                raw = body.get('caster_guid')
                if raw is None or same_world_map(guid_map_id(raw), expected['instance_id']):
                    from .packet_combat import remember as remember_combat
                    remember_combat(model, kind, body, sampled, expected)
            if kind == "QUEST_POI_UPDATE":
                _remember_quest_poi(model, safe, sampled, expected)
            if kind == "MAP_CHANGED" or body.get("teleport"):
                model.__dict__.pop("_packet_navigation", None)
                model.__dict__.pop("_packet_last_own", None)
            if kind == "MAP_CHANGED":
                model.__dict__.pop("_packet_entities", None)
                model.__dict__.pop("_entity_raw_maps", None)
                model.__dict__["_packet_server_map"] = {
                    "map_id": body["world_map_id"], "sampled_at": sampled,
                    "scope": _entity_scope(expected), "source": "SMSG_NEW_WORLD"}
                # The server's landing point is our observed position until
                # we move (live 2026-10-27: after the flight onto the citadel
                # wall the own height stayed unknown until the first step,
                # and a route was planned on the courtyard 44 yd below).
                model.__dict__["_packet_last_own"] = {
                    "context": copy(expected), "sampled_at": sampled,
                    **{k: body[k] for k in ("x", "y", "z")}, "flight": None}
            if kind in ENTITY_KINDS:
                _remember_entity(model, kind, body, sampled, expected)
            flight = _own_flight(safe, sampled, expected, in_vehicle=model.addon_state.get("in_vehicle") is True)
            if flight is not None:
                previous = model.__dict__.get("_packet_navigation") or {}
                _remember_own(model, flight, sampled, expected)
                if sampled > previous.get("sampled_at", -math.inf):
                    model.__dict__["_packet_navigation"] = {"context": copy(expected),
                        "sampled_at": sampled, "body": copy(body), "observed_at": obs.received_at}
                    point = copy(model.addon_state.get("player_world_position") or {})
                    point.update({k: body[k] for k in ("x", "y", "z")})
                    point.update(coordinate_space="WORLD_YARDS", source="PACKET_CLIENT_MOVEMENT", sample_time=sampled,
                                 instance_id=expected["instance_id"], z_known=True, z_observed=True)
                    # Evidence lifetime starts at the inbox's real sample
                    # time, not receipt. Do not subtract transport age twice.
                    model.add_evidence("player_world_position", point, obs, confidence=1., ttl=.75)
                    model.add_evidence("orientation", body["facing"], obs, confidence=1., ttl=.75)
                    # Skyriding/flight feedback (user 2026-10-25): pitch and the
                    # measured forward/up speed come only from these packets.
                    model.add_evidence("packet_flight", flight, obs, confidence=1., ttl=1.5)
            if kind in COURSE_KINDS:
                _remember_scene(model, kind, safe["direction"], body, sampled, expected)
            applicable = kind not in COURSE_KINDS
            if kind in {"COMBAT_STARTED", "ATTACK_STOPPED"}:
                applicable = any(same_player(body.get(k), expected["character_guid"])
                                 for k in ("attacker_guid", "victim_guid"))
            if kind.startswith("QUEST_"):
                applicable = any(str(q.get("quest_id")) == str(body.get("quest_id"))
                                 for q in model.addon_state.get("active_quests") or ())
            if applicable and kind == "QUEST_CREDIT_ADDED":
                # The live credit count per (quest, credit object), ahead of
                # the addon's quest log (Skyriding rings, 2026-10-25).
                scope = _entity_scope(expected)
                if model.__dict__.get("_packet_credits_context") != scope:
                    model.__dict__["_packet_credits"] = {}
                    model.__dict__["_packet_credits_context"] = scope
                credits = model.__dict__.setdefault("_packet_credits", {})
                objectives = credits.setdefault(str(body["quest_id"]), {})
                previous = objectives.get(str(body["object_id"]), {})
                if sampled >= previous.get("sampled_at", -math.inf):
                    objectives[str(body["object_id"])] = {
                        "count": body["count"], "required": body["required"], "sampled_at": sampled}
                    model.add_evidence("packet_quest_credits", copy(credits), obs,
                                       confidence=1., ttl=QUEST_CREDIT_MAX_AGE)
            if applicable and kind not in {"MOVEMENT_UPDATE", "MAP_CHANGED", *ENTITY_KINDS}:
                record = model._emit_derived_event(kind, {**body, "packet_event_id": safe["event_id"],
                    "semantic_status": "CONFIRMED", "packet_observed_at": sampled}, obs)
                if record:
                    model.quest_model.apply_event(record)
            # Death-like attack-stop evidence never awards corpse ownership
            # or loot eligibility. The existing corpse verifier remains owner.
        if defer_rebuild:
            model._state_dirty = True
        else:
            model._rebuild_state()
        return model._accepted(obs)

    @staticmethod
    def _hold(model, obs, safe, sampled, context) -> None:
        bound = SessionContext.from_mapping(context)
        if (bound is None or bound.world.ui_map_id is None
                or bound.identity.selected_pid != safe["selected_pid"]):
            return
        model.__dict__.setdefault("_packet_pending", deque(maxlen=PENDING_LIMIT)).append(
            (obs.received_at, safe, sampled, bound.entity_scope()))

    @staticmethod
    def hold(model, obs) -> None:
        """A packet observation from before the addon session is known:
        keep its entity fact (authentic, fresh) for ``_flush_pending``."""
        event, context = obs.payload.get("packet_event"), obs.payload.get("packet_context")
        provenance = obs.payload.get("provenance") or {}
        try:
            safe = normalize_event(event)
        except (ValueError, TypeError, OverflowError):
            return
        sampled = number(event.get("sampled_at_monotonic"))
        if (safe["event_type"] in PENDING_KINDS and isinstance(context, dict)
                and event.get("ipc_context") == context and context.get("context_id")
                and provenance.get("producer") == "RuntimePacketSource"
                and provenance.get("selected_pid") == safe["selected_pid"]
                and sampled is not None and math.isfinite(sampled)
                and 0 <= obs.received_at-sampled <= freshness_limit(safe["event_type"])):
            WorldPacketReducer._hold(model, obs, safe, sampled, context)

    @staticmethod
    def _flush_pending(model, expected, now, seen) -> None:
        """Apply entity facts held while the addon context was settling."""
        pending = model.__dict__.get("_packet_pending")
        if not pending:
            return
        model.__dict__["_packet_pending"] = deque(maxlen=PENDING_LIMIT)
        stable = _entity_scope(expected)
        for received, held, sampled, context in pending:
            if (stable is None or not 0 <= now-received <= PENDING_SECONDS or context != stable
                    or held["event_id"] in seen or not verified_semantics(held)
                    or held["provenance"].get("game_build") != expected["game_build"]):
                continue
            seen.append(held["event_id"])
            if held['event_type'] == 'QUEST_POI_UPDATE':
                _remember_quest_poi(model, held, sampled, expected)
            else:
                _remember_entity(model, held["event_type"], held["payload"], sampled, expected)

    @staticmethod
    def project_flight_feedback(model, state, reference):
        """Read the canonical selected-player sample; never restamp or fuse XY into Z.

        Newer addon XY cannot replace the packet's pitch/speed/3D sample.
        The same bounded projection is used by full and fast control views.
        """
        state.pop("packet_flight", None)
        state.pop("packet_vehicle_pose", None)
        last = model.__dict__.get("_packet_last_own") or {}
        context = last.get("context")
        if (not context or not last.get("flight")
                or _entity_scope(_context(model, state, context["selected_pid"])) != _entity_scope(context)
                or not 0 <= reference-last["sampled_at"] <= VEHICLE_POSE_HOLD_SECONDS):
            return
        if state.get("in_vehicle") is True and last["flight"].get("vehicle_mover"):
            # A hovering vehicle sends no movement and nothing moves it
            # meanwhile: its last own sample (pitch, facing, height) holds
            # (live 2026-10-26 11:34: 40 s without a packet at the hover).
            state["packet_vehicle_pose"] = copy(last["flight"])
        if reference-last["sampled_at"] <= 1.2:
            state["packet_flight"] = copy(last["flight"])

    @staticmethod
    def project_quest_credits(model, state, reference):
        """Bounded current-session counters, retaining their real sample time."""
        state.pop("packet_quest_credits", None)
        stored = model.__dict__.get("_packet_credits_context")
        if (not stored or state.get("loading") or state.get("player_present") is False
                or _entity_scope(_context(model, state, stored["selected_pid"])) != stored):
            model.__dict__.pop("_packet_credits", None)
            model.__dict__.pop("_packet_credits_context", None)
            return
        active = {str(q.get("quest_id")) for q in state.get("active_quests") or () if isinstance(q, dict)}
        projected = {}
        for quest, objectives in (model.__dict__.get("_packet_credits") or {}).items():
            if quest not in active:
                continue
            values = {key: value for key, value in objectives.items()
                      if 0 <= reference-value["sampled_at"] <= QUEST_CREDIT_MAX_AGE}
            if values:
                projected[quest] = values
        model.__dict__["_packet_credits"] = copy(projected)
        if projected:
            state["packet_quest_credits"] = copy(projected)

    @staticmethod
    def project(model, state):
        from .packet_continuity import refresh as refresh_continuity
        refresh_continuity(model, state)
        if (state.get("player_world_position") or {}).get("source") == "PACKET_CLIENT_MOVEMENT":
            state["player_world_position"] = copy(model.addon_state.get("player_world_position") or {})
            state["orientation"] = model.addon_state.get("orientation")
        status = model.__dict__.get("_packet_status")
        if status:
            state["packet_telemetry"] = copy(status)
        nav = model.__dict__.get("_packet_navigation")
        latest = getattr(model, 'latest', None)
        reference = max([model.last_received, latest.received_at if latest else 0.,
                         (nav or {}).get("observed_at", 0.),
                         (status or {}).get("last_received_at", 0.),
                         *(o.received_at for o in model.source_latest.values()),
                         *(model.__dict__.get("projection_received_at") or {}).values()])
        WorldPacketReducer.project_flight_feedback(model, state, reference)
        WorldPacketReducer.project_quest_credits(model, state, reference)
        state.pop("packet_quest_pois", None)
        poi_scope = model.__dict__.get("_packet_poi_context")
        if poi_scope:
            if state.get("loading") or state.get("player_present") is False:
                # Live 2026-10-31 08:00 (login, Fargodeep): the server answers
                # the client's POI queries during the loading screen. Wiping
                # them here left only the TDB ender spawn for the turn-in.
                # Loading hides the points; only a scope change drops them.
                pass
            elif _poi_scope(_context(model, state, poi_scope["selected_pid"])) is None:
                pass        # identity not (re)established yet: hide, never drop
            elif _poi_scope(_context(model, state, poi_scope["selected_pid"])) != poi_scope:
                model.__dict__.pop("_packet_quest_pois", None)
                model.__dict__.pop("_packet_poi_context", None)
                model.__dict__.pop("_packet_poi_active_quests", None)
            else:
                active = {str(q.get("quest_id")) for q in state.get("active_quests") or () if isinstance(q, dict)}
                previous = model.__dict__.get("_packet_poi_active_quests", set())
                for removed in previous-active:
                    (model.__dict__.get("_packet_quest_pois") or {}).pop(removed, None)
                model.__dict__["_packet_poi_active_quests"] = active
                # The full snapshot stays in this evidence owner. Current
                # consumers need turn-in blobs only; don't copy every quest
                # polygon into the world/status on every perception tick.
                points = {qid: {**value, "blobs": [blob for blob in value["blobs"]
                           if blob["objective_index"] == -1 and blob["objective_id"] == 0]}
                          for qid, value in (model.__dict__.get("_packet_quest_pois") or {}).items()
                          if qid in active and 0 <= reference-value["sampled_at"] <= QUEST_POI_MAX_AGE}
                if points:
                    state["packet_quest_pois"] = copy(points)
        _project_scene(model, state, reference)
        _project_entities(model, state, reference)
        from .packet_own_health import project as project_health
        project_health(model, state, reference, lambda pid: _context(model, state, pid))
        from .packet_own_profile import project as project_profile
        project_profile(model, state, reference, lambda pid: _context(model, state, pid))
        from .packet_own_power import project as project_power
        project_power(model, state, reference, lambda pid: _context(model, state, pid))
        from .packet_quest_log import project as project_quest_log
        project_quest_log(model, state, reference, lambda pid: _context(model, state, pid))
        from .packet_inventory import project as project_inventory
        project_inventory(model,state,reference,lambda pid:_context(model,state,pid))
        from .server_quest_definitions import project as project_definitions
        project_definitions(model, state, reference, lambda pid: _context(model, state, pid))
        from .packet_combat import project as project_combat
        project_combat(model, state, reference, lambda pid: _context(model, state, pid))
        _project_server_map(model, state)
        from .server_mode import status as server_mode_status
        last = (status or {}).get("last_received_at")
        state["server_mode"] = server_mode_status(
            reference - last if isinstance(last, (int, float)) else None,
            len(state.get("packet_entities") or {}))
        WorldPacketReducer.project_own_navigation(model, state, reference)

    @staticmethod
    def project_own_navigation(model, state, reference):
        """The same scoped own-position projection for medium and FAST views."""
        from .packet_continuity import current
        if not current(model):
            point = state.get('player_world_position') or {}
            if (point.get('source') == 'PACKET_CLIENT_MOVEMENT'
                    or str(point.get('z_source') or '').startswith('PACKET_')):
                if point.get('source') == 'PACKET_CLIENT_MOVEMENT':
                    point = copy(model.addon_state.get('player_world_position') or {})
                else:
                    point = copy(point)
                point.pop('z', None);point.pop('observed_z', None)
                point.update(z_known=False,z_observed=False,z_source='PACKET_CONTINUITY_GAP')
                state['player_world_position'] = point
            return
        _held_own_height(model, state)
        nav = model.__dict__.get('_packet_navigation')
        if not nav:
            return
        context = _context(model, model.addon_state, nav["context"]["selected_pid"])
        if (_entity_scope(context) != _entity_scope(nav["context"]) or not 0 <= reference-nav["sampled_at"] <= .75
                or state.get("loading") or state.get("player_present") is False):
            model.__dict__.pop("_packet_navigation", None)
            return
        point = state.get('player_world_position') or {}
        addon_sample = number(point.get('sample_time', model.addon_state.get("monotonic_time")))
        if addon_sample is not None and addon_sample >= nav["sampled_at"]:
            return  # newer addon position/heading wins; never restamp an old packet
        body = nav["body"]
        position = copy(point)
        position.update({k: body[k] for k in ("x", "y", "z")})
        position.update(coordinate_space="WORLD_YARDS", source="PACKET_CLIENT_MOVEMENT",
                        instance_id=context["instance_id"],
                        sample_time=nav["sampled_at"], z_known=True, z_observed=True,
                        z_source="PACKET_CLIENT_MOVEMENT")
        state["player_world_position"] = position  # instance/UI map remain addon-owned
        state["orientation"] = body["facing"]
