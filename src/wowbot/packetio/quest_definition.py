"""Allowlisted quest definitions from the pinned 12.1 QueryHandler layout.

Definitions do not assert active membership, objective progress, an actor's
current GUID/location, or a reward receipt. No chat/account payload is read.
"""
import math

from .update_object import _Bits

LAYOUT = 'WPP_12_1_QUEST_DEFINITION_REVIEWED_V1'
EVENTS = frozenset({'QUEST_DEFINITION', 'QUEST_DEFINITION_UNAVAILABLE'})
TEXT_LIMITS = {'title':511, 'log_description':4095, 'description':4095, 'area_description':511,
               'completion_log':2047, 'giver_portrait_name':255, 'turn_in_portrait_name':255}


def _count(value, limit=256):
    if not 0 <= value <= limit:
        raise ValueError('quest definition count exceeds reviewed bound')
    return value


def _text(cursor, count):
    # WPP ReadWoWString removes NUL bytes, then decodes UTF-8. Invalid UTF-8
    # fails closed here rather than inserting replacement characters.
    return cursor.take(count).replace(b'\0',b'').decode('utf-8')


def decode_definition(data):
    c = _Bits(data)
    requested = c.i32()
    if not 0 < requested < 2**31:
        raise ValueError('invalid requested quest ID')
    if not c.bit():
        if c.offset != len(data): raise ValueError('unreviewed missing-definition tail')
        return 'QUEST_DEFINITION_UNAVAILABLE', {'quest_id':requested}
    quest_id = c.i32()
    if quest_id != requested:
        raise ValueError('quest response identity mismatch')
    result = {'quest_id':quest_id}
    for field in ('quest_type','quest_package_id','content_tuning_id','quest_sort_id','quest_info_id',
                  'suggested_group_size','reward_next_quest_id'):
        result[field] = c.i32()
    c.take(4*6)  # XP difficulty/multiplier; money/difficulty/multiplier; bonus money
    display_spells = _count(c.u32(),64)
    c.take(4*7)  # reward spell/honor/kill-honor/favor/artifact XP difficulty/multiplier/category
    result['start_item_id'] = c.i32()
    for field in ('flags','flags_ex','flags_ex2','flags_ex3'): result[field] = c.u32()
    c.take(4*4*4+6*3*4)   # item rewards/drops and choice-item display records
    c.take(4*4+4*4+4*4)   # POI display, title/skill rewards and portrait model IDs
    c.take(5*4*4+4+4*2*4) # faction and currency rewards
    c.take(4*3)           # sounds, area group
    result['time_allowed'] = c.i64()
    objectives = _count(c.u32(),64)
    result['allowable_races'] = c.u64()
    treasure, hidden_treasure = _count(c.u32()), _count(c.u32())
    result['expansion'] = c.i32()
    c.take(4*2)           # managed world state, quest-session bonus
    result['giver_creature_id'] = c.i32()
    conditional_description, conditional_completion = _count(c.u32(),16), _count(c.u32(),16)
    house_rooms, house_decor = _count(c.u32()), _count(c.u32())
    c.take(display_spells*12)  # spell/player-condition/display type, Retail >=10.1
    result['objectives'] = []
    for order in range(objectives):
        row = {'objective_id':c.i32(), 'raw_type':c.u32(), 'storage_index':c.i8(), 'order':order,
               'object_id':c.i32(), 'amount':c.i32(), 'conditional_amount':c.i32(),
               'flags':c.u32(), 'flags2':c.u32(), 'progress_bar_weight':c.f32()}
        effects = _count(c.i32(),64)
        row['parent_objective_id'] = c.i32()
        c.take(effects*4)
        c.reset()
        size = c.bits(8)
        row['visible'] = c.bit()
        row['description'] = _text(c,size)
        result['objectives'].append(row)
    c.take(4*(treasure+hidden_treasure))
    # Conditional text is not the current text without its player-condition
    # result. Consume it by exact reviewed sizes; retain its existence only.
    result['has_conditional_texts'] = bool(conditional_description+conditional_completion)
    for _ in range(conditional_description+conditional_completion):
        c.take(8)        # PlayerConditionID, QuestGiverCreatureID
        c.reset()
        c.take(c.bits(12))
    c.take(4*(house_rooms+house_decor))
    c.reset()
    lengths = [c.bits(n) for n in (9,12,12,9,10,8,10,8,11)]
    c.bit(), c.bit()    # translation and scheduler flags, not current completion
    fields = ('title','log_description','description','area_description',None,
              'giver_portrait_name',None,'turn_in_portrait_name','completion_log')
    for field,size in zip(fields,lengths):
        if field is None: c.take(size)
        else: result[field] = _text(c,size)
    if c.offset != len(data):
        raise ValueError('unreviewed quest definition tail')
    return 'QUEST_DEFINITION', {'quest_id':quest_id,'definition':normalize_definition(result)}


