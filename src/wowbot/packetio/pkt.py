from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
import os
import struct
import time
from typing import Iterable, Iterator

from .models import AgentPacketEvent, FlowDirection
from .builds import (OPCODE_DEFINING_BUILD, WPP_REVISION, compatible_opcode_build, opcode_family)
from .update_object import UpdateLayoutError, decode_monster_move, decode_update_object


PKT_V3_1 = 0x0301
_SMSG = 0x47534D53
_CMSG = 0x47534D43
_BN_SERVER = 0x4E425F53
_BN_CLIENT = 0x4E425F43


class PktFormatError(ValueError):
    pass


@dataclass(frozen=True)
class PktHeader:
    version: int
    sniffer_id: int
    game_build: int
    locale: str
    start_unix_seconds: int
    start_tick: int
    optional_data: bytes
    header_size: int


@dataclass(frozen=True)
class PktRecord:
    record_number: int
    direction: str
    connection_index: int
    tick_count: int
    timestamp: float
    opcode: int
    payload: bytes
    optional_data: bytes
    file_offset: int


class PktV31StreamParser:
    """Incremental PKT 3.1 parser compatible with WPP BinaryPacketReader.

    Incomplete trailing records stay buffered, which makes the parser suitable
    for following a packet file while the sniffer is still writing it.
    """

    def __init__(self, *, max_record_bytes: int = 32 * 1024 * 1024):
        self.max_record_bytes = int(max_record_bytes)
        self.header: PktHeader | None = None
        self._buffer = bytearray()
        self._stream_offset = 0
        self._record_number = 0
        self._cursor = 0

    def reset(self) -> None:
        self.header = None
        self._buffer.clear()
        self._stream_offset = 0
        self._record_number = 0
        self._cursor = 0

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)-self._cursor

    def feed(self, data: bytes) -> list[PktRecord]:
        if len(data) > self.max_record_bytes*2:
            raise PktFormatError("PKT input chunk exceeds bounded parser budget")
        self._buffer.extend(data)
        output: list[PktRecord] = []
        if self.header is None and not self._parse_header():
            return output
        while True:
            record = self._parse_record()
            if record is None:
                break
            output.append(record)
        if self._cursor:
            del self._buffer[:self._cursor]  # one compacting copy per feed, not per record
            self._cursor = 0
        return output

    def _consume(self, count: int) -> bytes:
        value = bytes(self._buffer[self._cursor:self._cursor+count])
        self._cursor += count
        self._stream_offset += count
        return value

    def _parse_header(self) -> bool:
        fixed_size = 66
        if self.buffered_bytes < fixed_size:
            return False
        if self._buffer[:3] != b"PKT":
            raise PktFormatError("missing PKT signature")
        version = struct.unpack_from("<H", self._buffer, 3)[0]
        if version != PKT_V3_1:
            raise PktFormatError(f"unsupported PKT version 0x{version:04X}; expected 3.1")
        optional_length = struct.unpack_from("<i", self._buffer, 62)[0]
        if optional_length < 0 or optional_length > self.max_record_bytes:
            raise PktFormatError(f"invalid PKT optional header length {optional_length}")
        total = fixed_size + optional_length
        if len(self._buffer) < total:
            return False
        raw = self._consume(total)
        self.header = PktHeader(
            version=version,
            sniffer_id=raw[5],
            game_build=struct.unpack_from("<I", raw, 6)[0],
            locale=raw[10:14].decode("ascii", errors="replace"),
            start_unix_seconds=struct.unpack_from("<I", raw, 54)[0],
            start_tick=struct.unpack_from("<I", raw, 58)[0],
            optional_data=raw[66:],
            header_size=total,
        )
        return True

    def _parse_record(self) -> PktRecord | None:
        fixed_size = 20
        if self.buffered_bytes < fixed_size:
            return None
        magic, connection, tick, optional_size, packet_size = struct.unpack_from("<IiIii", self._buffer, self._cursor)
        if optional_size < 0 or packet_size < 4:
            raise PktFormatError(f"invalid PKT record sizes optional={optional_size}, packet={packet_size}")
        total = fixed_size + optional_size + packet_size
        if total > self.max_record_bytes:
            raise PktFormatError(f"PKT record exceeds limit: {total} bytes")
        if self.buffered_bytes < total:
            return None
        offset = self._stream_offset
        raw = self._consume(total)
        optional = raw[fixed_size:fixed_size + optional_size]
        packet = raw[fixed_size + optional_size:]
        opcode = struct.unpack_from("<i", packet, 0)[0]
        if magic == _SMSG:
            direction = FlowDirection.SERVER_TO_CLIENT.value
        elif magic == _CMSG:
            direction = FlowDirection.CLIENT_TO_SERVER.value
        elif magic == _BN_SERVER:
            direction = "BN_SERVER_TO_CLIENT"
        elif magic == _BN_CLIENT:
            direction = "BN_CLIENT_TO_SERVER"
        else:
            raise PktFormatError(f"invalid PKT direction marker 0x{magic:08X} at {offset}")
        header = self.header
        assert header is not None
        timestamp = header.start_unix_seconds + ((tick - header.start_tick) & 0xFFFFFFFF) / 1000.0
        if header.sniffer_id in (0x15, 0x16) and len(optional) >= 8:
            timestamp = struct.unpack_from("<d", optional, 0)[0] / 1000.0
        if not math.isfinite(timestamp) or timestamp < 0:
            raise PktFormatError("invalid PKT timestamp")
        result = PktRecord(
            record_number=self._record_number,
            direction=direction,
            connection_index=connection,
            tick_count=tick,
            timestamp=timestamp,
            opcode=opcode,
            payload=packet[4:],
            optional_data=optional,
            file_offset=offset,
        )
        self._record_number += 1
        return result


