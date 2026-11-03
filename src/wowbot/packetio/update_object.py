"""Retail 12.1.5 (70340 family) SMSG_UPDATE_OBJECT / SMSG_ON_MONSTER_MOVE readers.

Written from the field order of WowPacketParser commit
1a72288ca3fab3363b99965d5e9782b99cd6803b (V12_0_0_65390 UpdateHandler,
MovementHandler and UpdateFieldsHandler1215), not copied code. Only the
fields the agent needs are kept; everything else is skipped by its reviewed
size. A record that does not end exactly where the layout says is rejected
as a whole, so a misread bit can never surface as a world fact.
"""
from __future__ import annotations

import math
import struct


class UpdateLayoutError(ValueError):
    pass


class _Bits:
    """Byte cursor plus WPP's bit reader (MSB first; byte reads keep bit state)."""

    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.bitpos = 8
        self.current = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.offset+count > len(self.data):
            raise UpdateLayoutError("truncated update payload")
        value = self.data[self.offset:self.offset+count]
        self.offset += count
        return value

    def u8(self): return self.take(1)[0]
    def i8(self): return struct.unpack("<b", self.take(1))[0]
    def u16(self): return struct.unpack("<H", self.take(2))[0]
    def i16(self): return struct.unpack("<h", self.take(2))[0]
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def i32(self): return struct.unpack("<i", self.take(4))[0]
    def u64(self): return struct.unpack("<Q", self.take(8))[0]
    def i64(self): return struct.unpack("<q", self.take(8))[0]
    def f32(self): return struct.unpack("<f", self.take(4))[0]
    def vec3(self): return struct.unpack("<3f", self.take(12))

    def reset(self):
        self.bitpos = 8

    def bit(self) -> bool:
        if self.bitpos == 8:
            self.bitpos, self.current = 0, self.u8()
        value = (self.current >> (7-self.bitpos)) & 1
        self.bitpos += 1
        return bool(value)

    def bits(self, count: int) -> int:
        value = 0
        for index in range(count-1, -1, -1):
            if self.bit():
                value |= 1 << index
        return value

    def guid(self) -> str:
        low_mask, high_mask = self.u8(), self.u8()
        low = sum(self.u8() << (8*i) for i in range(8) if low_mask & (1 << i))
        high = sum(self.u8() << (8*i) for i in range(8) if high_mask & (1 << i))
        return f"{high:016X}{low:016X}"


def _bounded(value: int, limit: int, what: str) -> int:
    if not 0 <= value <= limit:
        raise UpdateLayoutError(f"{what} exceeds reviewed bound")
    return value


def _finite(*values) -> bool:
    return all(math.isfinite(v) for v in values) and all(abs(v) <= 100_000. for v in values)


# ObjectType801 (byte after the GUID of a create block).
OBJECT_TYPES = {5: "UNIT", 6: "PLAYER", 7: "ACTIVE_PLAYER", 8: "GAMEOBJECT", 10: "CORPSE"}
# WowCSEntityFragments1215 ids.
_FRAGMENT_END, _F_ENTITY_POSITION, _CG_OBJECT = 255, 2, 3
_INDIRECT = frozenset({3, 14, 16, 33, 38})     # CGObject, FPlayerOwnershipLink, CActor, PlayerHouseInfo, PlayerInitiative
_UPDATEABLE = frozenset({3, 18, 20, 21, 22, 23, 24, 28, 31, 32, 33, 34, 35, 38})


def _transport(c: _Bits) -> None:
    c.reset()
    c.guid()
    c.take(16+1+4)               # TransportPosition (Vector4), VehicleSeatIndex, MoveTime
    previous, vehicle = c.bit(), c.bit()
    if previous:
        c.u32()
    if vehicle:
        c.i32()


def _movement_force(c: _Bits) -> None:
    c.guid()
    c.take(12+12+4+4+4+4+4+4)    # Origin, Direction, TransportID, Magnitude, ForceID, Duration, EndTimestamp, Flags
    c.reset()
    c.bits(2)


