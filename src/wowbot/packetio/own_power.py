"""Retail POWER_UPDATE uses an explicit power enum, never an array-slot guess."""
from .context import same_player


POWER_LAYOUT = 'WPP_12_1_POWER_REVIEWED_V1'


def decode_power(cursor, own_character_guid):
    if own_character_guid is None:
        return []
    guid = cursor.packed_guid128()
    if not same_player(guid, own_character_guid):
        return []
    count = cursor.i32()
    if not 0 <= count <= 32:
        raise ValueError('unreviewed power count')
    values = {}
    for _ in range(count):
        # WPP V6 CharacterHandler: since TWW the byte enum precedes int32.
        kind, raw = cursor.u8(), cursor.i32()
        if kind in values and values[kind] != raw:
            raise ValueError('conflicting same-record power type')
        values[kind] = raw
    if cursor.offset != len(cursor.data):
        raise ValueError('unreviewed power record tail')
    return [('OWN_POWER_UPDATE', {'mover_guid': guid, 'power_type': kind, 'raw_power': raw})
            for kind, raw in values.items()]