class OpcodeManifest:
    """Exact-build opcode-name lookup. Nearby builds are never substituted."""

    def __init__(self, game_build: int, entries: dict[tuple[str, int], str], *, verified_source=False):
        self.game_build = int(game_build)
        self._entries = dict(entries)
        self.verified_source = bool(verified_source)

    @classmethod
    def reviewed(cls, game_build=OPCODE_DEFINING_BUILD):
        from .opcodes_12_1 import FAMILY_OPCODES, REVIEWED_OPCODES
        family = opcode_family(game_build)
        if family is None:
            raise PktFormatError("unsupported game build: no reviewed opcode family")
        names = {**REVIEWED_OPCODES, **FAMILY_OPCODES.get(family.defining_build, {})}
        return cls(family.defining_build, {
            (FlowDirection.CLIENT_TO_SERVER.value if name.startswith("CMSG_")
             else FlowDirection.SERVER_TO_CLIENT.value, opcode): name
            for name, opcode in names.items()}, verified_source=True)

    def name(self, direction: str, opcode: int) -> str | None:
        return self._entries.get((str(direction), int(opcode)))

    def opcode(self, direction: str, name: str) -> int | None:
        wanted = str(name)
        for (entry_direction, opcode), entry_name in self._entries.items():
            if entry_direction == str(direction) and entry_name == wanted:
                return opcode
        return None

    @classmethod
    def from_wpp_csharp(cls, path: Path, *, game_build: int) -> "OpcodeManifest":
        import re

        text = Path(path).read_text(encoding="utf-8-sig")
        namespace = re.search(r"namespace\s+WowPacketParser\.Enums\.Version\.(V\d+_\d+_\d+_\d+)\b", text)
        digest = hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        family = opcode_family(game_build)
        if (family is None or namespace is None or namespace.group(1) != family.namespace
                or digest != family.sha256):
            raise PktFormatError("opcode table is not the pinned verified 12.1 build family")
        current: str | None = None
        entries: dict[tuple[str, int], str] = {}
        for line in text.splitlines():
            if "private static readonly BiDictionary<Opcode, int> ClientOpcodes" in line:
                current = FlowDirection.CLIENT_TO_SERVER.value
            elif "private static readonly BiDictionary<Opcode, int> ServerOpcodes" in line:
                current = FlowDirection.SERVER_TO_CLIENT.value
            elif "private static readonly BiDictionary<Opcode, int> MiscOpcodes" in line:
                current = "MISC"
            match = re.search(r"\{\s*Opcode\.([A-Z0-9_]+),\s*0x([0-9A-Fa-f]+)\s*\}", line)
            if current and match:
                entries[(current, int(match.group(2), 16))] = match.group(1)
        if not entries:
            raise PktFormatError(f"no opcode mappings found in {path}")
        return cls(family.defining_build, entries, verified_source=True)