def _create_spline(c: _Bits) -> dict:
    c.reset()
    c.i32()                      # ID
    destination = c.vec3()
    result = {"destination": destination, "duration_ms": None}
    if not c.bit():              # MovementSplineMove
        return result
    c.reset()
    c.u32()                      # SplineFlags
    face = c.u8()
    c.i32()                      # Elapsed
    result["duration_ms"] = c.u32()
    c.take(8)                    # DurationModifier, NextDurationModifier
    if face == 1:
        c.take(12)
    elif face == 2:
        c.guid()
    elif face == 3:
        c.take(4)
    special = c.bit()
    points = c.bits(16)
    has_filter, spell_effect, jump, turn, tier, visual = (c.bit() for _ in range(6))
    if special:
        c.u32()
    if has_filter:
        c.reset()
        count = _bounded(c.u32(), 256, "spline filter")
        c.take(8*count)
        c.bits(2)
    c.take(12*_bounded(points, 4096, "spline points"))
    if spell_effect:
        c.guid()
        c.take(16)
    if jump:
        c.take(12)
    if turn:
        c.take(12)
    if tier:
        c.take(13)
    if visual:
        c.take(16*16)
    return result


def _movement_block(c: _Bits) -> dict:
    c.reset()
    (_position_fragment, _no_birth, _portals, _hover, this_is_you, has_move, has_move_transport,
     stationary, combat_victim, server_time, vehicle_create, anim_kit, rotation, game_object,
     smooth_phasing, scene, player_create, conversation, room, decor, mesh) = (c.bit() for _ in range(21))
    pause_count = _bounded(c.u32(), 256, "pause times")
    result = {"position": None, "facing": None, "source": None, "on_transport": False,
              "this_is_you": this_is_you, "spline": None}
    if has_move:
        c.reset()
        c.guid()                 # MoverGUID
        c.u64()                  # MovementFlags
        c.u32()                  # MoveTime
        position, facing = c.vec3(), c.f32()
        c.take(8)                # Pitch, StepUpStartElevation
        remove_count = _bounded(c.i32(), 64, "removed forces")
        c.take(8)                # MoveIndex, GravityModifier
        for _ in range(remove_count):
            c.guid()
        standing, transport, fall, _spline, _height, _remote, inertia, adv_flying, drive = (
            c.bit() for _ in range(9))
        if standing:
            c.guid()
        if transport:
            _transport(c)
        if fall:
            c.reset()
            c.take(8)            # FallTime, JumpVelocity
            if c.bit():
                c.take(12)       # Fall direction, horizontal speed
        if inertia:
            c.take(4+12+4)
        if adv_flying:
            c.take(8)
        if drive:
            c.reset()
            c.take(8)
            c.bits(2)
        c.take(9*4)              # walk .. pitch-rate speeds
        force_count = _bounded(c.u32(), 64, "movement forces")
        c.take(4+17*4)           # MovementForcesModMagnitude, 17 advanced-flying values
        c.reset()
        has_spline = c.bit()
        for _ in range(force_count):
            _movement_force(c)
        if has_spline:
            result["spline"] = _create_spline(c)
        result.update(position=position, facing=facing, source="MOVEMENT", on_transport=transport)
    if has_move_transport:
        _transport(c)
        result["on_transport"] = True
    if stationary:
        result.update(position=c.vec3(), facing=c.f32(), source="STATIONARY")
    if combat_victim:
        c.guid()
    if server_time:
        c.u32()
    if vehicle_create:
        c.take(8)
    if anim_kit:
        c.take(6)
    if rotation:
        c.take(8)
    if game_object:
        c.reset()
        c.u32()                  # WorldEffectID
        int1, ship_path, state_percent = c.bit(), c.bit(), c.bit()
        if ship_path:
            c.reset()
            c.take(8)
            c.bits(3)
        if int1:
            c.u32()
        if state_percent:
            c.f32()
    if smooth_phasing:
        c.reset()
        c.bit(), c.bit()
        if c.bit():
            c.guid()
    if scene:
        c.reset()
        local_script, pet_battle = c.bit(), c.bit()
        if local_script:
            c.reset()
            c.take(c.bits(7))
        if pet_battle:
            raise UpdateLayoutError("pet battle create block is not reviewed")
    if player_create:
        c.reset()
        scene_ids, runes = c.bit(), c.bit()
        if scene_ids:
            c.take(4*_bounded(c.u32(), 256, "scene instances"))
        if runes:
            c.take(2)
            c.take(_bounded(c.u32(), 16, "runes"))
    if conversation:
        c.reset()
        if c.bit():
            c.u32()
    if room:
        c.guid()
    if decor:
        c.guid()
    if mesh:
        c.guid()
        c.take(12+16+4+1)
    c.take(4*pause_count)
    return result