def normalize_definition(value):
    if not isinstance(value,dict): raise ValueError('quest definition object required')
    result = {}
    integer_limits = {'quest_id':(1,2**31), 'quest_type':(-2**31,2**31), 'quest_package_id':(-2**31,2**31),
        'content_tuning_id':(-2**31,2**31), 'quest_sort_id':(-2**31,2**31), 'quest_info_id':(-2**31,2**31),
        'suggested_group_size':(-1,256), 'reward_next_quest_id':(-2**31,2**31), 'start_item_id':(-2**31,2**31),
        'flags':(0,2**32), 'flags_ex':(0,2**32), 'flags_ex2':(0,2**32), 'flags_ex3':(0,2**32),
        'time_allowed':(-2**63,2**63), 'allowable_races':(0,2**64), 'expansion':(-1,256),
        'giver_creature_id':(-2**31,2**31)}
    for field,(low,high) in integer_limits.items():
        number = value.get(field)
        if type(number) is not int or not low <= number < high: raise ValueError('invalid quest definition number')
        result[field] = number
    def text(raw,limit):
        if (not isinstance(raw,str) or len(raw.encode('utf-8')) > limit
                or any(ord(char)<32 and char not in '\n\r\t' for char in raw)):
            raise ValueError('invalid bounded quest text')
        return raw
    for field,limit in TEXT_LIMITS.items(): result[field] = text(value.get(field),limit)
    if type(value.get('has_conditional_texts')) is not bool: raise ValueError('conditional-text flag required')
    result['has_conditional_texts'] = value['has_conditional_texts']
    rows = value.get('objectives')
    if not isinstance(rows,list) or len(rows)>64: raise ValueError('invalid objective count')
    result['objectives'], seen = [], set()
    for order,row in enumerate(rows):
        if not isinstance(row,dict): raise ValueError('objective object required')
        limits = {'objective_id':(1,2**31),'raw_type':(0,2**32),'storage_index':(-128,128),
                  'object_id':(-2**31,2**31),'amount':(-2**31,2**31),'conditional_amount':(-2**31,2**31),
                  'flags':(0,2**32),'flags2':(0,2**32),'parent_objective_id':(-2**31,2**31)}
        clean = {'order':order}
        for field,(low,high) in limits.items():
            number = row.get(field)
            if type(number) is not int or not low <= number < high: raise ValueError('invalid objective number')
            clean[field] = number
        if clean['objective_id'] in seen or row.get('order') != order: raise ValueError('ambiguous objective identity/order')
        seen.add(clean['objective_id'])
        weight = row.get('progress_bar_weight')
        if type(weight) not in {int,float} or not math.isfinite(weight) or abs(weight)>1e6:
            raise ValueError('invalid objective weight')
        if type(row.get('visible')) is not bool: raise ValueError('objective visibility required')
        clean.update(progress_bar_weight=weight,visible=row['visible'],description=text(row.get('description'),255))
        result['objectives'].append(clean)
    return result