class PktEventDecoder:
    """Converts framed records to safe observations, not guessed game facts."""

    def __init__(self, *, selected_pid: int, header: PktHeader, manifest: OpcodeManifest | None = None,
                 include_payload_digest: bool = True, process_generation: str | None = None):
        self.selected_pid = int(selected_pid)
        self.header = header
        self.manifest = manifest
        self.include_payload_digest = bool(include_payload_digest)
        # Entity fragment ids per GUID, learned from create blocks: a values
        # update's changed-fragment bitmask is only readable with them.
        self.entity_fragments = {}
        import secrets
        self.capture_epoch = secrets.token_hex(16)
        self.process_generation = process_generation
        from .session_bootstrap import SessionHandshake
        self._handshake = SessionHandshake()
        self._verified_player_guids = {}
        self._owned_items = {}
        self.collection_decode_failures = 0
        if self.selected_pid <= 0:
            raise PktFormatError("positive selected PID required")
        if manifest is not None and not compatible_opcode_build(manifest.game_build, header.game_build):
            raise PktFormatError(
                f"opcode manifest build {manifest.game_build} does not match PKT build {header.game_build}"
            )

    def decode(self, record: PktRecord) -> AgentPacketEvent:
        """Return the safe opcode observation retained for audit/replay."""
        name = self.manifest.name(record.direction, record.opcode) if self.manifest else None
        payload = {
            "opcode_name": name,
            "byte_count": len(record.payload),
            "connection_index": record.connection_index,
            "record_number": record.record_number,
        }
        if self.include_payload_digest:
            payload["sha256"] = hashlib.sha256(record.payload).hexdigest()
        return AgentPacketEvent.create(
            pid=self.selected_pid,
            flow_id=f"pkt:{self.header.game_build}:{record.connection_index}",
            direction=record.direction,
            event_type="PACKET_OPCODE_OBSERVED",
            timestamp=record.timestamp,
            semantic_status="UNKNOWN",
            opcode=record.opcode,
            payload=payload,
            provenance={
                "producer": "PktEventDecoder",
                "container": "PKT_V3_1",
                "game_build": self.header.game_build,
                "locale": self.header.locale,
                "semantic_ground_truth": False,
                "opcode_name_verified_for_exact_build": bool(name and self.manifest.verified_source),
                "file_offset": record.file_offset,
            },
            confidence=1.0 if name else 0.0,
        )

    def decode_all(self, record: PktRecord) -> list[AgentPacketEvent]:
        observed = self.decode(record)
        name = observed.payload.get("opcode_name")
        return [observed, *(self._decode_semantic(record, name) if name else ())]

    def _decode_semantic(self, record: PktRecord, name: str) -> list[AgentPacketEvent]:
        family = opcode_family(self.header.game_build)
        if (not self.manifest or not self.manifest.verified_source
                or family is None or self.manifest.game_build != family.defining_build):
            return []
        prefix = []
        try:
            if name in {"CMSG_PLAYER_LOGIN", "SMSG_LOGIN_VERIFY_WORLD"}:
                return self._session_events(record, name, family)
            if name == 'SMSG_POWER_UPDATE':
                from .own_power import decode_power
                decoded = (decode_power(_Cursor(record.payload), self._verified_player_guids.get(record.connection_index))
                           if record.direction == FlowDirection.SERVER_TO_CLIENT.value else [])
                return [self._semantic_event(record, name, family, kind, body) for kind, body in decoded]
            if name == 'SMSG_QUERY_QUEST_INFO_RESPONSE':
                from .quest_definition import decode_definition
                if record.direction != FlowDirection.SERVER_TO_CLIENT.value:
                    return []
                kind, body = decode_definition(record.payload)
                return [self._semantic_event(record, name, family, kind, body)]
            from .spell_cast import SPELL_OPCODES, decode_spell
            if name in SPELL_OPCODES:
                decoded = (decode_spell(name, _Cursor(record.payload))
                           if record.direction == FlowDirection.SERVER_TO_CLIENT.value else [])
                return [self._semantic_event(record, name, family, kind, body) for kind, body in decoded]
            if record.direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_UPDATE_OBJECT":
                own = self._verified_player_guids.get(record.connection_index) if family.defining_build == 70340 else None
                if own is None and family.defining_build == 70340 and self._handshake.needs_create(record):
                    # First read public identity/movement flags only. A private
                    # own prefix is allowed only after exact login GUID proof.
                    rows = decode_update_object(record.payload,{})
                    binding = self._handshake.identify_create(rows,record)
                    if binding is not None and self.process_generation is not None:
                        prefix.append(self._session_baseline(record,name,family,binding,
                                      'WPP_12_1_SESSION_REVIEWED_V2'))
                        own = binding.character_guid
                owned = self._owned_items.setdefault(record.connection_index,{}) if own is not None else None
                decoded = _decode_update_object(record.payload, self.entity_fragments,
                                               own_character_guid=own, owned_items=owned)
            elif record.direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_QUEST_POI_QUERY_RESPONSE":
                if family.defining_build != 70340:
                    return []  # payload capture checked for the explicit 12.1.5 family only
                from .quest_poi import decode_quest_pois
                decoded = decode_quest_pois(record.payload)
            else:
                decoded = _decode_verified_payloads(name, record.direction, record.payload)
        except (ValueError, UpdateLayoutError, struct.error, OverflowError):
            if name == 'SMSG_UPDATE_OBJECT':
                self.collection_decode_failures += 1
                self._owned_items.clear()
                self.entity_fragments.clear()
            return prefix  # an independently proved identity survives a failed private prefix
        return [*prefix, *[self._semantic_event(record, name, family, event_type, payload)
                for event_type, payload in decoded]]

    def _session_events(self, record, name, family):
        """WPP CharacterHandler V11.2.7 + MovementHandler login-verify.

        Login intent alone cannot establish a world. A different instance
        connection also needs its exact ThisIsYou ActivePlayer CREATE proof.
        This layout has offline tests, not new live validation.
        """
        cursor = _Cursor(record.payload)
        if name == "CMSG_PLAYER_LOGIN" and record.direction == FlowDirection.CLIENT_TO_SERVER.value:
            from .session_bootstrap import SessionHandshake
            import secrets
            # A new attempt is a lifecycle boundary, even for the same GUID.
            # No old connection, item owner, fragments or replay may survive.
            self._handshake = SessionHandshake()
            self.capture_epoch = secrets.token_hex(16)
            self._verified_player_guids.clear()
            self._owned_items.clear()
            self.entity_fragments.clear()
            self.collection_decode_failures = 0
            guid = cursor.packed_guid128()
            cursor.f32()  # FarClip is not exported
            bits = cursor.u8()
            _exact_end(cursor)
            high, low = int(guid[:16], 16), int(guid[16:], 16)
            if high >> 58 != 2 or low == 0 or bits & 0x7f:
                return []
            self._handshake.begin(f"Player-{(high >> 42) & 0x1FFF}-{low:08X}",record)
            return []
        if name != "SMSG_LOGIN_VERIFY_WORLD" or record.direction != FlowDirection.SERVER_TO_CLIENT.value:
            return []
        map_id = cursor.i32()
        position = tuple(cursor.f32() for _ in range(4))
        cursor.u32()  # reason is not identity
        _exact_end(cursor)
        if (self.process_generation is None or not 0 <= map_id < 2**16
                or not _valid_position(*position)):
            return []
        binding = self._handshake.verify_world(map_id,record)
        return ([self._session_baseline(record,name,family,binding,'WPP_12_1_SESSION_REVIEWED_V1')]
                if binding is not None else [])

    def _session_baseline(self, record, name, family, binding, layout):
        event = self._semantic_event(record, name, family, "SESSION_BASELINE", {
            "character_guid": binding.character_guid, "capture_epoch": self.capture_epoch,
            "sequence": record.record_number, "world_map_id": binding.world_map_id,
            "process_generation": self.process_generation})
        self._verified_player_guids = {binding.connection_index:binding.character_guid}
        from dataclasses import replace
        return replace(event, provenance={**event.provenance,"payload_layout":layout})

    def _semantic_event(self, record, name, family, event_type, payload) -> AgentPacketEvent:
        return AgentPacketEvent.create(
            pid=self.selected_pid,
            flow_id=f"pkt:{self.header.game_build}:{record.connection_index}",
            direction=record.direction,
            event_type=event_type,
            timestamp=record.timestamp,
            semantic_status="CONFIRMED",
            opcode=record.opcode,
            payload=payload,
            provenance={
                "producer": "PktEventDecoder",
                "container": "PKT_V3_1",
                "game_build": self.header.game_build,
                "opcode_name": name,
                "opcode_defining_build": self.manifest.game_build,
                "opcode_table_sha256": family.sha256,
                "opcode_source_revision": WPP_REVISION,
                'capture_epoch': self.capture_epoch,
                "payload_layout": ("WPP_12_1_QUEST_DEFINITION_REVIEWED_V1" if event_type in {'QUEST_DEFINITION','QUEST_DEFINITION_UNAVAILABLE'} else
                                   ("WPP_12_1_OWN_INVENTORY_REVIEWED_V2" if payload.get('sample_kind')=='VALUES'
                                    else "WPP_12_1_OWN_INVENTORY_REVIEWED_V1") if event_type in {'OWN_INVENTORY_ROOTS','OWN_INVENTORY_INVALIDATED','OWN_ITEM_UPDATE','OWN_ITEM_REMOVED'} else
                                   'WPP_12_1_QUEST_LOG_INVALIDATION_V1' if event_type == 'OWN_QUEST_LOG_INVALIDATED' else
                                   ("WPP_12_1_QUEST_LOG_REVIEWED_V2" if payload.get('sample_kind') == 'CREATE'
                                    else "WPP_12_1_QUEST_LOG_REVIEWED_V1") if event_type == 'OWN_QUEST_LOG_UPDATE' else
                                   "WPP_12_1_OWN_PROFILE_REVIEWED_V1" if event_type == 'OWN_PROFILE_UPDATE' else
                                   "WPP_12_1_POWER_REVIEWED_V1" if event_type == 'OWN_POWER_UPDATE' else
                                   "WPP_12_1_OWN_UNIT_REVIEWED_V2" if event_type == 'OWN_UNIT_UPDATE' else
                                   PAYLOAD_LAYOUTS.get(name, "WPP_12_1_REVIEWED_PREFIX_V1")),
                "payload_scope": "REVIEWED_FIELDS_ONLY_NOT_FULL_RECORD",
                "semantic_ground_truth": True,
                "file_offset": record.file_offset,
            },
            confidence=1.0,
        )


