"""Narrow, readonly spell-target relations; no condition/script execution."""
from functools import lru_cache
import sqlite3


@lru_cache(maxsize=256)
def spell_target_entries(provider, spell_id):
    """Accept one positive creature-entry predicate, preserving its effect mask.

    Trinity conditions source 13 uses an effect mask, not an effect ordinal:
    https://trinitycore.info/database/master/world/conditions
    Compound/alternative/reference predicates are deliberately unresolved.
    The caller must also bind the mask to a decoded DB2 effect and objective.
    """
    raw = provider.catalog.raw
    if raw is None or 'conditions' not in raw.tables:
        return []
    try:
        rows = raw.rows('SELECT * FROM conditions WHERE SourceTypeOrReferenceId=13 '
                        'AND SourceEntry=? LIMIT 2', (spell_id,))
    except sqlite3.Error:
        return []
    if len(rows) != 1:
        return []
    row = rows[0]
    mask, entry = row.get('SourceGroup'), row.get('ConditionValue2')
    if (row.get('ConditionTypeOrReference') != 31 or row.get('ConditionValue1') != 3
            or row.get('ConditionTarget') != 0 or row.get('NegativeCondition') != 0
            or row.get('SourceId') != 0 or row.get('ElseGroup') != 0
            or row.get('ConditionValue3') != 0 or row.get('ConditionStringValue1')
            or row.get('ScriptName') or type(mask) is not int or not 0 < mask < 2**32
            or type(entry) is not int or entry <= 0):
        return []
    return [{'entry': entry, 'effect_mask': mask, 'spell_id': spell_id,
             'source': 'TDB_SPELL_TARGET_CONDITION', 'confirmed': False}]
