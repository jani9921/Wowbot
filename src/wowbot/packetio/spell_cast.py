"""Allowlisted NPC cast fields from the pinned WPP 12.x handlers.

START/GO share a reviewed fixed prefix, not a full-record codec. Failure and
interrupt records are consumed exactly. No spell name, target text, player
identity, arbitrary payload or inferred interruptibility is exported.
"""
import struct


SPELL_OPCODES = frozenset({'SMSG_SPELL_START', 'SMSG_SPELL_GO', 'SMSG_SPELL_FAILURE',
                           'SMSG_SPELL_FAILED_OTHER', 'SMSG_SPELL_INTERRUPT_LOG'})
CAST_EVENTS = frozenset({'SPELL_CAST_STARTED', 'SPELL_CAST_RELEASED', 'SPELL_CAST_RESULT',
                         'SPELL_INTERRUPT_OBSERVED'})
SPELL_LAYOUT = 'WPP_12_1_SPELL_REVIEWED_V1'


def _npc(guid):
    return int(guid[:16], 16) >> 58 in {8, 9} and int(guid[16:], 16) != 0


def _spell(value):
    if not 0 < value < 2**31:
        raise ValueError('invalid spell identifier')
    return value


def _end(cursor):
    if cursor.offset != len(cursor.data):
        raise ValueError('unreviewed trailing spell bytes')


def decode_spell(name, cursor):
    if name in {'SMSG_SPELL_START', 'SMSG_SPELL_GO'}:
        cursor.packed_guid128()  # CasterGUID can be an item; never exported
        caster = cursor.packed_guid128()  # actual CasterUnit
        cast_id = cursor.packed_guid128()
        cursor.packed_guid128()  # OriginalCastID, no semantic shortcut
        spell_id = _spell(cursor.u32())
        cursor.take(8)  # ReadSpellCastVisual: two int32 values
        flags, flags_ex, flags_ex2 = cursor.u32(), cursor.u32(), cursor.u32()
        cast_time = cursor.u32()
        if not _npc(caster) or int(cast_id, 16) == 0:
            return []
        if name == 'SMSG_SPELL_START' and cast_time > 600_000:
            raise ValueError('unsupported cast duration')
        # GO's CastTime is a server clock, not a new cast duration.
        time_key = 'cast_time_ms' if name == 'SMSG_SPELL_START' else 'server_cast_time_ms'
        return [('SPELL_CAST_STARTED' if name == 'SMSG_SPELL_START' else 'SPELL_CAST_RELEASED',
                 {'caster_guid': caster, 'cast_id': cast_id, 'spell_id': spell_id,
                  time_key: cast_time, 'cast_flags': flags, 'cast_flags_ex': flags_ex,
                  'cast_flags_ex2': flags_ex2})]
    if name in {'SMSG_SPELL_FAILURE', 'SMSG_SPELL_FAILED_OTHER'}:
        caster, cast_id = cursor.packed_guid128(), cursor.packed_guid128()
        spell_id = _spell(cursor.u32())
        cursor.take(8)  # same visual structure
        code = (struct.unpack('<h', cursor.take(2))[0] if name == 'SMSG_SPELL_FAILURE' else cursor.u8())
        cursor.packed_guid128()  # FailedBy (Retail >= 12.0), not exported
        _end(cursor)
        if not _npc(caster) or int(cast_id, 16) == 0 or code < 0:
            return []
        return [('SPELL_CAST_RESULT', {'caster_guid': caster, 'cast_id': cast_id,
                                      'spell_id': spell_id, 'failure_code': code})]
    if name == 'SMSG_SPELL_INTERRUPT_LOG':
        cursor.packed_guid128()  # interruptor may be a player; not exported
        victim = cursor.packed_guid128()
        interrupt_spell, interrupted_spell = _spell(cursor.u32()), _spell(cursor.u32())
        flags = cursor.u8()  # HideFromCombatLog, Retail >= 12.0.1
        if flags & 0x7f:
            raise ValueError('unreviewed interrupt padding')
        _end(cursor)
        if not _npc(victim):
            return []
        # This record has NO CastID. Do not invent one or certify an exact
        # cast interrupt through a same-spell/proximity/time guess.
        return [('SPELL_INTERRUPT_OBSERVED', {'caster_guid': victim, 'spell_id': interrupted_spell,
                                             'interrupt_spell_id': interrupt_spell})]
    return []