class _Cursor:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.offset + count > len(self.data):
            raise PktFormatError("truncated packet payload")
        value = self.data[self.offset:self.offset + count]
        self.offset += count
        return value

    def u8(self) -> int:
        return self.take(1)[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.take(4))[0]

    def packed_guid128(self) -> str:
        low_mask, high_mask = self.u8(), self.u8()
        low = self._packed_u64(low_mask)
        high = self._packed_u64(high_mask)
        return f"{high:016X}{low:016X}"

    def _packed_u64(self, mask: int) -> int:
        value = 0
        for index in range(8):
            if mask & (1 << index):
                value |= self.u8() << (index * 8)
        return value


_CLIENT_MOVEMENT_NAMES = frozenset({
    "CMSG_MOVE_CHANGE_TRANSPORT", "CMSG_MOVE_DISMISS_VEHICLE", "CMSG_MOVE_FALL_LAND",
    "CMSG_MOVE_FALL_RESET", "CMSG_MOVE_HEARTBEAT", "CMSG_MOVE_JUMP",
    "CMSG_MOVE_REMOVE_MOVEMENT_FORCES", "CMSG_MOVE_SET_FACING",
    "CMSG_MOVE_SET_FACING_HEARTBEAT", "CMSG_MOVE_SET_FLY", "CMSG_MOVE_SET_PITCH",
    "CMSG_MOVE_SET_RUN_MODE", "CMSG_MOVE_SET_WALK_MODE", "CMSG_MOVE_START_ASCEND",
    "CMSG_MOVE_START_BACKWARD", "CMSG_MOVE_START_DESCEND", "CMSG_MOVE_START_FORWARD",
    "CMSG_MOVE_START_PITCH_DOWN", "CMSG_MOVE_START_PITCH_UP", "CMSG_MOVE_START_SWIM",
    "CMSG_MOVE_START_TURN_LEFT", "CMSG_MOVE_START_TURN_RIGHT",
    "CMSG_MOVE_START_STRAFE_LEFT", "CMSG_MOVE_START_STRAFE_RIGHT", "CMSG_MOVE_STOP",
    "CMSG_MOVE_STOP_ASCEND", "CMSG_MOVE_STOP_PITCH", "CMSG_MOVE_STOP_STRAFE",
    "CMSG_MOVE_STOP_SWIM", "CMSG_MOVE_STOP_TURN", "CMSG_MOVE_DOUBLE_JUMP",
    "CMSG_MOVE_SET_ADV_FLY", "CMSG_MOVE_START_DRIVE_FORWARD",
})


# Retail 12 MovementFlags (WPP Enums.v12.MovementFlag, 2026-10-23 tree).
MOVE_FALLING = 0x800
MOVE_CAN_FLY = 0x800000
MOVE_FLYING = 0x1000000
MOVE_ADV_FLYING = 0x400000000000


def _movement_tail(cursor, optional_flags: bytes) -> dict:
    """Skyriding speeds from the optional movement blocks (WPP
    ReadMovementStats1210): standing-on GUID, transport, fall, inertia,
    AdvFlying (ForwardVelocity, UpVelocity), drive status -- in this order.

    User 2026-10-25 (Skyriding lessons 65118/65120/65133): gliding needs the
    measured forward/up speed; the addon cannot read either."""
    first, second = optional_flags[0], optional_flags[1]
    has_standing, has_transport, has_fall = bool(first & 0x80), bool(first & 0x40), bool(first & 0x20)
    has_inertia, has_adv_flying, has_drive = bool(first & 0x02), bool(first & 0x01), bool(second & 0x80)
    result = {}
    if has_standing:
        cursor.packed_guid128()
    if has_transport:
        cursor.packed_guid128()
        cursor.take(16 + 1 + 4)                 # offset xyzo, seat, move time
        bits = cursor.take(1)[0]
        if bits & 0x80:
            cursor.u32()                        # PrevMoveTime
        if bits & 0x40:
            cursor.u32()                        # VehicleRecID
    if has_fall:
        cursor.u32()                            # FallTime
        z_speed = cursor.f32()
        if math.isfinite(z_speed):
            result["fall_z_speed"] = z_speed
        if cursor.take(1)[0] & 0x80:
            cursor.take(8)                      # sin/cos of the fall direction
            xy_speed = cursor.f32()
            if math.isfinite(xy_speed):
                result["fall_xy_speed"] = xy_speed
    if has_inertia:
        cursor.take(4 + 12 + 4)                 # ID, Force, Lifetime
    if has_adv_flying:
        forward, up = cursor.f32(), cursor.f32()
        if math.isfinite(forward) and math.isfinite(up) and abs(forward) < 500 and abs(up) < 500:
            result.update(forward_velocity=forward, up_velocity=up)
    del has_drive                               # nothing of it is used
    return result


