"""Explicit TDB spell-hit credit links; no script execution or live phase claims."""
from copy import deepcopy
from functools import lru_cache
import sqlite3


@lru_cache(maxsize=256)
def spell_hit_credits(provider, spell_id):
    raw = provider.catalog.raw
    if not raw or not {'smart_scripts', 'conditions'} <= raw.tables:
        return []
    try:
        rows = raw.rows("""SELECT * FROM smart_scripts WHERE source_type=0 AND entryorguid>0
            AND event_type=8 AND event_param1=? AND action_type=33 AND target_type=7 LIMIT 65""", (spell_id,))
        if not rows:
            return []
        conditions = raw.rows('SELECT * FROM conditions WHERE SourceTypeOrReferenceId=13 AND SourceEntry=? LIMIT 65',
                              (spell_id,))
    except sqlite3.Error:
        return []  # an older/incomplete world schema provides no relationship
    if len(rows) > 64 or len(conditions) != 1:
        return []
    condition = conditions[0]
    if (condition.get('ConditionTypeOrReference') != 31 or condition.get('ConditionValue1') != 3
            or condition.get('NegativeCondition') or condition.get('ConditionTarget') != 0
            or condition.get('SourceId') or condition.get('ScriptName')
            or condition.get('ConditionValue3') or condition.get('ConditionStringValue1')
            or type(condition.get('SourceGroup')) is not int or not 0 < condition['SourceGroup'] < 2**32):
        return []
    entry = condition.get('ConditionValue2')
    if type(entry) is not int or entry <= 0:
        return []
    result = []
    for row in rows:
        if (row['entryorguid'] != entry or type(row.get('action_param1')) is not int
                or row['action_param1'] <= 0):
            continue
        # Unknown additional SmartAI conditions cannot be treated as a
        # fulfilled live eligibility predicate by this reviewed adapter.
        try:
            if raw.rows('''SELECT * FROM conditions WHERE SourceTypeOrReferenceId=22
                           AND SourceEntry=? AND SourceGroup=? AND SourceId=0 LIMIT 1''',
                        (entry, row['id']+1)):
                continue
        except sqlite3.Error:
            continue
        result.append({'kind':'CREATURE_CREDIT', 'id':row['action_param1'],
                       'subject_entry':entry, 'hit_spell_id':spell_id,
                       'source':'TDB_SPELL_HIT_CREDIT', 'conditional':True,
                       'script':deepcopy(row), 'target_conditions':[deepcopy(condition)]})
    return result