def _fragments(c: _Bits) -> tuple[int, ...]:
    values = []
    while (value := c.u8()) != _FRAGMENT_END:
        values.append(value)
        _bounded(len(values), 64, "entity fragments")
    return tuple(values)


# UpdateFieldFlag (WPP Enums/UpdateFieldFlag.cs): conditional UnitData blocks.
_OWNER, _UNIT_ALL, _EMPATH = 0x01, 0x04, 0x08
_GUID_ZERO = "0"*32


def _unit_tail(c: _Bits, field_flags: int) -> dict:
    """UnitData after NpcFlags up to CombatReach (WPP UpdateFieldsHandler1215
    ReadCreateUnitData, V12_1_5_70340): health, level, faction, unit flags,
    the unit's target, who summoned/created it, bounding radius and reach.

    User 2026-10-27 ("wpp-ből ezeket tudjuk kiolvasni"): mob HP shows the
    fight's progress, the target GUID who attacks whom, the reach a better
    stop distance, SummonedBy/CreatedBy a follower that is ours."""
    c.take(4*3)                  # StateSpellVisualID, StateAnimID, StateAnimKitID
    effects = _bounded(c.u32(), 64, "state world effects")
    c.take(4+4)                  # StateWorldEffectsQuestObjectiveID, SpellOverrideNameID
    c.take(4*effects)
    c.guid(), c.guid()           # Charm, Summon
    if field_flags & _OWNER:
        c.guid()                 # Critter
    c.guid()                     # CharmedBy
    summoned_by, created_by = c.guid(), c.guid()
    c.guid(), c.guid()           # DemonCreator, LookAtControllerTarget
    target = c.guid()
    c.guid()                     # BattlePetCompanionGUID
    c.u64()                      # BattlePetDBID
    c.guid(), c.guid()           # BattlePetAttachedToDecorGUID, BattlePetDecorHouseGUID
    c.reset()
    c.take(4+4+4+4+4)            # ChannelData: SpellID, SpellVisual (2), StartTimeMs, Duration
    c.i8()                       # SpellEmpowerStage
    c.u32()                      # SummonedByHomeRealm
    race, class_id, player_class = c.u8(), c.u8(), c.u8()
    c.take(2)                    # Sex, CreatureType: not exported
    power_type = c.u8()          # DisplayPower is an enum, not a Power[] slot
    c.u32()                      # OverrideDisplayPowerID
    health = c.i64()
    c.take(8*10)                 # Power, MaxPower
    if field_flags & (_OWNER | _UNIT_ALL):
        c.take(8*10)             # PowerRegen(Interrupted)FlatModifier
    max_health = c.i64()
    level = c.i32()
    c.take(4*5)                  # EffectiveLevel, ContentTuningID, ScalingLevelMin/Max/Delta
    c.u8()                       # ScalingFactionGroup
    faction = c.i32()
    for _ in range(3):           # VirtualItems
        c.reset()
        c.take(4*3+2+2+4+1+1)
        c.reset()
        c.bit(), c.bit()         # HasTransmog, HasIllusion
    unit_flags, unit_flags2, unit_flags3 = c.u32(), c.u32(), c.u32()
    c.u32()                      # Flags4
    c.u32()                      # AuraState
    c.take(4*2)                  # AttackRoundBaseTime
    if field_flags & _OWNER:
        c.u32()                  # RangedAttackRoundBaseTime
    bounding, reach = c.f32(), c.f32()
    if not (0 < max_health < 1 << 40 and 0 <= health <= max_health and 0 < level <= 100
            and 0 <= faction < 1 << 16 and _finite(bounding, reach)
            and 0 <= bounding <= 60 and 0 <= reach <= 60):
        raise UpdateLayoutError("implausible unit fields")
    result = {"health": health, "max_health": max_health, "level": level, "faction_template": faction,
              "unit_flags": unit_flags, "unit_flags2": unit_flags2, "unit_flags3": unit_flags3,
              "bounding_radius": round(bounding, 3), "combat_reach": round(reach, 3)}
    result.update(race_id=race, class_id=class_id, player_class_id=player_class, power_type=power_type)
    for key, value in (("target_guid", target), ("summoned_by", summoned_by), ("created_by", created_by)):
        if value != _GUID_ZERO:
            result[key] = value
    return result


