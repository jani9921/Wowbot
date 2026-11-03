"""Allowlisted wire-event schema. Unknown fields, raw bodies and chat are dropped."""
from __future__ import annotations

import math
import re
from .player_quest_log import EVENTS as QUEST_LOG_EVENTS, INVALIDATION_LAYOUT as QUEST_INVALIDATION_LAYOUT
from .own_inventory_codec import EVENTS as INVENTORY_EVENTS, LAYOUT as INVENTORY_LAYOUT
from .spell_cast import CAST_EVENTS, SPELL_LAYOUT

_FIELDS = {
    'OWN_INVENTORY_ROOTS': {'mover_guid','world_map_id','sample_kind','root_slots'},
    'OWN_INVENTORY_INVALIDATED': {'mover_guid','world_map_id'},
    'OWN_ITEM_UPDATE': {'mover_guid','world_map_id','sample_kind','item_guid','item_id','stack_count',
                        'container_guid','durability','max_durability','container_slots','num_slots','container_slots_delta'},
    'OWN_ITEM_REMOVED': {'mover_guid','world_map_id','item_guid','removal'},
    "SESSION_BASELINE": {"character_guid", "capture_epoch", "sequence", "world_map_id", "process_generation"},
    "OWN_UNIT_UPDATE": {"mover_guid", "world_map_id", "health", "max_health", "sample_kind"},
    "OWN_POWER_UPDATE": {'mover_guid', 'power_type', 'raw_power'},
    'OWN_PROFILE_UPDATE': {'mover_guid', 'world_map_id', 'sample_kind', 'race_id', 'class_id',
                           'player_class_id', 'power_type', 'level'},
    'OWN_QUEST_LOG_UPDATE': {'mover_guid', 'world_map_id', 'slots', 'sample_kind'},
    'OWN_QUEST_LOG_INVALIDATED': {'mover_guid', 'world_map_id'},
    'QUEST_DEFINITION': {'quest_id','definition'},
    'QUEST_DEFINITION_UNAVAILABLE': {'quest_id'},
    "QUEST_POI_UPDATE": {"quest_id", "blobs", "capture_timestamp"},
    "NETWORK_STREAM_CHUNK": {"sequence_start", "byte_count", "sha256"},
    "PACKET_OPCODE_OBSERVED": {"opcode_name", "byte_count", "sha256", "connection_index", "record_number"},
    "MOVEMENT_UPDATE": {"mover_guid", "movement_flags", "move_time", "x", "y", "z", "facing",
                        "coordinate_space", "source_opcode", "is_selected_client_movement", "sequence_index", "teleport",
                        "on_transport", "standing_on_game_object", "pitch", "flying", "can_fly", "adv_flying",
                        "falling", "fall_z_speed", "fall_xy_speed", "forward_velocity", "up_velocity"},
    "MAP_CHANGED": {"world_map_id", "x", "y", "z", "facing", "reason", "floor_difficulty", "floor_index",
                    "coordinate_space"},
    "QUEST_COMPLETED": {"quest_id"},
    "QUEST_UPDATED": {"quest_id", "failed", "timer_failed"},
    "QUEST_CREDIT_ADDED": {"quest_id", "object_id", "count", "required", "objective_type"},
    "COMBAT_STARTED": {"attacker_guid", "victim_guid"},
    "ATTACK_STOPPED": {"attacker_guid", "victim_guid", "now_dead"},
    "SPELL_CAST_FAILED": {"reason", "attack_swing"},
    "SPELL_CAST_STARTED": {"caster_guid", "cast_id", "spell_id", "cast_time_ms", "cast_flags", "cast_flags_ex", "cast_flags_ex2"},
    "SPELL_CAST_RELEASED": {"caster_guid", "cast_id", "spell_id", "server_cast_time_ms", "cast_flags", "cast_flags_ex", "cast_flags_ex2"},
    "SPELL_CAST_RESULT": {"caster_guid", "cast_id", "spell_id", "failure_code"},
    "SPELL_INTERRUPT_OBSERVED": {"caster_guid", "spell_id", "interrupt_spell_id"},
    "ENTITY_POSITION": {"entity_guid", "entry_id", "x", "y", "z", "coordinate_space", "source_opcode",
                        "move_time_ms", "destination_x", "destination_y", "destination_z"},
    "ENTITY_CREATED": {"entity_guid", "entry_id", "object_kind", "world_map_id", "x", "y", "z", "facing",
                       "coordinate_space", "position_source", "dynamic_flags", "npc_flags", "go_flags",
                       "go_state", "go_type", "quest_objective_id", "health", "max_health", "level", "faction_template", "unit_flags", "unit_flags2", "unit_flags3", "bounding_radius", "combat_reach", "target_guid", "summoned_by", "created_by"},
    # A creature's changed health/target/flags/reach (UnitData value update).
    "ENTITY_UNIT_UPDATE": {"entity_guid", "entry_id", "health", "max_health", "level", "faction_template", "unit_flags", "unit_flags2", "unit_flags3", "bounding_radius", "combat_reach", "target_guid", "summoned_by", "created_by"},
    "ENTITY_REMOVED": {"entity_guid", "entry_id", "removal"},
    "ENTITY_FLAGS": {"entity_guid", "entry_id", "dynamic_flags"},
    "QUEST_GIVER_STATUS": {"entity_guid", "entry_id", "status_flags", "quest_available", "reward_ready",
                           "quest_incomplete", "trivial_available", "future_quest"},
    # Scene playback (Skyriding courses and races, 2026-10-25): which client
    # scene package runs, and the own client's ring/finish trigger events.
    "SCENE_STARTED": {"scene_id", "playback_flags", "scene_instance_id", "package_id"},
    "SCENE_ENDED": {"scene_instance_id", "canceled"},
    "SCENE_EVENT": {"scene_instance_id", "scene_event"},
    "MOVEMENT_ROOT": {"mover_guid", "rooted"},
    # The gossip row picked at an NPC (what started a scene course).
    "GOSSIP_SELECTED": {"entity_guid", "entry_id", "gossip_menu_id", "gossip_option_id"},
}
ALLOWED_EVENTS = frozenset(_FIELDS)
# Each payload layout may only confirm the event kinds it was reviewed for.
ENTITY_EVENTS = frozenset({"ENTITY_POSITION", "QUEST_GIVER_STATUS", "ENTITY_CREATED",
                           "ENTITY_REMOVED", "ENTITY_FLAGS", "ENTITY_UNIT_UPDATE"})