def _valid_position(x: float, y: float, z: float, facing: float) -> bool:
    import math
    return all(math.isfinite(value) for value in (x, y, z, facing)) and all(
        abs(value) <= 100_000.0 for value in (x, y, z)
    ) and abs(facing) <= 100.0


# Field order from WPP/TrinityCore, then checked byte-exact on a real Retail
# 70448 Ymir capture (2026-10-19), not a WPP prefix review. Only these
# opcodes carry this provenance.  Re-checked on a user-run 70575 capture
# (2026-10-25: 154 creates, all TDB templates, 127/148 within 30 yd of a TDB
# spawn); the label names the layout, provenance.game_build the build.
CAPTURE_LAYOUT = "RETAIL_70448_CAPTURE_VERIFIED_V1"
PAYLOAD_LAYOUTS = {name: CAPTURE_LAYOUT for name in (
    "SMSG_ON_MONSTER_MOVE", "SMSG_QUEST_GIVER_STATUS", "SMSG_QUEST_GIVER_STATUS_MULTIPLE",
    "SMSG_UPDATE_OBJECT")}
# Scene playback (WPP V11_0_0 SceneHandler) and the own root/unroot (WPP
# V6_0_2 HandleMovementIndex), checked on two user-run 70575 captures
# (2026-10-25 17:26 and 20:46: 3 plays, 2 cancels, 9 trigger events, 4 roots).
# Quest POIs: all 9 complete responses in the user-run 70575 capture of
# 2026-10-28 15:56 were decoded to exact record end (including XYZ).
CAPTURE_70575_LAYOUT = "RETAIL_70575_CAPTURE_VERIFIED_V1"
PAYLOAD_LAYOUTS.update({name: CAPTURE_70575_LAYOUT for name in (
    "SMSG_PLAY_SCENE", "SMSG_CANCEL_SCENE", "CMSG_SCENE_TRIGGER_EVENT",
    "CMSG_SCENE_PLAYBACK_COMPLETE", "CMSG_SCENE_PLAYBACK_CANCELED",
    "SMSG_MOVE_ROOT", "SMSG_MOVE_UNROOT", "CMSG_GOSSIP_SELECT_OPTION", "SMSG_QUEST_POI_QUERY_RESPONSE")})
from .spell_cast import SPELL_OPCODES, SPELL_LAYOUT
PAYLOAD_LAYOUTS.update({name: SPELL_LAYOUT for name in SPELL_OPCODES})

# WowGuid128 high type (high >> 58). Players and pets never become entity
# facts: other players' positions are personal data and a pet's owner is not
# known from these packets. SMSG_MOVE_UPDATE (player movers only) is skipped.
# HighGuid 7 Conversation (WPP HighGuidType703), REV4 P8.4: a scripted
# conversation exists while its object does; no line or actor field is read.
_ENTITY_KINDS = {7: "CONVERSATION", 8: "CREATURE", 9: "VEHICLE", 11: "GAMEOBJECT"}

# TrinityCore QuestGiverStatus (uint64) bit groups.
_QG_FUTURE = 0x1E                      # Future, Future{Journey,Legendary,Important}Quest
_QG_TRIVIAL = 0x1FE0                   # Trivial* (gray low-level markers)
_QG_AVAILABLE = (1 << 33)-(1 << 21)    # QuestAccountCompleted .. ImportantQuest ("!")
# Blizzard's plain "*Reward" bits are the grey "?" of a quest still in progress
# (TrinityCore sets them for QUEST_STATUS_INCOMPLETE); the yellow, turn-in-ready
# "?" is RepeatableTurnin or *RewardComplete(No)POI. Live 2026-10-19 14:47:
# Henry Garrick 0x40000000000 (turn-in) -> 0x10000000 (new "!") ->
# 0x10020000 (one more "!" + one taken) -> 0x20000 (only the taken one left).
_QG_INCOMPLETE = 0xFE000                # Reward .. ImportantReward (grey "?")
_QG_REWARD = 0x100000 | ((1 << 47)-(1 << 33))  # RepeatableTurnin, *RewardComplete* (yellow "?")


def entity_guid_kind(guid: str) -> tuple[str, int] | None:
    high = int(guid[:16], 16)
    kind = _ENTITY_KINDS.get(high >> 58)
    return (kind, (high >> 6) & 0x7FFFFF) if kind else None


def _exact_end(cursor: _Cursor) -> None:
    if cursor.offset != len(cursor.data):
        raise PktFormatError("unreviewed trailing payload bytes")


def _quest_giver_status(guid: str, flags: int) -> tuple[str, dict] | None:
    entity = entity_guid_kind(guid)
    if entity is None:
        return None
    return "QUEST_GIVER_STATUS", {"entity_guid": guid, "entry_id": entity[1],
        "status_flags": flags, "quest_available": bool(flags & _QG_AVAILABLE),
        "reward_ready": bool(flags & _QG_REWARD), "quest_incomplete": bool(flags & _QG_INCOMPLETE),
        "trivial_available": bool(flags & _QG_TRIVIAL),
        "future_quest": bool(flags & _QG_FUTURE)}


_OBJECT_KINDS = {5: "UNIT", 8: "GAMEOBJECT", 13: "CONVERSATION"}


# UnitData facts (health, level, faction, unit flags, reach, the unit's target
# and who summoned/created it), 2026-10-27; see update_object._unit_tail.
UNIT_FIELDS = ("health", "max_health", "level", "faction_template", "unit_flags", "unit_flags2", "unit_flags3", "bounding_radius", "combat_reach", "target_guid", "summoned_by", "created_by")


