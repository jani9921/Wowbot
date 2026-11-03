"""Read-only FactionTemplate.db2 (WDC5): which creature factions attack players.

User 2026-10-20 ("csináld meg mind": route around dangerous spawns, an idea
from PixelBuddy's path service).  TDB's creature_template names a faction
template; whether it attacks players on sight is the template's EnemyGroup
(TrinityCore ``FactionTemplateEntry::IsHostileToPlayers``: EnemyGroup &
FACTION_MASK_PLAYER) or an enemy entry naming the player's own faction.

The client's extracted DB2 (``<retail>/dbc/enUS/FactionTemplate.db2``) is
the source.  Only what this table uses of WDC5 is read: one or more plain
sections with an ID list and a copy table, fields stored inline, bitpacked
(signed or not) or through a pallet (single or array).  Anything else is
refused rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

FACTION_MASK_PLAYER, FACTION_MASK_ALLIANCE, FACTION_MASK_HORDE = 1, 2, 4
_HEADER = struct.Struct("<9IHH7I")
_SECTION = struct.Struct("<Q8I")
_STORAGE = struct.Struct("<HHIIIII")
NONE, BITPACKED, COMMON, PALLET, PALLET_ARRAY, BITPACKED_SIGNED = range(6)


class Db2FormatError(ValueError):
    pass


def read_wdc5(path: str | Path) -> dict[int, list]:
    """{id: [field values]} with array fields as lists."""
    data = Path(path).read_bytes()
    if data[:4] != b"WDC5":
        raise Db2FormatError("not a WDC5 file")
    (records, fields, record_size, _strings, _table, _layout, _min, _max, _locale,
     flags, _id_index, total_fields, bitpacked_offset, _lookup, storage_size,
     common_size, pallet_size, section_count) = _HEADER.unpack_from(data, 136)
    if flags & 0x1 or common_size:
        raise Db2FormatError("offset map / common data not supported")
    offset = 136 + _HEADER.size
    sections = [_SECTION.unpack_from(data, offset + k*_SECTION.size) for k in range(section_count)]
    offset += section_count*_SECTION.size + 4*total_fields
    storage = [_STORAGE.unpack_from(data, offset + k*_STORAGE.size)
               for k in range(storage_size // _STORAGE.size)]
    offset += storage_size
    pallets, cursor = [], offset
    for info in storage:
        pallets.append(cursor if info[3] in {PALLET, PALLET_ARRAY} else None)
        if info[3] in {PALLET, PALLET_ARRAY}:
            cursor += info[2]
    rows: dict[int, list] = {}
    for (_key, file_offset, count, string_size, _end, id_size, relation_size, _ids, copies) in sections:
        if relation_size:
            raise Db2FormatError("relationship data not supported")
        ids_at = file_offset + count*record_size + string_size
        ids = struct.unpack_from(f"<{id_size // 4}I", data, ids_at)
        for index in range(count):
            record = int.from_bytes(data[file_offset+index*record_size:file_offset+(index+1)*record_size],
                                    "little")
            values = []
            for info, pallet in zip(storage, pallets):
                bit_offset, bit_size, _extra, kind, _v1, width, array = info
                if kind == NONE:
                    values.append((record >> bit_offset) & ((1 << bit_size) - 1))
                    continue
                raw = (record >> (bit_offset + bitpacked_offset*8)) & ((1 << width) - 1)
                if kind == BITPACKED:
                    values.append(raw)
                elif kind == BITPACKED_SIGNED:
                    values.append(raw - (1 << width) if raw >> (width-1) else raw)
                elif kind == PALLET:
                    values.append(struct.unpack_from("<I", data, pallet + raw*4)[0])
                elif kind == PALLET_ARRAY:
                    values.append(list(struct.unpack_from(f"<{array}I", data, pallet + raw*4*array)))
                else:
                    raise Db2FormatError(f"storage type {kind} not supported")
            rows[ids[index]] = values
        copy_at = ids_at + id_size
        for k in range(copies):
            new_id, source = struct.unpack_from("<2I", data, copy_at + 8*k)
            if source in rows:
                rows[new_id] = list(rows[source])
    if len(rows) < records:
        raise Db2FormatError("fewer rows than the header promises")
    return rows


@dataclass(frozen=True)
class FactionTemplate:
    template_id: int
    faction: int
    faction_group: int
    friend_group: int
    enemy_group: int
    enemies: tuple[int, ...]
    friends: tuple[int, ...]


class FactionTemplates:
    def __init__(self, templates: dict[int, FactionTemplate]):
        self.templates = templates

    @classmethod
    def load(cls, path: str | Path) -> FactionTemplates:
        rows = read_wdc5(path)
        return cls({key: FactionTemplate(key, row[0], row[2], row[3], row[4],
                                         tuple(v for v in row[5] if v), tuple(v for v in row[6] if v))
                    for key, row in rows.items()})

    def hostile_to_player(self, template_id: int, player_template_id: int | None = None) -> bool:
        """TrinityCore IsHostileTo(player) / IsHostileToPlayers; unknown = False."""
        mob = self.templates.get(int(template_id))
        if mob is None:
            return False
        player = self.templates.get(int(player_template_id)) if player_template_id is not None else None
        if player is None:
            return bool(mob.enemy_group & FACTION_MASK_PLAYER)
        if mob.template_id == player.template_id:
            return False
        if player.faction:
            if player.faction in mob.enemies:
                return True
            if player.faction in mob.friends:
                return False
        return bool(mob.enemy_group & player.faction_group)
