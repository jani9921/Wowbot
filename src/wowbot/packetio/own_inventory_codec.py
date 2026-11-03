"""Selected-own inventory prefixes from WPP 70340, with numeric/GUID allowlists.

Native indices describe server storage, never client bag button coordinates.
Unrelated player/account/cosmetic text is skipped without decoding/exporting it.
"""
import re

from .player_quest_log import _skip_guid

LAYOUT = 'WPP_12_1_OWN_INVENTORY_REVIEWED_V1'
EVENTS = frozenset({'OWN_INVENTORY_ROOTS','OWN_INVENTORY_INVALIDATED','OWN_ITEM_UPDATE','OWN_ITEM_REMOVED'})
ZERO = '0'*32
ROOT_COUNT, CONTAINER_COUNT = 105, 98


def count(cursor, maximum=512):
    value = cursor.u32()
    if value > maximum: raise ValueError('inventory collection exceeds reviewed bound')
    return value


def _item_instance(cursor):
    cursor.take(4)
    cursor.reset()
    cursor.take(cursor.bits(7)*5)
    cursor.reset()
    if cursor.bit():
        cursor.take(1)
        cursor.take(count(cursor)*4)


def create_roots(cursor, *, customizations, random_customizations):
    """PlayerData after QuestLog, then the ActivePlayerData InvSlots prefix."""
    cursor.take(count(cursor,175)*8)    # QuestLogQuestIdToIndex
    session_slots = count(cursor,175)
    for _ in range(19):               # VisibleItem, incl. its final two bits
        cursor.reset();cursor.take(22);cursor.reset();cursor.bits(2)
    cursor.take(6*4+6*4+1+4+8)        # title/realm/spec/taxi, avg item lvls, pet/honor/logout
    arena = count(cursor)
    cursor.take(32*8+3*4)             # forced reactions, offered quests/pet species
    pet_names = count(cursor)
    ctr = count(cursor)
    cursor.take(1+4+ctr*4)            # CTROptions
    cursor.take(2*4+2*4)              # covenant/soulbind, dungeon score totals
    runs = count(cursor)
    for _ in range(runs):
        cursor.take(17);cursor.reset();cursor.bit()
    _skip_guid(cursor)                # LeaverInfo BnetAccountGUID
    cursor.take(40);cursor.reset();cursor.bit()
    _skip_guid(cursor)                # SpectateTarget
    cursor.take(4)                    # WorldLootObjectInventorySwapSlot
    for _ in range(16):_item_instance(cursor)
    replacements = count(cursor)
    cursor.take(19*4+5*4)             # Plunderstorm displays, tabard
    cursor.reset();cursor.take(28);_skip_guid(cursor)  # NPCAsPlayerInfo
    cursor.take((customizations+random_customizations)*8)
    cursor.take(session_slots*70)
    cursor.take(arena*25)
    for _ in range(pet_names):
        cursor.reset();cursor.take(4);cursor.take(cursor.bits(8))
    cursor.take(replacements*4)
    cursor.reset()
    size = cursor.bits(6)
    cursor.bit();cursor.bit()         # HasQuestSession, HasLevelLink
    declined = cursor.bit()
    cursor.take(size)                 # own name: skipped, never decoded
    if declined:
        cursor.reset()
        sizes = [cursor.bits(10) for _ in range(5)]
        cursor.take(sum(sizes))
    cursor.reset()
    return normalize_guid_slots([[i,cursor.guid()] for i in range(ROOT_COUNT)],ROOT_COUNT)


def create_item(cursor, *, flags, own_guid):
    """Read ItemData only after its owner is the verified selected player."""
    from .context import same_player
    cursor.reset()
    owner = cursor.guid()
    if not same_player(owner,own_guid):
        return {'foreign_owner':True}  # no other player's private ItemData is read
    if not flags & 1:
        return None
    parent = cursor.guid()
    _skip_guid(cursor);_skip_guid(cursor)  # creator and gift creator, not exported
    result = {'mover_guid':owner,'container_guid':parent,'stack_count':cursor.u32()}
    cursor.take(4+5*4+4+13*12)           # expiration/charges/flags/enchantments
    result.update(durability=cursor.u32(),max_durability=cursor.u32())
    cursor.take(4+1+8+8+1)              # played/context/time/artifactXP/appearance
    cursor.reset();cursor.take(cursor.bits(7)*5)  # item modifier list
    artifact,gems = count(cursor),count(cursor,16)
    cursor.take(4+4)                    # ZoneFlags, bonus-key ItemID
    bonuses,modifiers = count(cursor),count(cursor)
    cursor.take(bonuses*4+modifiers*5+2) # bonus key, DEBUGItemLevel
    cursor.take(artifact*4+gems*37)
    return result