def _decode_update_object(data: bytes, fragments: dict, *, own_character_guid=None,
                         owned_items=None) -> list[tuple[str, dict]]:
    """Public entities, plus health deltas of the correlated own login only."""
    events = []
    from .context import same_player
    owned_items = owned_items if owned_items is not None else {}
    world_map = struct.unpack_from('<H',data)[0]
    for row in decode_update_object(data, fragments, own_character_guid=own_character_guid,
                                   own_item_guids=owned_items if own_character_guid is not None else ()):
        guid = row['guid']
        item = row.get('own_item')
        if item is not None:
            owned_items[guid] = item['mover_guid']
            if len(owned_items)>2048:owned_items.pop(next(iter(owned_items)))
            events.append(('OWN_ITEM_UPDATE',{'item_guid':guid,'item_id':row['entry_id'],
                'world_map_id':world_map,'sample_kind':'CREATE',**item}))
            continue
        previous = owned_items.get(guid)
        if previous is not None and own_character_guid is not None and same_player(previous,own_character_guid):
            if row.get('own_item_delta'):
                events.append(('OWN_ITEM_UPDATE',{'mover_guid':previous,'item_guid':guid,
                    'world_map_id':world_map,'sample_kind':'VALUES',**row['own_item_delta']}))
                continue
            reason = (row.get('reason') if row['kind']=='REMOVED' else
                      'OWNER_CHANGED' if row.get('foreign_item_owner') else 'UNREVIEWED_UPDATE')
            events.append(('OWN_ITEM_REMOVED',{'mover_guid':previous,'item_guid':guid,
                          'world_map_id':world_map,'removal':reason}))
            owned_items.pop(guid,None)  # unknown ownership/layout must be re-established by CREATE
            continue
        if own_character_guid is not None:
            from .context import same_player
            if same_player(row['guid'], own_character_guid):
                if row.get('inventory_roots') is not None:
                    events.append(('OWN_INVENTORY_ROOTS',{'mover_guid':row['guid'],'world_map_id':world_map,
                        'sample_kind':'CREATE','root_slots':row['inventory_roots']}))
                elif row.get('inventory_root_delta'):
                    events.append(('OWN_INVENTORY_ROOTS',{'mover_guid':row['guid'],'world_map_id':world_map,
                        'sample_kind':'VALUES','root_slots':row['inventory_root_delta']}))
                elif row.get('inventory_invalidated') or row['kind']=='CREATED':
                    events.append(('OWN_INVENTORY_INVALIDATED',{'mover_guid':row['guid'],'world_map_id':world_map}))
                if row.get('quest_log_slots'):
                    events.append(('OWN_QUEST_LOG_UPDATE', {'mover_guid': row['guid'],
                        'world_map_id': struct.unpack_from('<H', data)[0], 'slots': row['quest_log_slots'],
                        **({'sample_kind':'CREATE'} if row['kind'] == 'CREATED' else {})}))
                elif row.get('quest_log_invalidated') or row['kind']=='CREATED':
                    events.append(('OWN_QUEST_LOG_INVALIDATED', {'mover_guid':row['guid'],
                        'world_map_id':world_map}))
                profile = {k: row[k] for k in ('race_id', 'class_id', 'player_class_id', 'power_type', 'level') if k in row}
                if row['kind'] in {'VALUES', 'CREATED'} and profile:
                    events.append(('OWN_PROFILE_UPDATE', {'mover_guid': row['guid'],
                        'world_map_id': struct.unpack_from('<H', data)[0],
                        'sample_kind': 'CREATE' if row['kind'] == 'CREATED' else 'VALUES', **profile}))
                health = {k: row[k] for k in ('health', 'max_health') if k in row}
                if row['kind'] in {'VALUES', 'CREATED'} and health:
                    events.append(('OWN_UNIT_UPDATE', {'mover_guid': row['guid'],
                        'world_map_id': struct.unpack_from('<H', data)[0],
                        'sample_kind': 'CREATE' if row['kind'] == 'CREATED' else 'VALUES', **health}))
                continue  # never export own private PlayerData/ActivePlayerData
        entity = entity_guid_kind(row["guid"])
        if entity is None:
            continue
        base = {"entity_guid": row["guid"], "entry_id": entity[1]}
        if row["kind"] == "REMOVED":
            events.append(("ENTITY_REMOVED", {**base, "removal": row["reason"]}))
        elif row["kind"] == "VALUES":
            if "dynamic_flags" in row:
                events.append(("ENTITY_FLAGS", {**base, "dynamic_flags": row["dynamic_flags"]}))
            unit = {key: row[key] for key in UNIT_FIELDS if key in row}
            if unit:
                events.append(("ENTITY_UNIT_UPDATE", {**base, **unit}))
        elif row["object_type"] in _OBJECT_KINDS and row.get("entry_id") == entity[1]:
            payload = {**base, "object_kind": _OBJECT_KINDS[row["object_type"]],
                       "world_map_id": row["map_id"], "dynamic_flags": row.get("dynamic_flags")}
            for key in ("npc_flags", "go_flags", "go_state", "go_type", "quest_objective_id", *UNIT_FIELDS):
                if key in row:
                    payload[key] = row[key]
            position, facing = row["position"], row["facing"]
            if (position is not None and not row["on_transport"]
                    and _valid_position(*position, facing) and tuple(position) != (0., 0., 0.)):
                payload.update(x=position[0], y=position[1], z=position[2], facing=facing,
                               coordinate_space="WORLD_YARDS", position_source=row["source"])
            events.append(("ENTITY_CREATED", payload))
    return events


def _decode_verified_payloads(name: str, direction: str, data: bytes) -> list[tuple[str, dict]]:
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_QUEST_GIVER_STATUS_MULTIPLE":
        cursor = _Cursor(data)
        count = cursor.u32()
        if count > 1024:
            raise PktFormatError("quest-giver status count exceeds reviewed bound")
        rows = [(cursor.packed_guid128(), cursor.u64()) for _ in range(count)]
        _exact_end(cursor)
        return [value for value in (_quest_giver_status(g, f) for g, f in rows) if value]
    value = _decode_verified_payload(name, direction, data)
    return [value] if value is not None else []