def _create_fields(blob: bytes, object_type: int, *, own_player=False, own_character_guid=None) -> dict:
    """ObjectData plus the leading UnitData/GameObjectData fields we use."""
    c = _Bits(blob)
    field_flags = c.u8()         # FieldFlags
    fragments = _fragments(c)
    result = {"fragments": fragments}
    for fragment in fragments:
        if fragment == _F_ENTITY_POSITION:
            continue
        if fragment != _CG_OBJECT:
            return result        # an unreviewed fragment precedes CGObject
        if not c.u8():           # IndirectFragmentActive
            return result
        c.reset()
        result.update(entry_id=c.i32(), dynamic_flags=c.u32())
        c.f32()                  # Scale
        if object_type == 5 or own_player and object_type in {6, 7}:
            c.reset()
            c.i32()              # DisplayID
            result["npc_flags"] = c.u32() | (c.u32() << 32)
            try:
                result.update(_unit_tail(c, field_flags))
                if own_player and object_type in {6, 7}:
                    from .own_create_quest_log import read_create_slots
                    try:
                        cosmetic_counts = {}
                        slots = read_create_slots(c, field_flags, cosmetic_counts=cosmetic_counts)
                        if slots:
                            result['quest_log_slots'] = slots
                            if object_type == 7 and field_flags & _OWNER:
                                from .own_inventory_codec import create_roots
                                try:
                                    result['inventory_roots'] = create_roots(c,**cosmetic_counts)
                                except ValueError:
                                    pass  # later prefix unavailable, valid quest slots remain
                    except ValueError:
                        pass    # reviewed HP/profile prefix remains; no partial slot list
            except UpdateLayoutError:
                pass             # the reviewed prefix stands; no guessed unit facts
        elif object_type in {1, 2} and own_character_guid is not None:
            from .own_inventory_codec import create_item, create_container
            try:
                item = create_item(c,flags=field_flags,own_guid=own_character_guid)
                if item is not None and item.get('foreign_owner'):
                    result['foreign_item_owner'] = True
                elif item is not None:
                    if object_type == 2:
                        item.update(create_container(c))
                    result['own_item'] = item
            except ValueError:
                pass  # no incomplete inventory item baseline
        elif object_type == 8:
            c.reset()
            c.take(4*5)          # DisplayID .. SpawnTrackingStateAnimKitID
            effects = _bounded(c.u32(), 64, "state world effects")
            result["quest_objective_id"] = c.u32()
            c.take(4*effects)
            c.guid(), c.guid()   # CreatedBy, GuildGUID
            result["go_flags"] = c.u32()
            c.u32()              # FlagsB
            c.take(16+4)         # ParentRotation, FactionTemplate
            result["go_state"] = c.i8()
            result["go_type"] = c.i8()
        return result
    return result