def create_container(cursor):
    cursor.reset()
    slots = normalize_guid_slots([[i,cursor.guid()] for i in range(CONTAINER_COUNT)],CONTAINER_COUNT)
    size = cursor.u32()
    if size > CONTAINER_COUNT or any(guid != ZERO for i,guid in slots if i >= size):
        raise ValueError('invalid own container capacity')
    return {'container_slots':slots,'num_slots':size}


def normalize_guid_slots(rows, limit, *, partial=False):
    if (not isinstance(rows,list) or not 1 <= len(rows) <= limit
            or not partial and len(rows) != limit):
        raise ValueError('complete native slot list required')
    result,seen = [],set()
    for row in rows:
        if not isinstance(row,list) or len(row)!=2:
            raise ValueError('invalid native slot shape')
        index,guid = row
        if type(index) is not int or not 0 <= index < limit or index in seen:
            raise ValueError('invalid or repeated native slot index')
        _guid(guid,item=True,zero=True)
        guid = guid.upper()
        if guid != ZERO and any(guid == prior[1] for prior in result):
            raise ValueError('duplicate item identity in a slot collection')
        seen.add(index);result.append([index,guid.upper()])
    return result


def _guid(value, *, item=False, zero=False):
    if not isinstance(value,str) or re.fullmatch('[a-fA-F0-9]{32}',value) is None:
        raise ValueError('invalid inventory identity')
    if int(value,16)==0:
        if zero:return
        raise ValueError('nonzero inventory identity required')
    if int(value[:16],16)>>58 != (3 if item else 2) or int(value[16:],16)==0:
        raise ValueError('wrong inventory identity kind')


def normalize_body(kind, body):
    _guid(body.get('mover_guid'))
    world = body.get('world_map_id')
    if type(world) is not int or not 0 <= world < 2**16:
        raise ValueError('inventory world context required')
    result = {'mover_guid':body['mover_guid'].upper(),'world_map_id':world}
    if kind == 'OWN_INVENTORY_INVALIDATED':
        return result
    if kind == 'OWN_INVENTORY_ROOTS':
        sample=body.get('sample_kind')
        if sample not in {'CREATE','VALUES'}:raise ValueError('reviewed root sample required')
        return {**result,'sample_kind':sample,
                'root_slots':normalize_guid_slots(body.get('root_slots'),ROOT_COUNT,partial=sample=='VALUES')}
    _guid(body.get('item_guid'),item=True)
    result['item_guid'] = body['item_guid'].upper()
    if kind == 'OWN_ITEM_REMOVED':
        if body.get('removal') not in {'DESTROYED','OUT_OF_RANGE','OWNER_CHANGED','UNREVIEWED_UPDATE'}:
            raise ValueError('invalid item removal')
        return {**result,'removal':body['removal']}
    sample = body.get('sample_kind')
    if sample not in {'CREATE','VALUES'}:raise ValueError('reviewed item sample required')
    for key in ('item_id','stack_count','durability','max_durability'):
        if sample == 'VALUES' and key not in body:continue
        value = body.get(key)
        if type(value) is not int or not 0 <= value < 2**32 or key=='item_id' and not value:
            raise ValueError('invalid own item number')
        result[key] = value
    if sample=='CREATE' or 'container_guid' in body:
        parent = body.get('container_guid')
        if not isinstance(parent,str) or parent.upper() != result['mover_guid']:
            _guid(parent,item=True,zero=True)
        result['container_guid'] = parent.upper()
    result['sample_kind'] = sample
    if sample=='CREATE' and ('container_slots' in body or 'num_slots' in body):
        slots=normalize_guid_slots(body.get('container_slots'),CONTAINER_COUNT)
        size=body.get('num_slots')
        if type(size) is not int or not 0 <= size <= CONTAINER_COUNT or any(g != ZERO for i,g in slots if i >= size):
            raise ValueError('invalid own container size')
        result.update(container_slots=slots,num_slots=size)
    if sample=='VALUES':
        if 'num_slots' in body:
            size=body['num_slots']
            if type(size) is not int or not 0 <= size <= CONTAINER_COUNT:
                raise ValueError('invalid container capacity')
            result['num_slots']=size
        if 'container_slots_delta' in body:
            result['container_slots_delta']=normalize_guid_slots(body['container_slots_delta'],CONTAINER_COUNT,partial=True)
        if not set(result)-{'mover_guid','world_map_id','item_guid','sample_kind'}:
            raise ValueError('empty inventory delta')
    return result