def _decode_verified_payload(name: str, direction: str, data: bytes) -> tuple[str, dict] | None:
    cursor = _Cursor(data)
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_QUEST_GIVER_STATUS":
        guid, flags = cursor.packed_guid128(), cursor.u64()
        _exact_end(cursor)
        return _quest_giver_status(guid, flags)
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_ON_MONSTER_MOVE":
        # WPP V12 HandleOnMonsterMove: mover, MovementMonsterSpline, Position.
        # Position is the spline start; on the capture it equals the previous
        # spline's first point exactly. A transport-relative move is no fact.
        move = decode_monster_move(data)
        entity = entity_guid_kind(move["mover"])
        if entity is None or move["on_transport"]:
            return None
        x, y, z = move["start"]
        if not _valid_position(x, y, z, 0.) or (x, y, z) == (0., 0., 0.):
            raise PktFormatError("invalid monster-move coordinates")
        payload = {"entity_guid": move["mover"], "entry_id": entity[1], "x": x, "y": y, "z": z,
                   "coordinate_space": "WORLD_YARDS", "source_opcode": name,
                   "move_time_ms": move["move_time_ms"]}
        # The last of Points is where the spline ends: a one-point spline's
        # only point, an uncompressed path's last waypoint (live 2026-10-26
        # 12:15:42: an Intrusive Pupstinger's 4-point return ended exactly at
        # its next spline's start; without it the patrol "parked" at the turn).
        destination = move.get("end", move["destination"] if move["points"] == 1 else None)
        if destination is not None and _valid_position(*destination, 0.):
            payload.update(destination_x=destination[0], destination_y=destination[1],
                           destination_z=destination[2])
        return "ENTITY_POSITION", payload
    if direction == FlowDirection.CLIENT_TO_SERVER.value and name in _CLIENT_MOVEMENT_NAMES:
        mover_guid = cursor.packed_guid128()
        movement_flags = cursor.u64()
        move_time = cursor.u32()
        x, y, z, facing = cursor.f32(), cursor.f32(), cursor.f32(), cursor.f32()
        if not _valid_position(x, y, z, facing):
            raise PktFormatError("invalid movement coordinates")
        pitch = cursor.f32()
        cursor.take(4)  # StepUpStartElevation
        remove_count = cursor.i32()
        if not 0 <= remove_count <= 64:
            raise PktFormatError("movement force count exceeds reviewed bound")
        cursor.take(8)  # MoveIndex, GravityModifier
        for _ in range(remove_count):
            cursor.packed_guid128()
        optional_flags = cursor.take(2)
        payload = {
            "mover_guid": mover_guid,
            "movement_flags": movement_flags,
            "move_time": move_time,
            "x": x, "y": y, "z": z, "facing": facing,
            "coordinate_space": "WORLD_YARDS",
            "source_opcode": name,
            "is_selected_client_movement": True,
            "on_transport": bool(optional_flags[0] & 0x40),
            "standing_on_game_object": bool(optional_flags[0] & 0x80),
            "pitch": pitch if math.isfinite(pitch) and abs(pitch) <= 3.2 else None,
            "flying": bool(movement_flags & MOVE_FLYING),
            # A flying vehicle that touched down keeps CAN_FLY (live
            # 2026-10-26 11:31:59: the whelp landed on the Lifeshrine).
            "can_fly": bool(movement_flags & MOVE_CAN_FLY),
            "adv_flying": bool(movement_flags & MOVE_ADV_FLYING),
            "falling": bool(movement_flags & MOVE_FALLING),
        }
        try:
            payload.update(_movement_tail(cursor, optional_flags))
        except (PktFormatError, IndexError, ValueError, struct.error):
            pass  # the reviewed prefix above stands; the optional speeds stay absent
        return "MOVEMENT_UPDATE", payload
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_NEW_WORLD":
        map_id = cursor.i32()
        x, y, z, facing = cursor.f32(), cursor.f32(), cursor.f32(), cursor.f32()
        floor_difficulty, floor_index = cursor.i32(), cursor.i32()
        reason = cursor.u32()
        if not _valid_position(x, y, z, facing):
            raise PktFormatError("invalid new-world coordinates")
        return "MAP_CHANGED", {
            "world_map_id": map_id, "x": x, "y": y, "z": z, "facing": facing,
            "floor_difficulty": floor_difficulty, "floor_index": floor_index,
            "reason": reason, "coordinate_space": "WORLD_YARDS",
        }
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_MOVE_TELEPORT":
        mover_guid = cursor.packed_guid128()
        sequence_index = cursor.i32()
        x, y, z, facing = cursor.f32(), cursor.f32(), cursor.f32(), cursor.f32()
        if not _valid_position(x, y, z, facing):
            raise PktFormatError("invalid teleport coordinates")
        return "MOVEMENT_UPDATE", {
            "mover_guid": mover_guid, "sequence_index": sequence_index,
            "x": x, "y": y, "z": z, "facing": facing,
            "coordinate_space": "WORLD_YARDS", "teleport": True,
        }
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_QUEST_UPDATE_ADD_CREDIT":
        # WPP V11_2_5+: VictimGUID, QuestID, ObjectID, Count, Required,
        # ObjectiveType.  Live 2026-10-25 (Skyriding lesson 65118): every ring
        # passed came as ObjectID 182800 1/5 .. 5/5, the target as 182847.
        cursor.packed_guid128()             # the victim is not forwarded
        quest_id = cursor.i32() & 0xFFFFFFFF
        object_id = cursor.i32()
        count, required = struct.unpack("<HH", cursor.take(4))
        objective_type = cursor.u32()
        if not 0 <= count <= max(required, 1) <= 10000:
            raise PktFormatError("quest credit count out of bounds")
        return "QUEST_CREDIT_ADDED", {"quest_id": quest_id, "object_id": object_id, "count": count,
                                      "required": required, "objective_type": objective_type}
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_QUEST_UPDATE_COMPLETE":
        quest_id = cursor.i32() & 0xFFFFFFFF
        cursor.u8()  # HideCreditMessage bit must exist; truncated completion is not a fact
        return "QUEST_COMPLETED", {"quest_id": quest_id}
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name in {
        "SMSG_QUEST_UPDATE_FAILED", "SMSG_QUEST_UPDATE_FAILED_TIMER"
    }:
        return "QUEST_UPDATED", {
            "quest_id": cursor.i32() & 0xFFFFFFFF,
            "failed": True,
            "timer_failed": name.endswith("_TIMER"),
        }
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_ATTACK_START":
        return "COMBAT_STARTED", {
            "attacker_guid": cursor.packed_guid128(),
            "victim_guid": cursor.packed_guid128(),
        }
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_ATTACK_STOP":
        return "ATTACK_STOPPED", {"attacker_guid": cursor.packed_guid128(),
            "victim_guid": cursor.packed_guid128(), "now_dead": bool(cursor.u8() & 0x80)}
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_ATTACK_SWING_ERROR":
        reason = cursor.u8() >> 6
        labels = {0: "CANT_ATTACK", 1: "OUT_OF_RANGE", 2: "BAD_FACING", 3: "DEAD_TARGET"}
        return "SPELL_CAST_FAILED", {"reason": labels[reason], "attack_swing": True}
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_PLAY_SCENE":
        # WPP V11_0_0 SceneHandler: SceneID, PlaybackFlags, SceneInstanceID,
        # SceneScriptPackageID, TransportGUID, Location, MovieID, Encrypted.
        # Live 70575 (2026-10-25): lesson 77345 played package 3978, the
        # Skytop Observatory race package 3562 (39-byte payloads).
        scene_id, flags = cursor.i32(), cursor.i32()
        instance, package = cursor.u32(), cursor.i32()
        if not 0 < package < 2**20 or not 0 < instance < 2**31:
            raise PktFormatError("scene identifiers out of bounds")
        return "SCENE_STARTED", {"scene_id": scene_id, "playback_flags": flags & 0xFFFFFFFF,
                                 "scene_instance_id": instance, "package_id": package}
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name in {"SMSG_MOVE_ROOT", "SMSG_MOVE_UNROOT"}:
        # MoverGUID, SequenceIndex.  Live 20:47:09-20:47:17 (Skytop race): the
        # start line roots the rider, the unroot is the start signal.
        mover = cursor.packed_guid128()
        cursor.i32()
        _exact_end(cursor)
        return "MOVEMENT_ROOT", {"mover_guid": mover, "rooted": name == "SMSG_MOVE_ROOT"}
    if direction == FlowDirection.CLIENT_TO_SERVER.value and name == "CMSG_GOSSIP_SELECT_OPTION":
        # GossipUnit, MenuID, GossipOptionID (WPP V6_0_2 NpcHandler, 10.0+).
        # Live 2026-10-25 21:05:51 / 21:09:38 / 21:22:47: Celormu (198040),
        # menu 29949, option 107284 started the Skytop race each time.
        unit = cursor.packed_guid128()
        menu, option = cursor.u32(), cursor.i32()
        high = int(unit[:16], 16)
        if high >> 58 not in {8, 9, 11} or not 0 < option < 2**31:
            return None                    # only an NPC or object, never a player
        return "GOSSIP_SELECTED", {"entity_guid": unit, "entry_id": (high >> 6) & 0x7FFFFF,
                                   "gossip_menu_id": menu, "gossip_option_id": option}
    if direction == FlowDirection.SERVER_TO_CLIENT.value and name == "SMSG_CANCEL_SCENE":
        return "SCENE_ENDED", {"scene_instance_id": cursor.u32(), "canceled": True}
    if direction == FlowDirection.CLIENT_TO_SERVER.value and name in {
            "CMSG_SCENE_PLAYBACK_COMPLETE", "CMSG_SCENE_PLAYBACK_CANCELED"}:
        return "SCENE_ENDED", {"scene_instance_id": cursor.u32(),
                               "canceled": name.endswith("CANCELED")}
    if direction == FlowDirection.CLIENT_TO_SERVER.value and name == "CMSG_SCENE_TRIGGER_EVENT":
        # bits(6) length, SceneInstanceID, Event.  The own client's scene
        # script sends "Checkpoint" for every ring it flew through and
        # "RaceComplete" at the target (live 17:27:53-17:29:49, 8 + 1, each
        # ~0.1 s before the server's quest credit).  Only these names pass.
        length = cursor.u8() >> 2
        instance = cursor.u32()
        label = {b"Checkpoint": "CHECKPOINT", b"RaceComplete": "RACE_COMPLETE"}.get(cursor.take(length))
        if label is None:
            return None
        return "SCENE_EVENT", {"scene_instance_id": instance, "scene_event": label}
    return None