# UnitData update fields by change-mask bit (WPP UpdateFieldsHandler1215
# ReadUpdateUnitData, bits 6-55): (bit, name or None, reader).
_UNIT_UPDATE_FIELDS = (
    (6, None, "i32"), (7, None, "u32"), (8, None, "u32"), (9, None, "u32"), (10, None, "u32"),
    (11, None, "u32"), (12, None, "u32"), (13, None, "i32"), (14, None, "guid"), (15, None, "guid"),
    (16, None, "guid"), (17, None, "guid"), (18, "summoned_by", "guid"), (19, "created_by", "guid"),
    (20, None, "guid"), (21, None, "guid"), (22, "target_guid", "guid"), (23, None, "guid"),
    (24, None, "u64"), (25, None, "guid"), (26, None, "guid"), (27, None, "channel"), (28, None, "i8"),
    (29, None, "u32"), (30, "race_id", "u8"), (31, "class_id", "u8"),
    (33, "player_class_id", "u8"), (34, None, "u8"), (35, None, "u8"), (36, "power_type", "u8"), (37, None, "u32"),
    (38, "health", "i64"), (39, "max_health", "i64"), (40, "level", "i32"), (41, None, "i32"),
    (42, None, "i32"), (43, None, "i32"), (44, None, "i32"), (45, None, "i32"), (46, None, "u8"),
    (47, "faction_template", "i32"), (48, "unit_flags", "u32"), (49, "unit_flags2", "u32"),
    (50, "unit_flags3", "u32"), (51, None, "u32"), (52, None, "u32"), (53, None, "u32"),
    (54, "bounding_radius", "f32"), (55, "combat_reach", "f32"),
)


