"""Reviewed 70340 PlayerData quest-slot prefix; no player/account text.

Compact row: slot, QuestID, StateFlags, EndTime, ObjectiveFlags,
EnabledObjectivesMask, 24 ObjectiveProgress storage values. None means not
sampled in this delta; zero is a real wire value, including an empty slot.
"""
SLOT_COUNT = 175
PROGRESS_COUNT = 24
LAYOUT = 'WPP_12_1_QUEST_LOG_REVIEWED_V1'
EVENTS = frozenset({'OWN_QUEST_LOG_UPDATE', 'OWN_QUEST_LOG_INVALIDATED'})
INVALIDATION_LAYOUT = 'WPP_12_1_QUEST_LOG_INVALIDATION_V1'


def _skip_guid(cursor):
    count = cursor.u8().bit_count()+cursor.u8().bit_count()
    cursor.take(count)  # never construct/retain account, guild or player IDs


def _slot(cursor, index, full):
    result = [index, None, None, None, None, None, [None]*PROGRESS_COUNT]
    if full:
        cursor.reset()
        result[1], result[2] = cursor.i32(), cursor.u16()
        result[6] = [cursor.i16() for _ in range(PROGRESS_COUNT)]
        result[3], result[4], result[5] = cursor.i64(), cursor.u32(), cursor.u32()
        return result
    cursor.reset()
    mask = cursor.bits(32) if cursor.bit() else 0
    if (mask >> 31 or mask & 0x3e and not mask & 1
            or mask & 0x7fffff80 and not mask & (1 << 6)):
        raise ValueError('unsupported quest slot mask')
    cursor.reset()
    if mask & 1:
        for bit, column, read in ((1, 1, 'i32'), (2, 2, 'u16'), (3, 3, 'i64'),
                                  (4, 4, 'u32'), (5, 5, 'u32')):
            if mask >> bit & 1:
                result[column] = getattr(cursor, read)()
    if mask >> 6 & 1:
        for i in range(PROGRESS_COUNT):
            if mask >> (7+i) & 1:
                result[6][i] = cursor.i16()
    return result


def read_slots(cursor):
    """Read through QuestLog only when every preceding changed field is known.

    Dynamic maps/arrays, names, declined names and other complex blocks before
    QuestLog deliberately make this prefix unavailable, never guessed offsets.
    A later PlayerData/ActivePlayerData tail is outside this reviewed scope.
    """
    cursor.reset()
    present = cursor.bits(11)
    words = [cursor.bits(32) if present >> i & 1 else 0 for i in range(11)]
    changed = lambda bit: bool(words[bit//32] >> (bit % 32) & 1)
    full = cursor.bit()  # noPartyMemberChangesMask
    slot_changes = any(changed(i) for i in range(54,54+SLOT_COUNT))
    if slot_changes and not changed(53):
        raise ValueError('unrooted quest slot mask')
    if not slot_changes:
        return []  # mask proves QuestLog unchanged, without reading private fields
    supported = {0, 1, 2, *range(9, 25), *range(26, 32), 50, 51, 52}
    if (not changed(53) or any(changed(i) and i not in supported for i in range(53))
            or any(changed(i) for i in (*range(1, 3), *range(9, 25), *range(26, 32))) and not changed(0)
            or any(changed(i) for i in (51, 52)) and not changed(50)):
        return None
    if changed(0):
        for bit in (1, 2):
            if changed(bit): cursor.bit()
    cursor.reset()
    if changed(0):
        for bit in range(9, 32):
            if not changed(bit): continue
            if bit in (9, 10, 11, 13): _skip_guid(cursor)
            elif bit == 12: cursor.take(8)
            elif bit in (19, 20, 21, 22): cursor.take(1)
            else: cursor.take(4)
    cursor.reset()
    if changed(50):
        for bit in (51, 52):
            if changed(bit): cursor.take(1)
    rows = [_slot(cursor, i, full) for i in range(SLOT_COUNT) if changed(54+i)]
    rows = [row for row in rows if any(v is not None for v in row[1:6])
            or any(v is not None for v in row[6])]
    return normalize_slots(rows)


def normalize_slots(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= SLOT_COUNT:
        raise ValueError('invalid quest slot list')
    seen, result = set(), []
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError('invalid quest slot shape')
        index = row[0]
        if type(index) is not int or not 0 <= index < SLOT_COUNT or index in seen:
            raise ValueError('invalid or repeated quest slot')
        seen.add(index)
        limits = (2**31, 2**16, 2**63, 2**32, 2**32)
        for value, limit in zip(row[1:6], limits):
            if value is not None and (type(value) is not int or not 0 <= value < limit):
                raise ValueError('invalid quest slot value')
        progress = row[6]
        if not isinstance(progress, list) or len(progress) != PROGRESS_COUNT:
            raise ValueError('invalid quest storage progress')
        if any(v is not None and (type(v) is not int or not -2**15 <= v < 2**15) for v in progress):
            raise ValueError('invalid quest counter')
        if all(v is None for v in row[1:6]) and all(v is None for v in progress):
            raise ValueError('empty quest slot delta')
        result.append([*row[:6], list(progress)])
    return result