class PktFileFollower:
    """Follows one growing PKT file without reading partial records as facts."""

    def __init__(self, path: Path, *, poll_interval: float = 0.05, read_size: int = 1024 * 1024):
        self.path = Path(path)
        self.poll_interval = max(0.01, float(poll_interval))
        self.read_size = max(4096, int(read_size))
        self.parser = PktV31StreamParser()
        self.bytes_read = 0
        self.rotations = 0

    def records(self, stop) -> Iterator[PktRecord]:
        # Keep no handle across yield/wait: Windows producers must be able
        # to rotate/replace their capture without being blocked by a reader.
        identity, offset = None, 0
        while not stop.is_set():
            with self.path.open("rb") as stream:
                status = os.fstat(stream.fileno())
                if identity is not None and (status.st_ino != identity or status.st_size < offset):
                    offset = 0
                    self.parser.reset()
                    self.rotations += 1
                identity = status.st_ino
                stream.seek(offset)
                data = stream.read(self.read_size)
                offset = stream.tell()
            if not data:
                stop.wait(self.poll_interval)
                continue
            self.bytes_read += len(data)
            yield from self.parser.feed(data)

    def snapshot(self) -> dict[str, object]:
        header = self.parser.header
        return {
            "path": str(self.path),
            "bytes_read": self.bytes_read,
            "buffered_bytes": self.parser.buffered_bytes,
            "rotations": self.rotations,
            "game_build": header.game_build if header else None,
            "pkt_version": header.version if header else None,
        }