def _values_unit(c: _Bits) -> dict:
    """Changed UnitData fields up to CombatReach (see _UNIT_UPDATE_FIELDS).

    Live need (user 2026-10-27): a mob's health during the fight and whom it
    targets change only through these value updates."""
    c.reset()
    mask_mask = c.bits(8)
    raw = [c.bits(32) if mask_mask >> i & 1 else 0 for i in range(8)]

    def changed(bit):
        return bool(raw[bit // 32] >> (bit % 32) & 1)
    if changed(0) and (changed(3) or changed(4) or changed(5)):
        raise UpdateLayoutError("unit dynamic arrays are not reviewed")
    if changed(0):
        if changed(1):
            c.bit()              # Field_314
        if changed(2):
            count = _bounded(c.bits(32), 64, "state world effects")
            c.take(4*count)
    c.reset()                    # dynamic-array masks (bits 3-5): none
    c.reset()
    result = {}
    for bit, name, reader in _UNIT_UPDATE_FIELDS:
        block = 0 if bit < 32 else 32
        if not changed(block) or not changed(bit):
            continue
        if reader == "guid":
            value = c.guid()
        elif reader == "channel":
            c.reset()
            c.take(4*5)
            continue
        else:
            value = getattr(c, reader)()
        if name is not None:
            result[name] = value
    health, maximum = result.get("health"), result.get("max_health")
    if ((health is not None and not 0 <= health < 1 << 40)
            or (maximum is not None and not 0 < maximum < 1 << 40)
            or not _finite(*(result[k] for k in ("bounding_radius", "combat_reach") if k in result))):
        raise UpdateLayoutError("implausible unit update")
    for key in ("bounding_radius", "combat_reach"):
        if key in result:
            result[key] = round(result[key], 3)
    return result


def _values_fields(blob: bytes, fragments: tuple[int, ...], *, own_player=False) -> dict:
    """Changed ObjectData (dynamic flags) and UnitData fields of one value update."""
    c = _Bits(blob)
    c.u8()                       # IsOwned
    if c.u8():                   # HasFragmentUpdates
        return ({'inventory_invalidated':True, 'quest_log_invalidated':True}
                if own_player else {})  # fragment-set changes are not reviewed
    bit_count = sum(1+(f in _INDIRECT) for f in fragments if f in _UPDATEABLE)
    changed = c.take((bit_count+7)//8)
    index = 0
    for fragment in fragments:
        if fragment not in _UPDATEABLE:
            continue
        if fragment != _CG_OBJECT:
            return ({'inventory_invalidated':True, 'quest_log_invalidated':True}
                    if own_player else {})
        set_ = lambda i: bool(changed[i//8] >> (i % 8) & 1)
        if not set_(index) or not set_(index+1):
            return {}
        update_type = c.u32()
        result = {}
        if own_player and update_type & 0x80:
            result['inventory_invalidated'] = True  # cleared only after reviewed InvSlots handling
        if own_player and update_type & 0x40:
            result['quest_log_invalidated'] = True
        if update_type & 1:      # ObjectData
            c.reset()
            mask = c.bits(4)
            c.reset()
            if mask & 1:
                if mask & 2:
                    c.i32()      # EntryID
                if mask & 4:
                    result["dynamic_flags"] = c.u32()
                if mask & 8:
                    c.f32()      # Scale
        if update_type & 0x1E:   # item/container/azerite data: not a creature
            return result
        if own_player and update_type & 0x80 and not update_type & ~0x81:
            from .own_item_delta import read_root_slots
            try:
                roots=read_root_slots(c)
                result.pop('inventory_invalidated',None)
                if roots:result['inventory_root_delta']=roots
            except ValueError:
                pass  # explicit invalidation, not stale root membership
        if update_type & 0x20:   # UnitData
            # Reaching PlayerData requires all changed UnitData bytes, not
            # merely the useful prefix. Unknown unit tails stop that path.
            unit_end_known = True
            if own_player and update_type & 0x40:
                probe = _Bits(c.data)
                probe.offset = c.offset
                presence = probe.bits(8)
                masks = [probe.bits(32) if presence >> i & 1 else 0 for i in range(8)]
                unit_end_known = not (masks[1] >> 24 or any(masks[2:]) or masks[0] & 0x38)
            try:
                result.update(_values_unit(c))
            except UpdateLayoutError:
                return result    # the reviewed ObjectData part stands
            if not unit_end_known:
                return result
        if own_player and update_type & 0x40:  # own PlayerData only
            from .player_quest_log import read_slots
            try:
                slots = read_slots(c)
                if slots is not None:
                    result.pop('quest_log_invalidated',None)
                if slots:
                    result['quest_log_slots'] = slots
            except ValueError:
                pass             # no partly decoded quest slot collection
        return result
    return ({'inventory_invalidated':True, 'quest_log_invalidated':True}
            if own_player else {})


def _values_dynamic_flags(blob: bytes, fragments: tuple[int, ...]) -> int | None:
    return _values_fields(blob, fragments).get("dynamic_flags")


def decode_update_object(data: bytes, fragments_by_guid: dict, *, own_character_guid=None,
                         own_item_guids=()) -> list[dict]:
    """All objects of one record, or UpdateLayoutError for the whole record."""
    c = _Bits(data)
    map_id = c.u16()
    count = _bounded(c.u32(), 4096, "object updates")
    c.reset()
    c.bit()                      # IsEndOfBatch
    rows = []
    if c.bit():                  # HasRemovedObjects
        destroyed = _bounded(c.i16(), 4096, "destroyed objects")
        removed = _bounded(c.u32(), 8192, "removed objects")
        if removed < destroyed:
            raise UpdateLayoutError("removed objects below destroyed count")
        for index in range(removed):
            rows.append({"kind": "REMOVED", "guid": c.guid(),
                         "reason": "DESTROYED" if index < destroyed else "OUT_OF_RANGE"})
    if c.u32() != len(data)-c.offset:
        raise UpdateLayoutError("update data size does not match record")
    pending = {}
    known_own_items = set(own_item_guids)
    for _ in range(count):
        update_type = c.u8()
        guid = c.guid()
        if update_type == 0:
            blob = c.take(_bounded(c.u32(), len(data), "values size"))
            if guid in known_own_items:
                from .own_item_delta import read_values
                try:
                    delta=read_values(blob,pending.get(guid,fragments_by_guid.get(guid,())),own_character_guid)
                    if delta.get('foreign_owner'):
                        rows.append({'kind':'VALUES','guid':guid,'foreign_item_owner':True})
                        known_own_items.discard(guid)
                    elif delta:
                        rows.append({'kind':'VALUES','guid':guid,'own_item_delta':delta})
                except ValueError:
                    rows.append({'kind':'VALUES','guid':guid,'own_item_invalidated':True})
                    known_own_items.discard(guid)
                continue  # only reviewed fields of a previously confirmed owned GUID
            known = pending.get(guid, fragments_by_guid.get(guid))
            if int(guid[:16], 16) >> 58 == 2:
                from .context import same_player
                if own_character_guid is None or not same_player(guid, own_character_guid):
                    continue    # no reading of another player's unit profile
            own_player = own_character_guid is not None and int(guid[:16], 16) >> 58 == 2
            fields = _values_fields(blob, known, own_player=own_player) if known else {}
            if fields:
                rows.append({"kind": "VALUES", "guid": guid, **fields})
        elif update_type in (1, 2):
            object_type = c.u8()
            movement = _movement_block(c)
            blob = c.take(_bounded(c.u32(), len(data), "create fields size"))
            from .context import same_player
            own_player = own_character_guid is not None and same_player(guid, own_character_guid)
            fields = _create_fields(blob, object_type, own_player=own_player,
                                    own_character_guid=own_character_guid)
            if fields.get('own_item') is not None:
                known_own_items.add(guid)
            elif object_type in {1,2}:
                known_own_items.discard(guid)
            pending[guid] = fields["fragments"]
            rows.append({"kind": "CREATED", "guid": guid, "object_type": object_type,
                         "map_id": map_id, **movement, **fields})
        else:
            raise UpdateLayoutError("unknown update type")
    if c.offset != len(data):
        raise UpdateLayoutError("unreviewed trailing update bytes")
    fragments_by_guid.update(pending)
    return rows


def decode_monster_move(data: bytes) -> dict:
    """SMSG_ON_MONSTER_MOVE: mover, spline start, first point and move time."""
    c = _Bits(data)
    mover = c.guid()
    c.u32()                      # Id
    flags = c.u32()
    face = c.u8()
    c.i32()                      # Elapsed
    move_time = c.u32()
    c.u32()                      # FadeObjectTime
    c.u8()                       # Mode
    transport = c.guid()
    c.i8()                       # VehicleSeat
    if face == 1:
        c.take(12)
    elif face == 2:
        c.take(4)
        c.guid()
    elif face == 3:
        c.take(4)
    c.reset()
    points = _bounded(c.bits(16), 4096, "spline points")
    c.bit(), c.bit()             # VehicleExitVoluntary, Interpolate
    packed = _bounded(c.bits(16), 4096, "packed deltas")
    has_filter, spell_effect, jump, turn, tier, visual = (c.bit() for _ in range(6))
    # Points: the path after the start (an uncompressed path lists every
    # waypoint; a compressed one only its end, the rest as packed deltas).
    # Either way the last one is where the spline ends.
    path = [c.vec3() for _ in range(points)]
    first = path[0] if path else None
    c.take(4*packed)
    if has_filter:
        count = _bounded(c.u32(), 256, "spline filter")
        c.take(4+2+4+2+4*count)
        c.reset()
        c.bits(2)
    if spell_effect:
        c.guid()
        c.take(16)
    if jump:
        c.take(12)
    if turn:
        c.take(12)
    if tier:
        c.take(13)
    if visual:
        c.take(16*16)
    c.reset()
    c.bits(5)                    # CrzTeleport, StopUseFaceDirection, StopDistanceTolerance
    start = c.vec3()
    if c.offset != len(data):
        raise UpdateLayoutError("unreviewed trailing monster-move bytes")
    return {"mover": mover, "start": start, "destination": first, "end": path[-1] if path else None,
            "points": points, "packed_points": packed, "move_time_ms": move_time,
            "spline_flags": flags, "on_transport": transport != "0"*32}
