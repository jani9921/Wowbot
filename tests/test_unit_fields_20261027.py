"""Creature UnitData from the server (user 2026-10-27, WPP list item 1):
health, level, faction, unit flags, reach, the unit's target and creator.
Checked on the 16:35 capture: 896/896 unit creates and 3417 health updates
decoded; a Qalashi's health fell 120033 -> 119783 while it targeted us."""
import struct
from types import SimpleNamespace

from wowbot.agent import world_packet_reducer as reducer
from wowbot.agent.packet_entity_facts import attackers, kill_objective_units
from wowbot.packetio.update_object import _Bits, _unit_tail, _values_unit

ME = "Player-1402-0B578799"


def packed(raw: str) -> bytes:
    high, low = int(raw[:16], 16), int(raw[16:], 16)
    out, masks = b"", []
    for value in (low, high):
        mask, data = 0, b""
        for i in range(8):
            byte = value >> (8*i) & 0xFF
            if byte:
                mask |= 1 << i
                data += bytes([byte])
        masks.append((mask, data))
    return bytes([masks[0][0], masks[1][0]]) + masks[0][1] + masks[1][1]


def player_raw(realm: int, low: int) -> str:
    high = (2 << 58) | (realm << 42)
    return f"{high:016X}{low:016X}"


ZERO = bytes([0, 0])
TARGET = player_raw(1402, 0x0B578799)


def unit_tail_bytes(*, target=TARGET, health=102625, max_health=120736, reach=7., owner=False,
                    unit_all=False, identity=bytes(6)):
    b = struct.pack("<III", 0, 0, 0) + struct.pack("<I", 0) + struct.pack("<Ii", 0, 0)
    b += ZERO*2                        # Charm, Summon
    if owner: b += ZERO                 # Critter
    b += ZERO                          # CharmedBy
    b += ZERO*2                        # SummonedBy, CreatedBy
    b += ZERO*2                        # DemonCreator, LookAtControllerTarget
    b += packed(target) if target else ZERO
    b += ZERO + struct.pack("<Q", 0) + ZERO*2
    b += struct.pack("<iiiII", 0, 0, 0, 0, 0)      # ChannelData
    b += struct.pack("<bI", 0, 0) + identity + struct.pack("<I", 0)
    b += struct.pack("<q", health) + bytes(8*10)
    if owner or unit_all: b += bytes(8*10)  # owner/unit-all regen fields
    b += struct.pack("<q", max_health)
    b += struct.pack("<i", 70) + bytes(4*5) + bytes([0]) + struct.pack("<i", 14)
    for _ in range(3):
        b += bytes(4*3+2+2+4+1+1) + bytes([0])      # VirtualItem + its 2 bits
    b += struct.pack("<IIII", 0x88840, 0, 0, 0) + struct.pack("<I", 0) + bytes(8)
    if owner: b += bytes(4)              # ranged attack time
    b += struct.pack("<ff", 3.495, reach)
    return b


def test_unit_create_tail_reads_health_target_and_reach():
    result = _unit_tail(_Bits(unit_tail_bytes()), 0)
    assert result["health"] == 102625 and result["max_health"] == 120736 and result["level"] == 70
    assert result["faction_template"] == 14 and result["unit_flags"] == 0x88840
    assert result["combat_reach"] == 7. and result["target_guid"] == TARGET
    assert "summoned_by" not in result                  # a zero GUID is no relation


def test_implausible_unit_fields_are_refused():
    import pytest
    from wowbot.packetio.update_object import UpdateLayoutError
    with pytest.raises(UpdateLayoutError):
        _unit_tail(_Bits(unit_tail_bytes(health=200, max_health=100)), 0)


def bits(fields: list[tuple[int, int]]) -> bytes:
    """MSB-first bit packing like WPP's ReadBits."""
    out, acc, used = bytearray(), 0, 0
    for value, width in fields:
        for i in range(width-1, -1, -1):
            acc = (acc << 1) | ((value >> i) & 1)
            used += 1
            if used == 8:
                out.append(acc)
                acc, used = 0, 0
    if used:
        out.append(acc << (8-used))
    return bytes(out)


def test_unit_value_update_reads_target_and_health():
    mask0 = (1 << 0) | (1 << 22)                         # block 0, Target
    mask1 = (1 << 0) | (1 << 6)                          # block 32, Health (bit 38)
    blob = bits([(0b11, 8), (mask0, 32), (mask1, 32)]) + packed(TARGET) + struct.pack("<q", 119783)
    result = _values_unit(_Bits(blob))
    assert result == {"target_guid": TARGET, "health": 119783}


def test_the_reducer_keeps_us_not_other_players():
    entity = {}
    context = {"character_guid": ME}
    reducer._remember_unit(entity, {"target_guid": TARGET, "health": 5}, 10., context)
    assert entity["unit"]["targets_me"] is True and entity["unit"]["target_entity"] is None
    other = player_raw(1402, 0x0C000001)
    reducer._remember_unit(entity, {"target_guid": other}, 11., context)
    assert entity["unit"]["targets_me"] is False and other not in str(entity)
    reducer._remember_unit(entity, {"health": 9}, 9., context)        # older sample
    assert entity["unit"]["health"] == 5


def citadel(**units):
    entities = {}
    for name, (x, y, z, unit) in units.items():
        guid = f"Creature-0-1461-2534-147807-186892-{name}"
        entities[guid] = {"guid": guid, "kind": "CREATURE", "entry_id": 186892, "map_id": 2444,
                          "position": {"x": x, "y": y, "z": z}, "unit": unit}
    return {"player_world_position": {"x": 0., "y": 0., "z": 260., "z_observed": True, "instance_id": 2444},
            "packet_entities": entities}


def test_attackers_are_live_attackable_units_targeting_us_nearest_in_3d():
    state = citadel(near_low=(5., 0., 214., {"targets_me": True, "health": 10}),
                    far_level=(20., 0., 260., {"targets_me": True, "health": 10}),
                    dead=(2., 0., 260., {"targets_me": True, "health": 0}),
                    immune=(3., 0., 260., {"targets_me": True, "health": 10, "unit_flags": 0x100}),
                    idle=(1., 0., 260., {"health": 10}))
    assert [value["guid"].split("-")[-1] for _, value in attackers(state)] == ["far_level", "near_low"]


def test_dead_and_unattackable_objective_units_are_not_hunted():
    state = citadel(alive=(5., 0., 260., {"health": 10, "targets_me": True}),
                    dead=(6., 0., 260., {"health": 0}), immune=(7., 0., 260., {"unit_flags": 0x2}))
    state.update(active_quests=[{"quest_id": 65939, "is_complete": False, "objectives": [
                     {"description": "3/12 Qalashi Forces slain", "is_complete": False, "type": "KILL",
                      "raw_type": "monster"}]}],
                 reference_knowledge={"quests": {"65939": {"objectives": [
                     {"description": "", "credit_kind": "CREATURE_CREDIT", "credit_object_id": 191596,
                      "credit_name": "Qalashi Forces", "raw_type": 0,
                      "credit_creatures": [{"entry": 186892, "name": "Qalashi Necksnapper"}]}]}}})
    units = kill_objective_units(state)
    assert [unit["guid"].split("-")[-1] for unit in units] == ["alive"] and units[0]["targets_me"] is True