SCENE_EVENTS = frozenset({"SCENE_STARTED", "SCENE_ENDED", "SCENE_EVENT"})
CAPTURE_70575_EVENTS = SCENE_EVENTS | {"MOVEMENT_ROOT", "GOSSIP_SELECTED", "QUEST_POI_UPDATE"}
_LAYOUT_EVENTS = {
    "WPP_12_1_REVIEWED_PREFIX_V1": frozenset(ALLOWED_EVENTS-ENTITY_EVENTS-CAPTURE_70575_EVENTS-CAST_EVENTS-INVENTORY_EVENTS-QUEST_LOG_EVENTS-{"SESSION_BASELINE", "OWN_UNIT_UPDATE", 'OWN_POWER_UPDATE', 'OWN_PROFILE_UPDATE', 'QUEST_DEFINITION', 'QUEST_DEFINITION_UNAVAILABLE'}),
    INVENTORY_LAYOUT: INVENTORY_EVENTS,
    'WPP_12_1_OWN_INVENTORY_REVIEWED_V2': INVENTORY_EVENTS,
    "WPP_12_1_SESSION_REVIEWED_V1": frozenset({"SESSION_BASELINE"}),
    "WPP_12_1_SESSION_REVIEWED_V2": frozenset({"SESSION_BASELINE"}),
    "WPP_12_1_OWN_UNIT_REVIEWED_V1": frozenset({'OWN_UNIT_UPDATE'}),
    "WPP_12_1_OWN_UNIT_REVIEWED_V2": frozenset({'OWN_UNIT_UPDATE'}),
    'WPP_12_1_POWER_REVIEWED_V1': frozenset({'OWN_POWER_UPDATE'}),
    'WPP_12_1_OWN_PROFILE_REVIEWED_V1': frozenset({'OWN_PROFILE_UPDATE'}),
    'WPP_12_1_QUEST_LOG_REVIEWED_V1': frozenset({'OWN_QUEST_LOG_UPDATE'}),
    'WPP_12_1_QUEST_LOG_REVIEWED_V2': frozenset({'OWN_QUEST_LOG_UPDATE'}),
    QUEST_INVALIDATION_LAYOUT: frozenset({'OWN_QUEST_LOG_INVALIDATED'}),
    'WPP_12_1_QUEST_DEFINITION_REVIEWED_V1': frozenset({'QUEST_DEFINITION','QUEST_DEFINITION_UNAVAILABLE'}),
    SPELL_LAYOUT: CAST_EVENTS,
    "RETAIL_70448_CAPTURE_VERIFIED_V1": ENTITY_EVENTS,
    "RETAIL_70575_CAPTURE_VERIFIED_V1": CAPTURE_70575_EVENTS,
}
DIAGNOSTIC_EVENTS = frozenset({"NETWORK_STREAM_CHUNK", "PACKET_OPCODE_OBSERVED"})
_PROVENANCE = frozenset({"producer", "container", "game_build", "locale", "semantic_ground_truth",
    "opcode_name", "opcode_defining_build", "opcode_table_sha256", "opcode_source_revision",
    "payload_layout", "payload_scope", "file_offset", "transport", "opcode_name_verified_for_exact_build", 'capture_epoch', 'semantic_record_id'})


def _safe_scalar(value):
    return (value is None or type(value) in {str, bool, int, float}) and not (
        isinstance(value, str) and len(value) > 160 or isinstance(value, (int, float))
        and (not math.isfinite(value) or abs(value) > 2**128))


def normalize_event(event):
    if not isinstance(event, dict) or event.get("schema") != "aipc.packet-event.v1":
        raise ValueError("unsupported packet-event schema")
    kind = event.get("event_type")
    if kind not in _FIELDS or event.get("semantic_status") not in {"UNKNOWN", "CONFIRMED"}:
        raise ValueError("unsupported packet event/status")
    if not re.fullmatch(r"[a-f0-9]{24}", str(event.get("event_id") or "")):
        raise ValueError("invalid packet event id")
    if type(event.get("selected_pid")) is not int or event["selected_pid"] <= 0:
        raise ValueError("selected PID must be positive")
    if event.get("direction") not in {"CLIENT_TO_SERVER", "SERVER_TO_CLIENT", "BN_SERVER_TO_CLIENT", "BN_CLIENT_TO_SERVER"}:
        raise ValueError("invalid direction")
    for key in ("timestamp", "confidence"):
        value = event.get(key)
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("invalid timestamp/confidence")
    if not 0 <= event["confidence"] <= 1:
        raise ValueError("invalid confidence")
    if not isinstance(event.get("flow_id"), str) or not 1 <= len(event["flow_id"]) <= 128:
        raise ValueError("invalid flow id")
    if event.get("opcode") is not None and (type(event["opcode"]) is not int or not 0 <= event["opcode"] < 2**32):
        raise ValueError("invalid opcode")
    body, provenance = event.get("payload"), event.get("provenance")
    if not isinstance(body, dict) or not isinstance(provenance, dict):
        raise ValueError("invalid packet body/provenance")
    safe_body = {k: v for k, v in body.items() if k in _FIELDS[kind] and _safe_scalar(v)}
    if kind in INVENTORY_EVENTS:
        if event['direction'] != 'SERVER_TO_CLIENT':
            raise ValueError('own inventory requires a server observation')
        from .own_inventory_codec import normalize_body
        safe_body = normalize_body(kind,body)
        if (safe_body.get('sample_kind')=='VALUES'
                and provenance.get('payload_layout')!='WPP_12_1_OWN_INVENTORY_REVIEWED_V2'):
            raise ValueError('inventory deltas require reviewed V2 layout')
    if kind in {'QUEST_DEFINITION','QUEST_DEFINITION_UNAVAILABLE'}:
        if type(body.get('quest_id')) is not int or not 0 < body['quest_id'] < 2**31:
            raise ValueError('quest definition response requires a quest ID')
        if event.get('direction') != 'SERVER_TO_CLIENT':
            raise ValueError('quest definitions require a server response')
        if kind == 'QUEST_DEFINITION':
            from .quest_definition import normalize_definition
            safe_body['definition'] = normalize_definition(body.get('definition'))
            if safe_body.get('quest_id') != safe_body['definition']['quest_id']:
                raise ValueError('quest definition identity mismatch')
    if kind == 'OWN_QUEST_LOG_UPDATE':
        from .player_quest_log import normalize_slots
        safe_body['slots'] = normalize_slots(body.get('slots'))
    if kind == "QUEST_POI_UPDATE":
        from .quest_poi import normalize_poi_blobs
        if type(body.get("quest_id")) is not int or not 0 < body["quest_id"] < 2**31:
            raise ValueError("quest POI requires a quest id")
        safe_body["blobs"] = normalize_poi_blobs(body.get("blobs"))
        captured = body.get('capture_timestamp')
        if ('capture_timestamp' in body
                and (type(captured) not in {int, float} or not math.isfinite(captured)
                     or not 0 < captured <= event['timestamp'])):
            raise ValueError('invalid quest POI capture time')
    safe_provenance = {k: v for k, v in provenance.items() if k in _PROVENANCE and _safe_scalar(v)}
    # Allowlisted *values* as well as keys: free text must not hide in an
    # opcode/reason/provenance field and then leak through the recorder.
    patterns = {"mover_guid": r"[A-Fa-f0-9]{32}", "attacker_guid": r"[A-Fa-f0-9]{32}",
        'item_guid': r'[A-Fa-f0-9]{32}', 'container_guid': r'[A-Fa-f0-9]{32}',
        "caster_guid": r"[A-Fa-f0-9]{32}", "cast_id": r"[A-Fa-f0-9]{32}",
        "character_guid": r"Player-\d{1,5}-[A-Fa-f0-9]{1,16}", "capture_epoch": r"[a-f0-9]{32}",
        "process_generation": r"[a-f0-9]{16}",
        'semantic_record_id': r'[a-f0-9]{24}',
        "target_guid": r"[A-Fa-f0-9]{32}", "summoned_by": r"[A-Fa-f0-9]{32}", "created_by": r"[A-Fa-f0-9]{32}",
        "victim_guid": r"[A-Fa-f0-9]{32}", "entity_guid": r"[A-Fa-f0-9]{32}", "sha256": r"[a-f0-9]{64}",
        "opcode_name": r"(?:CMSG|SMSG|MSG)_[A-Z0-9_]{1,120}",
        "source_opcode": r"(?:CMSG|SMSG|MSG)_[A-Z0-9_]{1,120}",
        "opcode_table_sha256": r"[a-f0-9]{64}", "opcode_source_revision": r"[a-f0-9]{40}",
        "locale": r"[a-zA-Z]{4}"}
    enums = {"reason": {"CANT_ATTACK", "OUT_OF_RANGE", "BAD_FACING", "DEAD_TARGET"},
        "coordinate_space": {"WORLD_YARDS"}, "producer": {"OpaqueStreamDecoder", "PktEventDecoder", "JsonLineSemanticDecoder"},
        "transport": {"TCP"}, "container": {"PKT_V3_1"},
        "payload_layout": set(_LAYOUT_EVENTS),
        "payload_scope": {"REVIEWED_FIELDS_ONLY_NOT_FULL_RECORD", "SANDBOX_TEST_ONLY"},
        "object_kind": {"UNIT", "GAMEOBJECT"}, "position_source": {"MOVEMENT", "STATIONARY"},
        "sample_kind": {'CREATE', 'VALUES'},
        "removal": {"DESTROYED", "OUT_OF_RANGE"}, "scene_event": {"CHECKPOINT", "RACE_COMPLETE"}}
    if kind == 'OWN_ITEM_REMOVED':
        enums['removal'] |= {'OWNER_CHANGED','UNREVIEWED_UPDATE'}
    for values in (safe_body, safe_provenance):
        for key, value in values.items():
            if value is None:
                continue
            if key in patterns and (not isinstance(value, str) or not re.fullmatch(patterns[key], value)):
                raise ValueError("invalid packet identifier")
            if key in enums and key != "reason" and value not in enums[key]:
                raise ValueError("unrecognized packet metadata")
            if key == "reason" and kind == "SPELL_CAST_FAILED" and value not in enums[key]:
                raise ValueError("unrecognized attack failure")
            if key == "reason" and kind == "MAP_CHANGED" and type(value) is not int:
                raise ValueError("world-change reason must be numeric")
            if isinstance(value, str) and key not in patterns and key not in enums:
                raise ValueError("free packet text is not allowed")
    if kind in DIAGNOSTIC_EVENTS and event["semantic_status"] != "UNKNOWN":
        raise ValueError("diagnostics are not game facts")
    if kind == "SESSION_BASELINE":
        if (set(safe_body) != _FIELDS[kind] or type(safe_body.get("sequence")) is not int
                or safe_body["sequence"] < 0 or event["direction"] != "SERVER_TO_CLIENT"):
            raise ValueError("incomplete session baseline")
        if safe_provenance.get('payload_layout')=='WPP_12_1_SESSION_REVIEWED_V2':
            from .builds import opcode_family
            family=opcode_family(safe_provenance.get('game_build'))
            if (family is None or family.defining_build!=70340
                    or safe_provenance.get('opcode_name')!='SMSG_UPDATE_OBJECT'):
                raise ValueError('own-create baseline requires reviewed instance connection proof')
    if kind == 'OWN_UNIT_UPDATE':
        guid = safe_body.get('mover_guid')
        for key in ('health', 'max_health'):
            if key in safe_body and (type(safe_body[key]) is not int or not 0 <= safe_body[key] < 2**40
                                    or key == 'max_health' and safe_body[key] == 0):
                raise ValueError('invalid own health field')
        if (not isinstance(guid, str) or int(guid[:16], 16) >> 58 != 2 or int(guid[16:], 16) == 0
                or event['direction'] != 'SERVER_TO_CLIENT' or 'world_map_id' not in safe_body
                or not {'health', 'max_health'} & safe_body.keys()
                or ('health' in safe_body and 'max_health' in safe_body and safe_body['health'] > safe_body['max_health'])):
            raise ValueError('own player unit delta requires health and context')
        if safe_body.get('sample_kind') == 'CREATE' and not {'health', 'max_health'}.issubset(safe_body):
            raise ValueError('own health baseline requires both fields')
        if safe_body.get('sample_kind') == 'CREATE' and safe_provenance.get('payload_layout') != 'WPP_12_1_OWN_UNIT_REVIEWED_V2':
            raise ValueError('own health baseline requires reviewed create layout')
    if kind in QUEST_LOG_EVENTS:
        guid = safe_body.get('mover_guid')
        if (not isinstance(guid, str) or int(guid[:16], 16) >> 58 != 2 or int(guid[16:], 16) == 0
                or event['direction'] != 'SERVER_TO_CLIENT' or 'world_map_id' not in safe_body):
            raise ValueError('quest log requires own identity and world context')
    if kind == 'OWN_QUEST_LOG_UPDATE':
        if safe_body.get('sample_kind') not in {None,'CREATE','VALUES'}:
            raise ValueError('invalid quest slot sample kind')
        if (safe_body.get('sample_kind') == 'CREATE'
                and safe_provenance.get('payload_layout') != 'WPP_12_1_QUEST_LOG_REVIEWED_V2'):
            raise ValueError('quest create baseline requires reviewed create layout')
        if safe_body.get('sample_kind') == 'CREATE':
            slots = safe_body['slots']
            if (len(slots) != 175 or any(any(v is None for v in row[1:6])
                    or any(v is None for v in row[6]) for row in slots)):
                raise ValueError('quest create baseline requires every complete slot')
    if kind == 'OWN_PROFILE_UPDATE':
        guid = safe_body.get('mover_guid')
        if (not isinstance(guid, str) or int(guid[:16], 16) >> 58 != 2 or int(guid[16:], 16) == 0
                or event['direction'] != 'SERVER_TO_CLIENT' or 'world_map_id' not in safe_body
                or safe_body.get('sample_kind') not in {'CREATE', 'VALUES'}
                or not {'race_id', 'class_id', 'player_class_id', 'power_type', 'level'} & safe_body.keys()):
            raise ValueError('own profile requires identity, context and reviewed fields')
        for key in ('race_id', 'class_id', 'player_class_id', 'power_type'):
            if key in safe_body and (type(safe_body[key]) is not int or not 0 <= safe_body[key] <= 255):
                raise ValueError('invalid own profile enum')
    if kind == 'OWN_POWER_UPDATE':
        guid = safe_body.get('mover_guid')
        if (set(safe_body) != _FIELDS[kind] or not isinstance(guid, str)
                or int(guid[:16], 16) >> 58 != 2 or int(guid[16:], 16) == 0
                or event['direction'] != 'SERVER_TO_CLIENT'
                or type(safe_body.get('power_type')) is not int or not 0 <= safe_body['power_type'] <= 255
                or type(safe_body.get('raw_power')) is not int or not -2**31 <= safe_body['raw_power'] < 2**31):
            raise ValueError('invalid own power update')
    if kind in CAST_EVENTS:
        guid = safe_body.get('caster_guid')
        required = ({'caster_guid', 'spell_id', 'interrupt_spell_id'} if kind == 'SPELL_INTERRUPT_OBSERVED'
                    else {'caster_guid', 'spell_id', 'cast_id'})
        if (not required.issubset(safe_body) or not isinstance(guid, str)
                or event['direction'] != 'SERVER_TO_CLIENT'
                or int(guid[:16], 16) >> 58 not in {8, 9}
                or int(guid[16:], 16) == 0):
            raise ValueError('NPC spell identity required')
        if 'cast_id' in safe_body and (not isinstance(safe_body['cast_id'], str) or int(safe_body['cast_id'], 16) == 0):
            raise ValueError('nonzero cast id required')
        for key in ('spell_id', 'interrupt_spell_id'):
            if key in safe_body and (type(safe_body[key]) is not int or not 0 < safe_body[key] < 2**31):
                raise ValueError('invalid spell id')
        for key in ('cast_time_ms', 'server_cast_time_ms', 'cast_flags', 'cast_flags_ex', 'cast_flags_ex2', 'failure_code'):
            if key in safe_body and (type(safe_body[key]) is not int or not 0 <= safe_body[key] < 2**32):
                raise ValueError('invalid cast field')
        if kind == 'SPELL_CAST_STARTED' and ('cast_time_ms' not in safe_body or safe_body['cast_time_ms'] > 600_000):
            raise ValueError('cast duration required')
        if kind == 'SPELL_CAST_RELEASED' and 'server_cast_time_ms' not in safe_body:
            raise ValueError('server cast clock required')
        if kind == 'SPELL_CAST_RESULT' and ('failure_code' not in safe_body or safe_body['failure_code'] >= 2**15):
            raise ValueError('cast result required')
    for key in ("x", "y", "z", "facing"):
        if key in safe_body and (type(safe_body[key]) not in {int, float}
                or abs(safe_body[key]) > (100. if key == "facing" else 100_000.)):
            raise ValueError("invalid position")
    if kind in ENTITY_EVENTS or kind == "GOSSIP_SELECTED":
        # Creature/vehicle/game-object GUIDs only; a player GUID (other
        # players, the own character) never enters through these kinds.
        guid = safe_body.get("entity_guid")
        if not isinstance(guid, str) or (int(guid[:16], 16) >> 58) not in {8, 9, 11}:
            raise ValueError("entity facts require a creature/vehicle/game-object GUID")
        if type(safe_body.get("entry_id")) is not int or not 0 < safe_body["entry_id"] < 2**23:
            raise ValueError("invalid entity entry")
    for key, bits in (("dynamic_flags", 32), ("npc_flags", 64), ("go_flags", 32), ("move_time_ms", 32),
                      ("quest_objective_id", 32), ("world_map_id", 16)):
        if key in safe_body and (type(safe_body[key]) is not int or not 0 <= safe_body[key] < 2**bits):
            raise ValueError("invalid entity field")
    for key, limit in (("health", 2**40), ("max_health", 2**40), ("level", 256), ("faction_template", 2**16),
                       ("unit_flags", 2**32), ("unit_flags2", 2**32), ("unit_flags3", 2**32)):
        if key in safe_body and (type(safe_body[key]) is not int or not 0 <= safe_body[key] < limit):
            raise ValueError("invalid unit field")
    for key in ("bounding_radius", "combat_reach"):
        if key in safe_body and (type(safe_body[key]) not in {int, float} or not 0 <= safe_body[key] <= 60):
            raise ValueError("invalid unit size")
    for key in ("go_state", "go_type"):
        if key in safe_body and (type(safe_body[key]) is not int or not -128 <= safe_body[key] < 128):
            raise ValueError("invalid game-object field")
    for key in ("destination_x", "destination_y", "destination_z"):
        if key in safe_body and (type(safe_body[key]) not in {int, float} or not math.isfinite(safe_body[key])
                                 or abs(safe_body[key]) > 100_000.):
            raise ValueError("invalid destination")
    if "status_flags" in safe_body and (type(safe_body["status_flags"]) is not int
            or not 0 <= safe_body["status_flags"] < 2**64):
        raise ValueError("invalid quest-giver status")
    if "quest_id" in safe_body and (type(safe_body["quest_id"]) is not int or not 0 < safe_body["quest_id"] < 2**32):
        raise ValueError("invalid quest id")
    for key, bits in (("scene_instance_id", 32), ("package_id", 20), ("playback_flags", 32),
                      ("gossip_menu_id", 32), ("gossip_option_id", 31)):
        if key in safe_body and (type(safe_body[key]) is not int or not 0 <= safe_body[key] < 2**bits):
            raise ValueError("invalid scene field")
    return {key: event.get(key) for key in ("event_id", "schema", "timestamp", "selected_pid", "flow_id",
        "direction", "event_type", "semantic_status", "opcode", "confidence")} | {
        "payload": safe_body, "provenance": safe_provenance}


def verified_semantics(event):
    from .builds import opcode_family
    source = event.get("provenance") or {}
    family = opcode_family(source.get("game_build"))
    return (event.get("semantic_status") == "CONFIRMED" and event.get("confidence") == 1.
            and (event.get("event_type") != "QUEST_POI_UPDATE" or source.get("semantic_ground_truth") is True)
            and source.get("producer") == "PktEventDecoder" and source.get("container") == "PKT_V3_1"
            and family is not None
            and (event.get('event_type') not in INVENTORY_EVENTS | QUEST_LOG_EVENTS | {'OWN_UNIT_UPDATE', 'OWN_PROFILE_UPDATE'}
                 or family.defining_build == 70340)
            and source.get("opcode_defining_build") == family.defining_build
            and source.get("opcode_table_sha256") == family.sha256
            and event.get("event_type") in _LAYOUT_EVENTS.get(source.get("payload_layout"), ()))
